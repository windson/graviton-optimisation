#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Writes the report's tables as Markdown fragments, straight from the measured data.

    uv run analysis/tables.py             # writes report/tables/*.md

README.md includes the summary from here instead of a hand-typed table, so a table can
only show what is in results/comparison.json, results/ceiling.json, results/rated.json,
results/bom.json and the price snapshot. Every figure carries its unit, in its cell or
in the heading of its column.

Run after analysis/compare.py, analysis/ceiling.py and analysis/rated.py.
"""
from __future__ import annotations

import json
import math
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "report/tables"

NAMES = {
    "A": "A: Graviton2 baseline",
    "B": "B: Graviton5, same size",
    "C": "C: Graviton5, right-sized",
}
STAGE_OF = {"A": "a-graviton2-baseline", "B": "b-graviton5-same-size", "C": "c-graviton5-right-sized"}
TIER_TITLES = {"web": "Web tier", "api": "API tier", "db": "Database writer"}
TIER_WORDS = {"web": "web tier", "api": "API tier", "db": "database writer", None: "latency limit"}
HOURS = 730


def money(value: float) -> str:
    """Whole dollars, halves rounded up (Python's own formatting rounds halves to even)."""
    return f"${math.floor(value + 0.5):,}"


def rps(value: float) -> str:
    return f"{value:,.0f} requests per second"


def table(header: list[str], rows: list[list[str]], right: set[int] | None = None) -> str:
    right = right or set()
    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join("---:" if i in right else "---" for i in range(len(header))) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def by_config(first: str, rows: list[tuple[str, dict]], letters: tuple[str, ...] = ("A", "B", "C")) -> str:
    """A table with one column per configuration and one row per measure."""
    return table([first] + [f"**{NAMES[letter]}**" for letter in letters],
                 [[name] + [cells.get(letter, "") for letter in letters] for name, cells in rows],
                 set(range(1, len(letters) + 1)))


def spread(value: dict, unit: str, digits: int = 1, scale: float = 1.0) -> str:
    """A median with the lowest and highest run next to it, if there is more than one run."""
    text = f"{value['median'] * scale:.{digits}f}{unit}"
    if value.get("runs", 1) > 1:
        text += f" ({value['min'] * scale:.{digits}f} to {value['max'] * scale:.{digits}f}{unit})"
    return text


def run_words(entry: dict) -> str:
    seconds = entry["seconds_per_run"][0]
    if entry["source"] == "runs":
        count = len(entry["runs"])
        return f"{count} run{'s' if count != 1 else ''} of {seconds:.0f} seconds"
    return f"1 step of {seconds:.0f} seconds, at {rps(entry['target_rps'])}"


# ---- The configurations ------------------------------------------------------------------------


def configurations(bom: dict, prices: dict) -> str:
    """The configurations as deployed: instance types, counts, pods and vCPUs per tier."""
    columns = {}
    for stage, entry in bom["stages"].items():
        values = (ROOT / "infra/stages" / stage / "values.yaml").read_text()
        replicas = [int(n) for n in re.findall(r"^\s+replicas:\s*(\d+)", values, re.M)]
        shape = entry["shape"]
        vcpus = {tier: prices["ec2"][shape[tier][0]]["vcpu"] * shape[tier][1] for tier in ("web", "api", "system")}
        database = prices["aurora_mysql"][shape["database"][0]]["standard"]["vcpu"]
        memory = prices["aurora_mysql"][shape["database"][0]]["standard"]["memory"]
        columns[entry["title"][0]] = {
            "Web nodes": f"{shape['web'][1]} x `{shape['web'][0]}`, {vcpus['web']} vCPUs in all",
            "Web pods (0.95 vCPU requested each)": f"{replicas[0]} pods",
            "API nodes": f"{shape['api'][1]} x `{shape['api'][0]}`, {vcpus['api']} vCPUs in all",
            "API pods (CPU limit 1.75 vCPUs each)": f"{replicas[1]} pods, {replicas[1] * 1.75:g} vCPUs of CPU limits",
            "Aurora MySQL writer and reader": f"2 x `{shape['database'][0]}`, {database} vCPUs and {memory} each",
            "System nodes": f"{shape['system'][1]} x `{shape['system'][0]}`, {vcpus['system']} vCPUs in all",
            "vCPUs of the web, API and database tiers, counting the reader":
                f"{vcpus['web'] + vcpus['api'] + 2 * database} vCPUs",
        }
    names = list(next(iter(columns.values())))
    return by_config("", [(name, {letter: column[name] for letter, column in columns.items()}) for name in names])


# ---- The summary ----------------------------------------------------------------------------------


def summary(by_letter: dict, ceiling: dict, rated: dict, bom: dict) -> str:
    """The three configurations at a glance."""
    rate = rated["rate_rps"]
    compared = {entry["letter"]: entry for entry in rated["stages"].values()}
    baseline_cost = by_letter["A"]["cost"]
    busy, p99, load, instances, bill, shape = {}, {}, {}, {}, {}, {}
    footnote = ""
    for letter, entry in by_letter.items():
        cost = entry["cost"]
        s = cost["shape"]
        shape[letter] = (f"{s['web'][1]} x `{s['web'][0]}`<br>{s['api'][1]} x `{s['api'][0]}`<br>"
                         f"{s['database'][1]} x `{s['database'][0]}`")
        at_rate = compared.get(letter)
        if at_rate:
            step = at_rate["source"] != "runs"
            mark = f", at {rps(at_rate['target_rps'])} ¹" if step else ""
            busy[letter] = f"{at_rate['busiest_utilization']:.0%}, {TIER_WORDS[at_rate['busiest_tier']]}{mark}"
            # Two tiers within a percentage point of each other: name both.
            if not step and at_rate["busiest_utilization"] - at_rate["second_busiest_utilization"] < 0.01:
                busy[letter] += f" ({TIER_WORDS[at_rate['second_busiest_tier']]}: {at_rate['second_busiest_utilization']:.0%})"
            p99[letter] = f"{at_rate['latency_ms']['p99']['median']:.1f} ms{mark}"
            if step:
                footnote = (f"\n¹ Configuration {letter} was not run at {rps(rate)}. Its figures are from one "
                            f"{at_rate['seconds_per_run'][0]:.0f}-second step of its capacity run, at "
                            f"{rps(at_rate['target_rps'])}, and are shown for reference.\n")
        else:
            busy[letter] = p99[letter] = "not measured yet"
        own = ceiling["stages"][STAGE_OF[letter]]
        load[letter] = f"about {rps(own['rated_rps'])}"
        change = "" if letter == "A" else f" ({cost['compute_database_change']:+.0%} against A)"
        instances[letter] = money(cost["on_demand_groups"]["Compute and database"]) + " per month" + change
        change = "" if letter == "A" else f" ({cost['on_demand_total'] / baseline_cost['on_demand_total'] - 1:+.0%} against A)"
        bill[letter] = money(cost["on_demand_total"]) + " per month" + change
    rows = [
        ("Web nodes<br>API nodes<br>Aurora MySQL instances", shape),
        (f"CPU utilization of the busiest tier at the comparison load of {rps(rate)}; the API tier's is a share "
         "of its pods' CPU limits", busy),
        (f"p99 response time at the comparison load of {rps(rate)}", p99),
        ("Rated load: the request rate at 80% CPU utilization, from each configuration's ceiling run", load),
        ("EC2 and Aurora instances, On-Demand", instances),
        (f"Modelled bill of the stack, On-Demand, at an average of {rps(bom['usage']['average_rps'])}: the items "
         "listed in `report/tables/bom-on-demand.md`", bill),
    ]
    return by_config("", rows) + footnote


# ---- Step 1: rating a configuration ---------------------------------------------------------------


def tiers_of_run(stage: str, run: str, pod_limit: float) -> tuple[list[dict], dict]:
    """Each tier of one run: what it may use, what it used, and its busiest node."""
    directory = ROOT / "results" / stage / run
    summary_ = json.loads((directory / "summary.json").read_text())
    window = summary_["windows"][0]
    tiers, pods = window["tiers"], summary_["shape"]["pods"]
    api_limit = pods["storefront-api"] * pod_limit
    import rated as at_rate  # noqa: PLC0415  the busiest node, by the same rule as the rating
    node = at_rate.busiest_node(summary_, window, directory)
    web, api, db = tiers["web"], tiers["api"], tiers["db_writer"]
    rows = [
        {"tier": "web", "may_use": web["vcpus"],
         "basis": f"{web['vcpus']} vCPUs: {web['nodes']} web nodes of {web['vcpus'] // web['nodes']} vCPUs",
         "used": web["cores_used"], "node": node["web"]},
        {"tier": "api", "may_use": api_limit,
         "basis": f"{api_limit:g} vCPUs: the CPU limits of {pods['storefront-api']} API pods, {pod_limit:g} vCPUs each",
         "used": api["cores_used"], "node": node["api"]},
        {"tier": "db", "may_use": db["vcpus"], "basis": f"{db['vcpus']} vCPUs: one `{db['class']}` instance",
         "used": db["cores_used"], "node": None},
    ]
    return rows, window


def rating(ceiling: dict, letter: str) -> str:
    """The ceiling run of one configuration, tier by tier, and the rated load it gives."""
    entry = ceiling["stages"][STAGE_OF[letter]]
    run = entry.get("ceiling_run")
    if not run:
        return ""
    tiers, window = tiers_of_run(STAGE_OF[letter], run["run"], ceiling["api_pod_cpu_limit"])
    rows = []
    for tier in tiers:
        share = tier["used"] / tier["may_use"]
        rows.append([TIER_TITLES[tier["tier"]], tier["basis"], f"{tier['used']:.1f} vCPUs", f"**{share:.1%}**",
                     f"{tier['node']:.1%}" if tier["node"] is not None else "one instance",
                     rps(window["achieved_rps"] * ceiling["ceiling"] / share)])
    return table(["Tier", "CPU the tier may use", f"CPU in use at {rps(window['target_rps'])}",
                  "CPU utilization: in use, as a share of what the tier may use",
                  "CPU utilization of the busiest node, measured the same way",
                  "Request rate at which this tier would be at 80% CPU utilization"], rows, {2, 3, 4, 5})


# ---- Step 2: what the generation changes ---------------------------------------------------------


def cpu_per_request(by_letter: dict, rated: dict) -> str:
    """CPU time per request on Graviton2 and Graviton5 at the same instance size, at two loads."""
    a, b = by_letter.get("A"), by_letter.get("B")
    if not (a and b and a.get("steady") and b.get("steady")):
        return ""
    compared = {entry["letter"]: entry for entry in rated["stages"].values()}
    rows = []
    for tier, key, title in (("web", "web", "Web tier: React pages rendered on Node.js 24"),
                             ("api", "api", "API tier: Java 21, Spring Boot"),
                             ("db_writer", "db", "Database: Aurora MySQL 3.10 writer")):
        before = a["steady"]["tiers"][tier]["cpu_ms_per_request"]["median"]
        after = b["steady"]["tiers"][tier]["cpu_ms_per_request"]["median"]
        rows.append([title, f"{rps(a['steady']['target_rps'])}: three 590-second runs of each",
                     f"{before:.3f} ms", f"{after:.3f} ms", f"{before / after:.2f}", f"{1 - after / before:.0%}"])
        if "A" in compared and "B" in compared:
            before = compared["A"]["cpu_ms_per_request"][key]["median"]
            after = compared["B"]["cpu_ms_per_request"][key]["median"]
            rows.append(["", f"A at {rps(compared['A']['target_rps'])} ({run_words(compared['A']).split(',')[0]}), "
                             f"B at {rps(compared['B']['target_rps'])} ({run_words(compared['B']).split(',')[0]})",
                         f"{before:.3f} ms", f"{after:.3f} ms", f"{before / after:.2f}", f"{1 - after / before:.0%}"])
    return table(["Tier", "Request rate and runs", "A, Graviton2: CPU time per request",
                  "B, Graviton5: CPU time per request", "A divided by B", "Less CPU time per request on Graviton5"],
                 rows, {2, 3, 4, 5})


# ---- Step 3: working backwards from the rated load to sizes -----------------------------------------


def work_backwards(rated: dict, bom: dict) -> str:
    w = rated.get("work_backwards")
    if not w:
        return ""
    shape = bom["stages"]["c-graviton5-right-sized"]["shape"]
    chosen = {"web": f"{shape['web'][1]} x `{shape['web'][0]}`", "api": f"pods on {shape['api'][1]} x `{shape['api'][0]}`",
              "db": f"`{shape['database'][0]}`"}
    unit = {"web": "vCPUs", "api": "vCPUs of pod CPU limits", "db": "vCPUs"}
    tiers = w["tiers"]

    def cells(make) -> dict:
        return {tier: make(tier, tiers[tier]) for tier in tiers}

    rows = [
        (f"1. CPU time per request on Graviton5, measured on configuration B at {rps(w['cpu_per_request_at_rps'])}",
         cells(lambda tier, t: f"{t['cpu_ms_per_request_graviton5']:.3f} ms")),
        (f"2. CPU in use at the baseline's rated load of {rps(round(w['load_rps'], -2))}: row 1 times the request rate, "
         "divided by 1,000",
         cells(lambda tier, t: f"{t['cores_at_load']:.1f} vCPUs")),
        (f"3. Capacity that keeps row 2 at {w['ceiling']:.0%} CPU utilization: row 2 divided by {w['ceiling']:g}",
         cells(lambda tier, t: f"**{t['capacity_needed']:.1f} {unit[tier]}**")),
        ("4. Capacity of the Graviton2 baseline",
         cells(lambda tier, t: f"{t['baseline_capacity']:g} {unit[tier]}")),
        ("5. One instance size down: half the baseline, as deployed in configuration C",
         cells(lambda tier, t: f"**{t['chosen_capacity']:g} {unit[tier]}**: {chosen[tier]}")),
        ("6. Two instance sizes down: a quarter of the baseline. Not deployed, and for the API tier not deployable "
         "with pods of 1.75 vCPUs",
         cells(lambda tier, t: f"{t['next_size_down']:.2g} {unit[tier]}: less than row 3")),
        ("7. Calculated CPU utilization at the rated load: row 2 divided by row 5",
         cells(lambda tier, t: f"{t['predicted_utilization']:.1%}")),
    ]
    note = (f"\nThe rows are computed from unrounded figures; the rated load is {w['load_rps']:,.1f} requests per second "
            f"before it is rounded to {round(w['load_rps'], -2):,.0f}.\n")
    if all("measured_utilization" in t for t in tiers.values()):
        at = next(iter(tiers.values()))["measured_at_rps"]
        rows.append((f"8. The same calculation for the comparison load of {rps(at)}",
                     cells(lambda tier, t: f"{t['calculated_utilization_at_measured_rate']:.1%}")))
        rows.append((f"9. Measured CPU utilization of configuration C at {rps(at)}: median of three 590-second runs",
                     cells(lambda tier, t: f"**{t['measured_utilization']:.1%}**")))
    return table(["Step"] + [TIER_TITLES[tier] for tier in tiers],
                 [[name] + [row[tier] for tier in tiers] for name, row in rows], {1, 2, 3}) + note


# ---- Step 4: the comparison at the baseline's rated load -------------------------------------------


def rated_load(rated: dict) -> str:
    """Every configuration at the comparison rate."""
    compared = {entry["letter"]: entry for entry in rated["stages"].values()}
    letters = tuple(letter for letter in ("A", "B", "C") if letter in compared)

    def cells(make) -> dict:
        return {letter: make(compared[letter]) for letter in letters}

    def node(entry: dict) -> str:
        nodes = {tier: value for tier, value in entry["busiest_node"].items() if value is not None}
        tier = max(nodes, key=nodes.get)
        return f"{nodes[tier]:.1%}, a{'n' if tier == 'api' else ''} {'API' if tier == 'api' else tier} node"

    def per_request(tier: str):
        return lambda e: spread(e["cpu_ms_per_request"][tier], " ms", 3)

    rows = [
        ("Request rate", cells(lambda e: rps(e["target_rps"]))),
        ("Runs", cells(lambda e: run_words(e).split(",")[0])),
        ("Achieved request rate, as a share of the target rate", cells(lambda e: spread(e["achieved_share"], "%", 2, 100))),
        ("Failed requests, as a share of the requests sent", cells(lambda e: spread(e["error_rate"], "%", 3, 100))),
        ("p50 response time", cells(lambda e: spread(e["latency_ms"]["p50"], " ms"))),
        ("p95 response time", cells(lambda e: spread(e["latency_ms"]["p95"], " ms"))),
        ("p99 response time", cells(lambda e: spread(e["latency_ms"]["p99"], " ms"))),
        ("Web tier: CPU utilization, as a share of the web nodes' vCPUs",
         cells(lambda e: spread(e["utilization"]["web"], "%", 1, 100))),
        ("API tier: CPU utilization, as a share of the API pods' CPU limits",
         cells(lambda e: spread(e["utilization"]["api"], "%", 1, 100))),
        ("Database writer: CPU utilization, as a share of its vCPUs",
         cells(lambda e: spread(e["utilization"]["db"], "%", 1, 100))),
        ("CPU utilization of the busiest tier: the highest of the three figures above",
         cells(lambda e: f"**{e['busiest_utilization']:.1%}**, {TIER_WORDS[e['busiest_tier']]}")),
        ("CPU utilization of the busiest single node in any run, measured the same way", cells(node)),
        ("API containers: share of their scheduling periods in which the CPU limit stopped them, counted over each "
         "run as a whole",
         cells(lambda e: spread(e["api_throttled_share"], "%", 1, 100) if e["source"] == "runs"
               else f"{e['api_throttled_share']['median']:.1%} over its whole staircase")),
        ("Web tier: CPU time per request", cells(per_request("web"))),
        ("API tier: CPU time per request", cells(per_request("api"))),
        ("Database writer: CPU time per request", cells(per_request("db"))),
    ]
    note = "\nFigures of several runs are the median, with the lowest and highest run in brackets."
    step = [letter for letter in letters if compared[letter]["source"] != "runs"]
    if step:
        entry = compared[step[0]]
        note += (f" Configuration {step[0]} was not run at {rps(rated['rate_rps'])}: its column is one "
                 f"{entry['seconds_per_run'][0]:.0f}-second step of its capacity run at {rps(entry['target_rps'])}, "
                 "from the first session, shown for reference.")
    return by_config("Measure", rows, letters) + note + "\n"


def criteria_rated(rated: dict) -> str:
    """The decision rule of the second session: C against A at the comparison rate."""
    if not rated.get("criteria"):
        return ""
    rows = []
    for row in rated["criteria"]:
        if row["unit"] == "ms":
            value, base, change = f"{row['value']:.1f} ms", f"{row['baseline']:.1f} ms", f"{row['change']:+.0%}"
        elif row["criterion"].startswith("Error"):
            value, base = f"{row['value']:.3%} of requests", f"{row['baseline']:.3%} of requests"
            change = f"{(row['value'] - row['baseline']) * 100:+.3f} percentage points"
        elif row["criterion"].startswith("Achieved"):
            value, base = f"{row['value']:.2%} of the target rate", f"{row['baseline']:.2%} of the target rate"
            change = "not used: the threshold is absolute"
        else:
            names = {"web": "web tier", "api": "API tier", "db": "database writer"}
            value, base = f"{row['value']:.1%}, {names[row['tier']]}", f"{row['baseline']:.1%}, {names[row['baseline_tier']]}"
            change = f"{(row['value'] - row['baseline']) * 100:+.1f} percentage points"
        rows.append([row["criterion"].replace(", share of the target rate", "").replace(", share of requests", ""),
                     base, value, change, row["threshold"][0].upper() + row["threshold"][1:],
                     "**Met**" if row["met"] else "**Not met**"])
    a, c = rated["stages"]["a-graviton2-baseline"], rated["stages"]["c-graviton5-right-sized"]
    def runs(entry: dict) -> str:
        return "one run" if len(entry["runs"]) == 1 else f"median of {len(entry['runs'])} runs"

    rows[-1][0] = "CPU utilization of the busiest tier: the highest of the three tier medians"
    return table([f"Criterion at {rps(rated['rate_rps'])}", f"A: Graviton2 baseline, {runs(a)}",
                  f"C: Graviton5, right-sized, {runs(c)}", "Difference", "Threshold for C", "Result"],
                 rows, {1, 2, 3})


# ---- Headroom ------------------------------------------------------------------------------------


def headroom(by_letter: dict, ceiling: dict, rated: dict) -> str:
    """What each configuration has above the comparison load: its rated load, and how far the
    staircase went beyond it."""
    rate = rated["rate_rps"]
    base = ceiling["stages"][STAGE_OF["A"]]

    def cells(make) -> dict:
        return {letter: make(letter, ceiling["stages"][STAGE_OF[letter]], by_letter[letter]) for letter in by_letter}

    def ceiling_run(letter, own, entry) -> str:
        run = own["ceiling_run"]
        return (f"{rps(run['target_rps'])}: {TIER_WORDS[run['busiest_tier']]} at {run['busiest_utilization']:.1%} CPU "
                f"utilization, p99 response time {run['p99_ms']:.1f} ms, {run['error_rate']:.2%} of requests failed")

    def against(letter, own, entry) -> str:
        if letter == "A":
            return ""
        return f"{own['rated_rps'] / base['rated_rps']:.2f} times ({own['rated_rps'] / base['rated_rps'] - 1:+.0%})"

    def room(letter, own, entry) -> str:
        extra = own["rated_rps"] - rate
        return f"{extra:+,.0f} requests per second ({own['rated_rps'] / rate - 1:+.0%})"

    def step(letter, own, entry) -> str:
        capacity = entry["capacity"]
        return ("at least " if capacity["limit_not_reached"] else "") + rps(capacity["mst_rps"])

    def failing(letter, own, entry) -> str:
        capacity = entry["capacity"]
        first = capacity.get("first_failing_step")
        if not first:
            return "none: it passed every step"
        found = next(s for s in capacity["steps"] if s["target_rps"] == first["target_rps"])
        why = (f"{found['error_rate']:.0%} of requests failed" if (found["error_rate"] or 0) > 0.001
               else f"p99 response time {found['p99_ms']:,.0f} ms")
        return f"{rps(first['target_rps'])}: {why}"

    def margin(letter, own, entry) -> str:
        capacity = entry["capacity"]
        return ("at least " if capacity["limit_not_reached"] else "") + f"{capacity['mst_rps'] / own['rated_rps'] - 1:+.0%}"

    compared = {entry["letter"]: entry for entry in rated["stages"].values()}

    def later(letter, own, entry) -> str:
        at_rate = compared.get(letter)
        if not at_rate:
            return ""
        if at_rate["source"] != "runs":
            return (f"not given: one step, at {rps(at_rate['target_rps'])} and "
                    f"{at_rate['busiest_utilization']:.0%} CPU utilization")
        scaled = at_rate["rating_from_these_runs_rps"]["median"]
        return (f"about {rps(round(scaled, -2))}, scaled from {at_rate['busiest_utilization']:.0%} CPU utilization "
                f"in {len(at_rate['runs'])} runs")

    rows = [
        ("Ceiling run, 590 seconds", cells(ceiling_run)),
        ("**Rated load:** the rate of that run, scaled to 80% CPU utilization of the busiest tier",
         cells(lambda letter, own, entry: f"**about {rps(own['rated_rps'])}**")),
        ("Rated load against the baseline's", cells(against)),
        (f"Rated load above the comparison load of {rps(rate)}", cells(room)),
        (f"For comparison: the rating that the runs at {rps(rate)} point to, their rate scaled to 80% CPU utilization",
         cells(later)),
        ("Highest passing step of the staircase, 110 seconds per step", cells(step)),
        ("First failing step", cells(failing)),
        ("From the rated load to the highest passing step", cells(margin)),
    ]
    note = ("\nThe ratios and differences in this table are those of the reported rated loads, which are rounded to "
            "100 requests per second, so that they can be recomputed from the table.\n")
    return by_config("", rows, tuple(by_letter)) + note


def node_out(rated: dict) -> str:
    """The right-sized stack with one of its two web nodes out of service."""
    n = rated.get("one_web_node_out")
    if not n or "both_nodes" not in n:
        return ""
    both = n["both_nodes"]
    nodes_left = sum(1 for pods in n["web_pods_per_node"] if pods > 0)   # the nodes that still run web pods
    rows = [
        ["Web pods running", f"{n['web_pods_wanted']} of {n['web_pods_wanted']} pods",
         f"{n['web_pods_running']} of {n['web_pods_wanted']} pods"],
        ["Achieved request rate, as a share of the target rate", f"{both['achieved_share']:.2%}", f"{n['achieved_share']:.2%}"],
        ["Failed requests, as a share of the requests sent", f"{both['error_rate']:.3%}", f"{n['error_rate']:.3%}"],
        ["p50 response time", f"{both['p50_ms']:.1f} ms", f"{n['p50_ms']:.1f} ms"],
        ["p95 response time", f"{both['p95_ms']:.1f} ms", f"{n['p95_ms']:.1f} ms"],
        ["p99 response time", f"{both['p99_ms']:.1f} ms", f"{n['p99_ms']:.1f} ms"],
        ["CPU utilization of the web nodes in service, as a share of their vCPUs",
         f"{both['web_utilization']:.1%} of two nodes",
         f"{n['surviving_node_utilization']:.1%} of {'one node' if nodes_left == 1 else f'{nodes_left} nodes'}"],
        ["Within the limits of the staircase", "yes", "yes" if n["within_limits"] else "no: " + "; ".join(n["reasons"])],
    ]
    return table([f"Measure at {rps(n['target_rps'])}, one run of {n['seconds']:.0f} seconds each",
                  f"Both web nodes in service (`{both['run']}`)", f"One web node out of service (`{n['run']}`)"], rows, {1, 2})


# ---- Do the results repeat? --------------------------------------------------------------------------


SESSION_MEASURES = (
    ("p50_ms", "p50 response time", " ms", 2, 1), ("p95_ms", "p95 response time", " ms", 2, 1),
    ("p99_ms", "p99 response time", " ms", 2, 1),
    ("cpu_ms_per_request_web", "Web tier: CPU time per request", " ms", 3, 1),
    ("cpu_ms_per_request_api", "API tier: CPU time per request", " ms", 3, 1),
    ("cpu_ms_per_request_db", "Database writer: CPU time per request", " ms", 3, 1),
    ("utilization_web", "Web tier: CPU utilization", "%", 1, 100),
    ("utilization_api", "API tier: CPU utilization", "%", 1, 100),
    ("utilization_db", "Database writer: CPU utilization", "%", 1, 100),
)


def sessions(rated: dict, key: str) -> str:
    """One configuration at one request rate in both sessions."""
    entry = (rated.get("sessions") or {}).get(key)
    if not entry:
        return ""

    def when(part: dict) -> str:
        runs = len(part["runs"])
        day = f"{int(part['from'][8:10])} Nov, {part['from'][11:16]} to {part['to'][11:16]} UTC"
        return f"{'one run' if runs == 1 else f'median of {runs} runs (lowest to highest)'}, on {day}"

    rows = []
    for name, title, unit, digits, scale in SESSION_MEASURES:
        m = entry["measures"][name]
        if unit == "%":
            change = f"{m['difference'] * 100:+.1f} percentage points"
        else:
            change = f"{m['change']:+.1%}"
        rows.append([title, spread(m["first"], unit, digits, scale), spread(m["second"], unit, digits, scale), change])
    return table([f"Measure at {rps(entry['rate_rps'])}", f"First session (23 to 24 Nov): {when(entry['first'])}",
                  f"Second session (24 Nov): {when(entry['second'])}", "Difference"], rows, {1, 2, 3})


def again(by_letter: dict) -> str:
    """The baseline deployed again within the first session: does it reproduce the first deployment?"""
    entry = by_letter.get("A", {}).get("again", {}).get("same_placement")
    if not entry:
        return ""
    rows = []

    def inside(value: dict) -> str:
        return "yes" if value["reference_min"] <= value["value"] <= value["reference_max"] else "no"

    for name, value in entry["latency_ms"].items():
        rows.append([f"{name} response time",
                     f"{value['reference']:.2f} ms ({value['reference_min']:.2f} to {value['reference_max']:.2f})",
                     f"{value['value']:.2f} ms", f"{value['change']:+.1%}", inside(value)])
    for tier, title in (("web", "Web tier: CPU time per request"), ("api", "API tier: CPU time per request"),
                        ("db_writer", "Database writer: CPU time per request")):
        value = entry["tiers"].get(tier)
        if value:
            rows.append([title, f"{value['reference']:.3f} ms ({value['reference_min']:.3f} to {value['reference_max']:.3f})",
                         f"{value['value']:.3f} ms", f"{value['change']:+.1%}", inside(value)])

    def span(start: str, end: str) -> str:
        day = "" if start[:10] == end[:10] else f" on {int(end[8:10])} Nov"
        return f"{int(start[8:10])} Nov, {start[11:16]} to {end[11:16]}{day} UTC"

    return table(["Measure at 8,000 requests per second",
                  f"First deployment: median of three runs (lowest to highest), {span(entry['reference_from'], entry['reference_to'])}",
                  f"Deployed again: one run, {span(entry['from'], entry['to'])}", "Difference",
                  "Inside the first deployment's range"], rows, {1, 2, 3})


def placement(by_letter: dict) -> str:
    """The same deployment of the baseline with one and with two of its three API nodes in
    the database writer's Availability Zone."""
    entry = by_letter.get("A", {}).get("again", {}).get("other_placement")
    if not entry:
        return ""
    rows = [[f"{name} response time", f"{value['reference']:.2f} ms", f"{value['value']:.2f} ms",
             f"{value['value'] - value['reference']:+.2f} ms"] for name, value in entry["latency_ms"].items()]
    return table(["Measure at 8,000 requests per second, one run of 590 seconds each",
                  "One API node of three in the writer's zone (`a2-r1`)",
                  "Two API nodes of three in the writer's zone (`a2p-r1`)", "Difference"], rows, {1, 2, 3})


# ---- The lighter load of the first session ---------------------------------------------------------


def lighter_load(by_letter: dict, ceiling: dict) -> str:
    """The first session's runs at 8,000 requests per second: response time and CPU utilization."""
    pod_limit = ceiling["api_pod_cpu_limit"]
    chosen = {letter: entry["steady"] for letter, entry in by_letter.items() if entry.get("steady")}
    if not chosen:
        return ""

    def cells(make) -> dict:
        return {letter: make(steady) for letter, steady in chosen.items()}

    def api(steady: dict) -> str:
        limit = steady["pods"]["storefront-api"] * pod_limit
        cores = steady["tiers"]["api"]["cores_used"]
        return spread({key: cores[key] / limit for key in ("median", "min", "max")} | {"runs": cores["runs"]}, "%", 1, 100)

    rate = next(iter(chosen.values()))["target_rps"]
    rows = [
        ("Failed requests, of the requests sent in the three runs",
         cells(lambda s: f"{s['pooled']['failed']:,} of {s['pooled']['requests']:,}")),
        ("p50 response time", cells(lambda s: spread(s["latency_ms"]["p50"], " ms"))),
        ("p95 response time", cells(lambda s: spread(s["latency_ms"]["p95"], " ms"))),
        ("p99 response time", cells(lambda s: spread(s["latency_ms"]["p99"], " ms"))),
        ("Web tier: CPU utilization, as a share of the web nodes' vCPUs",
         cells(lambda s: spread(s["tiers"]["web"]["utilization"], "%", 1, 100))),
        ("API tier: CPU utilization, as a share of the API pods' CPU limits", cells(api)),
        ("Database writer: CPU utilization, as a share of its vCPUs",
         cells(lambda s: spread(s["tiers"]["db_writer"]["utilization"], "%", 1, 100))),
    ]
    rows[0] = ("Failed requests, counted over the three runs together", rows[0][1])
    return by_config(f"Measure at {rps(rate)}: median of three 590-second runs (lowest to highest)", rows, tuple(chosen))


def criteria_first_plan(entry: dict) -> str:
    """The criteria registered before the system was built, at the load of the first plan."""
    rows = []
    for row in entry.get("criteria", []):
        name = row["criterion"].replace(" at operating load", "").replace(
            "Achieved rate", "Achieved request rate (requests sent, failed ones included)").replace("latency", "response time")
        change = f"{row['change']:+.1%}" if "change" in row else ""
        if "rate" in name and "Error" not in name:
            measured, base = f"{row['value']:.2%} of the target rate", f"{row['baseline']:.2%} of the target rate"
        elif "Error" in name:
            measured, base = f"{row['value']:.3%} of requests", f"{row['baseline']:.3%} of requests"
        elif "throughput" in name:
            # A capacity run that passed its last step gives a lower bound, not a value.
            open_ended = bool(row.get("note"))
            measured = ("at least " if open_ended else "") + rps(row["value"])
            base = rps(row["baseline"])
            change = ("at least " if open_ended else "") + f"{row['change']:+.0%}"
            name = "Highest passing step of the capacity run"
        else:
            measured, base = f"{row['value']:.1f} ms", f"{row['baseline']:.1f} ms"
        threshold = row["threshold"].replace(">=", "at least").replace("<=", "at most").replace("pp", " percentage points")
        rows.append([name, base, measured, change, threshold, "**Met**" if row["met"] else "**Not met**"])
    note = ("\nThe first five rows are medians of three 590-second runs at 8,000 requests per second. The last row "
            "compares the two staircases, with 110 seconds measured per step.\n")
    return table(["Criterion of the first plan", "A: Graviton2 baseline",
                  f"Configuration {entry['letter']}", "Difference", "Threshold", "Result"], rows, {1, 2, 3}) + note


def capacity(stages: list[dict]) -> str:
    """One row per request rate that any configuration was tested at in its staircase."""
    rates = sorted({step["target_rps"] for entry in stages if entry.get("capacity")
                    for step in entry["capacity"]["steps"]})
    tested = [entry for entry in stages if entry.get("capacity")]
    rows = []
    for rate in rates:
        row = [f"{rate:,.0f}"]
        for entry in tested:
            step = next((s for s in entry["capacity"]["steps"] if s["target_rps"] == rate), None)
            if not step:
                row.append("")
            elif step["within_slo"]:
                row.append(f"{step['p99_ms']:.0f} ms")
            elif (step["error_rate"] or 0) > 0.001:
                row.append(f"fails: {step['error_rate']:.0%} of requests failed")
            else:
                row.append(f"fails: {step['p99_ms']:,.0f} ms")
        rows.append(row)
    return table(["Request rate of the step, requests per second"]
                 + [f"{NAMES[entry['letter']]}: p99 response time" for entry in tested], rows, set(range(len(tested) + 1)))


# ---- Cost ------------------------------------------------------------------------------------------


def usage_basis(items: list[dict]) -> str:
    """Quantity times unit price of a line outside the instances, and where the quantity comes from."""
    first = items[0]

    def number(value: float) -> str:
        return f"{value:,.0f}" if value >= 100 or value == int(value) else f"{value:,.1f}"

    quantities = sorted({round(item["quantity"], 1) for item in items})
    amount = number(quantities[0]) if len(quantities) == 1 else f"{number(quantities[0])} to {number(quantities[-1])}"
    unit = {"secrets": "secret", "million requests": "million I/Os"}.get(first["unit"], first["unit"])
    price = first["unit_usd"]
    rate = f"{price:.4f}".rstrip("0")
    rate = "$" + (rate + "0" if len(rate.split(".")[1]) < 2 else rate)
    per = {"million requests": "million", "cluster-hours": "cluster-hour", "GB-months": "GB-month", "hours": "hour",
           "LCU-hours": "LCU-hour", "secrets": "secret per month", "instance-hours": "instance-hour"}
    if first["item"].startswith("Data transfer"):
        return f"{amount} GB at the tiered rate ($0.09 per GB for the first 10,240 GB, then $0.085 per GB); {first['note']}"
    text = f"{amount} {unit} x {rate} per {per[first['unit']]}"
    return f"{text}; {first['note']}" if first["note"] else text


def bill(bom: dict, letters: tuple[str, ...], pricing: str, collapse: tuple[str, ...] = ()) -> str:
    """The bill of materials. Groups named in `collapse` are shown as one line, their subtotal:
    the committed bill uses it for the lines that are the same as in the On-Demand bill."""
    by_letter = {entry["title"][0]: entry for entry in bom["stages"].values()}
    chosen = [by_letter[letter] for letter in letters]
    rows = []
    count = len(chosen[0][pricing]["rows"])
    group = None
    for index in range(count):
        items = [entry[pricing]["rows"][index] for entry in chosen]
        first = items[0]
        if first["group"] in collapse:
            if first["group"] != group:
                group = first["group"]
                rows.append([f"{group}: the same lines and amounts as in the On-Demand bill"]
                            + [money(entry[pricing]["groups"][group]) for entry in chosen] + ["Not covered by a commitment"])
            continue
        if first["group"] != group:
            group = first["group"]
            rows.append([f"**{group}**"] + [""] * (len(chosen) + 1))
        # The instance lines differ per configuration; name the role once and show each type in its column.
        if first["group"] == "Compute and database":
            role = first["item"].split(":")[0]
            cells = [f"{item['item'].split(': ')[1]}<br>{money(item['monthly_usd'])}" for item in items]
            notes = {item["note"] for item in items}
            if pricing == "on_demand":
                basis = f"{HOURS} hours x the On-Demand rate per instance-hour"
            elif len(notes) == 1:
                basis = f"{HOURS} hours; {first['note']}"
            else:
                # The configurations do not all get the same kind of price: say which in each cell.
                cells = [f"{cell}<br>{item['note'].split(',')[0]}" for cell, item in zip(cells, items)]
                basis = f"{HOURS} hours; one year, no upfront, where AWS offered it"
        else:
            role = first["item"]
            cells = [money(item["monthly_usd"]) if item["monthly_usd"] >= 1 else f"${item['monthly_usd']:.2f}"
                     for item in items]
            basis = usage_basis(items)
        rows.append([role] + cells + [basis])
        last_of_group = index + 1 == count or chosen[0][pricing]["rows"][index + 1]["group"] != group
        if last_of_group:
            rows.append([f"*Subtotal: {group.lower()}*"]
                        + [f"*{money(entry[pricing]['groups'][group])}*" for entry in chosen] + [""])
    rows.append(["**Total per month**"] + [f"**{money(entry[pricing]['total'])}**" for entry in chosen] + [""])
    baseline = chosen[0][pricing]["total"]
    rows.append(["Difference from A"] + ["" if i == 0 else f"{entry[pricing]['total'] / baseline - 1:+.1%}"
                                          for i, entry in enumerate(chosen)] + [""])
    return table(["Line item, in US dollars per month"] + [NAMES[letter] for letter in letters]
                 + ["Quantity and unit price"], rows, set(range(1, len(chosen) + 1)))


def unit_prices(prices: dict) -> str:
    pairs = [("c6g.4xlarge", "c9g.4xlarge", "ec2"), ("m6g.xlarge", "m9g.xlarge", "ec2"),
             ("m6g.large", "m9g.large", "ec2"),
             ("db.r6g.8xlarge", "db.r9g.8xlarge", "aurora"), ("c6g.4xlarge", "c9g.2xlarge", "ec2"),
             ("m6g.xlarge", "m9g.large", "ec2"), ("db.r6g.8xlarge", "db.r9g.4xlarge", "aurora")]
    rows = []
    for old, new, kind in pairs:
        if kind == "ec2":
            before, after = prices["ec2"][old]["usd"], prices["ec2"][new]["usd"]
            vcpus = f"{prices['ec2'][old]['vcpu']} to {prices['ec2'][new]['vcpu']}"
        else:
            before = prices["aurora_mysql"][old]["standard"]["usd"]
            after = prices["aurora_mysql"][new]["standard"]["usd"]
            vcpus = f"{prices['aurora_mysql'][old]['standard']['vcpu']} to {prices['aurora_mysql'][new]['standard']['vcpu']}"
        rows.append([f"`{old}` to `{new}`", vcpus, f"${before:.4f}", f"${after:.4f}", f"{after / before - 1:+.1%}"])
    return table(["Instance type, from Graviton2 to Graviton5", "vCPUs per instance",
                  "Graviton2: On-Demand price per instance-hour", "Graviton5: On-Demand price per instance-hour",
                  "Difference in price"], rows, {1, 2, 3, 4})


def sensitivity(bom: dict) -> str:
    """How far the bill's comparison moves when its assumptions do."""
    a, b, c = STAGE_OF["A"], STAGE_OF["B"], STAGE_OF["C"]
    rows = []

    def row(name: str, totals: dict) -> None:
        rows.append([name, money(totals[a]), money(totals[b]), money(totals[c]),
                     f"{totals[b] / totals[a] - 1:+.1%}", f"{totals[c] / totals[a] - 1:+.1%}"])

    load = bom["load_sensitivity"]
    assumed = str(bom["usage"]["average_rps"])
    at_comparison = (load.get("comparison_load") or {}).get("average_requests_per_second")
    for rate, scenario in load.items():
        if rate == "comparison_load":   # the same scenario under a second name
            continue
        totals = {k: v["total"] for k, v in scenario["stages"].items()}
        if rate == assumed:
            rows.insert(0, [])
            row(f"**As in the bill:** an average of {rps(float(rate))}", totals)
            rows[0] = rows.pop()
        elif scenario["average_requests_per_second"] == at_comparison:
            row(f"An average of {rps(float(rate))}: the comparison load around the clock", totals)
        else:
            row(f"An average of {rps(float(rate))}", totals)
    row("Without the data transfer line", {k: v["total"] for k, v in bom["without_data_transfer"].items()})
    io = bom["io_sensitivity"]
    row(f"Aurora I/O at the lowest ratio of a single block, {io['lowest_block']['billed_per_operation']:.2f} billed I/Os "
        f"per write operation (in the bill: {bom['io_ratio']['billed_per_operation']:.2f})",
        {k: v["total"] for k, v in io["lowest_block"]["stages"].items()})
    row(f"Aurora I/O at the highest ratio of a single block, {io['highest_block']['billed_per_operation']:.2f} billed I/Os "
        "per write operation",
        {k: v["total"] for k, v in io["highest_block"]["stages"].items()})
    optimized = bom["aurora_io_optimized"]
    totals = {k: bom["stages"][k]["on_demand"]["total"] for k in (a, b)}
    totals[c] = optimized[c]["total_with_io_optimized"]
    row("C on Aurora I/O-Optimized, A and B on Aurora Standard", totals)
    return table(["Assumption", "A: bill per month", "B: bill per month", "C: bill per month", "B against A",
                  "C against A"], rows, {1, 2, 3, 4, 5})


def derived(stages: list[dict], ceiling: dict, bom: dict) -> str:
    """Cost per unit of work: per million requests at the traffic the bill assumes, and the
    instances per 1,000 requests per second of rated load. The whole bill is not divided by
    the rated load: its usage lines are priced for the assumed traffic, not for a month at
    the rating."""
    rows = []
    for entry in stages:
        extra, cost = entry.get("derived", {}), entry.get("cost")
        if not cost:
            continue
        own = ceiling["stages"][STAGE_OF[entry["letter"]]]
        rows.append([f"**{NAMES[entry['letter']]}**", money(cost["on_demand_total"]) + " per month",
                     f"${extra['cost_per_million_requests']:.2f} per million requests",
                     money(cost["on_demand_groups"]["Compute and database"]) + " per month",
                     f"about {rps(own['rated_rps'])}",
                     money(own["cost"]["compute_database_per_1000_rps"]) + " per month"])
    return table(["Configuration", "Modelled On-Demand bill of the whole stack",
                  f"Bill per million requests, at an average of {rps(bom['usage']['average_rps'])}",
                  "EC2 and Aurora instances, On-Demand", "Rated load at 80% CPU utilization",
                  "Monthly instance cost per 1,000 requests per second of rated load"], rows, {1, 2, 3, 4, 5})


def main() -> None:
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    comparison = json.loads((ROOT / "results/comparison.json").read_text())
    bom = json.loads((ROOT / "results/bom.json").read_text())
    prices = json.loads((ROOT / "results/pricing/us-west-2.json").read_text())
    ceiling = json.loads((ROOT / "results/ceiling.json").read_text())
    rated = json.loads((ROOT / "results/rated.json").read_text())
    stages = list(comparison["stages"].values())
    by_letter = {entry["letter"]: entry for entry in stages}
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.md"):
        old.unlink()
    fragments = {
        "summary": summary(by_letter, ceiling, rated, bom),
        "configurations": configurations(bom, prices),
        "rating-baseline": rating(ceiling, "A"),
        "rating-right-sized": rating(ceiling, "C"),
        "cpu-per-request": cpu_per_request(by_letter, rated),
        "work-backwards": work_backwards(rated, bom),
        "rated-load": rated_load(rated),
        "criteria-rated-load": criteria_rated(rated),
        "headroom": headroom(by_letter, ceiling, rated),
        "one-web-node-out": node_out(rated),
        "sessions-baseline": sessions(rated, "a"),
        "sessions-right-sized": sessions(rated, "c"),
        "again": again(by_letter),
        "placement": placement(by_letter),
        "lighter-load": lighter_load(by_letter, ceiling),
        "capacity": capacity(stages),
        "unit-prices": unit_prices(prices),
        "bom-on-demand": bill(bom, ("A", "B", "C"), "on_demand"),
        "bom-committed": bill(bom, ("A", "B", "C"), "committed", collapse=("Rest of the stack",)),
        "sensitivity": sensitivity(bom),
        "derived": derived(stages, ceiling, bom),
    }
    for letter in ("B", "C"):
        if by_letter.get(letter, {}).get("criteria"):
            fragments[f"criteria-first-plan-{letter.lower()}"] = criteria_first_plan(by_letter[letter])
    for name, text in fragments.items():
        if text:
            (OUT / f"{name}.md").write_text(text)
            print(f"wrote report/tables/{name}.md")


if __name__ == "__main__":
    main()

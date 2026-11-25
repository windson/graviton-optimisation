#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""The comparison at the baseline's rated load (docs/02-experiment-protocol.md, section 14).

    uv run analysis/rated.py        # writes results/rated.json and prints the tables

The first session rated every configuration at an 80% CPU ceiling (analysis/ceiling.py).
The second holds the baseline and the right-sized Graviton5 stack at one request rate, the
rate of the baseline's ceiling run, and this script puts those runs next to each other:

  - each configuration at that rate: latency, errors, and the CPU utilization of each tier
    by the rule of section 12 (web: share of the web nodes' vCPUs; API: share of the API
    pods' CPU limits; database: CloudWatch CPUUtilization of the writer);
  - the acceptance criteria of section 8 applied at that rate, plus the ceiling itself;
  - the sizes that follow from the baseline's rated load and the CPU each request costs on
    Graviton5, against the sizes that were deployed ("working backwards");
  - the run with one of the two web nodes out of service.

Run after analysis/compare.py and analysis/ceiling.py.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ceiling as rule  # noqa: E402
import compare  # noqa: E402

# The runs at the comparison rate. The baseline's first one is the ceiling run that rates
# it, and the rate of that run is the comparison rate (section 14): both are read from the
# recorded runs (analysis/ceiling.py, baseline_rating_run), so that the analysis cannot
# compare at another rate than the runs were made at.
SECOND_SESSION = {
    "a-graviton2-baseline": ("a3-rated-1", "a3-rated-2"),
    "c-graviton5-right-sized": ("c2-rated-1", "c2-rated-2", "c2-rated-3"),
}
# Not deployed again: the nearest step of its capacity run stands in, and is labelled as that.
STEP = {"b-graviton5-same-size": "b-cap"}


def rating_run() -> dict:
    run = rule.baseline_rating_run() if (ROOT / "results/a-graviton2-baseline").exists() else None
    if not run:
        raise SystemExit("the baseline has no ceiling run that counts: there is no comparison rate")
    return run


def comparison_rate() -> float:
    return rating_run()["target_rps"]


def runs_at_the_comparison_rate() -> dict:
    return {"a-graviton2-baseline": (rating_run()["run"],) + SECOND_SESSION["a-graviton2-baseline"],
            "c-graviton5-right-sized": SECOND_SESSION["c-graviton5-right-sized"]}
NODE_OUT = ("c-graviton5-right-sized", "c2n-r1", "c2-r1")  # stage, the run, the same rate on both nodes
TIERS = ("web", "api", "db")
TIER_NAMES = {"web": "Web", "api": "API", "db": "Database writer"}
CPU_KEYS = {"web": "web", "api": "api", "db": "db_writer"}


def load(path: pathlib.Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def busiest_node(summary: dict, window: dict, directory: pathlib.Path) -> dict:
    """The busiest node of each tier, measured as the tier is: a web node against its vCPUs,
    an API node against the CPU limits of the API pods that run on it."""
    tiers = window["tiers"]
    out = {"web": max(tiers["web"]["node_utilization"])}
    containers: dict[str, int] = {}
    for line in (directory / "kubelet.jsonl").read_text().splitlines():
        sample = json.loads(line)
        if sample["tier"] == "api":
            containers[sample["node"]] = sample["app_containers"]
    per_node = set(containers.values())
    if len(per_node) != 1:
        # The per-node figures of a window are not labelled with the node: an uneven spread
        # of the pods cannot be assigned, and is reported as missing instead of guessed.
        out["api"] = None
        return out
    limit = per_node.pop() * rule.api_pod_cpu_limit()
    vcpus = tiers["api"]["vcpus"] / tiers["api"]["nodes"]
    out["api"] = max(tiers["api"]["node_utilization"]) * vcpus / limit
    return out


def row(summary: dict, window: dict, directory: pathlib.Path | None = None) -> dict:
    """One measured window, reduced to what is compared."""
    client, tiers = window["client"], window["tiers"]
    extra = {"busiest_node": busiest_node(summary, window, directory)} if directory else {}
    shares = rule.utilization(window, summary["shape"]["pods"])
    tier, share = rule.busiest(shares)
    # What this window alone would rate the configuration at: its rate scaled to the ceiling.
    extra.update({"busiest_tier": tier, "busiest_utilization": share,
                  "rating_rps": window["achieved_rps"] * rule.CEILING / share})
    return {
        **extra,
        "run": summary["name"], "from": window["from"], "to": window["to"], "seconds": window["seconds"],
        "target_rps": window["target_rps"], "achieved_rps": window["achieved_rps"],
        "achieved_share": window["achieved_share"], "error_rate": client["error_rate"] or 0.0,
        "p50_ms": client["p50_ms"], "p95_ms": client["p95_ms"], "p99_ms": client["p99_ms"],
        "utilization": rule.utilization(window, summary["shape"]["pods"]),
        "node_utilization": {tier: tiers.get(tier, {}).get("node_utilization") for tier in ("web", "api")},
        "cpu_ms_per_request": {tier: tiers.get(CPU_KEYS[tier], {}).get("cpu_ms_per_request") for tier in TIERS},
        "buffer_cache_hit_ratio": tiers.get("db_writer", {}).get("buffer_cache_hit_ratio"),
        "generator_peak_cpu_share": (summary.get("generator") or {}).get("peak_cpu_share"),
        "tasks": summary["tasks"],
        # Share of the API containers' scheduling periods in which their CPU limit stopped
        # them, counted over the whole run it belongs to (a staircase as a whole).
        "api_throttled_share": ((summary.get("cpu_throttling") or {}).get("api") or {}).get("throttled_share"),
        # The percentiles above are over all operations together; per operation they differ.
        "operations_p99_ms": {name: operation["p99_ms"] for name, operation in window.get("operations", {}).items()},
    }


def combine(rows: list[dict]) -> dict:
    out = {
        "runs": [r["run"] for r in rows],
        "seconds_per_run": [r["seconds"] for r in rows],
        "target_rps": rows[0]["target_rps"],
        "achieved_share": compare.spread([r["achieved_share"] for r in rows]),
        "error_rate": compare.spread([r["error_rate"] for r in rows]),
        "latency_ms": {name: compare.spread([r[f"{name}_ms"] for r in rows]) for name in ("p50", "p95", "p99")},
        "utilization": {tier: compare.spread([r["utilization"].get(tier) for r in rows]) for tier in TIERS},
        "api_pods_only": compare.spread([r["utilization"].get("api_pods_only") for r in rows]),
        "cpu_ms_per_request": {tier: compare.spread([r["cpu_ms_per_request"][tier] for r in rows]) for tier in TIERS},
        "api_throttled_share": compare.spread([r["api_throttled_share"] for r in rows]),
        "busiest_node": {tier: max((r["busiest_node"][tier] for r in rows
                                    if r.get("busiest_node") and r["busiest_node"][tier] is not None), default=None)
                         for tier in ("web", "api")},
        "per_run": rows,
    }
    # The busiest tier of a configuration is the tier with the highest median over its runs.
    busiest = max(TIERS, key=lambda tier: out["utilization"][tier]["median"] or 0.0)
    out["busiest_tier"] = busiest
    out["busiest_utilization"] = out["utilization"][busiest]["median"]
    ranked = sorted((out["utilization"][tier]["median"] or 0.0 for tier in TIERS), reverse=True)
    out["second_busiest_tier"] = next(tier for tier in TIERS if (out["utilization"][tier]["median"] or 0.0) == ranked[1])
    out["second_busiest_utilization"] = ranked[1]
    # What these runs alone would rate the configuration at: each run's rate scaled to the
    # ceiling by its own busiest tier, and the same by its busiest single node.
    out["rating_from_these_runs_rps"] = compare.spread([r["rating_rps"] for r in rows])
    by_node = [r["achieved_rps"] * rule.CEILING / max(v for v in r["busiest_node"].values() if v is not None)
               for r in rows if r.get("busiest_node") and any(v is not None for v in r["busiest_node"].values())]
    if by_node:
        out["rating_by_busiest_node_rps"] = compare.spread(by_node)
    return out


def measured(stage: str) -> dict | None:
    rows, missing = [], []
    for name in RUNS[stage]:
        directory = ROOT / "results" / stage / name
        summary = load(directory / "summary.json")
        if not summary or summary["status"] != "complete":
            missing.append(name)
            continue
        if abs(summary["windows"][0]["target_rps"] - RATE) >= 1:
            raise SystemExit(f"{name} was run at {summary['windows'][0]['target_rps']:,.0f} requests per second; "
                             f"the comparison rate is {RATE:,.0f}")
        rows.append(row(summary, summary["windows"][0], directory))
    if not rows:
        return None
    out = combine(rows)
    out.update({"source": "runs", "missing_runs": missing})
    return out


def from_step(stage: str) -> dict | None:
    run = STEP[stage]
    summary = load(ROOT / "results" / stage / run / "summary.json")
    if not summary:
        return None
    window = min(summary["windows"], key=lambda w: abs(w["target_rps"] - RATE))   # the step nearest to the rate
    out = combine([row(summary, window, ROOT / "results" / stage / run)])
    out.update({"source": "capacity step", "step_run": run, "missing_runs": []})
    return out


def criteria(candidate: dict, baseline: dict, limit: float) -> list[dict]:
    """The criteria of section 8 at the comparison rate, and the ceiling of section 12."""
    c = compare.CRITERIA
    rows = []
    share = candidate["achieved_share"]["median"]
    rows.append({"criterion": "Achieved request rate, share of the target rate", "unit": "share", "value": share,
                 "baseline": baseline["achieved_share"]["median"],
                 "threshold": f"at least {c['min_achieved_share']:.1%}", "met": share >= c["min_achieved_share"]})
    error, base_error = candidate["error_rate"]["median"], baseline["error_rate"]["median"]
    rows.append({"criterion": "Error rate, share of requests", "unit": "share", "value": error, "baseline": base_error,
                 "threshold": f"at most {c['max_error_rate']:.1%}, and at most the baseline's plus 0.05 percentage points",
                 "met": error <= c["max_error_rate"] and error <= base_error + c["max_error_rate_over_baseline"]})
    for name, key in (("p50", "max_p50_increase"), ("p95", "max_p95_increase"), ("p99", "max_p99_increase")):
        value, base = candidate["latency_ms"][name]["median"], baseline["latency_ms"][name]["median"]
        rows.append({"criterion": f"{name} response time", "unit": "ms", "value": value, "baseline": base,
                     "change": value / base - 1, "threshold": f"at most {c[key]:.0%} above the baseline's",
                     "met": value / base - 1 <= c[key]})
    busiest = candidate["busiest_utilization"]
    # The median of the runs decides, as registered. The highest single run is kept next to it.
    highest = max(max(r["utilization"][tier] for tier in TIERS if r["utilization"].get(tier) is not None)
                  for r in candidate["per_run"])
    rows.append({"criterion": "CPU utilization of the busiest tier",
                 "unit": "share", "value": busiest, "baseline": baseline["busiest_utilization"],
                 "tier": candidate["busiest_tier"], "baseline_tier": baseline["busiest_tier"],
                 "highest_in_a_run": highest,
                 "threshold": f"at most {limit:.0%}", "met": busiest <= limit})
    return rows


def expected(stage: str, prefix: str) -> dict | None:
    """What the first session's capacity run predicts at the comparison rate: interpolated
    between the steps on either side of it."""
    summary = load(ROOT / "results" / stage / f"{prefix}-cap" / "summary.json")
    if not summary:
        return None
    steps = [row(summary, window) for window in summary["windows"]]
    for low, high in zip(steps, steps[1:]):
        if low["achieved_rps"] <= RATE <= high["achieved_rps"]:
            part = (RATE - low["achieved_rps"]) / (high["achieved_rps"] - low["achieved_rps"])
            between = lambda a, b: a + (b - a) * part  # noqa: E731
            utilization = {tier: between(low["utilization"][tier], high["utilization"][tier]) for tier in TIERS}
            busiest = max(TIERS, key=utilization.get)
            return {"between_steps_rps": [low["target_rps"], high["target_rps"]], "step_seconds": low["seconds"],
                    "utilization": utilization, "busiest_tier": busiest, "busiest_utilization": utilization[busiest],
                    **{f"{name}_ms": between(low[f"{name}_ms"], high[f"{name}_ms"]) for name in ("p50", "p95", "p99")}}
    return None


def work_backwards(stages: dict, rated: dict, comparison: dict) -> dict | None:
    """From the baseline's rated load to sizes: the CPU each tier needs on Graviton5 at that
    load, the capacity that keeps it at the ceiling, and the nearest sizes that exist."""
    baseline = rated["stages"]["a-graviton2-baseline"]
    same_size = comparison["stages"].get("b-graviton5-same-size", {}).get("steady")
    right_sized = comparison["stages"].get("c-graviton5-right-sized", {}).get("steady")
    if not same_size or not right_sized:
        return None
    load_rps, limit = baseline["rated_rps_exact"], rated["ceiling"]
    pod_limit = rated["api_pod_cpu_limit"]
    out = {"load_rps": load_rps, "ceiling": limit, "cpu_per_request_from": same_size["runs"],
           "cpu_per_request_at_rps": same_size["target_rps"], "tiers": {}}
    for tier in TIERS:
        key = CPU_KEYS[tier]
        cost_ms = same_size["tiers"][key]["cpu_ms_per_request"]["median"]
        # What each tier may use: the nodes' vCPUs, the pods' CPU limits, the writer's vCPUs.
        def capacity(steady: dict) -> float:
            return steady["pods"]["storefront-api"] * pod_limit if tier == "api" else steady["tiers"][key]["vcpus"]
        base_capacity = capacity(comparison["stages"]["a-graviton2-baseline"]["steady"])
        chosen = capacity(right_sized)
        cores = load_rps * cost_ms / 1000
        entry = {"cpu_ms_per_request_graviton5": cost_ms, "cores_at_load": cores, "capacity_needed": cores / limit,
                 "baseline_capacity": base_capacity, "needed_share_of_baseline": cores / limit / base_capacity,
                 "chosen_capacity": chosen, "next_size_down": chosen / 2, "predicted_utilization": cores / chosen}
        c_stage = stages.get("c-graviton5-right-sized")
        if c_stage and c_stage["source"] == "runs":
            # The runs were made at the comparison rate, a little below the rated load: the
            # calculation is repeated for that rate, so that like is compared with like.
            measured_at = c_stage["target_rps"]
            entry["measured_utilization"] = c_stage["utilization"][tier]["median"]
            entry["measured_at_rps"] = measured_at
            entry["calculated_utilization_at_measured_rate"] = measured_at * cost_ms / 1000 / chosen
            entry["measured_cpu_ms_per_request"] = c_stage["cpu_ms_per_request"][tier]["median"]
            # Where the measured CPU time per request would put a quarter of the baseline.
            entry["measured_utilization_on_next_size_down"] = entry["measured_utilization"] * 2
        out["tiers"][tier] = entry
    return out


def node_out() -> dict | None:
    """The run with one of the two web nodes cordoned and its pods deleted."""
    stage, name, reference_name = NODE_OUT
    directory = ROOT / "results" / stage / name
    summary = load(directory / "summary.json")
    if not summary or summary["status"] != "complete":
        return None
    window = summary["windows"][0]
    containers: dict[str, int] = {}
    for line in (directory / "kubelet.jsonl").read_text().splitlines():
        sample = json.loads(line)
        if sample["tier"] == "web":
            containers[sample["node"]] = sample["app_containers"]  # the last sample of each node stays
    utilization = window["tiers"]["web"]["node_utilization"]
    within, reasons = compare.step_passes(window)
    reference = load(ROOT / "results" / stage / reference_name / "summary.json")
    # A run records the pods that were ready when it started. The number the deployment
    # asks for is the one the run with both nodes found ready.
    wanted = (reference or summary)["shape"]["pods"]["storefront-web"]
    # The figures that divide by both web nodes' vCPUs do not describe this run: the tier's
    # utilization, its busiest tier and the rating that follows from them are left out.
    generic = ("utilization", "run", "busiest_tier", "busiest_utilization", "rating_rps", "node_utilization")
    out = {"run": name, **{k: v for k, v in row(summary, window).items() if k not in generic},
           "web_pods_wanted": wanted,
           "web_pods_running": sum(containers.values()), "web_pods_per_node": sorted(containers.values()),
           "web_node_utilization": sorted(utilization), "surviving_node_utilization": max(utilization),
           "web_cores_used": window["tiers"]["web"]["cores_used"],
           # An extrapolation, not a rating: the rate at which the node that was left would be at the ceiling.
           "rate_at_ceiling_on_the_node_left_rps": window["achieved_rps"] * rule.CEILING / max(utilization),
           "within_limits": within, "reasons": reasons}
    if reference and reference["status"] == "complete":
        base = row(reference, reference["windows"][0])
        out["both_nodes"] = {"run": reference_name, **{k: base[k] for k in ("p50_ms", "p95_ms", "p99_ms", "error_rate",
                                                                             "achieved_share")},
                             "web_utilization": base["utilization"]["web"]}
    return out


def direct_change() -> dict | None:
    """The change of the second session, from the baseline straight to the right-sized stack,
    read from its recordings: the pipeline runs with their longest actions, and the database
    failovers that Amazon RDS logged. No load generator ran, so it was not observed."""
    directory = ROOT / "results/c-graviton5-right-sized/evidence/change-session2"
    if not (directory / "pipeline-1.txt").exists():
        return None

    def moment(text: str) -> dt.datetime:
        return dt.datetime.fromisoformat(text).replace(tzinfo=dt.timezone.utc)

    runs = []
    for path in sorted(directory.glob("pipeline-*.txt")):
        actions = []
        for line in path.read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) == 5:
                actions.append({"stage": fields[0], "action": fields[1], "status": fields[2],
                                "from": fields[3], "to": fields[4],
                                "seconds": int((moment(fields[4]) - moment(fields[3])).total_seconds())})
        if actions:
            runs.append({"from": actions[0]["from"], "to": actions[-1]["to"],
                         "seconds": int((moment(actions[-1]["to"]) - moment(actions[0]["from"])).total_seconds()),
                         "succeeded": all(a["status"] == "Succeeded" for a in actions),
                         "node_groups_seconds": next((a["seconds"] for a in actions if a["action"] == "Cluster"), None),
                         "database_seconds": next((a["seconds"] for a in actions if a["action"] == "Database"), None)})
    failovers = []
    for line in (directory / "cluster-events.txt").read_text().splitlines()[1:]:
        stamp, _, message = line.partition("\t")
        if message.startswith("Started cross AZ failover"):
            failovers.append({"started": stamp})
        elif message.startswith("Completed") and failovers and "completed" not in failovers[-1]:
            failovers[-1]["completed"] = stamp
            failovers[-1]["seconds"] = int((moment(stamp) - moment(failovers[-1]["started"])).total_seconds())
    changed = [line for line in (directory / "changed-lines.txt").read_text().splitlines()[1:] if re.match(r"^[-+]", line)]
    return {"pipeline_runs": runs, "from": runs[0]["from"], "to": runs[-1]["to"],
            "seconds": int((moment(runs[-1]["to"]) - moment(runs[0]["from"])).total_seconds()),
            "failovers": failovers, "changed_lines": len(changed), "observed_under_load": False}


def session_rows(stage: str, names: tuple[str, ...]) -> list[dict]:
    rows = []
    for name in names:
        directory = ROOT / "results" / stage / name
        summary = load(directory / "summary.json")
        if summary and summary["status"] == "complete":
            rows.append(row(summary, summary["windows"][0], directory))
    return rows


def sessions() -> dict:
    """Does the second session reproduce the first? Each configuration was run at one rate in
    both: the baseline at the comparison rate, the right-sized stack at 8,000 requests per second."""
    out = {}
    for key, stage, first, second in (
            ("a", "a-graviton2-baseline", RUNS["a-graviton2-baseline"][:1], SECOND_SESSION["a-graviton2-baseline"]),
            ("c", "c-graviton5-right-sized", ("c-r1", "c-r2", "c-r3"), ("c2-r1",))):
        before, after = session_rows(stage, first), session_rows(stage, second)
        if not before or not after:
            continue
        entry = {"rate_rps": before[0]["target_rps"], "measures": {}}
        for label, rows in (("first", before), ("second", after)):
            entry[label] = {"runs": [r["run"] for r in rows], "from": rows[0]["from"], "to": rows[-1]["to"]}
        def measure(name: str, pick) -> None:
            a, b = compare.spread([pick(r) for r in before]), compare.spread([pick(r) for r in after])
            entry["measures"][name] = {"first": a, "second": b, "change": b["median"] / a["median"] - 1,
                                       "difference": b["median"] - a["median"]}
        for name in ("p50", "p95", "p99"):
            measure(f"{name}_ms", lambda r, n=name: r[f"{n}_ms"])
        for tier in TIERS:
            measure(f"cpu_ms_per_request_{tier}", lambda r, t=tier: r["cpu_ms_per_request"][t])
            measure(f"utilization_{tier}", lambda r, t=tier: r["utilization"][t])
        out[key] = entry
    return out


RATE = comparison_rate() if (ROOT / "results/a-graviton2-baseline").exists() else 0.0
RUNS = runs_at_the_comparison_rate() if RATE else {}


def main() -> None:
    rated = load(ROOT / "results/ceiling.json")
    comparison = load(ROOT / "results/comparison.json")
    if not rated or not comparison:
        raise SystemExit("run analysis/compare.py and analysis/ceiling.py first")
    letters = {stage: (letter, title) for stage, _, letter, title in compare.STAGES}
    stages = {}
    for stage in letters:
        entry = measured(stage) if stage in RUNS else from_step(stage)
        if not entry:
            continue
        own = rated["stages"][stage]
        entry.update({"letter": letters[stage][0], "title": letters[stage][1],
                      "rated_rps": own["rated_rps"], "rated_rps_exact": own["rated_rps_exact"],
                      "room_above_rate_rps": own["rated_rps_exact"] - RATE,
                      "room_above_rate": own["rated_rps_exact"] / RATE - 1})
        stages[stage] = entry
    out = {"rate_rps": RATE, "ceiling": rated["ceiling"],
           "baseline_rated_rps_exact": rated["stages"]["a-graviton2-baseline"]["rated_rps_exact"], "stages": stages}
    a, c = stages.get("a-graviton2-baseline"), stages.get("c-graviton5-right-sized")
    if a and c:
        out["criteria"] = criteria(c, a, rated["ceiling"])
        out["holds"] = all(r["met"] for r in out["criteria"])
        # The baseline's first run at this rate is the run that set the rate. The decision
        # is repeated against its two runs of the second session alone.
        fresh = [r for r in a["per_run"] if r["run"] != RUNS["a-graviton2-baseline"][0]]
        if fresh:
            again = criteria(c, combine(fresh), rated["ceiling"])
            out["holds_against_baseline_runs_of_second_session_only"] = {
                "runs": [r["run"] for r in fresh], "holds": all(r["met"] for r in again),
                "criteria_met": sum(r["met"] for r in again), "criteria": len(again)}
        base = rated["stages"]["a-graviton2-baseline"]["rated_rps"]
        scaled = c["rating_from_these_runs_rps"]
        ceiling_run = load(ROOT / "results/c-graviton5-right-sized" /
                           rated["stages"]["c-graviton5-right-sized"]["ceiling_run"]["run"] / "summary.json")
        before = ceiling_run["windows"][0]["tiers"]["web"]["cpu_ms_per_request"]
        after = c["cpu_ms_per_request"]["web"]["median"]
        def moment(text: str) -> dt.datetime:
            return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))

        fresh_ends = [r["to"] for r in a["per_run"] if r["run"] in SECOND_SESSION["a-graviton2-baseline"]]
        if fresh_ends:
            out["minutes_from_baseline_runs_to_right_sized_runs"] = round(
                (moment(c["per_run"][0]["from"]) - moment(max(fresh_ends))).total_seconds() / 60)
        out["right_sized_rating_from_second_session"] = {
            "web_cpu_ms_per_request": {"in_its_ceiling_run": before, "in_these_runs": after, "change": after / before - 1},
            "runs": c["runs"], "scaled_from_utilization": c["busiest_utilization"],
            "rated_rps": round(scaled["median"], -2), "rated_rps_exact": scaled["median"],
            "lowest": scaled["min"], "highest": scaled["max"],
            "above_comparison_rate_rps": round(scaled["median"], -2) - RATE,
            "vs_baseline_rating": round(scaled["median"], -2) / base - 1}
    out["expected"] = expected("c-graviton5-right-sized", "c")
    out["work_backwards"] = work_backwards(stages, rated, comparison)
    out["one_web_node_out"] = node_out()
    out["sessions"] = sessions()
    out["direct_change"] = direct_change()
    (ROOT / "results/rated.json").write_text(json.dumps(out, indent=2) + "\n")

    print(f"Comparison at {RATE:,.0f} requests per second, the rate of the baseline's ceiling run")
    print("  CPU utilization by the rule of section 12: web nodes' vCPUs, API pods' CPU limits, database writer")
    header = ("  config  runs  errors %  p50 ms  p95 ms  p99 ms  web CPU %  API CPU %  DB CPU %  busiest tier"
              "     rated req/s  room above this rate")
    print(header)
    for entry in stages.values():
        lat, use = entry["latency_ms"], entry["utilization"]
        runs = f"{len(entry['runs'])} x {entry['seconds_per_run'][0]:.0f} s" if entry["source"] == "runs" \
            else f"step, {entry['seconds_per_run'][0]:.0f} s"
        print(f"  {entry['letter']:<6} {runs:<11} {entry['error_rate']['median'] * 100:7.4f}  {lat['p50']['median']:6.1f}"
              f"  {lat['p95']['median']:6.1f}  {lat['p99']['median']:6.1f}  {use['web']['median'] * 100:9.1f}"
              f"  {use['api']['median'] * 100:9.1f}  {use['db']['median'] * 100:8.1f}"
              f"  {TIER_NAMES[entry['busiest_tier']]:<15} {entry['rated_rps']:>10,.0f}  {entry['room_above_rate']:+19.1%}")
        if entry["source"] == "runs":
            for r in entry["per_run"]:
                print(f"         {r['run']:<12} {r['error_rate'] * 100:7.4f}  {r['p50_ms']:6.1f}  {r['p95_ms']:6.1f}"
                      f"  {r['p99_ms']:6.1f}  {r['utilization']['web'] * 100:9.1f}  {r['utilization']['api'] * 100:9.1f}"
                      f"  {r['utilization']['db'] * 100:8.1f}")
            if entry["missing_runs"]:
                print(f"         not yet run: {', '.join(entry['missing_runs'])}")
        else:
            print(f"         from the step of {entry['step_run']} at {entry['target_rps']:,.0f} requests per second;"
                  " not run at the comparison rate")
    if out.get("criteria"):
        print(f"\nDoes C carry the baseline's rated load? {'yes' if out['holds'] else 'no'}")
        for r in out["criteria"]:
            value = f"{r['value']:.1f} ms" if r["unit"] == "ms" else f"{r['value'] * 100:.4g}%"
            base = f"{r['baseline']:.1f} ms" if r["unit"] == "ms" else f"{r['baseline'] * 100:.4g}%"
            change = f" ({r['change']:+.1%})" if "change" in r else ""
            print(f"  {'met' if r['met'] else 'NOT MET':<8} {r['criterion']}: C {value}{change}, A {base}; {r['threshold']}")
    if out["expected"]:
        e = out["expected"]
        print(f"\nExpected from C's capacity run (steps at {e['between_steps_rps'][0]:,.0f} and {e['between_steps_rps'][1]:,.0f}"
              f" requests per second, {e['step_seconds']:.0f} s each): busiest tier {TIER_NAMES[e['busiest_tier']]} at"
              f" {e['busiest_utilization']:.1%} CPU utilization, p99 {e['p99_ms']:.1f} ms")
    if out["work_backwards"]:
        w = out["work_backwards"]
        print(f"\nWorking backwards from {w['load_rps']:,.0f} requests per second at an {w['ceiling']:.0%} CPU ceiling")
        print("  tier             CPU ms/request  cores at   capacity  baseline  share of   deployed  next size  CPU utilization")
        print("                   on Graviton5    that load  needed    capacity  baseline   capacity  down       predicted  measured")
        for tier, t in w["tiers"].items():
            got = f"{t['measured_utilization']:8.1%}" if "measured_utilization" in t else "       -"
            print(f"  {TIER_NAMES[tier]:<16} {t['cpu_ms_per_request_graviton5']:13.3f}  {t['cores_at_load']:9.2f}  "
                  f"{t['capacity_needed']:8.2f}  {t['baseline_capacity']:8.2f}  {t['needed_share_of_baseline']:8.0%}   "
                  f"{t['chosen_capacity']:8.2f}  {t['next_size_down']:9.2f}  {t['predicted_utilization']:9.1%}  {got}")
        print("  capacity: vCPUs of the web nodes, CPU limits of the API pods, vCPUs of the database writer")
    n = out["one_web_node_out"]
    if n:
        print(f"\nOne of two web nodes out of service, {n['target_rps']:,.0f} requests per second ({n['run']}, {n['seconds']:.0f} s):"
              f" {n['web_pods_running']} of {n['web_pods_wanted']} web pods running")
        print(f"  achieved {n['achieved_share']:.2%} of the target rate, errors {n['error_rate'] * 100:.4f}%,"
              f" p50 {n['p50_ms']:.1f} ms, p95 {n['p95_ms']:.1f} ms, p99 {n['p99_ms']:.1f} ms;"
              f" remaining web node at {n['surviving_node_utilization']:.1%} CPU utilization;"
              f" {'within' if n['within_limits'] else 'outside'} the limits of section 7"
              + (f" ({'; '.join(n['reasons'])})" if n["reasons"] else ""))
        if "both_nodes" in n:
            b = n["both_nodes"]
            print(f"  with both nodes ({b['run']}): p50 {b['p50_ms']:.1f} ms, p95 {b['p95_ms']:.1f} ms, p99 {b['p99_ms']:.1f} ms,"
                  f" web tier at {b['web_utilization']:.1%} CPU utilization")
    d = out["direct_change"]
    if d:
        print(f"\nThe change from A to C in the second session, with no load generator running: {len(d['pipeline_runs'])} pipeline runs of "
              + " and ".join(f"{r['seconds'] // 60} min {r['seconds'] % 60} s" for r in d["pipeline_runs"])
              + f", {d['seconds'] // 60} min {d['seconds'] % 60} s from the start of the first to the end of the last; "
              f"{len(d['failovers'])} database failovers of " + " and ".join(f"{f['seconds']} s" for f in d["failovers"])
              + " as Amazon RDS logged them")
    names = {"p50_ms": "p50 response time, ms", "p95_ms": "p95 response time, ms", "p99_ms": "p99 response time, ms",
             **{f"cpu_ms_per_request_{tier}": f"{TIER_NAMES[tier]}: CPU ms per request" for tier in TIERS},
             **{f"utilization_{tier}": f"{TIER_NAMES[tier]}: CPU utilization, %" for tier in TIERS}}
    for key, entry in out["sessions"].items():
        print(f"\nConfiguration {key.upper()} at {entry['rate_rps']:,.0f} requests per second in both sessions:"
              f" {', '.join(entry['first']['runs'])} against {', '.join(entry['second']['runs'])}")
        print("  measure                                 first session              second session             difference")
        for name, m in entry["measures"].items():
            scale = 100 if name.startswith("utilization") else 1
            def show(v: dict) -> str:
                text = f"{v['median'] * scale:.3f}"
                return text + (f" ({v['min'] * scale:.3f} to {v['max'] * scale:.3f})" if v["runs"] > 1 else "")
            print(f"  {names[name]:<38}  {show(m['first']):<26} {show(m['second']):<26} {m['change']:+.1%}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Capacity at a CPU ceiling (docs/02-experiment-protocol.md, section 12).

    uv run analysis/ceiling.py estimate <run prefix>   # rate and task count for the ceiling run, from the capacity run
    uv run analysis/ceiling.py check <run prefix>      # after the ceiling run: is the busiest tier within 75-85%?
    uv run analysis/ceiling.py                         # every configuration: writes results/ceiling.json, prints the table

A tier above 80% CPU is treated as overloaded. A configuration's rated capacity is the
request rate at which its busiest tier is at 80%, provided the latency and error limits
that define maximum sustainable throughput still hold there.

Utilization is measured against the CPU a tier is allowed to use: the web nodes'
vCPUs, the sum of the API pods' CPU limits, and the database writer's vCPUs.
"""
from __future__ import annotations

import json
import math
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from compare import STAGES, step_passes  # noqa: E402

CEILING = 0.80
ACCEPT = (0.75, 0.85)  # a ceiling run counts if its busiest tier is within this range
RATE_PER_TASK = 8000 / 28  # the steady runs' load generator sizing
TIERS = {"web": "Web", "api": "API", "db": "Database writer"}


def api_pod_cpu_limit() -> float:
    """CPU limit of one API pod, from the Helm chart (the same in every configuration)."""
    values = (ROOT / "deploy/chart/storefront/values.yaml").read_text()
    block = values[values.index("\napi:"):]
    millis = re.search(r"^\s+cpu:\s*(\d+)m\s*$", block, re.M)
    if not millis:
        raise SystemExit("deploy/chart/storefront/values.yaml: api.cpu not found")
    return int(millis.group(1)) / 1000


def utilization(window: dict, pods: dict) -> dict:
    """Each tier's utilization in one measured window, as a share of the CPU it may use."""
    tiers = window["tiers"]
    out = {}
    if tiers.get("web", {}).get("utilization") is not None:
        out["web"] = tiers["web"]["utilization"]
    if tiers.get("api", {}).get("cores_used") is not None:
        out["api"] = tiers["api"]["cores_used"] / (pods["storefront-api"] * api_pod_cpu_limit())
        out["api_share_of_node_vcpus"] = tiers["api"]["utilization"]
        if tiers["api"].get("app_cores_used") is not None:
            # The API containers alone, without the system daemons of their nodes. Reported
            # next to the rated figure; the rating uses the node figure, as registered.
            out["api_pods_only"] = tiers["api"]["app_cores_used"] / (pods["storefront-api"] * api_pod_cpu_limit())
    if tiers.get("db_writer", {}).get("cpu_percent") is not None:
        out["db"] = tiers["db_writer"]["cpu_percent"] / 100
    return out


def busiest(values: dict) -> tuple[str, float]:
    name = max(TIERS, key=lambda tier: values.get(tier, 0.0))
    return name, values[name]


def load(path: pathlib.Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def stage_of(prefix: str) -> str:
    letter = prefix[0]
    return next(stage for stage, key, _, _ in STAGES if key == letter)


def estimate(prefix: str) -> dict:
    """From a capacity run: the lowest rate at which a tier reaches the ceiling."""
    summary = load(ROOT / "results" / stage_of(prefix) / f"{prefix}-cap" / "summary.json")
    if not summary:
        raise SystemExit(f"no capacity run {prefix}-cap")
    pods = summary["shape"]["pods"]
    steps = []
    for window in summary["windows"]:
        ok, _ = step_passes(window)
        if not ok:
            break
        steps.append({"rate": window["achieved_rps"], **utilization(window, pods)})
    if not steps:
        raise SystemExit(f"{prefix}-cap: no step within the latency and error limits")
    crossings = {}
    for tier in TIERS:
        points = [(s["rate"], s[tier]) for s in steps if tier in s]
        for index, (rate, value) in enumerate(points):
            if value >= CEILING:
                if index == 0:
                    crossings[tier] = rate * CEILING / value  # below the first step: proportional
                else:
                    r0, u0 = points[index - 1]
                    crossings[tier] = r0 + (rate - r0) * (CEILING - u0) / (value - u0)
                break
    result = {"prefix": prefix, "steps": steps, "crossings": {t: round(r, 1) for t, r in crossings.items()},
              "highest_step_within_limits": steps[-1]["rate"]}
    if crossings:
        tier = min(crossings, key=crossings.get)
        result.update({"limiting_tier": tier, "rate_at_ceiling": round(crossings[tier], 1),
                       "rate": int(crossings[tier] // 100 * 100)})
    else:
        # No tier reaches 80% while latency and errors are within limits.
        result.update({"limiting_tier": None, "rate_at_ceiling": None, "rate": int(steps[-1]["rate"] // 100 * 100)})
    result["tasks"] = math.ceil(result["rate"] / RATE_PER_TASK)
    return result


def ceiling_run(prefix: str) -> dict | None:
    """The latest ceiling run of a configuration, reduced to what the table needs."""
    stage_dir = ROOT / "results" / stage_of(prefix)
    runs = sorted(stage_dir.glob(f"{prefix}-ceiling*/summary.json"))
    attempts = []
    for path in runs:
        summary = json.loads(path.read_text())
        window = summary["windows"][0]
        values = utilization(window, summary["shape"]["pods"])
        tier, value = busiest(values)
        ok, reasons = step_passes(window)
        client = window["client"]
        attempts.append({
            "run": summary["name"], "status": summary["status"], "rate": window["achieved_rps"],
            "target_rps": window["target_rps"], "utilization": {k: round(v, 4) for k, v in values.items()},
            "busiest_tier": tier, "busiest_utilization": round(value, 4), "busiest_utilization_unrounded": value,
            "within_range": ACCEPT[0] <= value <= ACCEPT[1],
            "within_limits": ok, "reasons": reasons, "error_rate": client["error_rate"],
            "p50_ms": client["p50_ms"], "p95_ms": client["p95_ms"], "p99_ms": client["p99_ms"],
            "generator_peak_cpu_share": summary.get("generator", {}).get("peak_cpu_share"),
        })
    if not attempts:
        return None
    # A run counts only if it completed with its busiest tier within 75% to 85% (protocol,
    # section 12). The check command looks at the latest attempt, whatever it was.
    usable = [a for a in attempts if a["within_range"] and a["status"] == "complete"]
    latest = dict(attempts[-1])
    latest["attempts"] = [a["run"] for a in attempts]
    latest["usable"] = dict(usable[-1], attempts=[a["run"] for a in attempts]) if usable else None
    return latest


def rated(prefixes: list[str]) -> dict | None:
    """Rated capacity of a configuration: from its ceiling run, or interpolated from its
    capacity run if it has none. `prefixes` are the run prefixes of the configuration,
    latest deployment last.

    Rates are reported rounded to 100 requests per second: one run, and one one-minute
    database datapoint per staircase step, do not carry more. `rated_rps_exact` keeps the
    unrounded figure; the decision rule of section 12 is evaluated on it."""
    not_used = []
    for prefix in reversed(prefixes):
        latest = ceiling_run(prefix)
        if not latest:
            continue
        run = latest["usable"]
        if run and run["within_limits"]:
            capacity = run["rate"] * CEILING / run["busiest_utilization_unrounded"]
            return {"prefix": prefix, "source": "ceiling run", "rated_rps": round(capacity, -2),
                    "rated_rps_exact": round(capacity, 1), "limiting_tier": run["busiest_tier"], "ceiling_run": run}
        if run:
            # It could not hold the rate that puts its busiest tier at the ceiling within the
            # latency and error limits. Its capacity is below that rate; the CPU rule gives no rating.
            return {"prefix": prefix, "source": "ceiling run broke the latency or error limits",
                    "rated_rps": None, "rated_rps_exact": None, "below_rps": round(run["rate"], -2),
                    "limiting_tier": None, "ceiling_run": run}
        # Ceiling runs exist, but none completed with its busiest tier within 75% to 85%.
        not_used += latest["attempts"]
    for prefix in reversed(prefixes):
        path = ROOT / "results" / stage_of(prefix) / f"{prefix}-cap" / "summary.json"
        if not path.exists():
            continue
        guess = estimate(prefix)
        entry = {"prefix": prefix, "ceiling_run": None, "limiting_tier": guess["limiting_tier"]}
        if not_used:
            entry["ceiling_runs_not_used"] = not_used
        if guess["rate_at_ceiling"] is not None:
            entry.update({"source": "capacity run, interpolated", "rated_rps": round(guess["rate_at_ceiling"], -2),
                          "rated_rps_exact": guess["rate_at_ceiling"]})
        elif len(guess["steps"]) == len(load(path)["windows"]):
            # Every step passed and no tier reached 80%: the staircase ended too early to say.
            entry.update({"source": "no tier reached the ceiling in the range tested", "rated_rps": None,
                          "rated_rps_exact": None, "above_rps": round(guess["highest_step_within_limits"], -2)})
        else:
            # A step broke the latency or error limits before any tier was at 80%.
            entry.update({"source": "latency or error limits reached before any tier was at the ceiling",
                          "rated_rps": round(guess["highest_step_within_limits"], -2),
                          "rated_rps_exact": guess["highest_step_within_limits"]})
        if not_used:
            entry["source"] += "; ceiling run outside 75% to 85%, not used"
        return entry
    return None


def baseline_rating_run() -> dict | None:
    """The run that rates the baseline: its latest ceiling run that counts (section 12 and
    deviation 13). The comparison of section 14 is made at this run's rate, so the second
    session, the comparison and the bill's last scenario all read the rate from here."""
    stage, key = STAGES[0][0], STAGES[0][1]
    prefixes = [p for p in (key, f"{key}2") if list((ROOT / "results" / stage).glob(f"{p}-*"))]
    entry = rated(prefixes) if prefixes else None
    if not entry or entry["source"] != "ceiling run":
        return None
    run = dict(entry["ceiling_run"])
    run["tasks"] = math.ceil(run["target_rps"] / RATE_PER_TASK)
    return run


def main() -> None:
    arguments = sys.argv[1:]
    if arguments[:1] == ["comparison"]:
        # For the second session of a new run: RATE=<rate> TASKS=<tasks> scripts/phases/rated-load.sh
        run = baseline_rating_run()
        if not run:
            raise SystemExit("the baseline has no ceiling run that counts: there is no comparison rate yet")
        print(f"RATE={run['target_rps']:.0f} TASKS={run['tasks']}")
        return
    if arguments[:1] == ["estimate"]:
        result = estimate(arguments[1])
        if "--plain" in arguments:
            print(result["rate"], result["tasks"])
            return
        print(f"{arguments[1]}-cap: CPU utilization of each tier at the steps within the latency and error limits")
        print(f"  {'requests/s':>10s} {'web':>7s} {'API':>7s} {'database writer':>16s}")
        for step in result["steps"]:
            print(f"  {step['rate']:10.0f} {step.get('web', 0):7.1%} {step.get('api', 0):7.1%} {step.get('db', 0):16.1%}")
        for tier, rate in result["crossings"].items():
            print(f"  {TIERS[tier]} reaches {CEILING:.0%} CPU utilization at about {rate:,.0f} requests per second")
        if result["limiting_tier"]:
            print(f"ceiling run: {result['rate']:,} requests per second with {result['tasks']} load generator tasks "
                  f"(limited by: {TIERS[result['limiting_tier']]})")
        else:
            print(f"no tier reaches {CEILING:.0%} CPU utilization within the limits; ceiling run at the highest passing "
                  f"step: {result['rate']:,} requests per second with {result['tasks']} load generator tasks")
        return
    if arguments[:1] == ["check"]:
        run = ceiling_run(arguments[1])
        if not run:
            raise SystemExit(f"no ceiling run for {arguments[1]}")
        tier, value = run["busiest_tier"], run["busiest_utilization"]
        print(f"{run['run']}: {run['rate']:,.0f} req/s, busiest tier {TIERS[tier]} at {value:.1%}, "
              f"p99 {run['p99_ms']} ms, errors {run['error_rate']:.4%}", file=sys.stderr)
        if run["within_range"]:
            return
        corrected = int(run["rate"] * CEILING / value // 100 * 100)
        print(corrected, math.ceil(corrected / RATE_PER_TASK))
        sys.exit(3)

    bom = load(ROOT / "results/bom.json") or {"stages": {}}
    out = {"ceiling": CEILING, "api_pod_cpu_limit": api_pod_cpu_limit(), "stages": {}}
    for stage, key, letter, title in STAGES:
        # A configuration deployed a second time uses the prefix with a 2, e.g. a2 for "A again".
        prefixes = [p for p in (key, f"{key}2") if list((ROOT / "results" / stage).glob(f"{p}-*"))]
        if not prefixes:
            continue
        entry = rated(prefixes)
        if not entry:
            continue
        entry.update({"letter": letter, "title": title})
        # What the capacity run alone suggested, next to what the ceiling run measured.
        if (ROOT / "results" / stage / f"{key}-cap" / "summary.json").exists():
            guess = estimate(key)
            entry["staircase_estimate_rps"] = guess["rate_at_ceiling"]
            entry["staircase_limiting_tier"] = guess["limiting_tier"]
        costs = bom["stages"].get(stage)
        if costs and entry["rated_rps"]:
            total = costs["on_demand"]["total"]
            instances = costs["on_demand"]["groups"]["Compute and database"]
            entry["cost"] = {
                "on_demand_total": total, "compute_database": instances,
                # Instances per unit of capacity. The whole bill is not divided by capacity: its
                # usage lines are priced for the assumed traffic, not for a month at capacity.
                "compute_database_per_1000_rps": instances / entry["rated_rps"] * 1000,
            }
        out["stages"][stage] = entry
    baseline = out["stages"].get(STAGES[0][0])
    for entry in out["stages"].values():
        if baseline and entry is not baseline and entry["rated_rps"] and baseline["rated_rps"]:
            # The ratio is that of the reported figures, rounded to 100, so that a reader can
            # recompute it from the tables. The decision rule (is it at least the baseline's?)
            # uses the unrounded figures.
            entry["rated_vs_baseline"] = round(entry["rated_rps"] / baseline["rated_rps"], 4)
            entry["rated_vs_baseline_unrounded"] = round(entry["rated_rps_exact"] / baseline["rated_rps_exact"], 4)
            entry["at_least_baseline"] = entry["rated_rps_exact"] >= baseline["rated_rps_exact"]
    (ROOT / "results/ceiling.json").write_text(json.dumps(out, indent=2) + "\n")

    print(f"Rated load: the request rate at which the busiest tier is at {CEILING:.0%} CPU utilization")
    for entry in out["stages"].values():
        tier = TIERS.get(entry["limiting_tier"], "latency limit")
        if not entry["rated_rps"]:
            print(f"  {entry['letter']}: not rated ({entry['source']})")
            continue
        line = f"  {entry['letter']}: {entry['rated_rps']:>8,.0f} requests per second  busiest tier: {tier:16s} ({entry['source']})"
        if "rated_vs_baseline" in entry:
            line += f"  {entry['rated_vs_baseline']:.2f} times A's"
        if "cost" in entry:
            line += (f"  instances ${entry['cost']['compute_database_per_1000_rps']:,.0f} per month per 1,000 "
                     f"requests per second")
        print(line)
        run = entry.get("ceiling_run")
        if run:
            shares = ", ".join(f"{TIERS[t]} {run['utilization'][t]:.1%}" for t in TIERS if t in run["utilization"])
            print(f"       {run['run']}: {run['rate']:,.0f} requests per second; CPU utilization: {shares}; response time: "
                  f"p50 {run['p50_ms']:.1f} ms, p95 {run['p95_ms']:.1f} ms, p99 {run['p99_ms']:.1f} ms; "
                  f"errors {run['error_rate']:.4%} of requests")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Compares the configurations of the study and checks the acceptance criteria.

    uv run analysis/compare.py            # writes results/comparison.json and prints the tables

Inputs are the per-run summaries written by analysis/summarize.py and the bill of
materials written by analysis/bom.py. The thresholds are the ones fixed in
docs/02-experiment-protocol.md before the official runs.
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from dlthist import Distribution  # noqa: E402
import summarize  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
STAGES = [
    ("a-graviton2-baseline", "a", "A", "Graviton2 baseline"),
    ("b-graviton5-same-size", "b", "B", "Graviton5, same size"),
    ("c-graviton5-right-sized", "c", "C", "Graviton5, right-sized"),
]

# Maximum sustainable throughput: the limits a capacity step must stay within.
SLO = {"min_achieved_share": 0.99, "max_error_rate": 0.001, "max_p95_ms": 50.0, "max_p99_ms": 100.0}
# Acceptance criteria against the baseline.
CRITERIA = {
    "min_achieved_share": 0.995,
    "max_error_rate": 0.001,
    "max_error_rate_over_baseline": 0.0005,
    "max_p50_increase": 0.05,
    "max_p95_increase": 0.05,
    "max_p99_increase": 0.10,
    "min_mst_share": 0.95,
}


def load(path: pathlib.Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def spread(values: list[float]) -> dict:
    values = [v for v in values if v is not None]
    if not values:
        return {"median": None, "min": None, "max": None, "runs": 0}
    return {"median": statistics.median(values), "min": min(values), "max": max(values), "runs": len(values)}


def steady(stage: str, prefix: str, names: tuple[str, ...] = ("r1", "r2", "r3")) -> dict | None:
    """The steady runs of one deployment (run prefix) at one rate, taken together."""
    return steady_runs(stage, tuple(f"{prefix}-{name}" for name in names))


def steady_runs(stage: str, run_names: tuple[str, ...]) -> dict | None:
    """Steady runs of one configuration at one rate, taken together: the median of each
    measure with the lowest and highest run next to it."""
    runs = []
    pooled = Distribution()
    operations: dict[str, Distribution] = {}
    for run_name in run_names:
        directory = ROOT / "results" / stage / run_name
        summary = load(directory / "summary.json")
        if not summary or summary["status"] != "complete":
            continue
        runs.append(summary)
        dlt = json.loads((directory / "dlt.json").read_text())
        pooled.merge(Distribution.from_state(dlt["measured"]["state"]))
        for label, entry in dlt["labels"].items():
            if label not in ("ramp", "outside", ""):
                operations.setdefault(label, Distribution()).merge(Distribution.from_state(entry["state"]))
    if not runs:
        return None

    def pick(path: str) -> list[float]:
        values = []
        for run in runs:
            node = run["windows"][0]
            for key in path.split("."):
                node = node.get(key) if isinstance(node, dict) else None
                if node is None:
                    break
            values.append(node)
        return values

    result = {
        "runs": [run["name"] for run in runs],
        # Start of the first run's measured window and end of the last one's, UTC.
        "from": min(run["windows"][0]["from"] for run in runs),
        "to": max(run["windows"][0]["to"] for run in runs),
        "pods": runs[0]["shape"]["pods"],
        # Seconds by which this deployment's Aurora datapoints trail their timestamps, as
        # estimated from its steady runs (analysis/summarize.py); the last run saw them all.
        "metric_lag_seconds": (runs[-1].get("rds_metric_lag") or {}).get("seconds"),
        "target_rps": runs[0]["windows"][0]["target_rps"],
        "achieved_rps": spread(pick("achieved_rps")),
        "achieved_share": spread(pick("achieved_share")),
        "error_rate": spread(pick("client.error_rate")),
        "latency_ms": {name: spread(pick(f"client.{name}_ms")) for name in ("mean", "p50", "p90", "p95", "p99", "p99_9")},
        "tiers": {},
        "generator_peak_cpu_share": max((run.get("generator", {}).get("peak_cpu_share") or 0) for run in runs),
        "pooled": pooled.summary(),
        "pooled_state": pooled.to_state(),
        "operations": {name: d.summary() for name, d in sorted(operations.items())},
    }
    for tier in ("web", "api"):
        result["tiers"][tier] = {
            "vcpus": runs[0]["windows"][0]["tiers"].get(tier, {}).get("vcpus"),
            "utilization": spread(pick(f"tiers.{tier}.utilization")),
            "cores_used": spread(pick(f"tiers.{tier}.cores_used")),
            # The tier's containers alone, without the nodes' system daemons.
            "app_cores_used": spread(pick(f"tiers.{tier}.app_cores_used")),
            "cpu_ms_per_request": spread(pick(f"tiers.{tier}.cpu_ms_per_request")),
        }
    for role in ("db_writer", "db_reader"):
        result["tiers"][role] = {
            "class": runs[0]["windows"][0]["tiers"].get(role, {}).get("class"),
            "vcpus": runs[0]["windows"][0]["tiers"].get(role, {}).get("vcpus"),
            "utilization": spread([v / 100 if v is not None else None for v in pick(f"tiers.{role}.cpu_percent")]),
            "cores_used": spread(pick(f"tiers.{role}.cores_used")),
            "cpu_ms_per_request": spread(pick(f"tiers.{role}.cpu_ms_per_request")),
            "commit_latency_ms": spread(pick(f"tiers.{role}.commit_latency_ms")),
            "select_latency_ms": spread(pick(f"tiers.{role}.select_latency_ms")),
            "buffer_cache_hit_ratio": spread(pick(f"tiers.{role}.buffer_cache_hit_ratio")),
        }
    # Pages (rendered by the web tier) and direct API calls, apart: which of them fail, and
    # the range of the operations' median response times.
    def group(prefix: str) -> dict:
        chosen = [d for name, d in result["operations"].items() if name.startswith(prefix)]
        requests = sum(d["requests"] for d in chosen)
        failed = sum(d["failed"] for d in chosen)
        medians = [d["p50_ms"] for d in chosen if d.get("p50_ms") is not None]
        return {"requests": requests, "failed": failed, "error_rate": failed / requests if requests else None,
                "lowest_p50_ms": min(medians) if medians else None, "highest_p50_ms": max(medians) if medians else None}

    result["pages"] = group("page_")
    result["api_calls"] = group("api_")
    # What the nodes burn beyond the tier's own containers (kubelet, CNI, proxies, the kernel),
    # in cores, and what one web node would carry if the other were lost.
    result["node_overhead_cores"] = {
        tier: (result["tiers"][tier]["cores_used"]["median"] - result["tiers"][tier]["app_cores_used"]["median"])
        if result["tiers"][tier]["app_cores_used"]["median"] is not None else None for tier in ("web", "api")}
    # Share of scheduling periods in which the kernel held the API containers at their CPU limit.
    result["throttled_share"] = {"api": spread([(run.get("cpu_throttling") or {}).get("api", {}).get("throttled_share")
                                                for run in runs])}
    counters = [run.get("database_counters", {}) for run in runs]
    result["database"] = {
        "statements_per_request": spread([c.get("statements_per_request") for c in counters]),
        "rows_read_per_request": spread([c.get("rows_read_per_request") for c in counters]),
    }
    result["load_balancer"] = {
        key: spread(pick(f"load_balancer.{key}")) for key in
        ("requests_per_second", "target_5xx", "elb_5xx", "processed_bytes_per_second", "consumed_lcus_per_hour")}
    return result


def step_passes(step: dict) -> tuple[bool, list[str]]:
    client = step["client"]
    reasons = []
    if (step["achieved_share"] or 0) < SLO["min_achieved_share"]:
        reasons.append(f"achieved {step['achieved_share']:.1%} of target")
    if (client["error_rate"] or 0) > SLO["max_error_rate"]:
        reasons.append(f"errors {client['error_rate']:.2%}")
    if client["p95_ms"] is None or client["p95_ms"] > SLO["max_p95_ms"]:
        reasons.append(f"p95 {client['p95_ms']} ms")
    if client["p99_ms"] is None or client["p99_ms"] > SLO["max_p99_ms"]:
        reasons.append(f"p99 {client['p99_ms']} ms")
    return not reasons, reasons


def capacity(stage: str, prefix: str) -> dict | None:
    summary = load(ROOT / "results" / stage / f"{prefix}-cap" / "summary.json")
    if not summary:
        return None
    steps = []
    for window in summary["windows"]:
        ok, reasons = step_passes(window)
        tiers = window["tiers"]
        steps.append({
            "label": window["label"], "factor": window["factor"], "target_rps": window["target_rps"],
            "achieved_rps": window["achieved_rps"], "achieved_share": window["achieved_share"],
            "error_rate": window["client"]["error_rate"], "p50_ms": window["client"]["p50_ms"],
            "p95_ms": window["client"]["p95_ms"], "p99_ms": window["client"]["p99_ms"],
            "web_utilization": tiers.get("web", {}).get("utilization"),
            "api_utilization": tiers.get("api", {}).get("utilization"),
            "api_cores": tiers.get("api", {}).get("cores_used"),
            # Median response time of each tier's targets as the load balancer measured it.
            "web_target_p50_ms": window.get("load_balancer", {}).get("web_target_p50_ms"),
            "api_target_p50_ms": window.get("load_balancer", {}).get("api_target_p50_ms"),
            "timeouts": window["client"].get("codes", {}).get("1050", 0),
            "failed": window["client"].get("failed"),
            "db_cpu_percent": tiers.get("db_writer", {}).get("cpu_percent"),
            # CPU milliseconds each tier spent per request sent to the stack in this step.
            "cpu_ms_per_request": {tier: tiers.get(tier, {}).get("cpu_ms_per_request")
                                   for tier in ("web", "api", "db_writer")},
            "within_slo": ok, "reasons": reasons,
        })
    # The sustainable range is the unbroken run of passing steps from the start.
    passing = []
    for step in steps:
        if not step["within_slo"]:
            break
        passing.append(step)
    # The rate of the highest passing step, as it was set. A passing step achieved at least
    # 99% of it; the rate actually achieved is kept next to it.
    mst = passing[-1]["target_rps"] if passing else 0.0
    return {
        "status": summary["status"],
        "pods": summary["shape"]["pods"],
        "steps": steps,
        "mst_rps": mst,
        "mst_achieved_rps": passing[-1]["achieved_rps"] if passing else 0.0,
        "mst_factor": passing[-1]["factor"] if passing else 0.0,
        # True if no tested step broke: the real limit is above the highest rate tested.
        "limit_not_reached": len(passing) == len(steps),
        "first_failing_step": next(({"target_rps": s["target_rps"], "reasons": s["reasons"]}
                                    for s in steps if not s["within_slo"]), None),
        "generator_peak_cpu_share": summary.get("generator", {}).get("peak_cpu_share"),
        # Each tier's CPU per request over the passing steps: lowest and highest step value,
        # and the last passing step against the first.
        "cpu_ms_per_request_range": {
            tier: {"min": min(values), "max": max(values), "spread": max(values) / min(values) - 1,
                   "last_vs_first": values[-1] / values[0] - 1}
            for tier in ("web", "api", "db_writer")
            if (values := [s["cpu_ms_per_request"][tier] for s in passing if s["cpu_ms_per_request"][tier]])},
        # Share of scheduling periods in which the kernel held a tier's containers at their CPU limit.
        "cpu_throttling": summary.get("cpu_throttling", {}),
        # How much of a step's 110 measured seconds its CPU samples span (15 seconds apart).
        "cpu_sample_span_seconds": {
            "min": min(spans), "max": max(spans)} if (spans := [
                window["tiers"][tier]["span_seconds"] for window in summary["windows"]
                for tier in ("web", "api") if window["tiers"].get(tier, {}).get("span_seconds")]) else None,
    }


def criteria(candidate: dict, baseline: dict) -> list[dict]:
    """Each acceptance criterion as measured, with its threshold and verdict."""
    rows = []
    cs, bs = candidate.get("steady"), baseline.get("steady")
    if cs and bs:
        share = cs["achieved_share"]["median"]
        rows.append({"criterion": "Achieved rate at operating load", "value": share,
                     "baseline": bs["achieved_share"]["median"],
                     "threshold": f">= {CRITERIA['min_achieved_share']:.1%} of target",
                     "met": share >= CRITERIA["min_achieved_share"]})
        error, base_error = cs["error_rate"]["median"], bs["error_rate"]["median"]
        rows.append({"criterion": "Error rate at operating load", "value": error, "baseline": base_error,
                     "threshold": f"<= {CRITERIA['max_error_rate']:.1%} and <= baseline + 0.05 percentage points",
                     "met": error <= CRITERIA["max_error_rate"]
                     and error <= base_error + CRITERIA["max_error_rate_over_baseline"]})
        for name, limit in (("p50", "max_p50_increase"), ("p95", "max_p95_increase"), ("p99", "max_p99_increase")):
            value, base = cs["latency_ms"][name]["median"], bs["latency_ms"][name]["median"]
            change = value / base - 1
            rows.append({"criterion": f"{name} latency at operating load", "value": value, "baseline": base,
                         "change": change, "threshold": f"<= +{CRITERIA[limit]:.0%} vs baseline",
                         "met": change <= CRITERIA[limit]})
    cc, bc = candidate.get("capacity"), baseline.get("capacity")
    if cc and bc and bc["mst_rps"]:
        share = cc["mst_rps"] / bc["mst_rps"]
        rows.append({"criterion": "Maximum sustainable throughput", "value": cc["mst_rps"], "baseline": bc["mst_rps"],
                     "change": share - 1, "threshold": f">= {CRITERIA['min_mst_share']:.0%} of baseline",
                     "met": share >= CRITERIA["min_mst_share"],
                     "note": "limit not reached in the range tested" if cc["limit_not_reached"] else ""})
    return rows


SECONDS_PER_MONTH = 730 * 3600


def derived(entry: dict, usage: dict) -> dict:
    """Cost per unit of work, from the bill of materials and the measured throughput."""
    cost = entry["cost"]
    out = {}
    steady_runs = entry.get("steady")
    if steady_runs and usage.get("average_rps"):
        # The requests of a month at the average request rate that the bill assumes.
        millions = usage["average_rps"] * SECONDS_PER_MONTH / 1e6
        out["monthly_requests_millions"] = round(millions, 1)
        # Only meaningful if the configuration actually serves the operating load.
        if steady_runs["achieved_share"]["median"] >= CRITERIA["min_achieved_share"] \
                and steady_runs["error_rate"]["median"] <= CRITERIA["max_error_rate"]:
            out["cost_per_million_requests"] = round(cost["on_demand_total"] / millions, 4)
            out["compute_database_per_million_requests"] = round(
                cost["on_demand_groups"]["Compute and database"] / millions, 4)
    capacity_run = entry.get("capacity")
    if capacity_run and capacity_run["mst_rps"]:
        instances = cost["on_demand_groups"]["Compute and database"]
        out["requests_per_dollar_at_mst"] = round(capacity_run["mst_rps"] * SECONDS_PER_MONTH / instances)
    return out


def repeat_of(stage: str, prefix: str, first: dict | None) -> dict | None:
    """A configuration deployed a second time at the end of the study: its steady run next
    to the first deployment's, to show whether the results reproduce (run prefix with a 2),
    and one more steady run with the database writer in the other Availability Zone (prefix
    with 2p), to show what the placement of the API nodes relative to the writer changes."""
    if not first:
        return None

    def against(runs: dict, base: dict) -> dict:
        out = {"runs": runs["runs"], "from": runs["from"], "to": runs["to"], "reference_runs": base["runs"],
               "metric_lag_seconds": runs["metric_lag_seconds"],
               "reference_from": base["from"], "reference_to": base["to"],
               "latency_ms": {}, "tiers": {}, "error_rate": runs["error_rate"]["median"],
               "achieved_share": runs["achieved_share"]["median"]}
        for name in ("p50", "p95", "p99"):
            value, reference = runs["latency_ms"][name]["median"], base["latency_ms"][name]["median"]
            out["latency_ms"][name] = {"value": value, "reference": reference, "change": value / reference - 1,
                                       # The range of the reference runs: is the new value inside it?
                                       "reference_min": base["latency_ms"][name]["min"],
                                       "reference_max": base["latency_ms"][name]["max"]}
        for tier in ("web", "api", "db_writer"):
            value = runs["tiers"][tier]["cpu_ms_per_request"]["median"]
            reference = base["tiers"][tier]["cpu_ms_per_request"]["median"]
            if value and reference:
                out["tiers"][tier] = {"value": value, "reference": reference, "change": value / reference - 1,
                                      "reference_min": base["tiers"][tier]["cpu_ms_per_request"]["min"],
                                      "reference_max": base["tiers"][tier]["cpu_ms_per_request"]["max"],
                                      "utilization": runs["tiers"][tier]["utilization"]["median"],
                                      "reference_utilization": base["tiers"][tier]["utilization"]["median"]}
        return out

    again = steady(stage, f"{prefix}2", ("r1",))
    if not again:
        return None
    out = {"same_placement": against(again, first)}
    # How many of the repeat's values lie outside the range of the first deployment's runs.
    values = list(out["same_placement"]["latency_ms"].values()) + list(out["same_placement"]["tiers"].values())
    out["same_placement"]["measures"] = len(values)
    out["same_placement"]["outside_reference_range"] = sum(
        1 for v in values if not v["reference_min"] <= v["value"] <= v["reference_max"])
    other = steady(stage, f"{prefix}2p", ("r1",))
    if other:
        # Compared with the repeat in the baseline's placement: same deployment, same hour.
        out["other_placement"] = against(other, again)
    return out


def load_generators() -> dict:
    """The two checks on the load generators, over every benchmark run of the study: did all
    requested tasks report, and how busy was the busiest task in its busiest minute, as a
    share of the CPU reserved for it. Runs that observe a configuration change are left out;
    they are not benchmark runs."""
    runs = []
    for stage, _, _, _ in STAGES:
        for path in sorted((ROOT / "results" / stage).glob("*/summary.json")):
            summary = json.loads(path.read_text())
            if summary["name"].endswith(("-load", "-probe")) or summary["status"] != "complete":
                continue
            tasks = summary.get("tasks") or {}
            runs.append({"run": summary["name"], "requested": tasks.get("requested"), "reporting": tasks.get("reporting"),
                         "peak_cpu_share": summary.get("generator", {}).get("peak_cpu_share")})
    measured = [run for run in runs if run["peak_cpu_share"] is not None]
    busiest = max(measured, key=lambda run: run["peak_cpu_share"]) if measured else None
    return {
        "runs": len(runs),
        "all_tasks_reported": all(run["requested"] == run["reporting"] for run in runs),
        "incomplete": [run["run"] for run in runs if run["requested"] != run["reporting"]],
        "peak_cpu_share": busiest and busiest["peak_cpu_share"],
        "peak_cpu_run": busiest and busiest["run"],
        "limit": 0.60,
    }


def container_restarts() -> dict:
    """Did an application container restart between a deployment's warm-up and its last run?

    Every run samples, per node, the sum of the cumulative CPU seconds of the application's
    containers and their number (tools/bench.py, kubelet.jsonl). A restarted container
    starts counting from zero, so the node's sum falls by what that container had used. The
    check lists, per deployment (run prefix), how often a node's sum fell or its number of
    containers changed from one sample to the next, within and between runs. A restart of
    a container that had used less CPU than its neighbours add between two samples (15
    seconds) would escape it; after the warm-up no container is that young."""
    out = {}
    for stage, _, _, _ in STAGES:
        runs: dict[str, list[pathlib.Path]] = {}
        for path in sorted((ROOT / "results" / stage).glob("*/kubelet.jsonl")):
            name = path.parent.name
            if not name.endswith(("-load", "-probe")):
                runs.setdefault(name.split("-")[0], []).append(path)
        for prefix, paths in runs.items():
            samples: dict[str, list[tuple]] = {}
            for path in paths:
                for line in path.read_text().splitlines():
                    row = json.loads(line)
                    if row["tier"] in ("web", "api"):
                        samples.setdefault(row["node"], []).append((row["ts_ms"], row["app_cpu_s"], row["app_containers"]))
            falls = changes = intervals = 0
            for rows in samples.values():
                rows.sort()
                for (_, before, count_before), (_, after, count_after) in zip(rows, rows[1:]):
                    intervals += 1
                    falls += after < before - 1e-6
                    changes += count_after != count_before
            out[prefix] = {"stage": stage, "runs": sorted(path.parent.name for path in paths), "nodes": len(samples),
                           "sample_intervals": intervals, "counter_falls": falls, "container_count_changes": changes}
    return {"deployments": out,
            "seen": sum(d["counter_falls"] + d["container_count_changes"] for d in out.values())}


def database_cpu_timing() -> dict:
    """What the timing correction of Aurora's CPU datapoints changes (analysis/summarize.py).

    For every completed 10-minute run: the writer's CPU as analysed, with each datapoint
    assigned to the 60 seconds it covers, against the mean of the whole minutes that lie
    inside the measured window when a datapoint's timestamp is read as the start of its
    minute. For the baseline's staircase: the rate at which the writer crosses the ceiling,
    with and without the correction."""
    shifts = []
    for stage, _, _, _ in STAGES:
        for path in sorted((ROOT / "results" / stage).glob("*/summary.json")):
            run = json.loads(path.read_text())
            if run.get("kind") != "steady" or run["status"] != "complete" or run["name"].endswith(("-load", "-probe")):
                continue
            window = run["windows"][0]
            analysed = window["tiers"].get("db_writer", {}).get("cpu_percent")
            if window["seconds"] < 590 or analysed is None:
                continue
            series = json.loads((path.parent / "cloudwatch.json").read_text())["rds"]["writer.CPUUtilization.Average"]
            minutes = summarize.minutes_inside(series, summarize.parse(window["from"]), summarize.parse(window["to"]))
            if minutes:
                shifts.append({"run": run["name"], "analysed_percent": analysed,
                               "whole_minutes_by_timestamp_percent": round(sum(minutes) / len(minutes), 4),
                               "offset_seconds": run["rds_metric_lag"]["seconds"]})
    out = {"runs": len(shifts),
           "largest_shift_points": max((abs(s["analysed_percent"] - s["whole_minutes_by_timestamp_percent"]) for s in shifts),
                                       default=None),
           "offset_seconds": {"lowest": min((s["offset_seconds"] for s in shifts), default=None),
                              "highest": max((s["offset_seconds"] for s in shifts), default=None)},
           "per_run": shifts}
    staircase = load(ROOT / "results" / STAGES[0][0] / "a-cap" / "summary.json")
    if staircase:
        series = json.loads((ROOT / "results" / STAGES[0][0] / "a-cap" / "cloudwatch.json").read_text())["rds"][
            "writer.CPUUtilization.Average"]
        points = {"analysed": [], "by_timestamp": []}
        for window in staircase["windows"]:
            if not step_passes(window)[0]:
                break
            values = summarize.covered_inside(series, summarize.parse(window["from"]), summarize.parse(window["to"]), 0.0)
            points["analysed"].append((window["achieved_rps"], window["tiers"]["db_writer"]["cpu_percent"]))
            if values:
                points["by_timestamp"].append((window["achieved_rps"], sum(values) / len(values)))

        def crossing(pairs: list[tuple[float, float]], level: float = 80.0) -> float | None:
            for (r0, v0), (r1, v1) in zip(pairs, pairs[1:]):
                if v0 < level <= v1:
                    return round(r0 + (level - v0) / (v1 - v0) * (r1 - r0), 1)
            return None

        out["baseline_staircase_writer_at_80_percent_rps"] = {name: crossing(pairs) for name, pairs in points.items()}
    return out


def main() -> None:
    bom = load(ROOT / "results/bom.json") or {"stages": {}, "usage": {}}
    out = {"slo": SLO, "criteria": CRITERIA, "stages": {}}
    for stage, prefix, letter, title in STAGES:
        entry = {"letter": letter, "title": title, "steady": steady(stage, prefix), "capacity": capacity(stage, prefix)}
        costs = bom["stages"].get(stage)
        if costs:
            rows = {row["item"].split(":")[0]: row["monthly_usd"] for row in costs["on_demand"]["rows"]}
            aurora = {"instances": rows["Aurora MySQL writer and reader"], "io": rows["Aurora I/O requests"],
                      "storage": rows["Aurora storage"]}
            entry["cost"] = {
                # What the configuration pays for Aurora, and the share of it that is I/O.
                "aurora": {**aurora, "io_share": round(aurora["io"] / sum(aurora.values()), 4)},
                "on_demand_total": costs["on_demand"]["total"],
                "on_demand_groups": costs["on_demand"]["groups"],
                "committed_total": costs["committed"]["total"],
                "committed_groups": costs["committed"]["groups"],
                "shape": costs["shape"],
            }
        if costs:
            entry["derived"] = derived(entry, bom.get("usage", {}))
        again = repeat_of(stage, prefix, entry["steady"])
        if again:
            entry["again"] = again
        if entry["steady"] or entry["capacity"]:
            out["stages"][stage] = entry
    baseline = out["stages"].get(STAGES[0][0])
    for stage, entry in out["stages"].items():
        if baseline and entry is not baseline:
            entry["criteria"] = criteria(entry, baseline)
            entry["sustains_baseline"] = bool(entry["criteria"]) and all(row["met"] for row in entry["criteria"])
            # How much less CPU each tier spends per request than the baseline's processor.
            if entry.get("steady") and baseline.get("steady"):
                entry["cpu_per_request_vs_baseline"] = {
                    tier: round(baseline["steady"]["tiers"][tier]["cpu_ms_per_request"]["median"]
                                / entry["steady"]["tiers"][tier]["cpu_ms_per_request"]["median"], 3)
                    for tier in ("web", "api", "db_writer")
                    if entry["steady"]["tiers"][tier]["cpu_ms_per_request"]["median"]}
            if entry.get("cost") and baseline.get("cost"):
                entry["cost"]["on_demand_change"] = entry["cost"]["on_demand_total"] / baseline["cost"]["on_demand_total"] - 1
                key = "Compute and database"
                entry["cost"]["compute_database_change"] = (
                    entry["cost"]["on_demand_groups"][key] / baseline["cost"]["on_demand_groups"][key] - 1)
                entry["cost"]["committed_change"] = entry["cost"]["committed_total"] / baseline["cost"]["committed_total"] - 1

    out["load_generators"] = load_generators()
    out["container_restarts"] = container_restarts()
    out["database_cpu_timing"] = database_cpu_timing()
    (ROOT / "results/comparison.json").write_text(json.dumps(out, indent=2) + "\n")

    for stage, entry in out["stages"].items():
        print(f"\n== {entry['letter']}: {entry['title']}")
        s = entry.get("steady")
        if s:
            lat = s["latency_ms"]
            print(f"  steady ({len(s['runs'])} runs): {s['achieved_rps']['median']:.1f} req/s, "
                  f"errors {s['error_rate']['median']:.4%}, "
                  + ", ".join(f"{n} {lat[n]['median']:.1f} [{lat[n]['min']:.1f}-{lat[n]['max']:.1f}]"
                              for n in ("p50", "p95", "p99")) + " ms")
            for tier in ("web", "api", "db_writer"):
                t = s["tiers"][tier]
                if t["utilization"]["median"] is not None:
                    print(f"    {tier:10s} {t['utilization']['median']:6.1%} of {t['vcpus']} vCPU, "
                          f"{t['cores_used']['median']:.2f} cores, {t['cpu_ms_per_request']['median']:.3f} ms CPU/request")
        c = entry.get("capacity")
        if c:
            note = " (limit not reached)" if c["limit_not_reached"] else f"; first failing step {c['first_failing_step']}"
            print(f"  maximum sustainable throughput: {c['mst_rps']:.0f} req/s (x{c['mst_factor']}){note}")
        if entry.get("cpu_per_request_vs_baseline"):
            print(f"  CPU per request, baseline / this: {entry['cpu_per_request_vs_baseline']}")
        if entry.get("cost"):
            cost = entry["cost"]
            change = f" ({cost['on_demand_change']:+.1%} vs A; compute and database {cost['compute_database_change']:+.1%})" \
                if "on_demand_change" in cost else ""
            print(f"  On-Demand per month: ${cost['on_demand_total']:,.0f}{change}; committed ${cost['committed_total']:,.0f}")
            extra = entry.get("derived", {})
            if "cost_per_million_requests" in extra:
                print(f"  ${extra['cost_per_million_requests']:.3f} per million requests at the month's assumed traffic"
                      f" ({extra['monthly_requests_millions']:,.0f} million)")
            if "requests_per_dollar_at_mst" in extra:
                print(f"  {extra['requests_per_dollar_at_mst']:,} requests per instance dollar at maximum sustainable throughput")
        for key, label in (("same_placement", "deployed again, against the first deployment"),
                           ("other_placement", "writer in the other zone, against the repeat")):
            again = entry.get("again", {}).get(key)
            if again:
                print(f"  {label}: " + ", ".join(
                    f"{name} {v['value']:.1f} ms ({v['change']:+.1%})" for name, v in again["latency_ms"].items())
                    + "; CPU per request " + ", ".join(f"{tier} {v['change']:+.1%}" for tier, v in again["tiers"].items()))
        for row in entry.get("criteria", []):
            detail = f"{row['value']:.4g}"
            if "change" in row and row.get("baseline"):
                detail += f" vs {row['baseline']:.4g} ({row['change']:+.1%})"
            print(f"    [{'met' if row['met'] else 'NOT MET'}] {row['criterion']}: {detail}; {row['threshold']}")


if __name__ == "__main__":
    main()

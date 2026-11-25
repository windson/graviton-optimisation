#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Reduces one benchmark run (written by tools/bench.py) to its headline numbers.

    uv run analysis/summarize.py results/<stage>/<run> [...]

Writes summary.json next to the run's data. For each measured window it reports what
the clients saw (rate achieved, errors, latency percentiles) next to what each tier
spent (CPU cores in use, utilisation, CPU milliseconds per request).
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from dlthist import Distribution  # noqa: E402

UTC = dt.timezone.utc


def parse(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def tier_cpu(samples: list[dict], nodes: list[dict], start: dt.datetime, end: dt.datetime) -> dict:
    """Average cores used by each tier's nodes between start and end, from kubelet counters."""
    start_ms, end_ms = start.timestamp() * 1000, end.timestamp() * 1000
    tiers: dict[str, dict] = {}
    for node in nodes:
        rows = sorted((s for s in samples if s.get("node") == node["name"] and "node_cpu_s" in s
                       and start_ms <= s["ts_ms"] <= end_ms), key=lambda s: s["ts_ms"])
        if len(rows) < 2:
            continue
        first, last = rows[0], rows[-1]
        seconds = (last["ts_ms"] - first["ts_ms"]) / 1000
        tier = tiers.setdefault(node["tier"], {"vcpus": 0, "nodes": 0, "cores_used": 0.0, "app_cores_used": 0.0,
                                               "span_seconds": seconds, "node_utilization": []})
        cores = (last["node_cpu_s"] - first["node_cpu_s"]) / seconds
        tier["vcpus"] += int(node["cpu"])
        tier["nodes"] += 1
        tier["cores_used"] += cores
        # Container counters reset when a pod restarts; ignore a negative difference.
        tier["app_cores_used"] += max(0.0, (last["app_cpu_s"] - first["app_cpu_s"]) / seconds)
        tier["node_utilization"].append(round(cores / int(node["cpu"]), 4))
        tier["span_seconds"] = min(tier["span_seconds"], seconds)
    for tier in tiers.values():
        tier["utilization"] = round(tier["cores_used"] / tier["vcpus"], 4)
        tier["cores_used"] = round(tier["cores_used"], 3)
        tier["app_cores_used"] = round(tier["app_cores_used"], 3)
    return tiers


def minutes_inside(series: list, start: dt.datetime, end: dt.datetime, period: int = 60) -> list[float]:
    """Values of the one-minute datapoints that lie entirely inside [start, end]."""
    return [value for stamp, value in series
            if parse(stamp) >= start and parse(stamp) + dt.timedelta(seconds=period) <= end]


def mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


# ---- Timing of Aurora's CloudWatch metrics ----------------------------------------------
#
# CloudWatch stamps each one-minute Aurora datapoint with a minute, but the 60 seconds the
# instance averaged over begin some seconds before that minute (about 43 s on the
# baseline's instances). The end of a steady run shows it: the load stops at a known
# second, and the next CPU datapoint is a mix of busy and idle whose proportion gives the
# offset. Load balancer and EC2 datapoints do not have this offset.
#
# For a 10-minute window the offset hardly matters. For a 110-second capacity step it
# decides whether the step's datapoint mostly describes the step before it.

DEFAULT_RDS_LAG = 45.0
# The offset is known to a few seconds. Datapoints must be inside the window with this
# margin to spare. A 110-second capacity step does not always contain such a datapoint;
# it then takes the one that is at least 90% inside (6 of its 60 seconds may be outside).
RDS_MARGIN = 3.0
RDS_TOLERANCE = 6.0


def covered_inside(series: list, start: dt.datetime, end: dt.datetime, lag: float, period: int = 60) -> list[float]:
    """Values of the datapoints whose covered interval, [stamp - lag, stamp - lag + period],
    lies inside [start, end]."""
    for slack in (-RDS_MARGIN, RDS_TOLERANCE):
        lo, hi = start - dt.timedelta(seconds=slack), end + dt.timedelta(seconds=slack)
        values = []
        for stamp, value in series:
            begin = parse(stamp) - dt.timedelta(seconds=lag)
            if begin >= lo and begin + dt.timedelta(seconds=period) <= hi:
                values.append(value)
        if values:
            return values
    return []


def run_origin(dlt: dict) -> dt.datetime:
    """When the run's k6 scripts started: the median of the tasks' recorded start times."""
    starts = sorted(parse(t["start"]) for t in dlt["tasks"])
    return starts[len(starts) // 2]


def rds_lag_of_run(path: pathlib.Path) -> float | None:
    """Seconds by which the writer's CPU datapoints trail their timestamps, measured at the
    end of one steady run. None if the run is not a completed steady run or its end is unclear."""
    try:
        run = json.loads((path / "config.json").read_text())
        dlt = json.loads((path / "dlt.json").read_text())
        series = json.loads((path / "cloudwatch.json").read_text())["rds"]["writer.CPUUtilization.Average"]
    except (OSError, KeyError, ValueError):
        return None
    if run.get("kind") != "steady" or dlt.get("status") != "complete" or not dlt.get("tasks"):
        return None
    origin = run_origin(dlt)
    window = next(w for w in run["k6"]["windows"] if w["label"] != "ramp")
    start = origin + dt.timedelta(milliseconds=window["fromMs"])
    load_end = origin + dt.timedelta(seconds=run["script_seconds"])
    # The level while loaded, from datapoints that are inside the window whatever the offset is.
    loaded = [v for stamp, v in series if parse(stamp) >= start + dt.timedelta(seconds=60)
              and parse(stamp) + dt.timedelta(seconds=60) <= load_end]
    idle = min((v for _, v in series), default=0.5)
    if not loaded:
        return None
    # The level just before the end; a long run's level can change on the way.
    level = statistics.fmean(loaded[-3:])
    if level - idle < 5:
        return None
    best = None
    for stamp, value in series:
        at = parse(stamp)
        if abs((at - load_end).total_seconds()) > 120:
            continue
        share = (value - idle) / (level - idle)  # part of the datapoint's minute that was loaded
        if 0.05 < share < 0.95:
            lag = (at - load_end).total_seconds() + 60 * share
            if best is None or abs(share - 0.5) < best[0]:
                best = (abs(share - 0.5), lag)
    if best is None:
        # The load ended on a datapoint boundary: the first idle datapoint begins where the load ends.
        for stamp, value in series:
            at = parse(stamp)
            if at > load_end - dt.timedelta(seconds=60) and (value - idle) / (level - idle) <= 0.05:
                best = (0.0, (at - load_end).total_seconds())
                break
    if best is None:
        return None
    lag = best[1] % 60
    return round(lag, 1)


def rds_lag(path: pathlib.Path) -> dict:
    """The offset to use for a run: the median over the steady runs of the same deployment,
    or an assumed value if there is none.

    Runs of one deployment share a name prefix (a-cap, a-r1; a2-r1 for configuration A
    deployed again, on other database instances). A run without such siblings, like the
    calibration staircase, uses every steady run in its directory.
    """
    def measured(candidates: list[pathlib.Path]) -> list[float]:
        # Runs named "<change>-load" are the background load during a configuration change:
        # they end on the next configuration's database instances, whose offset differs.
        return sorted(lag for lag in (rds_lag_of_run(run) for run in candidates
                                      if run.is_dir() and not run.name.endswith("-load")) if lag is not None)

    siblings = sorted(path.parent.iterdir())
    prefix = path.name.split("-")[0] + "-"
    lags = measured([run for run in siblings if run.name.startswith(prefix)]) or measured(siblings)
    if lags:
        return {"seconds": statistics.median(lags), "source": "measured", "runs": len(lags),
                "min": lags[0], "max": lags[-1]}
    return {"seconds": DEFAULT_RDS_LAG, "source": "assumed", "runs": 0}


def window_metrics(run: dict, cloudwatch: dict, samples: list[dict], distribution: Distribution,
                   start: dt.datetime, end: dt.datetime, seconds: float, target_rps: float, lag: float) -> dict:
    client = distribution.summary()
    achieved = client["requests"] / seconds if seconds else 0.0
    result = {
        "from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seconds": seconds,
        "target_rps": round(target_rps, 2),
        "achieved_rps": round(achieved, 2),
        "achieved_share": round(achieved / target_rps, 5) if target_rps else None,
        "client": client,
        "tiers": {},
    }
    facts = run["facts"]
    for name, tier in tier_cpu(samples, [n for n in facts["nodes"] if n["tier"] in ("web", "api")], start, end).items():
        tier["cpu_ms_per_request"] = round(tier["cores_used"] / achieved * 1000, 4) if achieved else None
        result["tiers"][name] = tier

    rds = cloudwatch.get("rds", {})
    for role in ("writer", "reader"):
        instance = next((i for i in facts["database"]["instances"] if i["writer"] == (role == "writer")), None)
        if not instance:
            continue
        def inside(metric: str) -> list[float]:
            return covered_inside(rds.get(f"{role}.{metric}", []), start, end, lag)

        cpu = inside("CPUUtilization.Average")
        vcpus = run["pricing_vcpus"].get(instance["class"]) if "pricing_vcpus" in run else None
        entry = {
            "class": instance["class"],
            "cpu_percent": mean(cpu),
            "cpu_percent_max_minute": max(cpu) if cpu else None,
            "minutes": len(cpu),
            "connections": mean(inside("DatabaseConnections.Average")),
            "commit_latency_ms": mean(inside("CommitLatency.Average")),
            "select_latency_ms": mean(inside("SelectLatency.Average")),
            "dml_latency_ms": mean(inside("DMLLatency.Average")),
            "queries_per_second": mean(inside("Queries.Average")),
            "buffer_cache_hit_ratio": mean(inside("BufferCacheHitRatio.Average")),
            "replica_lag_ms": mean(inside("AuroraReplicaLag.Maximum")),
        }
        if vcpus and entry["cpu_percent"] is not None:
            entry["vcpus"] = vcpus
            entry["cores_used"] = round(entry["cpu_percent"] / 100 * vcpus, 3)
            entry["cpu_ms_per_request"] = round(entry["cores_used"] / achieved * 1000, 4) if achieved else None
        result["tiers"][f"db_{role}"] = entry

    alb = cloudwatch.get("alb", {})
    if alb:
        def total(key: str) -> float:
            return sum(minutes_inside(alb.get(key, []), start, end))

        minutes = len(minutes_inside(alb.get("alb.RequestCount.Sum", []), start, end))
        result["load_balancer"] = {
            "minutes": minutes,
            "requests_per_second": round(total("alb.RequestCount.Sum") / (minutes * 60), 2) if minutes else None,
            "target_5xx": total("alb.HTTPCode_Target_5XX_Count.Sum"),
            "elb_5xx": total("alb.HTTPCode_ELB_5XX_Count.Sum"),
            "target_connection_errors": total("alb.TargetConnectionErrorCount.Sum"),
            "rejected_connections": total("alb.RejectedConnectionCount.Sum"),
            "consumed_lcus_per_hour": round(total("alb.ConsumedLCUs.Sum") / minutes * 60, 2) if minutes else None,
            "processed_bytes_per_second": round(total("alb.ProcessedBytes.Sum") / (minutes * 60)) if minutes else None,
            "web_target_p50_ms": _ms(mean(minutes_inside(alb.get("web.TargetResponseTime.p50", []), start, end))),
            "web_target_p99_ms": _ms(mean(minutes_inside(alb.get("web.TargetResponseTime.p99", []), start, end))),
            "api_target_p50_ms": _ms(mean(minutes_inside(alb.get("api.TargetResponseTime.p50", []), start, end))),
            "api_target_p99_ms": _ms(mean(minutes_inside(alb.get("api.TargetResponseTime.p99", []), start, end))),
        }
    return result


def _ms(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds * 1000, 3)


def summarize(path: pathlib.Path, vcpus: dict[str, int]) -> dict:
    run = json.loads((path / "config.json").read_text())
    run["pricing_vcpus"] = vcpus
    dlt = json.loads((path / "dlt.json").read_text())
    cloudwatch = json.loads((path / "cloudwatch.json").read_text()) if (path / "cloudwatch.json").exists() else {}
    samples = [json.loads(line) for line in (path / "kubelet.jsonl").read_text().splitlines() if line.strip()]
    database = json.loads((path / "database.json").read_text()) if (path / "database.json").exists() else {}

    # k6 starts within a couple of seconds of the time each task records as its start.
    starts = sorted(parse(t["start"]) for t in dlt["tasks"])
    origin = run_origin(dlt)
    lag = rds_lag(path)
    k6 = run["k6"]
    ramp_windows = [w for w in k6["windows"] if w["label"] != "ramp"]

    summary = {
        "test_id": run["test_id"], "stage": run["stage"], "kind": run["kind"], "name": run["name"],
        "status": dlt["status"], "tasks": {"requested": run["tasks"], "reporting": dlt["tasks_reporting"],
                                           "start_spread_seconds": (starts[-1] - starts[0]).total_seconds()},
        "shape": {
            "nodes": {tier: sorted({n["instance_type"] for n in run["facts"]["nodes"] if n["tier"] == tier})
                      for tier in ("system", "web", "api")},
            "node_count": {tier: sum(1 for n in run["facts"]["nodes"] if n["tier"] == tier)
                           for tier in ("system", "web", "api")},
            "pods": run["facts"]["pods"],
            "database": sorted({i["class"] for i in run["facts"]["database"]["instances"]}),
        },
        "rds_metric_lag": lag,
        "windows": [],
    }

    labels = {label: Distribution.from_state(entry["state"]) for label, entry in dlt["labels"].items()}
    if run["kind"] in ("steady", "probe"):
        window = ramp_windows[0]
        start = origin + dt.timedelta(milliseconds=window["fromMs"])
        end = origin + dt.timedelta(milliseconds=window["toMs"])
        measured = Distribution.from_state(dlt["measured"]["state"])
        entry = window_metrics(run, cloudwatch, samples, measured, start, end, run["windows"][0]["seconds"],
                               run["target_rps"], lag["seconds"])
        entry["label"] = "steady"
        entry["operations"] = {label: d.summary() for label, d in sorted(labels.items())
                               if label not in ("ramp", "outside", "")}
        summary["windows"].append(entry)
    else:
        for window, js in zip(run["windows"], ramp_windows):
            start = origin + dt.timedelta(milliseconds=js["fromMs"])
            end = origin + dt.timedelta(milliseconds=js["toMs"])
            distribution = labels.get(window["label"], Distribution())
            entry = window_metrics(run, cloudwatch, samples, distribution, start, end, window["seconds"],
                                   run["target_rps"] * window["factor"], lag["seconds"])
            entry["label"] = window["label"]
            entry["factor"] = window["factor"]
            summary["windows"].append(entry)

    generator = cloudwatch.get("generator", {})
    used = [v for _, v in generator.get("generator.CpuUtilized.Maximum", [])]
    reserved = [v for _, v in generator.get("generator.CpuReserved.Maximum", [])]
    if used and reserved:
        summary["generator"] = {"peak_cpu_share": round(max(used) / max(reserved), 4), "tasks": run["tasks"]}

    if database.get("before") and database.get("after"):
        before, after = database["before"], database["after"]
        requests = sum(d.total for d in labels.values()) or 1
        summary["database_counters"] = {
            key: after[key] - before[key] for key in before if key not in ("at", "Uptime") and key in after}
        summary["database_counters"]["statements_per_request"] = round(
            (after["Questions"] - before["Questions"]) / requests, 3)
        summary["database_counters"]["rows_read_per_request"] = round(
            (after["Innodb_rows_read"] - before["Innodb_rows_read"]) / requests, 1)
    if database.get("throttling_before") is not None:
        throttling = {}
        for tier, after_counts in database.get("throttling_after", {}).items():
            before_counts = database["throttling_before"].get(tier, {})
            periods = after_counts.get("container_cpu_cfs_periods_total", 0) - before_counts.get(
                "container_cpu_cfs_periods_total", 0)
            throttled = after_counts.get("container_cpu_cfs_throttled_periods_total", 0) - before_counts.get(
                "container_cpu_cfs_throttled_periods_total", 0)
            if periods > 0:
                throttling[tier] = {"periods": periods, "throttled_periods": throttled,
                                    "throttled_share": round(throttled / periods, 5)}
        summary["cpu_throttling"] = throttling

    (path / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def show(summary: dict) -> None:
    """Prints one line per measured window under a header that names each column and a second
    line that gives its unit. The three columns after the response times are each tier's CPU
    utilization, measured against the CPU the tier may use, as the rating does
    (analysis/ceiling.py): the web nodes' CPU as a share of their vCPUs (%vCPU), the API
    nodes' CPU as a share of the API pods' CPU limits (%limit), and the database writer's CPU
    as a share of its vCPUs. The ms/req columns are each tier's CPU milliseconds per request
    sent to the stack."""
    import ceiling as rule  # noqa: PLC0415  the definition of a tier's utilization

    shape = summary["shape"]
    print(f"\n{summary['stage']} / {summary['name']} ({summary['kind']}, {summary['status']})")
    print(f"  web {shape['node_count']['web']} x {','.join(shape['nodes']['web'])}, "
          f"API {shape['node_count']['api']} x {','.join(shape['nodes']['api'])}, "
          f"database {','.join(shape['database'])}; pods: web {shape['pods']['storefront-web']}, "
          f"API {shape['pods']['storefront-api']}")
    if "generator" in summary:
        print(f"  load generators: {summary['tasks']['reporting']}/{summary['tasks']['requested']} tasks, "
              f"peak CPU {summary['generator']['peak_cpu_share']:.0%} of reserved")
    lag = summary.get("rds_metric_lag")
    if lag:
        print(f"  Aurora datapoints cover the 60 s that start {lag['seconds']:.0f} s before their timestamp ({lag['source']}"
              + (f" in {lag['runs']} steady runs: {lag['min']:.0f} to {lag['max']:.0f} s)" if lag["runs"] else ")"))
    print(f"  {'window':7s}{'target':>7s}{'achieved':>9s}{'errors':>8s}{'p50':>7s}{'p95':>7s}{'p99':>8s}"
          f"{'web':>8s}{'API':>8s}{'DB':>8s}{'web':>8s}{'API':>8s}{'DB':>8s}")
    print(f"  {'unit':7s}{'req/s':>7s}{'req/s':>9s}{'%':>8s}{'ms':>7s}{'ms':>7s}{'ms':>8s}"
          f"{'%vCPU':>8s}{'%limit':>8s}{'%vCPU':>8s}{'ms/req':>8s}{'ms/req':>8s}{'ms/req':>8s}")
    for window in summary["windows"]:
        client, tiers = window["client"], window["tiers"]
        shares = rule.utilization(window, shape["pods"])

        def pct(name: str) -> str:
            value = shares.get(name)
            return f"{value * 100:8.1f}" if value is not None else "       -"

        def cost(name: str) -> str:
            value = tiers.get(name, {}).get("cpu_ms_per_request")
            return f"{value:8.3f}" if value is not None else "       -"

        error = client["error_rate"]
        # Rounded once, from the count: the stored rate is already rounded to two decimals.
        achieved = client["requests"] / window["seconds"] if client.get("requests") and window.get("seconds") \
            else window["achieved_rps"]
        print(f"  {window['label']:7s}{window['target_rps']:7.0f}{achieved:9.1f}"
              f"{(error or 0) * 100:8.3f}{client['p50_ms'] or 0:7.1f}{client['p95_ms'] or 0:7.1f}"
              f"{client['p99_ms'] or 0:8.1f}{pct('web')}{pct('api')}{pct('db')}"
              f"{cost('web')}{cost('api')}{cost('db_writer')}")
        for name, operation in window.get("operations", {}).items():
            print(f"      {name:16s} n={operation['requests']:8d} err={operation['error_rate'] or 0:.4%} "
                  f"p50={operation['p50_ms']:7.1f} p95={operation['p95_ms']:7.1f} p99={operation['p99_ms']:8.1f}")


def main() -> None:
    root = pathlib.Path(__file__).resolve().parent.parent
    pricing = json.loads((root / "results/pricing/us-west-2.json").read_text())
    vcpus = {name: price["standard"]["vcpu"] for name, price in pricing["aurora_mysql"].items()}
    for argument in sys.argv[1:]:
        show(summarize(pathlib.Path(argument), vcpus))


if __name__ == "__main__":
    main()

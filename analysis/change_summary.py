#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""What a configuration change did to clients, from the recordings made while the
pipeline applied it (scripts/change-stage.sh).

    uv run analysis/change_summary.py a-graviton2-baseline ab

Reads the probe's second-by-second record, the event list and the inventory samples
of results/<stage>/<label>-*, prints the summary and writes
results/<stage>/<label>-summary.json.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
UTC = dt.timezone.utc


def parse(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def iso(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def span(events: list[dict], first, last) -> dict | None:
    starts = [parse(e["at"]) for e in events if first(e)]
    ends = [parse(e["at"]) for e in events if last(e)]
    if not starts or not ends:
        return None
    return {"from": iso(min(starts)), "to": iso(max(ends)), "seconds": int((max(ends) - min(starts)).total_seconds())}


def summarize(stage: str, label: str) -> dict:
    base = ROOT / "results" / stage
    events = json.loads((base / f"{label}-events.json").read_text())["events"]
    timeline = json.loads((base / f"{label}-probe" / "timeline.json").read_text())
    inventory = [json.loads(line) for line in (base / f"{label}-inventory.jsonl").read_text().splitlines() if line.strip()]

    pipeline = [e for e in events if e["source"] == "pipeline"]
    pushes = sorted(parse(e["at"]) for e in pipeline if e["subject"] == "Source/Source" and e["event"] == "started")
    done = sorted(parse(e["at"]) for e in pipeline if e["subject"].startswith("Verify/") and e["event"] == "succeeded")
    push, finished = pushes[0], done[-1]
    stack = [e for e in events if e["source"] == "cloudformation"]

    def resource(e: dict) -> str:
        return e["subject"].split("/", 1)[1]

    node_groups = span(stack, lambda e: resource(e).endswith("NodeGroup") and e["event"].startswith("UPDATE_IN_PROGRESS"),
                       lambda e: resource(e).endswith("NodeGroup") and e["event"].startswith("UPDATE_COMPLETE"))
    database = span(stack, lambda e: resource(e).startswith("Instance") and e["event"].startswith("UPDATE_IN_PROGRESS"),
                    lambda e: resource(e).startswith("Instance") and e["event"].startswith("UPDATE_COMPLETE"))

    failovers = []
    for event in events:
        if event["source"] == "rds" and event["event"].startswith("Started cross AZ failover"):
            failovers.append({"started": event["at"], "to": event["event"].rsplit(": ", 1)[-1].split("-instance")[-1][:1]})
        elif event["source"] == "rds" and event["event"].startswith("Completed") and failovers \
                and "completed" not in failovers[-1]:
            failovers[-1]["completed"] = event["at"]
            failovers[-1]["seconds"] = int((parse(event["at"]) - parse(failovers[-1]["started"])).total_seconds())

    # ---- the probe, second by second --------------------------------------------------------
    start, seconds = timeline["start_epoch"], timeline["seconds"]
    series = [s for name, s in timeline["series"].items() if name not in ("ramp", "outside")] or \
        list(timeline["series"].values())
    ok = [sum(s["ok"][i] for s in series) for i in range(seconds)]
    failed = [sum(s["failed"][i] for s in series) for i in range(seconds)]

    def index(moment: dt.datetime) -> int:
        return max(0, min(seconds, int(moment.timestamp()) - start))

    periods: list[dict] = []
    for i, count in enumerate(failed):
        if not count:
            continue
        if periods and i - periods[-1]["_last"] <= 5:
            periods[-1]["_last"] = i
        else:
            periods.append({"_first": i, "_last": i})
    for period in periods:
        a, b = period.pop("_first"), period.pop("_last")
        at = dt.datetime.fromtimestamp(start + a, UTC)
        near = [n for n, f in enumerate(failovers, start=1)
                if -10 <= (at - parse(f["started"])).total_seconds() <= 90]
        # Seconds in which no request completed at all, from the start of the failover (or
        # of the failures) to the last failure: requests were waiting, not failing yet.
        first = index(parse(failovers[near[0] - 1]["started"])) if near else a
        period.update({
            "from": iso(at), "to": iso(dt.datetime.fromtimestamp(start + b, UTC)), "seconds": b - a + 1,
            "failed": sum(failed[a:b + 1]), "requests": sum(ok[a:b + 1]) + sum(failed[a:b + 1]),
            "seconds_without_a_success": sum(1 for i in range(a, b + 1) if ok[i] == 0),
            # The longest uninterrupted run of seconds in which no request succeeded.
            "consecutive_seconds_without_a_success": max(
                (len(run) for run in "".join("x" if ok[i] == 0 else " " for i in range(a, b + 1)).split()), default=0),
            "seconds_without_any_response": sum(1 for i in range(min(first, a), b + 1) if ok[i] + failed[i] == 0),
            "failover": near[0] if near else None,
        })
        if near and "completed" in failovers[near[0] - 1]:
            # Failures that completed after Amazon RDS logged the failover as complete: the
            # event's end is not the end of what clients saw.
            done = index(parse(failovers[near[0] - 1]["completed"]))
            period["failed_after_rds_completed"] = sum(failed[max(done + 1, a):b + 1])
            period["seconds_after_rds_completed"] = max(0, b - done)

    # Mean response time of the probe, per 10 seconds: before the push, and while the node
    # groups were being replaced.
    def response_time(first: dt.datetime, last: dt.datetime) -> dict | None:
        lo, hi = index(first), index(last)
        means = []
        for at in range(lo, hi - 9, 10):
            total = weighted = 0.0
            for one in series:
                for i in range(at, at + 10):
                    count = one["ok"][i] + one["failed"][i]
                    if one["mean_ms"][i] is not None:
                        weighted += one["mean_ms"][i] * count
                        total += count
            if total:
                means.append(weighted / total)
        if not means:
            return None
        return {"mean_ms": round(sum(means) / len(means), 2), "worst_10s_mean_ms": round(max(means), 2),
                "best_10s_mean_ms": round(min(means), 2)}

    start_time = dt.datetime.fromtimestamp(start, UTC)
    latency = {"before_the_push": response_time(start_time + dt.timedelta(seconds=40), push)}
    if latency["before_the_push"]:
        # How much undisturbed time the "before" figure rests on.
        latency["before_the_push"]["seconds"] = int((push - start_time).total_seconds()) - 40
    if node_groups:
        latency["while_nodes_were_replaced"] = response_time(parse(node_groups["from"]), parse(node_groups["to"]))

    a, b = index(push), index(finished)
    during = {"requests": sum(ok[a:b]) + sum(failed[a:b]), "failed": sum(failed[a:b])}
    during["share"] = during["failed"] / during["requests"] if during["requests"] else None
    whole = {"requests": sum(ok) + sum(failed), "failed": sum(failed)}
    whole["share"] = whole["failed"] / whole["requests"]

    # ---- pods ready, from the inventory samples ----------------------------------------------
    pods = {}
    for tier in ("web", "api"):
        counts = [(row["at"], sum(n["ready_pods"] for n in row["nodes"] if n["tier"] == tier)) for row in inventory]
        most = max(count for _, count in counts)
        low = min(counts, key=lambda item: item[1])
        pods[tier] = {"most": most, "lowest": low[1], "lowest_at": low[0],
                      "samples_at_zero": sum(1 for _, count in counts if count == 0),
                      "zero_at": [at for at, count in counts if count == 0]}
        if node_groups:
            replaced = [count for at, count in counts if node_groups["from"] <= at <= node_groups["to"]]
            if replaced:
                # What the tier had at the start of the node replacement, and the least it had during it.
                pods[tier]["at_start_of_node_replacement"] = replaced[0]
                pods[tier]["lowest_while_nodes_were_replaced"] = min(replaced)
            # A change that reduces the pods first redeploys them before the nodes change.
            before = [(at, count) for at, count in counts if iso(push) <= at < node_groups["from"]]
            if before:
                least = min(before, key=lambda item: item[1])
                final = replaced[0] if replaced else before[-1][1]
                below = [at for at, count in before if count < final]
                pods[tier]["before_node_replacement"] = {
                    "lowest": least[1], "lowest_at": least[0], "settles_at": final,
                    "below_from": below[0] if below else None, "below_to": below[-1] if below else None,
                    "samples_below": len(below)}

    # ---- why requests failed: k6's error code or the HTTP status -----------------------------
    causes: dict[str, int] = {}
    for cause in timeline.get("causes", []):
        kind = "timeout" if cause["error_code"] == "1050" else f"HTTP {cause['status']}"
        causes[kind] = causes.get(kind, 0) + cause["count"]

    result = {
        "stage": stage, "label": label, "push": iso(push), "pipeline_finished": iso(finished),
        "pipeline_seconds": int((finished - push).total_seconds()), "pipeline_runs": len(pushes),
        "node_groups": node_groups, "database": database, "failovers": failovers,
        "probe": {"rate": 100, "whole_observation": whole, "during_the_change": during, "failure_periods": periods,
                  "response_time": latency, "failure_causes": dict(sorted(causes.items(), key=lambda kv: -kv[1])),
                  "failed_outside_failovers": sum(p["failed"] for p in periods if p["failover"] is None),
                  "failed_at_failovers": sum(p["failed"] for p in periods if p["failover"] is not None)},
        "pods": pods, "inventory_interval_seconds": 10,
    }
    load = base / f"{label}-load" / "dlt.json"
    if load.exists():
        measured = json.loads(load.read_text())["measured"]["summary"]
        config = json.loads((base / f"{label}-load" / "config.json").read_text())
        # What the arrival schedule asked for in the measured window. Arrivals that found no
        # free virtual user were dropped by k6 and are in neither count below.
        scheduled = round(config["target_rps"] * sum(w["seconds"] for w in config["windows"]))
        result["background_load"] = {"requests": measured["requests"], "failed": measured["failed"],
                                     "share": measured["error_rate"], "codes": measured["codes"],
                                     "rate": config["target_rps"], "scheduled": scheduled,
                                     "not_sent": max(0, scheduled - measured["requests"])}
    # The instance that is the writer before the change is the writer again after it (the
    # role moves away and back). Its CPU under the same constant load, before and after:
    metrics = base / f"{label}-load" / "cloudwatch.json"
    if metrics.exists() and len(failovers) >= 2 and "completed" in failovers[-1]:
        recorded = json.loads(metrics.read_text())
        cpu = recorded["rds"].get("writer.CPUUtilization.Average", [])
        requests = recorded["alb"].get("alb.RequestCount.Sum", [])
        before = (push, parse(failovers[0]["started"]) - dt.timedelta(minutes=2))
        after = (parse(failovers[-1]["completed"]) + dt.timedelta(minutes=3), finished)

        def mean_between(series: list, period: tuple) -> float | None:
            values = [v for stamp, v in series if period[0] <= parse(stamp) <= period[1]]
            return sum(values) / len(values) if values else None

        classes = sorted({i["class"] for row in inventory for i in row["database"]}, key=lambda c: ("9g" in c, c))
        result["writer_cpu"] = {
            # The two periods the averages are taken over, by the datapoints' timestamps. The
            # first begins at the push, so it spans the replacement of the nodes.
            "before_window": [iso(before[0]), iso(before[1])], "after_window": [iso(after[0]), iso(after[1])],
            "before_minutes": len([1 for stamp, _ in cpu if before[0] <= parse(stamp) <= before[1]]),
            "after_minutes": len([1 for stamp, _ in cpu if after[0] <= parse(stamp) <= after[1]]),
            "before_percent": mean_between(cpu, before), "after_percent": mean_between(cpu, after),
            "before_class": next(i["class"] for i in inventory[0]["database"] if i["writer"]),
            "after_class": next(i["class"] for i in inventory[-1]["database"] if i["writer"]),
            "requests_per_second_before": (mean_between(requests, before) or 0) / 60,
            "requests_per_second_after": (mean_between(requests, after) or 0) / 60,
            "classes_seen": classes,
        }
    (base / f"{label}-summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def minutes(seconds: int) -> str:
    return f"{seconds // 60} min {seconds % 60:02d} s"


def show(result: dict) -> None:
    print(f"Change observed in results/{result['stage']}/{result['label']}-*")
    print(f"  pushed {result['push']}, pipeline finished {result['pipeline_finished']} "
          f"({minutes(result['pipeline_seconds'])}, {result['pipeline_runs']} pipeline run(s))")
    for name, key in (("node groups", "node_groups"), ("database instances", "database")):
        part = result[key]
        if part:
            print(f"  {name}: {part['from'][11:19]} to {part['to'][11:19]} ({minutes(part['seconds'])})")
    for number, failover in enumerate(result["failovers"], start=1):
        print(f"  failover {number}: {failover['started'][11:19]} to {failover.get('completed', '?')[11:19]} "
              f"({failover.get('seconds', '?')} s by RDS events), to instance {failover['to']}")
    probe = result["probe"]
    during, whole = probe["during_the_change"], probe["whole_observation"]
    print(f"  probe, push to pipeline end: {during['failed']:,} of {during['requests']:,} requests failed ({during['share']:.2%})")
    print(f"  probe, whole observation:    {whole['failed']:,} of {whole['requests']:,} requests failed ({whole['share']:.2%})")
    for period in probe["failure_periods"]:
        cause = f"failover {period['failover']}" if period["failover"] else "no failover nearby"
        print(f"    {period['from'][11:19]} to {period['to'][11:19]} ({period['seconds']:3d} s): {period['failed']:5,} of "
              f"{period['requests']:5,} failed, {period['seconds_without_a_success']:2d} s without a success, "
              f"{period['seconds_without_any_response']} s without any response; {cause}")
    print(f"  failed at failovers: {probe['failed_at_failovers']:,}; at any other time: {probe['failed_outside_failovers']:,}")
    print("  failures by cause: " + ", ".join(f"{count:,} {kind}" for kind, count in probe["failure_causes"].items()))
    for name, value in probe["response_time"].items():
        if value:
            print(f"  probe mean response time {name.replace('_', ' ')}: {value['mean_ms']:.1f} ms "
                  f"(10-second means from {value['best_10s_mean_ms']:.1f} to {value['worst_10s_mean_ms']:.1f} ms)")
    for tier, pods in result["pods"].items():
        print(f"  {tier} pods ready: lowest {pods['lowest']} of {pods['most']} (at {pods['lowest_at'][11:19]}); "
              f"samples with none ready: {pods['samples_at_zero']} (one sample every 10 s)"
              + (f"; lowest while nodes were replaced: {pods['lowest_while_nodes_were_replaced']} of "
                 f"{pods['at_start_of_node_replacement']}" if "lowest_while_nodes_were_replaced" in pods else ""))
    load = result.get("background_load")
    if load:
        print(f"  background load: {load['failed']:,} of {load['requests']:,} requests failed ({load['share']:.2%}); "
              f"{load['not_sent']:,} of {load['scheduled']:,} scheduled requests were not sent")
    writer = result.get("writer_cpu")
    if writer and writer["before_percent"] is not None and writer["after_percent"] is not None:
        print(f"  writer CPU at the constant load: {writer['before_percent']:.1f}% on {writer['before_class']} "
              f"({writer['requests_per_second_before']:,.0f} req/s) before, {writer['after_percent']:.1f}% on "
              f"{writer['after_class']} ({writer['requests_per_second_after']:,.0f} req/s) after")


if __name__ == "__main__":
    show(summarize(sys.argv[1], sys.argv[2]))

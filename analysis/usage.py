#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3>=1.35"]
# ///
"""Measures the usage-priced quantities of the bill of materials at the operating load.

    uv run analysis/usage.py              # writes results/usage.json

Some CloudWatch metrics that drive the bill arrive late: the load balancer's consumed
capacity units by tens of minutes, Aurora's billed storage I/O by about an hour. This
script is therefore run after the benchmarks. It writes the per-second quantities that
analysis/bom.py prices.

Load balancer capacity units and bytes are read for the baseline's steady runs.

Aurora's billed write I/O needs two sources. CloudWatch's VolumeWriteIOPs is the billed
count, but it is published as an average over blocks of about an hour, so it cannot be
assigned to one run or one configuration. Enhanced Monitoring reports the writer's
storage write operations every 15 seconds. The script therefore takes
  - from Enhanced Monitoring, the writer's write operations per second during each
    configuration's warm-up run, which holds 4,000 requests per second: the average load
    the bill assumes;
  - from both sources over the whole study, the ratio of billed write I/Os to write
    operations;
and prices each configuration's write operations times that ratio.

results/usage.json in this repository was written after the first session of the study
(24 Nov 2026, 03:52 UTC) and is kept as it was recorded. analysis/bom.py takes the ratio
over the recorded blocks that hold load of the three configurations. Run again against a
deployed stack, this script reads the billed metric up to the end of the last run it finds.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import statistics
import time

import boto3

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGION = os.environ.get("AWS_REGION", "us-west-2")
PROJECT = os.environ.get("PROJECT", "graviton-uplift")
STAGE, PREFIX = "a-graviton2-baseline", "a"
UTC = dt.timezone.utc


def parse(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def series(client, namespace: str, metric: str, dimensions: dict, start: dt.datetime, end: dt.datetime,
           period: int, stat: str) -> list[tuple[dt.datetime, float]]:
    response = client.get_metric_statistics(
        Namespace=namespace, MetricName=metric, Dimensions=[{"Name": k, "Value": v} for k, v in dimensions.items()],
        StartTime=start, EndTime=end, Period=period, Statistics=[stat])
    return sorted((p["Timestamp"], p[stat]) for p in response["Datapoints"])


IO_PATTERN = (r'"writeThroughput":(?<bytes>[0-9.]+),"readThroughput":[0-9.]+,"readIOsPS":[0-9.]+,'
              r'"writeIOsPS":(?<ops>[0-9.]+)')


def storage_writes(logs, start: dt.datetime, end: dt.datetime, instance: str | None = None) -> list[dict]:
    """Average storage write operations and bytes per second of each Aurora instance
    between start and end, from Enhanced Monitoring (log group RDSOSMetrics)."""
    who = f'instanceID = "{instance}"' if instance else f"instanceID like /{PROJECT}-database-instance/"
    query = (f"filter {who} | parse @message /{IO_PATTERN}/ "
             "| stats avg(ops) as write_ops, avg(bytes) as write_bytes, count(*) as samples by instanceID")
    started = logs.start_query(logGroupName="RDSOSMetrics", startTime=int(start.timestamp()),
                               endTime=int(end.timestamp()), queryString=query, limit=100)
    while True:
        result = logs.get_query_results(queryId=started["queryId"])
        if result["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
            break
        time.sleep(1)
    rows = []
    for row in result.get("results", []):
        fields = {field["field"]: field["value"] for field in row}
        if fields.get("write_ops"):
            rows.append({"instance": fields["instanceID"], "write_ops": float(fields["write_ops"]),
                         "write_bytes": float(fields["write_bytes"]), "samples": int(fields["samples"])})
    return rows


def aurora_io(session, cloudwatch, cluster: dict) -> dict:
    """Billed write I/O per configuration at the average load; see the module docstring."""
    logs = session.client("logs")
    warmups = {}
    for path in sorted((ROOT / "results").glob("[a-c]-*/[a-c]-warmup/summary.json")) + \
            sorted((ROOT / "results").glob("a-*/a2*-warmup/summary.json")):   # the first session's warm-ups
        summary = json.loads(path.read_text())
        config = json.loads((path.parent / "config.json").read_text())
        window = summary["windows"][0]
        writer = next(i["id"] for i in config["facts"]["database"]["instances"] if i["writer"])
        rows = storage_writes(logs, parse(window["from"]), parse(window["to"]), writer)
        if rows:
            warmups[summary["name"]] = {
                "stage": summary["stage"], "from": window["from"], "to": window["to"],
                "requests_per_second": window["achieved_rps"], "writer": writer,
                "writer_class": next(i["class"] for i in config["facts"]["database"]["instances"] if i["writer"]),
                "write_ops_per_second": round(rows[0]["write_ops"], 1),
                "write_bytes_per_second": round(rows[0]["write_bytes"]), "samples": rows[0]["samples"],
            }
    if not warmups:
        return {}
    # The same quantity at the tested load, from each configuration's first steady run: it
    # shows how the write operations per request change with load and with the instance.
    tested = {}
    for path in sorted((ROOT / "results").glob("[a-c]-*/[a-c]-r1/summary.json")):
        summary = json.loads(path.read_text())
        config = json.loads((path.parent / "config.json").read_text())
        window = summary["windows"][0]
        writer = next(i["id"] for i in config["facts"]["database"]["instances"] if i["writer"])
        rows = storage_writes(logs, parse(window["from"]), parse(window["to"]), writer)
        if rows:
            tested[summary["name"]] = {
                "requests_per_second": window["achieved_rps"], "write_ops_per_second": round(rows[0]["write_ops"], 1),
                "write_ops_per_request": round(rows[0]["write_ops"] / window["achieved_rps"], 4),
                "samples": rows[0]["samples"]}
    for warmup in warmups.values():
        warmup["write_ops_per_request"] = round(warmup["write_ops_per_second"] / warmup["requests_per_second"], 4)
    # CloudWatch publishes the billed count in blocks of about an hour: every five-minute
    # datapoint of a block carries the block's average. The blocks are not announced as
    # such; they are read off the series as runs of equal values. The ratio is taken over
    # whole blocks: from the first block that begins after the first warm-up started (the
    # block before it also holds the loading of the data set) to the block that contains
    # the end of the last benchmark run.
    first = min(parse(w["from"]) for w in warmups.values())
    origin = (first - dt.timedelta(hours=3)).replace(second=0, microsecond=0)
    origin -= dt.timedelta(minutes=origin.minute % 5)
    billed = series(cloudwatch, "AWS/RDS", "VolumeWriteIOPs", cluster, origin, dt.datetime.now(UTC), 300, "Sum")
    blocks: list[dict] = []
    for stamp, value in billed:
        # Datapoints of one block agree to a fraction of a percent, not exactly.
        if blocks and abs(blocks[-1]["value"] - value) <= 0.002 * max(value, 1.0):
            blocks[-1]["to"] = stamp + dt.timedelta(minutes=5)
        else:
            blocks.append({"from": stamp, "to": stamp + dt.timedelta(minutes=5), "value": value})
    # The study ends with its last benchmark run. Blocks that begin after it hold no load of
    # the study and are left out, so the ratio no longer changes once the block that
    # contains that moment is finished.
    # The ratio belongs to the first session, whose warm-ups it is applied to: the runs of the
    # second session (a3-, c2-, c2n-) do not move the end of the period.
    study_end = max(parse(json.loads(path.read_text())["windows"][-1]["to"])
                    for path in (ROOT / "results").glob("[a-c]-*/*/summary.json")
                    if not path.parent.name.endswith(("-load", "-probe"))
                    and not path.parent.name.startswith(("a3-", "c2-", "c2n-")))
    # A block is published whole, when it ends: on 24 Nov at 03:42 UTC the series ended at
    # 02:25, and at 03:50 its sixteen datapoints from 02:30 to 03:45 were there together
    # (docs/02-experiment-protocol.md, deviation 17). Every published block is therefore used.
    blocks = [block for block in blocks if first <= block["from"] < study_end]
    complete = any(block["to"] >= study_end for block in blocks)
    if not blocks:
        return {"warmups": warmups, "at_tested_load": tested}
    billed_total = operations = 0.0
    per_block = []
    for block in blocks:
        seconds = (block["to"] - block["from"]).total_seconds()
        ios = block["value"] / 300 * seconds
        ops = sum(row["write_ops"] * seconds for row in storage_writes(logs, block["from"], block["to"]))
        billed_total += ios
        operations += ops
        per_block.append({"from": block["from"].strftime("%Y-%m-%dT%H:%M:%SZ"), "to": block["to"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "billed_write_ios_per_second": round(block["value"] / 300, 1),
                          "write_operations_per_second": round(ops / seconds, 1),
                          "billed_per_operation": round(ios / ops, 4) if ops else None})
    ratio = billed_total / operations
    for warmup in warmups.values():
        warmup["billed_write_ios_per_second"] = round(warmup["write_ops_per_second"] * ratio, 1)
    ratios = [block["billed_per_operation"] for block in per_block if block["billed_per_operation"]]
    return {"period": {"from": per_block[0]["from"], "to": per_block[-1]["to"]},
            # True once the billed metric's block that contains the end of the last run is
            # finished: from then on this file does not change when the script runs again.
            "study_end": study_end.strftime("%Y-%m-%dT%H:%M:%SZ"), "covers_whole_study": complete,
            "billed_write_ios": round(billed_total), "write_operations": round(operations),
            "billed_per_operation": round(ratio, 4),
            # How far single blocks are from the ratio over all of them: the blocks' edges are
            # not sharp, so the ratio of one block says little; the spread is the uncertainty.
            "billed_per_operation_by_block": {"lowest": min(ratios), "highest": max(ratios), "blocks": per_block},
            "warmups": warmups, "at_tested_load": tested}


def main() -> None:
    session = boto3.Session(region_name=REGION)
    cloudwatch = session.client("cloudwatch")
    balancer = next(b for b in session.client("elbv2").describe_load_balancers()["LoadBalancers"]
                    if b["LoadBalancerName"] == PROJECT)
    lb = {"LoadBalancer": balancer["LoadBalancerArn"].split(":loadbalancer/")[1]}
    cluster = {"DBClusterIdentifier": PROJECT}

    windows = []
    for run in ("r1", "r2", "r3"):
        summary = json.loads((ROOT / "results" / STAGE / f"{PREFIX}-{run}" / "summary.json").read_text())
        window = summary["windows"][0]
        windows.append((parse(window["from"]), parse(window["to"]), window["achieved_rps"],
                        window["load_balancer"]["processed_bytes_per_second"]))

    lcus_per_hour, write_ios, read_ios = [], [], []
    for start, end, _, _ in windows:
        # Whole minutes inside the window: ConsumedLCUs is reported per minute in LCU-hours.
        points = [value for stamp, value in series(cloudwatch, "AWS/ApplicationELB", "ConsumedLCUs", lb,
                                                   start - dt.timedelta(minutes=1), end, 60, "Sum")
                  if stamp >= start and stamp + dt.timedelta(minutes=1) <= end]
        if points:
            lcus_per_hour.append(statistics.fmean(points) * 60)
        # Aurora bills I/O per cluster; the metric is a count per five-minute period.
        for name, bucket in (("VolumeWriteIOPs", write_ios), ("VolumeReadIOPs", read_ios)):
            points = [value for stamp, value in series(cloudwatch, "AWS/RDS", name, cluster,
                                                       start - dt.timedelta(minutes=5), end, 300, "Sum")
                      if stamp >= start and stamp + dt.timedelta(minutes=5) <= end]
            bucket += [value / 300 for value in points]

    # The same quantities in the other configurations' steady runs. The bill prices every
    # configuration with the baseline's figures (they depend on the traffic, not on the
    # processor); this shows how far that holds.
    others = {}
    for stage_dir in sorted((ROOT / "results").glob("[b-c]-*")):
        prefix = stage_dir.name[0]
        ios, lcus, bytes_per_second = [], [], []
        for run in ("r1", "r2", "r3"):
            path = stage_dir / f"{prefix}-{run}" / "summary.json"
            if not path.exists():
                continue
            window = json.loads(path.read_text())["windows"][0]
            if window["client"]["error_rate"] and window["client"]["error_rate"] > 0.001:
                continue  # a run that did not hold the load says nothing about usage at that load
            start, end = parse(window["from"]), parse(window["to"])
            ios += [value / 300 for stamp, value in series(cloudwatch, "AWS/RDS", "VolumeWriteIOPs", cluster,
                                                           start - dt.timedelta(minutes=5), end, 300, "Sum")
                    if stamp >= start and stamp + dt.timedelta(minutes=5) <= end]
            lcus += [value for stamp, value in series(cloudwatch, "AWS/ApplicationELB", "ConsumedLCUs", lb,
                                                      start - dt.timedelta(minutes=1), end, 60, "Sum")
                     if stamp >= start and stamp + dt.timedelta(minutes=1) <= end]
            bytes_per_second.append(window["load_balancer"]["processed_bytes_per_second"])
        if bytes_per_second:
            others[stage_dir.name] = {
                "aurora_write_ios_per_second": round(statistics.fmean(ios), 1) if ios else None,
                "alb_lcus_per_hour_reported": round(statistics.fmean(lcus) * 60, 2) if lcus else None,
                "alb_processed_bytes_per_second": round(statistics.fmean(bytes_per_second)),
            }

    now = dt.datetime.now(UTC)
    volume = series(cloudwatch, "AWS/RDS", "VolumeBytesUsed", cluster, now - dt.timedelta(hours=3), now, 300, "Average")
    usage = {
        "measured_on": STAGE,
        "windows": [{"from": s.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": e.strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "requests_per_second": rps} for s, e, rps, _ in windows],
        "operating_rps": round(statistics.fmean(w[2] for w in windows)),
        "alb_processed_bytes_per_second": round(statistics.fmean(w[3] for w in windows)),
        "alb_lcus_per_hour_reported": round(statistics.fmean(lcus_per_hour), 2) if lcus_per_hour else None,
        "aurora_write_ios_per_second": round(statistics.fmean(write_ios), 1) if write_ios else 0.0,
        "aurora_read_ios_per_second": round(statistics.fmean(read_ios), 1) if read_ios else 0.0,
        "aurora_io_buckets": len(write_ios),
        "aurora_storage_gb": round(volume[-1][1] / 1e9, 2) if volume else 6.0,
        "other_configurations": others,
        "aurora_io": aurora_io(session, cloudwatch, cluster),
    }
    # The bill needs the writer's write operations in each warm-up and the billed I/Os by
    # block (analysis/bom.py). The published runs name their database instances by
    # placeholders (tools/redact.py), and the metrics are kept for a limited time: if either
    # is missing, the recorded file stays.
    missing = [what for what, found in (
        ("the Enhanced Monitoring records of the database writer in the warm-ups", usage["aurora_io"].get("warmups")),
        ("the blocks of the billed I/O metric", usage["aurora_io"].get("billed_per_operation_by_block", {}).get("blocks")),
    ) if not found]
    if missing:
        raise SystemExit(f"not found: {'; '.join(missing)}. results/usage.json is left as it is. "
                         "Build with SKIP_AWS=1 to use it.")
    (ROOT / "results/usage.json").write_text(json.dumps(usage, indent=2) + "\n")
    print(json.dumps(usage, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3>=1.35"]
# ///
"""Builds a second-by-second record of a DLT test from k6's per-request output.

    uv run tools/timeline.py <test id> <output.json>

In native run mode every load generator task uploads `kpi.json`, the newline-delimited
JSON that k6 writes for each request. This script streams those files from Amazon S3
(nothing is written to disk) and counts, for each second and operation, how many
requests succeeded and failed and how long they took. It is used for the probe that
runs while the pipeline changes instance types.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

import boto3

REGION = os.environ.get("AWS_REGION", "us-west-2")
# Name of the CloudFormation stack of your Distributed Load Testing on AWS deployment.
DLT_STACK = os.environ.get("DLT_STACK", "")


def epoch_second(stamp: str) -> int:
    # k6 writes RFC 3339 with nanoseconds, e.g. 2026-11-23T14:02:11.123456789Z
    return int(dt.datetime.fromisoformat(stamp[:19] + "+00:00").timestamp())


def build(test_id: str) -> dict:
    if not DLT_STACK:
        raise SystemExit("set DLT_STACK to the name of the CloudFormation stack of your "
                         "Distributed Load Testing on AWS deployment")
    session = boto3.Session(region_name=REGION)
    outputs = session.client("cloudformation").describe_stacks(StackName=DLT_STACK)["Stacks"][0]["Outputs"]
    bucket = next(o["OutputValue"] for o in outputs if o["OutputKey"] == "ScenariosBucket")
    s3 = session.client("s3")
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=f"results/{test_id}/"):
        keys += [o["Key"] for o in page.get("Contents", []) if o["Key"].endswith("/kpi.json")]
    if not keys:
        raise SystemExit(f"no kpi.json found for {test_id}; was the test run with --keep-raw?")

    # second -> operation -> [ok, failed, duration count, duration sum, duration max]
    seconds: dict[int, dict[str, list]] = {}
    failures: dict[tuple, int] = {}
    for key in keys:
        body = s3.get_object(Bucket=bucket, Key=key)["Body"]
        for raw in body.iter_lines(chunk_size=1 << 20):
            is_request = b'"metric":"http_reqs"' in raw
            if not is_request and b'"metric":"http_req_duration"' not in raw:
                continue
            point = json.loads(raw)
            if point.get("type") != "Point":
                continue
            data = point["data"]
            tags = data.get("tags", {})
            second = epoch_second(data["time"])
            cell = seconds.setdefault(second, {}).setdefault(tags.get("name", "?"), [0, 0, 0, 0.0, 0.0])
            if is_request:
                status = tags.get("status", "0")
                if status.startswith("2"):
                    cell[0] += 1
                else:
                    cell[1] += 1
                    cause = (second, tags.get("name", "?"), status, tags.get("error_code", ""))
                    failures[cause] = failures.get(cause, 0) + 1
            else:
                cell[2] += 1
                cell[3] += data["value"]
                cell[4] = max(cell[4], data["value"])

    start, end = min(seconds), max(seconds)
    operations = sorted({name for cells in seconds.values() for name in cells})
    series = {name: {"ok": [], "failed": [], "mean_ms": [], "max_ms": []} for name in operations}
    for second in range(start, end + 1):
        cells = seconds.get(second, {})
        for name in operations:
            ok, failed, count, total, peak = cells.get(name, [0, 0, 0, 0.0, 0.0])
            series[name]["ok"].append(ok)
            series[name]["failed"].append(failed)
            series[name]["mean_ms"].append(round(total / count, 1) if count else None)
            series[name]["max_ms"].append(round(peak, 1) if count else None)

    summary = {}
    for name in operations:
        failed_seconds = [start + i for i, n in enumerate(series[name]["failed"]) if n]
        # Seconds with failures that are at most 2 s apart belong to one period.
        periods: list[list[int]] = []
        for second in failed_seconds:
            if periods and second - periods[-1][1] <= 2:
                periods[-1][1] = second
            else:
                periods.append([second, second])
        summary[name] = {
            "requests": sum(series[name]["ok"]) + sum(series[name]["failed"]),
            "failed": sum(series[name]["failed"]),
            "seconds_with_failures": len(failed_seconds),
            "periods": [{"from": iso(a), "to": iso(b), "seconds": b - a + 1,
                         "failed": sum(series[name]["failed"][a - start:b - start + 1])} for a, b in periods],
        }
    causes: dict[tuple, int] = {}
    for (_, name, status, error_code), count in failures.items():
        causes[(name, status, error_code)] = causes.get((name, status, error_code), 0) + count
    return {
        "test_id": test_id,
        "from": iso(start),
        "to": iso(end),
        "start_epoch": start,
        "seconds": end - start + 1,
        "tasks": len(keys),
        "summary": summary,
        "causes": [{"operation": n, "status": s, "error_code": e, "count": c}
                   for (n, s, e), c in sorted(causes.items(), key=lambda item: -item[1])],
        "series": series,
    }


def iso(second: int) -> str:
    return dt.datetime.fromtimestamp(second, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    timeline = build(sys.argv[1])
    with open(sys.argv[2], "w") as out:
        json.dump(timeline, out)
        out.write("\n")
    total = sum(s["requests"] for s in timeline["summary"].values())
    failed = sum(s["failed"] for s in timeline["summary"].values())
    print(f"{timeline['test_id']}: {timeline['from']} to {timeline['to']}, {total} requests, {failed} failed")
    for name, entry in timeline["summary"].items():
        if entry["failed"]:
            print(f"  {name}: {entry['failed']} failed in {entry['seconds_with_failures']} s; periods: "
                  + ", ".join(f"{p['from'][11:19]} +{p['seconds']}s ({p['failed']})" for p in entry["periods"][:12]))
    for cause in timeline["causes"][:10]:
        print(f"  cause: {cause}")


if __name__ == "__main__":
    main()

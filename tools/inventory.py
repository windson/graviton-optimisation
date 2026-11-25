#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3>=1.35"]
# ///
"""Records, every few seconds, which nodes and database instances exist and their state.

    uv run tools/inventory.py <output.jsonl> [interval seconds]

Run alongside a configuration change (scripts/change-stage.sh starts and stops it). Each
line is one snapshot: every Kubernetes node with its tier, instance type, readiness and
number of application pods, and both Aurora instances with their class, status and
role. The snapshots show when each old node left, when each new one took traffic, and
when the database writer moved.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import signal
import subprocess
import sys
import time

import boto3

REGION = os.environ.get("AWS_REGION", "us-west-2")
PROJECT = os.environ.get("PROJECT", "graviton-uplift")
NAMESPACE = "storefront"


def kubectl_json(*args: str) -> dict:
    return json.loads(subprocess.run(["kubectl", *args, "-o", "json"], check=True, capture_output=True,
                                     text=True, timeout=30).stdout)


def snapshot(rds) -> dict:
    record: dict = {"at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        pods = kubectl_json("-n", NAMESPACE, "get", "pods")["items"]
        ready_pods: dict[str, int] = {}
        for pod in pods:
            conditions = {c["type"]: c["status"] for c in pod["status"].get("conditions", [])}
            if conditions.get("Ready") == "True" and "deletionTimestamp" not in pod["metadata"]:
                node = pod["spec"].get("nodeName", "")
                ready_pods[node] = ready_pods.get(node, 0) + 1
        record["nodes"] = []
        for node in kubectl_json("get", "nodes")["items"]:
            labels = node["metadata"]["labels"]
            conditions = {c["type"]: c["status"] for c in node["status"].get("conditions", [])}
            record["nodes"].append({
                "name": node["metadata"]["name"],
                "tier": labels.get("tier"),
                "type": labels.get("node.kubernetes.io/instance-type"),
                "created": node["metadata"]["creationTimestamp"],
                "ready": conditions.get("Ready") == "True",
                "schedulable": not node["spec"].get("unschedulable", False),
                "ready_pods": ready_pods.get(node["metadata"]["name"], 0),
            })
    except Exception as error:  # the API server can be briefly unreachable; keep sampling
        record["nodes_error"] = str(error)[:200]
    try:
        cluster = rds.describe_db_clusters(DBClusterIdentifier=PROJECT)["DBClusters"][0]
        writers = {m["DBInstanceIdentifier"]: m["IsClusterWriter"] for m in cluster["DBClusterMembers"]}
        record["database"] = []
        for identifier, writer in sorted(writers.items()):
            instance = rds.describe_db_instances(DBInstanceIdentifier=identifier)["DBInstances"][0]
            record["database"].append({
                "id": next((p for p in identifier.split("-") if p.startswith("instance")), identifier),
                "class": instance["DBInstanceClass"],
                "pending_class": instance.get("PendingModifiedValues", {}).get("DBInstanceClass"),
                "status": instance["DBInstanceStatus"],
                "writer": writer,
            })
    except Exception as error:
        record["database_error"] = str(error)[:200]
    return record


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
    running = True

    def stop(*_: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    rds = boto3.Session(region_name=REGION).client("rds")
    with open(sys.argv[1], "a") as out:
        while running:
            started = time.time()
            out.write(json.dumps(snapshot(rds)) + "\n")
            out.flush()
            while running and time.time() - started < interval:
                time.sleep(0.5)


if __name__ == "__main__":
    main()

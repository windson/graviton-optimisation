#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3>=1.35"]
# ///
"""Collects what AWS did during a configuration change, as one time-ordered list.

    uv run tools/change_events.py <start, ISO 8601> <end, ISO 8601> <output.json>

Sources: the pipeline's action executions, CloudFormation stack events for the cluster
and database stacks, Amazon EKS node group updates, and Amazon RDS events (which record
each instance restart and each failover). The result is lined up against the probe's
timeline to explain every period in which requests failed.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

import boto3

REGION = os.environ.get("AWS_REGION", "us-west-2")
PROJECT = os.environ.get("PROJECT", "graviton-uplift")
UTC = dt.timezone.utc


def iso(value: dt.datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect(start: dt.datetime, end: dt.datetime) -> list[dict]:
    session = boto3.Session(region_name=REGION)
    events: list[dict] = []

    def add(when: dt.datetime, source: str, subject: str, what: str) -> None:
        if start <= when <= end:
            events.append({"at": iso(when), "source": source, "subject": subject, "event": what})

    # Pipeline actions.
    pipeline = session.client("codepipeline")
    for page in pipeline.get_paginator("list_action_executions").paginate(pipelineName=PROJECT):
        for action in page["actionExecutionDetails"]:
            name = f"{action['stageName']}/{action['actionName']}"
            if "startTime" in action:
                add(action["startTime"], "pipeline", name, "started")
            if "lastUpdateTime" in action and action["status"] != "InProgress":
                add(action["lastUpdateTime"], "pipeline", name, action["status"].lower())
        if page["actionExecutionDetails"] and page["actionExecutionDetails"][-1].get("startTime", end) < start:
            break

    # CloudFormation: one event per resource state change.
    cloudformation = session.client("cloudformation")
    for stack in (f"{PROJECT}-eks", f"{PROJECT}-database"):
        for page in cloudformation.get_paginator("describe_stack_events").paginate(StackName=stack):
            for event in page["StackEvents"]:
                add(event["Timestamp"], "cloudformation", f"{stack}/{event['LogicalResourceId']}",
                    event["ResourceStatus"] + (f": {event['ResourceStatusReason']}"
                                               if event.get("ResourceStatusReason") else ""))
            if page["StackEvents"] and page["StackEvents"][-1]["Timestamp"] < start:
                break

    # EKS node group updates (the rolling replacement of nodes).
    eks = session.client("eks")
    for nodegroup in eks.list_nodegroups(clusterName=PROJECT)["nodegroups"]:
        tier = eks.describe_nodegroup(clusterName=PROJECT, nodegroupName=nodegroup)["nodegroup"].get(
            "labels", {}).get("tier", nodegroup)
        for update_id in eks.list_updates(name=PROJECT, nodegroupName=nodegroup)["updateIds"]:
            update = eks.describe_update(name=PROJECT, nodegroupName=nodegroup, updateId=update_id)["update"]
            add(update["createdAt"], "eks", f"{tier} node group", f"{update['type']} started")

    # RDS events: restarts, failovers, class changes.
    rds = session.client("rds")
    for source_type in ("db-instance", "db-cluster"):
        for page in rds.get_paginator("describe_events").paginate(
                SourceType=source_type, StartTime=start, EndTime=end):
            for event in page["Events"]:
                if PROJECT in event["SourceIdentifier"]:
                    subject = event["SourceIdentifier"]
                    # Shorten "graviton-uplift-database-instance1-abc123" to "instance1".
                    for part in subject.split("-"):
                        if part.startswith("instance"):
                            subject = part
                    add(event["Date"], "rds", subject, event["Message"])
    return sorted(events, key=lambda e: e["at"])


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    start = dt.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
    end = dt.datetime.fromisoformat(sys.argv[2].replace("Z", "+00:00"))
    events = collect(start, end)
    with open(sys.argv[3], "w") as out:
        json.dump({"from": iso(start), "to": iso(end), "events": events}, out, indent=1)
        out.write("\n")
    for event in events:
        print(f"{event['at'][11:19]}  {event['source']:14s} {event['subject'][:44]:44s} {event['event'][:110]}")


if __name__ == "__main__":
    main()

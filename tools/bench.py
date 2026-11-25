#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3>=1.35"]
# ///
"""Runs one benchmark of the study and records everything needed to analyse it.

    uv run tools/bench.py steady   --name a-r1 --rate 7000 --tasks 28
    uv run tools/bench.py capacity --name a-cap --rate 7000 --tasks 60 --factors 0.6,0.8,1.0,1.2
    uv run tools/bench.py probe    --name ab-probe --seconds 3000   # light load, per-request output kept
    uv run tools/bench.py reset                      # remove orders written by earlier runs
    uv run tools/bench.py sql "SELECT ..."           # run a statement through the RDS Data API

A run does the following, in order:

  1. records the deployed configuration (nodes, pods, images, database class);
  2. removes the orders earlier runs wrote, so every run starts from the same data;
  3. samples CPU counters from every node's kubelet while the test runs;
  4. starts the load with Distributed Load Testing on AWS (k6, native run mode);
  5. adds the latency histograms of all load generator tasks together;
  6. reads the load balancer, database, instance and load generator metrics from
     Amazon CloudWatch for the measured window.

Results are written to results/<stage>/<name>/.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import pathlib
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from dlthist import Distribution  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGION = os.environ.get("AWS_REGION", "us-west-2")
PROJECT = os.environ.get("PROJECT", "graviton-uplift")
# Name of the CloudFormation stack of your Distributed Load Testing on AWS deployment.
DLT_STACK = os.environ.get("DLT_STACK", "")
NAMESPACE = "storefront"
UTC = dt.timezone.utc

session = boto3.Session(region_name=REGION)


def log(message: str) -> None:
    print(f"[{dt.datetime.now(UTC):%H:%M:%S}] {message}", flush=True)


def iso(ts: dt.datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def stack_outputs(name: str) -> dict[str, str]:
    stack = session.client("cloudformation").describe_stacks(StackName=name)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}


def kubectl(*args: str) -> str:
    return subprocess.run(["kubectl", *args], check=True, capture_output=True, text=True).stdout


# ---- Deployed configuration -------------------------------------------------------------


def cluster_facts() -> dict:
    nodes = json.loads(kubectl("get", "nodes", "-o", "json"))["items"]
    pods = json.loads(kubectl("-n", NAMESPACE, "get", "pods", "-o", "json"))["items"]
    database = stack_outputs(f"{PROJECT}-database")
    rds = session.client("rds")
    cluster = rds.describe_db_clusters(DBClusterIdentifier=database["ClusterIdentifier"])["DBClusters"][0]
    instances = []
    for member in cluster["DBClusterMembers"]:
        instance = rds.describe_db_instances(DBInstanceIdentifier=member["DBInstanceIdentifier"])["DBInstances"][0]
        instances.append({
            "id": instance["DBInstanceIdentifier"],
            "class": instance["DBInstanceClass"],
            "writer": member["IsClusterWriter"],
            "zone": instance["AvailabilityZone"],
            "status": instance["DBInstanceStatus"],
        })
    running = [p for p in pods if p["status"].get("phase") == "Running" and "deletionTimestamp" not in p["metadata"]]
    images = sorted({c["image"] for p in running for c in p["spec"]["containers"]})
    return {
        "stage": (ROOT / "infra/config/ACTIVE_STAGE").read_text().strip(),
        "kubernetes": json.loads(kubectl("version", "-o", "json"))["serverVersion"]["gitVersion"],
        "nodes": sorted(
            (
                {
                    "name": n["metadata"]["name"],
                    "tier": n["metadata"]["labels"].get("tier"),
                    "instance_type": n["metadata"]["labels"].get("node.kubernetes.io/instance-type"),
                    "zone": n["metadata"]["labels"].get("topology.kubernetes.io/zone"),
                    "instance_id": n["spec"].get("providerID", "").rsplit("/", 1)[-1],
                    "cpu": n["status"]["capacity"]["cpu"],
                    "kernel": n["status"]["nodeInfo"]["kernelVersion"],
                    "os": n["status"]["nodeInfo"]["osImage"],
                }
                for n in nodes
            ),
            key=lambda n: (n["tier"] or "", n["name"]),
        ),
        "pods": {
            app: sum(1 for p in running if p["metadata"]["labels"].get("app") == app)
            for app in ("storefront-web", "storefront-api")
        },
        "images": images,
        "database": {
            "engine_version": cluster["EngineVersion"],
            "storage_type": cluster.get("StorageType") or "aurora",
            "instances": instances,
        },
    }


# ---- Database access through the RDS Data API -------------------------------------------


class Database:
    def __init__(self) -> None:
        outputs = stack_outputs(f"{PROJECT}-database")
        self.cluster_arn = outputs["ClusterArn"]
        self.secret_arn = outputs["SecretArn"]
        self.name = outputs["DatabaseName"]
        self.client = session.client("rds-data")

    def execute(self, sql: str) -> dict:
        return self.client.execute_statement(
            resourceArn=self.cluster_arn, secretArn=self.secret_arn, database=self.name, sql=sql,
            includeResultMetadata=True,
        )

    @staticmethod
    def to_rows(response: dict) -> list[dict]:
        names = [c["label"] for c in response.get("columnMetadata", [])]
        result = []
        for record in response.get("records", []):
            values = [None if f.get("isNull") else next(iter(f.values())) for f in record]
            result.append(dict(zip(names, values)))
        return result

    def rows(self, sql: str) -> list[dict]:
        return self.to_rows(self.execute(sql))

    def reset(self) -> dict:
        """Deletes the orders that load tests added on top of the generated data set."""
        seeded = int(self.rows("SELECT max_order_id FROM seed_meta WHERE id = 1")[0]["max_order_id"])
        deleted = {"order_item": 0, "orders": 0}
        for table, column in (("order_item", "order_id"), ("orders", "id")):
            while True:
                count = self.execute(f"DELETE FROM {table} WHERE {column} > {seeded} LIMIT 20000")[
                    "numberOfRecordsUpdated"]
                deleted[table] += count
                if count == 0:
                    break
        return {"seeded_max_order_id": seeded, "deleted": deleted}

    STATUS = (
        "Questions", "Queries", "Com_select", "Com_insert", "Com_update", "Com_delete", "Com_commit",
        "Com_stmt_execute", "Innodb_rows_read", "Innodb_rows_inserted", "Innodb_rows_updated",
        "Innodb_rows_deleted", "Innodb_buffer_pool_reads", "Innodb_buffer_pool_read_requests",
        "Innodb_row_lock_waits", "Innodb_row_lock_time", "Created_tmp_tables", "Created_tmp_disk_tables",
        "Sort_rows", "Slow_queries", "Aborted_clients", "Connections", "Uptime",
    )

    def status(self) -> dict:
        names = ", ".join(f"'{name}'" for name in self.STATUS)
        rows = self.rows(f"SHOW GLOBAL STATUS WHERE Variable_name IN ({names})")
        snapshot = {r["Variable_name"]: int(r["Value"]) for r in rows}
        snapshot["at"] = iso(dt.datetime.now(UTC))
        return snapshot


# ---- Node CPU sampling ------------------------------------------------------------------


class KubeletSampler(threading.Thread):
    """Reads cumulative CPU counters from each node's kubelet through `kubectl proxy`.

    Counters are cumulative CPU seconds, so the average number of cores a tier used
    over any window is (counter at end - counter at start) / elapsed time, independent
    of the sampling interval.
    """

    def __init__(self, nodes: list[dict], path: pathlib.Path, interval: float = 15.0) -> None:
        super().__init__(daemon=True)
        self.nodes = [n for n in nodes if n["tier"]]
        self.path = path
        self.interval = interval
        self.stop_event = threading.Event()
        # A free local port, so that several runs can sample at the same time.
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.proxy = subprocess.Popen(
            ["kubectl", "proxy", f"--port={self.port}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)

    LINE = re.compile(r"^(\w+)(\{[^}]*\})?\s+([0-9.eE+-]+)(?:\s+(\d+))?$")

    def sample_node(self, node: dict) -> dict | None:
        url = f"http://127.0.0.1:{self.port}/api/v1/nodes/{node['name']}/proxy/metrics/resource"
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                text = response.read().decode()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return {"node": node["name"], "tier": node["tier"], "error": str(error)}
        sample = {"node": node["name"], "tier": node["tier"], "app_cpu_s": 0.0, "app_containers": 0}
        for line in text.splitlines():
            match = self.LINE.match(line)
            if not match:
                continue
            metric, labels, value, timestamp = match.groups()
            if metric == "node_cpu_usage_seconds_total":
                sample["node_cpu_s"] = float(value)
                sample["ts_ms"] = int(timestamp) if timestamp else int(time.time() * 1000)
            elif metric == "node_memory_working_set_bytes":
                sample["node_memory_bytes"] = float(value)
            elif metric == "container_cpu_usage_seconds_total" and labels and f'namespace="{NAMESPACE}"' in labels:
                sample["app_cpu_s"] += float(value)
                sample["app_containers"] += 1
        return sample

    def run(self) -> None:
        with self.path.open("w") as out:
            while not self.stop_event.is_set():
                started = time.time()
                for node in self.nodes:
                    sample = self.sample_node(node)
                    if sample:
                        sample["at"] = iso(dt.datetime.now(UTC))
                        out.write(json.dumps(sample) + "\n")
                out.flush()
                self.stop_event.wait(max(1.0, self.interval - (time.time() - started)))

    def stop(self) -> None:
        self.stop_event.set()
        self.join(timeout=30)
        self.proxy.terminate()


def throttling_snapshot(nodes: list[dict]) -> dict:
    """CFS throttling counters of the application containers (from cAdvisor), per tier."""
    totals: dict[str, dict[str, float]] = {}
    pattern = re.compile(r'^(container_cpu_cfs_(?:throttled_)?periods_total|container_cpu_cfs_throttled_seconds_total)'
                         r'\{([^}]*)\}\s+([0-9.eE+-]+)')
    for node in nodes:
        if node["tier"] not in ("web", "api"):
            continue
        try:
            text = kubectl("get", "--raw", f"/api/v1/nodes/{node['name']}/proxy/metrics/cadvisor")
        except subprocess.CalledProcessError:
            continue
        tier = totals.setdefault(node["tier"], {})
        for line in text.splitlines():
            match = pattern.match(line)
            if match and f'namespace="{NAMESPACE}"' in match.group(2) and 'container=""' not in match.group(2):
                tier[match.group(1)] = tier.get(match.group(1), 0.0) + float(match.group(3))
    return totals


# ---- Distributed Load Testing on AWS ----------------------------------------------------


class Dlt:
    def __init__(self) -> None:
        if not DLT_STACK:
            raise SystemExit("set DLT_STACK to the name of the CloudFormation stack of your "
                             "Distributed Load Testing on AWS deployment")
        outputs = stack_outputs(DLT_STACK)
        self.endpoint = next(v for k, v in outputs.items() if k.startswith("DLTApiEndpoint")).rstrip("/")
        self.bucket = outputs["ScenariosBucket"]
        self.s3 = session.client("s3")
        self.credentials = session.get_credentials()

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = AWSRequest(method=method, url=f"{self.endpoint}{path}", data=data,
                             headers={"Content-Type": "application/json"})
        SigV4Auth(self.credentials.get_frozen_credentials(), "execute-api", REGION).add_auth(request)
        http = urllib.request.Request(request.url, data=data, method=method, headers=dict(request.headers))
        try:
            with urllib.request.urlopen(http, timeout=60) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"DLT API {method} {path}: {error.code} {error.read().decode()[:500]}") from error

    def start(self, test_id: str, script: str, tasks: int, description: str, seconds: int, tags: list[str]) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=f"public/test-scenarios/k6/{test_id}.js", Body=script.encode(),
                           ContentType="text/javascript")
        self.call("POST", "/scenarios", {
            "testId": test_id,
            "testName": test_id,
            "testDescription": description,
            "testType": "k6",
            "fileType": "script",
            "showLive": False,
            "tags": tags,
            "testTaskConfigs": [{"region": REGION, "taskCount": tasks, "concurrency": 1}],
            # In native run mode the script alone defines the load; these two values are
            # required by the API schema and only describe the run.
            "testScenario": {
                "execution": [{"ramp-up": "60s", "hold-for": f"{max(1, seconds - 60)}s", "scenario": test_id,
                               "executor": "k6"}],
                "scenarios": {test_id: {"script": f"{test_id}.js"}},
            },
            "regionalTaskDetails": {REGION: {"dltAvailableTasks": 2000}},
            # Generous: covers result reduction and upload after k6 exits.
            "nativeRunMode": {"maxTestDurationSeconds": seconds + 900},
        })

    def cancel(self, test_id: str) -> dict:
        """Stops a running test. Its tasks still reduce and upload what they measured."""
        return self.call("POST", f"/scenarios/{test_id}")

    def wait(self, test_id: str, timeout: int) -> dict:
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            scenario = self.call("GET", f"/scenarios/{test_id}?history=false")
            status = scenario.get("status")
            if status != last:
                log(f"DLT {test_id}: {status}")
                last = status
            if status in ("complete", "failed", "cancelled"):
                return scenario
            time.sleep(20)
        raise TimeoutError(f"DLT test {test_id} did not finish within {timeout} s")

    def task_results(self, test_id: str) -> list[dict]:
        keys = []
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=f"results/{test_id}/"):
            keys += [o["Key"] for o in page.get("Contents", [])]
        results = []
        for key in keys:
            if key.endswith("/result.json"):
                results.append(json.loads(self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()))
        return results

    def delete_raw_output(self, test_id: str) -> int:
        """Removes k6's per-request dumps of this test. The reduced results are kept."""
        paginator = self.s3.get_paginator("list_objects_v2")
        doomed = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=f"results/{test_id}/"):
            doomed += [{"Key": o["Key"]} for o in page.get("Contents", [])
                       if o["Key"].endswith(("/kpi.json", "/kpi.csv"))]
        for start in range(0, len(doomed), 1000):
            self.s3.delete_objects(Bucket=self.bucket, Delete={"Objects": doomed[start:start + 1000]})
        return len(doomed)


# ---- k6 script --------------------------------------------------------------------------


def k6_script(config: dict) -> str:
    template = (ROOT / "loadtest/workload.js").read_text()
    placeholder = "const CONFIG = __CONFIG__;"
    if template.count(placeholder) != 1:
        raise RuntimeError("loadtest/workload.js must contain the CONFIG placeholder exactly once")
    return template.replace(placeholder, f"const CONFIG = {json.dumps(config, indent=2)};")


def load_mix() -> dict:
    return json.loads((ROOT / "loadtest/mix.json").read_text())


def base_config(base_url: str, data_set: dict, mix: dict, per_task_peak: float) -> dict:
    return {
        "baseUrl": base_url,
        "dataSet": data_set,
        "mix": mix["weights"],
        "oneWordSearchShare": mix["oneWordSearchShare"],
        "timeout": "5s",
        # Rates are per minute so that a fractional per-second share stays exact.
        "timeUnit": "1m",
        "preAllocatedVUs": max(50, math.ceil(per_task_peak * 0.25)),
        "maxVUs": 600,
    }


def steady_config(common: dict, per_task: float, ramp: int, hold: int, settle: int) -> tuple[dict, int, list[dict]]:
    rate = round(per_task * 60)
    config = dict(common)
    config["startRate"] = max(1, round(rate * 0.2))
    config["stages"] = [{"target": rate, "duration": f"{ramp}s"}, {"target": rate, "duration": f"{hold}s"}]
    config["windows"] = [
        {"fromMs": 0, "toMs": (ramp + settle) * 1000, "label": "ramp"},
        {"fromMs": (ramp + settle) * 1000, "toMs": (ramp + hold) * 1000, "label": None},
    ]
    windows = [{"label": None, "seconds": hold - settle, "factor": 1.0}]
    return config, ramp + hold, windows


def capacity_config(common: dict, per_task: float, factors: list[float], ramp: int, step: int,
                    settle: int) -> tuple[dict, int, list[dict]]:
    """A staircase: each step holds a multiple of the base rate, and is labelled separately."""
    config = dict(common)
    config["startRate"] = max(1, round(per_task * factors[0] * 60 * 0.2))
    stages = [{"target": round(per_task * factors[0] * 60), "duration": f"{ramp}s"}]
    windows_js = [{"fromMs": 0, "toMs": ramp * 1000, "label": "ramp"}]
    windows = []
    elapsed = ramp
    for index, factor in enumerate(factors, start=1):
        target = round(per_task * factor * 60)
        stages += [{"target": target, "duration": "5s"}, {"target": target, "duration": f"{step - 5}s"}]
        label = f"s{index:02d}"
        windows_js.append({"fromMs": elapsed * 1000, "toMs": (elapsed + settle) * 1000, "label": "ramp"})
        windows_js.append({"fromMs": (elapsed + settle) * 1000, "toMs": (elapsed + step) * 1000, "label": label})
        windows.append({"label": label, "seconds": step - settle, "factor": factor,
                        "from_s": elapsed + settle, "to_s": elapsed + step})
        elapsed += step
    config["stages"] = stages
    config["windows"] = windows_js
    return config, elapsed, windows


# ---- Results ----------------------------------------------------------------------------

NON_MEASURED = {"ramp", "outside", ""}


def merge_tasks(results: list[dict]) -> tuple[dict[str, Distribution], list[dict]]:
    labels: dict[str, Distribution] = {}
    tasks = []
    for result in results:
        statistics = result["statistics"]
        if isinstance(statistics, str):
            statistics = json.loads(statistics)
        for entry in statistics["labels"]:
            labels.setdefault(entry["label"], Distribution()).add(entry)
        tasks.append({
            "task": result["taskId"],
            "start": result["startTime"],
            "end": result["endTime"],
            "requests": result["summary"]["totalRequestCount"],
            "failed": result["summary"]["failureCount"],
            "mean_ms": result["summary"]["averageResponseTimeMilliseconds"],
            "p99_ms": result["summary"]["p99"],
        })
    return labels, sorted(tasks, key=lambda t: t["task"])


def metric_data(namespace: str, queries: list[tuple[str, str, dict, str]], start: dt.datetime,
                end: dt.datetime, period: int = 60) -> dict:
    """queries: (id, metric name, dimensions, statistic). Returns id -> [[time, value], ...]."""
    client = session.client("cloudwatch")
    out: dict[str, list] = {}
    for offset in range(0, len(queries), 400):
        chunk = queries[offset:offset + 400]
        request = [{
            "Id": f"q{offset + i}",
            "MetricStat": {
                "Metric": {"Namespace": namespace, "MetricName": name,
                           "Dimensions": [{"Name": k, "Value": v} for k, v in dims.items()]},
                "Period": period, "Stat": stat},
            "ReturnData": True,
        } for i, (_, name, dims, stat) in enumerate(chunk)]
        ids = {f"q{offset + i}": chunk[i][0] for i in range(len(chunk))}
        paginator = client.get_paginator("get_metric_data")
        for page in paginator.paginate(MetricDataQueries=request, StartTime=start, EndTime=end,
                                       ScanBy="TimestampAscending"):
            for result in page["MetricDataResults"]:
                out.setdefault(ids[result["Id"]], []).extend(
                    [iso(t), v] for t, v in zip(result["Timestamps"], result["Values"]))
    return out


def cloudwatch_metrics(facts: dict, test_id: str, start: dt.datetime, end: dt.datetime) -> dict:
    start = start.replace(second=0, microsecond=0) - dt.timedelta(minutes=1)
    end = end.replace(second=0, microsecond=0) + dt.timedelta(minutes=2)
    metrics: dict = {"from": iso(start), "to": iso(end)}

    # Aurora instances and cluster.
    queries = []
    for instance in facts["database"]["instances"]:
        role = "writer" if instance["writer"] else "reader"
        dims = {"DBInstanceIdentifier": instance["id"]}
        for name, stats in {
            "CPUUtilization": ("Average", "Maximum"), "DatabaseConnections": ("Average",),
            "CommitLatency": ("Average",), "CommitThroughput": ("Average",), "SelectLatency": ("Average",),
            "SelectThroughput": ("Average",), "DMLLatency": ("Average",), "DMLThroughput": ("Average",),
            "Queries": ("Average",), "BufferCacheHitRatio": ("Average",), "FreeableMemory": ("Minimum",),
            "AuroraReplicaLag": ("Maximum",), "NetworkReceiveThroughput": ("Average",),
            "NetworkTransmitThroughput": ("Average",), "Deadlocks": ("Average",), "RowLockTime": ("Average",),
            "ActiveTransactions": ("Average",),
        }.items():
            queries += [(f"{role}.{name}.{stat}", name, dims, stat) for stat in stats]
    metrics["rds"] = metric_data("AWS/RDS", queries, start, end)
    # Billed storage I/O and volume size are published per cluster every five minutes.
    cluster = {"DBClusterIdentifier": stack_outputs(f"{PROJECT}-database")["ClusterIdentifier"]}
    five = dt.timedelta(minutes=5)
    metrics["rds_volume"] = metric_data(
        "AWS/RDS",
        [("cluster.VolumeReadIOPs.Sum", "VolumeReadIOPs", cluster, "Sum"),
         ("cluster.VolumeWriteIOPs.Sum", "VolumeWriteIOPs", cluster, "Sum"),
         ("cluster.VolumeBytesUsed.Average", "VolumeBytesUsed", cluster, "Average")],
        start - five, end + five, period=300)

    # Load balancer and its two target groups.
    elb = session.client("elbv2")
    balancers = [b for b in elb.describe_load_balancers()["LoadBalancers"] if b["LoadBalancerName"] == PROJECT]
    if balancers:
        arn = balancers[0]["LoadBalancerArn"]
        lb = arn.split(":loadbalancer/")[1]
        queries = []
        for name, stats in {
            "RequestCount": ("Sum",), "TargetResponseTime": ("Average", "p50", "p90", "p95", "p99"),
            "HTTPCode_Target_2XX_Count": ("Sum",), "HTTPCode_Target_4XX_Count": ("Sum",),
            "HTTPCode_Target_5XX_Count": ("Sum",), "HTTPCode_ELB_5XX_Count": ("Sum",),
            "HTTPCode_ELB_4XX_Count": ("Sum",), "TargetConnectionErrorCount": ("Sum",),
            "RejectedConnectionCount": ("Sum",), "ActiveConnectionCount": ("Sum",),
            "NewConnectionCount": ("Sum",), "ProcessedBytes": ("Sum",), "ConsumedLCUs": ("Sum",),
        }.items():
            queries += [(f"alb.{name}.{stat}", name, {"LoadBalancer": lb}, stat) for stat in stats]
        for group in elb.describe_target_groups(LoadBalancerArn=arn)["TargetGroups"]:
            # With IP targets the controller leaves the group's own port unset; the health
            # check path tells the two groups apart.
            tier = "api" if group.get("HealthCheckPath", "").startswith("/api/") else "web"
            dims = {"LoadBalancer": lb, "TargetGroup": group["TargetGroupArn"].split(":")[-1]}
            for name, stats in {"RequestCount": ("Sum",), "TargetResponseTime": ("Average", "p50", "p95", "p99"),
                                "HTTPCode_Target_5XX_Count": ("Sum",), "HealthyHostCount": ("Minimum",)}.items():
                queries += [(f"{tier}.{name}.{stat}", name, dims, stat) for stat in stats]
        metrics["alb"] = metric_data("AWS/ApplicationELB", queries, start, end)

    # Instance CPU as CloudWatch sees it (a cross-check of the kubelet counters).
    queries = [(f"{node['tier']}.{node['instance_id']}.CPUUtilization.Average", "CPUUtilization",
                {"InstanceId": node["instance_id"]}, "Average") for node in facts["nodes"] if node["instance_id"]]
    metrics["ec2"] = metric_data("AWS/EC2", queries, start, end)

    # Load generator tasks: confirm the generators themselves were not the bottleneck.
    dims = {"ClusterName": DLT_STACK, "ServiceName": f"dlt-{test_id}-{REGION}"}
    queries = [(f"generator.{name}.{stat}", name, dims, stat)
               for name in ("CpuUtilized", "CpuReserved", "MemoryUtilized", "MemoryReserved", "RunningTaskCount")
               for stat in ("Average", "Maximum")]
    metrics["generator"] = metric_data("ECS/ContainerInsights", queries, start, end)
    return metrics


# ---- Commands ---------------------------------------------------------------------------


def endpoint() -> str:
    host = kubectl("-n", NAMESPACE, "get", "ingress", "storefront", "-o",
                   "jsonpath={.status.loadBalancer.ingress[0].hostname}").strip()
    if not host:
        raise RuntimeError("the storefront ingress has no load balancer address")
    return f"http://{host}"


def run_test(args: argparse.Namespace) -> None:
    mix = load_mix()
    facts = cluster_facts()
    stage = facts["stage"]
    out = ROOT / "results" / stage / args.name
    if out.exists() and any(out.iterdir()) and not args.overwrite:
        raise SystemExit(f"{out} already has results; choose another --name or pass --overwrite")
    out.mkdir(parents=True, exist_ok=True)

    base_url = endpoint()
    database = Database()
    # Dimensions of the generated data set, read from the database so the script's random
    # choices cover exactly the rows that exist.
    meta = database.rows("SELECT version, categories, products, customers, orders, max_order_id, reviews "
                         "FROM seed_meta WHERE id = 1")[0]
    data_set = {key: int(meta[key]) for key in ("categories", "products", "customers")}

    if args.kind == "steady":
        per_task = args.rate / args.tasks
        common = base_config(base_url, data_set, mix, per_task)
        config, seconds, windows = steady_config(common, per_task, args.ramp, args.hold, args.settle)
    elif args.kind == "probe":
        # One long window, labelled by operation, at a constant low rate. The per-request
        # output is kept so that tools/timeline.py can rebuild what happened second by second.
        per_task = args.rate / args.tasks
        common = base_config(base_url, data_set, mix, per_task)
        config, seconds, windows = steady_config(common, per_task, 30, args.seconds, 0)
    else:
        factors = [float(f) for f in args.factors.split(",")]
        per_task = args.rate / args.tasks
        common = base_config(base_url, data_set, mix, per_task * max(factors))
        config, seconds, windows = capacity_config(common, per_task, factors, args.ramp, args.step, args.settle)

    test_id = f"gu-{args.name}-{dt.datetime.now(UTC):%m%d%H%M}"
    record = {
        "test_id": test_id, "kind": args.kind, "name": args.name, "stage": stage,
        "target_rps": args.rate, "tasks": args.tasks, "script_seconds": seconds, "windows": windows,
        "mix": mix, "k6": {k: v for k, v in config.items() if k not in ("mix", "dataSet")},
        "data_set": meta, "facts": facts,
    }
    (out / "config.json").write_text(json.dumps(record, indent=2) + "\n")
    (out / "workload.js").write_text(k6_script(config))

    if not args.no_reset:
        log(f"reset: {database.reset()['deleted']}")
        time.sleep(args.pause)

    sampler = KubeletSampler(facts["nodes"], out / "kubelet.jsonl")
    throttling_before = throttling_snapshot(facts["nodes"])
    status_before = database.status()
    sampler.start()
    dlt = Dlt()
    try:
        log(f"starting {test_id}: {args.kind}, {args.rate} req/s over {args.tasks} tasks, {seconds} s")
        dlt.start(test_id, k6_script(config), args.tasks,
                  f"{PROJECT} {stage} {args.kind} {args.name}", seconds, [PROJECT, stage, args.kind])
        scenario = dlt.wait(test_id, seconds + 1800)
    finally:
        status_after = database.status()
        throttling_after = throttling_snapshot(facts["nodes"])
        sampler.stop()

    results = dlt.task_results(test_id)
    labels, tasks = merge_tasks(results)
    measured = Distribution()
    for label, distribution in labels.items():
        if label not in NON_MEASURED:
            measured.merge(distribution)
    (out / "dlt.json").write_text(json.dumps({
        "test_id": test_id, "status": scenario.get("status"), "tasks_reporting": len(results), "tasks": tasks,
        "labels": {label: {"summary": d.summary(), "state": d.to_state()} for label, d in sorted(labels.items())},
        "measured": {"summary": measured.summary(), "state": measured.to_state()},
    }) + "\n")
    (out / "database.json").write_text(json.dumps({
        "before": status_before, "after": status_after,
        "throttling_before": throttling_before, "throttling_after": throttling_after}, indent=2) + "\n")

    if results:
        start = min(parse_time(r["startTime"]) for r in results)
        end = max(parse_time(r["endTime"]) for r in results)
        wait = (end + dt.timedelta(seconds=200) - dt.datetime.now(UTC)).total_seconds()
        if wait > 0:
            log(f"waiting {wait:.0f} s for CloudWatch metrics")
            time.sleep(wait)
        (out / "cloudwatch.json").write_text(json.dumps(cloudwatch_metrics(facts, test_id, start, end)) + "\n")
    if not args.keep_raw:
        log(f"deleted {dlt.delete_raw_output(test_id)} raw k6 output objects")

    seconds_measured = sum(w["seconds"] for w in windows)
    summary = measured.summary()
    log(f"{test_id}: status={scenario.get('status')} tasks={len(results)}/{args.tasks} "
        f"requests={summary['requests']} failed={summary['failed']} "
        f"mean={summary['mean_ms']} p50={summary['p50_ms']} p95={summary['p95_ms']} p99={summary['p99_ms']} ms")
    if args.kind in ("steady", "probe"):
        log(f"achieved {summary['requests'] / seconds_measured:.1f} req/s of {args.rate} target")
    else:
        for window in windows:
            d = labels.get(window["label"])
            if d:
                s = d.summary()
                log(f"  {window['label']} x{window['factor']:<4} target={args.rate * window['factor']:8.0f} "
                    f"achieved={s['requests'] / window['seconds']:8.1f} req/s  err={s['error_rate']:.4%} "
                    f"p50={s['p50_ms']} p95={s['p95_ms']} p99={s['p99_ms']} ms")
    if scenario.get("status") not in ("complete", "cancelled"):
        raise SystemExit(f"DLT reported status {scenario.get('status')}: {scenario.get('errorReason', '')}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    def common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--name", required=True, help="run name; results go to results/<stage>/<name>")
        sub.add_argument("--rate", type=float, required=True, help="total requests per second (base rate)")
        sub.add_argument("--tasks", type=int, required=True, help="number of load generator tasks")
        sub.add_argument("--ramp", type=int, default=60, help="seconds to ramp up before measuring")
        sub.add_argument("--settle", type=int, default=10, help="seconds discarded after each rate change")
        sub.add_argument("--pause", type=int, default=45, help="seconds to wait after the data reset")
        sub.add_argument("--no-reset", action="store_true", help="do not remove orders written by earlier runs")
        sub.add_argument("--keep-raw", action="store_true", help="keep k6's per-request output in S3")
        sub.add_argument("--overwrite", action="store_true")

    steady = commands.add_parser("steady", help="fixed arrival rate, measured per operation")
    common(steady)
    steady.add_argument("--hold", type=int, default=600, help="seconds at the target rate")
    steady.set_defaults(kind="steady")

    capacity = commands.add_parser("capacity", help="staircase of arrival rates, measured per step")
    common(capacity)
    capacity.add_argument("--factors", required=True, help="comma-separated multiples of --rate, one per step")
    capacity.add_argument("--step", type=int, default=120, help="seconds per step")
    capacity.set_defaults(kind="capacity")

    probe = commands.add_parser("probe", help="constant low rate with per-request output kept, for timelines")
    probe.add_argument("--name", required=True)
    probe.add_argument("--rate", type=float, default=100.0)
    probe.add_argument("--tasks", type=int, default=2)
    probe.add_argument("--seconds", type=int, required=True, help="how long to probe")
    probe.add_argument("--overwrite", action="store_true")
    probe.set_defaults(kind="probe", no_reset=True, keep_raw=True, pause=0)

    cancel = commands.add_parser("cancel", help="stop the DLT test of a run that is in progress")
    cancel.add_argument("run", help="run directory, e.g. results/<stage>/<name>")
    delete_raw = commands.add_parser("delete-raw", help="delete the per-request k6 output a run kept in S3")
    delete_raw.add_argument("run", help="run directory, e.g. results/<stage>/<name>")

    commands.add_parser("reset", help="remove orders written by earlier runs")
    commands.add_parser("facts", help="print the deployed configuration")
    sql = commands.add_parser("sql", help="run one SQL statement through the RDS Data API")
    sql.add_argument("statement")

    args = parser.parse_args()
    if args.command in ("steady", "capacity", "probe"):
        run_test(args)
    elif args.command == "cancel":
        test_id = json.loads((pathlib.Path(args.run) / "config.json").read_text())["test_id"]
        print(json.dumps(Dlt().cancel(test_id)))
    elif args.command == "delete-raw":
        test_id = json.loads((pathlib.Path(args.run) / "config.json").read_text())["test_id"]
        print(f"deleted {Dlt().delete_raw_output(test_id)} objects")
    elif args.command == "reset":
        print(json.dumps(Database().reset(), indent=2))
    elif args.command == "facts":
        print(json.dumps(cluster_facts(), indent=2))
    elif args.command == "sql":
        response = Database().execute(args.statement)
        if response.get("columnMetadata"):
            print(json.dumps(Database.to_rows(response), indent=1, default=str))
        else:
            print(json.dumps({"numberOfRecordsUpdated": response.get("numberOfRecordsUpdated")}))


if __name__ == "__main__":
    main()

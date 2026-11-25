#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3>=1.35"]
# ///
"""Takes a snapshot of every public price the study's bill of materials uses.

    uv run analysis/pricing.py            # writes results/pricing/<region>.json

Prices come from the AWS Price List API (On-Demand), the Savings Plans API and the
Amazon RDS reserved-instance offerings API (one-year, no-upfront rates). Each entry records the SKU and usage type it was read from, so the
figures in the report can be traced back to the API response.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib

import boto3

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGION = os.environ.get("AWS_REGION", "us-west-2")
session = boto3.Session()
pricing = session.client("pricing", region_name="us-east-1")


def products(service: str, **filters: str) -> list[dict]:
    request = [{"Type": "TERM_MATCH", "Field": k, "Value": v} for k, v in filters.items()]
    found = []
    for page in pricing.get_paginator("get_products").paginate(ServiceCode=service, Filters=request):
        found += [json.loads(item) for item in page["PriceList"]]
    return found


def on_demand(product: dict) -> dict:
    """The single On-Demand price dimension of a product."""
    term = next(iter(product["terms"]["OnDemand"].values()))
    dimensions = list(term["priceDimensions"].values())
    # Tiered products (data transfer) have several dimensions; keep them all, lowest tier first.
    dimensions.sort(key=lambda d: float(d.get("beginRange", 0)))
    return {
        "sku": product["product"]["sku"],
        "usagetype": product["product"]["attributes"].get("usagetype"),
        "description": dimensions[0]["description"],
        "unit": dimensions[0]["unit"],
        "usd": float(dimensions[0]["pricePerUnit"]["USD"]),
        "tiers": [{"from": d.get("beginRange"), "to": d.get("endRange"), "usd": float(d["pricePerUnit"]["USD"])}
                  for d in dimensions] if len(dimensions) > 1 else None,
    }


def one(items: list[dict], what: str) -> dict:
    priced = [p for p in items if p["terms"].get("OnDemand")]
    if len(priced) != 1:
        raise RuntimeError(f"expected one product for {what}, found {len(priced)}: "
                           f"{[p['product']['attributes'].get('usagetype') for p in priced]}")
    return priced[0]


def stage_instance_types() -> tuple[set[str], set[str]]:
    ec2, rds = set(), set()
    for stage in sorted((ROOT / "infra/stages").iterdir()):
        eks = json.loads((stage / "eks.json").read_text())["Parameters"]
        ec2 |= {eks[key] for key in ("SystemInstanceType", "WebInstanceType", "ApiInstanceType")}
        rds.add(json.loads((stage / "database.json").read_text())["Parameters"]["DBInstanceClass"])
    return ec2, rds


def ec2_price(instance_type: str) -> dict:
    product = one(products("AmazonEC2", instanceType=instance_type, regionCode=REGION, operatingSystem="Linux",
                           tenancy="Shared", preInstalledSw="NA", capacitystatus="Used"), instance_type)
    attributes = product["product"]["attributes"]
    return {**on_demand(product), "vcpu": int(attributes["vcpu"]), "memory": attributes["memory"],
            "processor": attributes["physicalProcessor"], "family": attributes["instanceFamily"]}


def aurora_price(instance_class: str) -> dict:
    found = products("AmazonRDS", instanceType=instance_class, regionCode=REGION, databaseEngine="Aurora MySQL")
    result = {}
    for product in found:
        attributes = product["product"]["attributes"]
        usagetype = attributes.get("usagetype", "")
        # Usage types look like USW2-InstanceUsage:db.r6g.8xl (Aurora Standard) and
        # USW2-InstanceUsageIOOptimized:db.r6g.8xl (Aurora I/O-Optimized).
        if "-InstanceUsage:" in usagetype:
            kind = "standard"
        elif "-InstanceUsageIOOptimized:" in usagetype:
            kind = "io_optimized"
        else:
            continue
        result[kind] = {**on_demand(product), "vcpu": int(attributes["vcpu"]), "memory": attributes["memory"],
                        "processor": attributes["physicalProcessor"]}
    if "standard" not in result:
        raise RuntimeError(f"no Aurora Standard price for {instance_class}")
    result["commitments"] = aurora_commitments(instance_class)
    return result


def aurora_commitments(instance_class: str) -> dict:
    """One-year, no-upfront commitment rates for an Aurora MySQL class, or None where AWS
    publishes no such offer. Older classes are covered by Reserved Instances, newer ones by
    Database Savings Plans, and a class can be too new to have either."""
    offers = session.client("rds", region_name=REGION).describe_reserved_db_instances_offerings(
        DBInstanceClass=instance_class, ProductDescription="aurora-mysql", Duration="31536000",
        OfferingType="No Upfront", MultiAZ=False)["ReservedDBInstancesOfferings"]
    reserved = offers[0]["RecurringCharges"][0]["RecurringChargeAmount"] if offers else None

    plans = session.client("savingsplans", region_name="us-east-1").describe_savings_plans_offering_rates(
        savingsPlanTypes=["Database"], savingsPlanPaymentOptions=["No Upfront"],
        filters=[{"name": "region", "values": [REGION]}, {"name": "instanceType", "values": [instance_class]}],
        maxResults=1000)["searchResults"]
    savings_plan = None
    for rate in plans:
        properties = {p["name"]: p["value"] for p in rate["properties"]}
        if (properties.get("productDescription") == "Aurora MySQL" and "-InstanceUsage:" in rate["usageType"]
                and rate["savingsPlanOffering"]["durationSeconds"] == 31_536_000):
            savings_plan = float(rate["rate"])
    return {"reserved_1yr_no_upfront_usd": reserved, "database_sp_1yr_no_upfront_usd": savings_plan}


def by_usagetype(service: str, usagetype: str, **filters: str) -> dict:
    return on_demand(one(products(service, usagetype=usagetype, **filters), usagetype))


def savings_plan_rates(instance_types: set[str]) -> dict:
    """One-year, no-upfront Compute and EC2 Instance Savings Plans rates, where published."""
    client = session.client("savingsplans", region_name="us-east-1")
    rates: dict[str, dict] = {}
    for plan_type, key in (("Compute", "compute_sp_1yr_no_upfront_usd"), ("EC2Instance", "ec2_instance_sp_1yr_no_upfront_usd")):
        token = None
        while True:
            request = dict(
                savingsPlanPaymentOptions=["No Upfront"], savingsPlanTypes=[plan_type], products=["EC2"],
                serviceCodes=["AmazonEC2"],
                filters=[
                    {"name": "region", "values": [REGION]},
                    {"name": "instanceType", "values": sorted(instance_types)},
                    {"name": "tenancy", "values": ["shared"]},
                    {"name": "productDescription", "values": ["Linux/UNIX"]},
                ],
                maxResults=1000,
            )
            if token:
                request["nextToken"] = token
            response = client.describe_savings_plans_offering_rates(**request)
            for rate in response["searchResults"]:
                if rate["savingsPlanOffering"]["durationSeconds"] != 31_536_000:
                    continue
                properties = {p["name"]: p["value"] for p in rate["properties"]}
                # BoxUsage is the running-instance usage type; skip dedicated, unused reservations, etc.
                if "BoxUsage" not in rate["usageType"]:
                    continue
                rates.setdefault(properties["instanceType"], {})[key] = float(rate["rate"])
            token = response.get("nextToken")
            if not token:
                break
    return rates


def main() -> None:
    ec2_types, rds_classes = stage_instance_types()
    prefix = {"us-west-2": "USW2", "us-east-1": "USE1", "us-east-2": "USE2"}[REGION]
    snapshot = {
        "region": REGION,
        "retrieved_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "AWS Price List API, Savings Plans API, Amazon RDS reserved DB instance offerings API",
        "currency": "USD",
        "ec2": {t: ec2_price(t) for t in sorted(ec2_types)},
        "aurora_mysql": {c: aurora_price(c) for c in sorted(rds_classes)},
        # Storage and I/O are listed once for all Aurora engines ("Any") and again for PostgreSQL.
        "aurora_storage_gb_month": by_usagetype("AmazonRDS", f"{prefix}-Aurora:StorageUsage", databaseEngine="Any"),
        # Used only to compare Aurora Standard with Aurora I/O-Optimized (analysis/bom.py).
        "aurora_io_optimized_storage_gb_month": by_usagetype(
            "AmazonRDS", f"{prefix}-Aurora:IO-OptimizedStorageUsage", databaseEngine="Aurora MySQL"),
        "aurora_io_request": by_usagetype("AmazonRDS", f"{prefix}-Aurora:StorageIOUsage", databaseEngine="Any"),
        "aurora_backup_gb_month": by_usagetype("AmazonRDS", f"{prefix}-Aurora:BackupUsage",
                                               databaseEngine="Aurora MySQL"),
        "eks_cluster_hour": by_usagetype("AmazonEKS", f"{prefix}-AmazonEKS-Hours:perCluster"),
        "alb_hour": by_usagetype("AWSELB", f"{prefix}-LoadBalancerUsage", productFamily="Load Balancer-Application"),
        "alb_lcu_hour": by_usagetype("AWSELB", f"{prefix}-LCUUsage", productFamily="Load Balancer-Application"),
        "nat_gateway_hour": by_usagetype("AmazonEC2", f"{prefix}-NatGateway-Hours"),
        "nat_gateway_gb": by_usagetype("AmazonEC2", f"{prefix}-NatGateway-Bytes"),
        "ebs_gp3_gb_month": by_usagetype("AmazonEC2", f"{prefix}-EBS:VolumeUsage.gp3"),
        "data_transfer_out_gb": by_usagetype("AWSDataTransfer", f"{prefix}-DataTransfer-Out-Bytes"),
        "secrets_manager_secret_month": by_usagetype("AWSSecretsManager", f"{prefix}-AWSSecretsManager-Secrets"),
    }
    for instance_type, rates in savings_plan_rates(ec2_types).items():
        snapshot["ec2"][instance_type].update(rates)

    out = ROOT / "results/pricing" / f"{REGION}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(f"wrote {out.relative_to(ROOT)}")
    for name, price in snapshot["ec2"].items():
        print(f"  {name:14s} {price['usd']:.5f}  compute-sp={price.get('compute_sp_1yr_no_upfront_usd')}  "
              f"ec2-sp={price.get('ec2_instance_sp_1yr_no_upfront_usd')}")
    for name, price in snapshot["aurora_mysql"].items():
        print(f"  {name:14s} {price['standard']['usd']:.5f}  {price['commitments']}")


if __name__ == "__main__":
    main()

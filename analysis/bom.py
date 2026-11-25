#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Bill of materials for each configuration of the study, priced from the price snapshot.

    uv run analysis/bom.py                # prints the tables and writes results/bom.json

Every line is quantity x unit price. Instance quantities come from the configuration
files under infra/stages. Usage quantities (load balancer capacity units, Aurora I/O,
storage, data transfer) come from what was measured in the runs and are scaled to the
average request rate that the bill assumes for a month.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOURS_PER_MONTH = 730
SECONDS_PER_MONTH = HOURS_PER_MONTH * 3600
NODE_VOLUME_GB = 40
# The two request rates at which each configuration's write operations were read from
# Enhanced Monitoring: its warm-up run and its first 10-minute run of the first session.
WARMUP_RPS = 4000
LIGHTER_LOAD_RPS = 8000
# The ratio of billed write I/Os to write operations is taken over the blocks of the billed
# metric that hold load of the three configurations. Two blocks of the first session, from
# 22:55 to 01:15 UTC, hold load that is not among the runs of the study
# (docs/02-experiment-protocol.md, deviation 24). They are left out, so that every figure
# of the bill rests on the study's runs.
IO_BLOCKS_LEFT_OUT = (("2026-11-23T22:55:00Z", "2026-11-24T01:15:00Z"),)

STAGES = {
    "a-graviton2-baseline": "A: Graviton2 baseline",
    "b-graviton5-same-size": "B: Graviton5, same size",
    "c-graviton5-right-sized": "C: Graviton5, right-sized",
}


def load_prices() -> dict:
    return json.loads((ROOT / "results/pricing/us-west-2.json").read_text())


def stage_shape(stage: str) -> dict:
    eks = json.loads((ROOT / "infra/stages" / stage / "eks.json").read_text())["Parameters"]
    database = json.loads((ROOT / "infra/stages" / stage / "database.json").read_text())["Parameters"]
    return {
        "web": (eks["WebInstanceType"], int(eks["WebNodeCount"])),
        "api": (eks["ApiInstanceType"], int(eks["ApiNodeCount"])),
        "system": (eks["SystemInstanceType"], int(eks["SystemNodeCount"])),
        "database": (database["DBInstanceClass"], 2),
    }


def io_ratio(usage: dict) -> dict:
    """Billed write I/Os per write operation, over the blocks of the billed metric that are
    kept, with the lowest and highest ratio of a single block."""
    blocks = usage["aurora_io"]["billed_per_operation_by_block"]["blocks"]

    def seconds(block: dict) -> float:
        start, end = (dt.datetime.fromisoformat(block[key].replace("Z", "+00:00")) for key in ("from", "to"))
        return (end - start).total_seconds()

    kept = [b for b in blocks if not any(start <= b["from"] and b["to"] <= end for start, end in IO_BLOCKS_LEFT_OUT)]
    billed = sum(b["billed_write_ios_per_second"] * seconds(b) for b in kept)
    operations = sum(b["write_operations_per_second"] * seconds(b) for b in kept)
    ratios = [b["billed_per_operation"] for b in kept]
    # The kept blocks as periods: neighbours are joined.
    periods: list[list[str]] = []
    for block in kept:
        if periods and periods[-1][1] == block["from"]:
            periods[-1][1] = block["to"]
        else:
            periods.append([block["from"], block["to"]])
    return {"billed_per_operation": round(billed / operations, 4), "lowest": min(ratios), "highest": max(ratios),
            "blocks": len(kept), "blocks_left_out": len(blocks) - len(kept), "periods": periods,
            "over_all_blocks": usage["aurora_io"]["billed_per_operation"]}


def write_operations(stage: str, usage: dict) -> tuple[float, int] | None:
    """The writer's storage write operations per second at the bill's average request rate,
    and the request rate they were measured at. They were measured at 4,000 requests per
    second (the warm-up) and at 8,000 (the first 10-minute run); for another rate the nearer
    of the two is scaled in proportion."""
    io = usage.get("aurora_io", {})
    measured = {WARMUP_RPS: io.get("warmups", {}).get(f"{stage[0]}-warmup"),
                LIGHTER_LOAD_RPS: io.get("at_tested_load", {}).get(f"{stage[0]}-r1")}
    measured = {rate: entry["write_ops_per_second"] for rate, entry in measured.items() if entry}
    if not measured:
        return None
    rate = min(measured, key=lambda r: abs(r - usage["average_rps"]))
    return measured[rate] * usage["average_rps"] / rate, rate


def data_transfer_cost(gb: float, tiers: list[dict]) -> float:
    """Internet data transfer out is tiered by monthly volume."""
    cost, remaining = 0.0, gb
    for tier in sorted(tiers, key=lambda t: float(t["from"])):
        if remaining <= 0:
            break
        upper = float(tier["to"]) if tier["to"] not in (None, "Inf") else float("inf")
        size = min(remaining, upper - float(tier["from"]))
        cost += size * tier["usd"]
        remaining -= size
    return cost


def usage_assumptions(measured: dict | None = None) -> dict:
    """Quantities that depend on traffic. `measured` overrides the defaults with values
    taken from the baseline's steady runs."""
    usage = {
        # The month's average traffic that the bill assumes, in requests per second. An
        # assumption, not a measurement: about a third of the baseline's rated load.
        "average_rps": 4000,
        # The request rate of the runs in which the load balancer's bytes were measured.
        "operating_rps": 8000,
        "alb_processed_bytes_per_second": 32_320_000,
        "response_share_of_bytes": 0.95,
        "aurora_write_ios_per_second": 0.0,
        "aurora_read_ios_per_second": 0.0,
        "aurora_storage_gb": 6.0,
    }
    usage.update(measured or {})
    # The share of the load balancer's bytes that are responses is a property of the workload,
    # not of the measurement: keep the default if the measurement file does not carry it.
    usage.setdefault("response_share_of_bytes", 0.95)
    return usage


def bill(stage: str, prices: dict, usage: dict, pricing: str = "on_demand") -> list[dict]:
    """Returns the bill of materials as rows: group, item, quantity, unit, unit price, monthly cost.

    pricing: "on_demand", or "committed" for one-year no-upfront rates where AWS publishes
    one for the instance type (EC2 Instance Savings Plans; Aurora Reserved Instances or
    Database Savings Plans). Types without a published commitment stay On-Demand.
    """
    shape = stage_shape(stage)
    rows: list[dict] = []

    def add(group: str, item: str, quantity: float, unit: str, unit_price: float, note: str = "") -> None:
        rows.append({"group": group, "item": item, "quantity": quantity, "unit": unit,
                     "unit_usd": unit_price, "monthly_usd": round(quantity * unit_price, 2), "note": note})

    def ec2_rate(instance_type: str) -> tuple[float, str]:
        price = prices["ec2"][instance_type]
        if pricing == "committed" and price.get("ec2_instance_sp_1yr_no_upfront_usd"):
            return price["ec2_instance_sp_1yr_no_upfront_usd"], "EC2 Instance Savings Plan, 1 year, no upfront"
        return price["usd"], "On-Demand"

    def aurora_rate(instance_class: str) -> tuple[float, str]:
        price = prices["aurora_mysql"][instance_class]
        commitments = price["commitments"]
        if pricing == "committed":
            if commitments.get("reserved_1yr_no_upfront_usd"):
                return commitments["reserved_1yr_no_upfront_usd"], "Reserved Instance, 1 year, no upfront"
            if commitments.get("database_sp_1yr_no_upfront_usd"):
                return commitments["database_sp_1yr_no_upfront_usd"], "Database Savings Plan, 1 year, no upfront"
            return price["standard"]["usd"], "On-Demand: no one-year rate was returned"
        return price["standard"]["usd"], "On-Demand"

    # ---- What the upgrade changes: instances -------------------------------------------
    for tier, label in (("web", "Web tier nodes"), ("api", "API tier nodes"), ("system", "System nodes")):
        instance_type, count = shape[tier]
        rate, basis = ec2_rate(instance_type)
        add("Compute and database", f"{label}: {count} x {instance_type}", count * HOURS_PER_MONTH, "instance-hours",
            rate, basis)
    instance_class, count = shape["database"]
    rate, basis = aurora_rate(instance_class)
    add("Compute and database", f"Aurora MySQL writer and reader: {count} x {instance_class}",
        count * HOURS_PER_MONTH, "instance-hours", rate, basis)

    # ---- The rest of the stack: identical in every configuration ------------------------
    nodes = sum(shape[tier][1] for tier in ("web", "api", "system"))
    load = usage["average_rps"] / usage["operating_rps"]   # the measured bytes, scaled to the assumed average
    add("Rest of the stack", "Amazon EKS control plane", HOURS_PER_MONTH, "cluster-hours", prices["eks_cluster_hour"]["usd"])
    add("Rest of the stack", f"Node volumes: {nodes} x {NODE_VOLUME_GB} GiB gp3", nodes * NODE_VOLUME_GB, "GB-months",
        prices["ebs_gp3_gb_month"]["usd"])
    add("Rest of the stack", "Application Load Balancer", HOURS_PER_MONTH, "hours", prices["alb_hour"]["usd"])
    lcus = usage["alb_processed_bytes_per_second"] * 3600 / 1e9 * load
    add("Rest of the stack", "Load balancer capacity units", lcus * HOURS_PER_MONTH, "LCU-hours",
        prices["alb_lcu_hour"]["usd"],
        "bytes through the load balancer as measured in the baseline's runs at 8,000 requests per second, "
        "scaled to the average request rate; one LCU for each GB per hour of throughput")
    add("Rest of the stack", "NAT gateway", HOURS_PER_MONTH, "hours", prices["nat_gateway_hour"]["usd"])
    add("Rest of the stack", "Aurora storage", usage["aurora_storage_gb"], "GB-months",
        prices["aurora_storage_gb_month"]["usd"])
    # Aurora bills each write I/O to its storage. How many a request causes depends on how
    # the engine batches them, which depends on the load and on the instance, so the writer's
    # write operations are taken for each configuration at the measured rate nearest to the
    # bill's average (analysis/usage.py) and multiplied by the ratio of billed I/Os to write
    # operations. Reads cause no I/O here: the data set is served from memory.
    operations = write_operations(stage, usage)
    if operations:
        rate = operations[0] * io_ratio(usage)["billed_per_operation"]
        scaled = "" if operations[1] == usage["average_rps"] else ", scaled in proportion"
        add("Rest of the stack", "Aurora I/O requests", rate * SECONDS_PER_MONTH / 1e6,
            "million requests", prices["aurora_io_request"]["usd"] * 1e6,
            f"estimated: the writer's write operations in this configuration at {operations[1]:,} requests per second"
            f"{scaled}, times the ratio of billed I/Os to write operations")
    else:
        rate = (usage["aurora_write_ios_per_second"] + usage["aurora_read_ios_per_second"]) * load
        add("Rest of the stack", "Aurora I/O requests", rate * SECONDS_PER_MONTH / 1e6, "million requests",
            prices["aurora_io_request"]["usd"] * 1e6,
            "billed write I/Os at the average request rate; not measured for this configuration, the baseline's figure")
    add("Rest of the stack", "Secrets Manager secret", 1, "secrets", prices["secrets_manager_secret_month"]["usd"])
    egress_gb = (usage["alb_processed_bytes_per_second"] * usage["response_share_of_bytes"] * SECONDS_PER_MONTH
                 * load / 1e9)
    tiers = prices["data_transfer_out_gb"]["tiers"] or [
        {"from": "0", "to": "Inf", "usd": prices["data_transfer_out_gb"]["usd"]}]
    cost = data_transfer_cost(egress_gb, tiers)
    rows.append({"group": "Rest of the stack", "item": "Data transfer out to the internet", "quantity": egress_gb,
                 "unit": "GB", "unit_usd": round(cost / egress_gb, 4) if egress_gb else 0.0,
                 "monthly_usd": round(cost, 2),
                 "note": "the same bytes; 95% of them taken as responses (assumed), all sent to the internet, no CDN"})
    return rows


def totals(rows: list[dict]) -> dict:
    groups: dict[str, float] = {}
    for row in rows:
        groups[row["group"]] = groups.get(row["group"], 0.0) + row["monthly_usd"]
    return {"groups": {k: round(v, 2) for k, v in groups.items()}, "total": round(sum(groups.values()), 2)}


def main() -> None:
    prices = load_prices()
    measured_path = ROOT / "results/usage.json"
    usage = usage_assumptions(json.loads(measured_path.read_text()) if measured_path.exists() else None)
    out = {"prices_retrieved_at": prices["retrieved_at"], "region": prices["region"], "usage": usage, "stages": {}}
    for stage, title in STAGES.items():
        entry = {"title": title, "shape": stage_shape(stage)}
        for pricing in ("on_demand", "committed"):
            rows = bill(stage, prices, usage, pricing)
            entry[pricing] = {"rows": rows, **totals(rows)}
        out["stages"][stage] = entry
        print(f"\n{title}")
        for row in entry["on_demand"]["rows"]:
            print(f"  {row['group'][:10]:10s} {row['item']:58s} {row['quantity']:>12,.1f} {row['unit']:16s} "
                  f"x {row['unit_usd']:<10.5g} = {row['monthly_usd']:>10,.2f}")
        print(f"  {'':10s} {'On-Demand total':58s} {'':>12s} {'':16s}   {'':10s}   {entry['on_demand']['total']:>10,.2f}"
              f"   (committed: {entry['committed']['total']:,.2f})")
    out["io_ratio"] = io_ratio(usage)
    out["io_sensitivity"] = io_sensitivity(out["stages"], usage, prices)
    out["load_sensitivity"] = load_sensitivity(prices, usage)
    out["without_data_transfer"] = without_data_transfer(out["stages"])
    out["aurora_io_optimized"] = aurora_io_optimized(out["stages"], prices, usage)
    out["commitment_scenarios"] = commitment_scenarios(out["stages"], prices)
    out["not_in_the_bill"] = NOT_IN_THE_BILL
    out["saving_breakdown"] = saving_breakdown(out["stages"])
    (ROOT / "results/bom.json").write_text(json.dumps(out, indent=2) + "\n")


# What the bill leaves out. None of it is measured here.
NOT_IN_THE_BILL = [
    "data transfer between Availability Zones (API nodes to the database writer, web pods to API pods)",
    "NAT gateway data processing and public IPv4 addresses",
    "Aurora backup storage beyond the free allowance, and the growth of the database: a month of this "
    "traffic would add several hundred million orders",
    "monitoring: Enhanced Monitoring at 15 seconds, Performance Insights, CloudWatch logs and metrics",
    "the container registry, the delivery pipeline and support",
    "the load generators, and the one-time cost of making the change",
]


def saving_breakdown(stages: dict) -> dict:
    """Where each configuration's bill differs from the baseline's: Aurora instances, EC2
    nodes, and everything else, per pricing view. Positive numbers are savings."""
    def parts(rows: list[dict]) -> dict:
        aurora = sum(r["monthly_usd"] for r in rows if r["item"].startswith("Aurora MySQL writer"))
        nodes = sum(r["monthly_usd"] for r in rows if r["group"] == "Compute and database") - aurora
        rest = sum(r["monthly_usd"] for r in rows if r["group"] != "Compute and database")
        return {"aurora_instances": aurora, "ec2_nodes": nodes, "rest": rest, "total": aurora + nodes + rest}

    out = {}
    first = next(iter(stages))
    for pricing in ("on_demand", "committed"):
        base = parts(stages[first][pricing]["rows"])
        out[pricing] = {}
        for stage, entry in stages.items():
            if stage == first:
                continue
            own = parts(entry[pricing]["rows"])
            saving = {key: round(base[key] - own[key], 2) for key in base}
            saving["aurora_share_of_saving"] = round(saving["aurora_instances"] / saving["total"], 4) if saving["total"] else None
            out[pricing][stage] = saving
    return out


# Average request rates at which the bill is recomputed. One more is added to them: the
# comparison load, the rate of the run that rates the baseline (analysis/ceiling.py), for a
# month in which the stack runs at that rate around the clock.
AVERAGE_RPS_SCENARIOS = (2000, 4000, 8000)


def comparison_load() -> float | None:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import ceiling  # noqa: PLC0415  reads the recorded runs; imported here to keep this module usable without them

    run = ceiling.baseline_rating_run() if (ROOT / "results" / next(iter(STAGES))).exists() else None
    return run["target_rps"] if run else None


def load_sensitivity(prices: dict, usage: dict) -> dict:
    """The On-Demand totals at other average request rates than the bill's. Instance lines
    do not move; data transfer, load balancer capacity units and Aurora I/O do. The entry
    "comparison_load" is the scenario at the rate of the baseline's rating run."""
    out = {}
    at_comparison = comparison_load()
    for rate in sorted({*AVERAGE_RPS_SCENARIOS, *([at_comparison] if at_comparison else [])}):
        scenario = dict(usage, average_rps=rate)
        totals = {stage: totals_of(bill(stage, prices, scenario)) for stage in STAGES}
        baseline = next(iter(totals.values()))
        entry = {
            "average_requests_per_second": float(rate),
            "stages": {stage: {"total": total, "change_vs_baseline": round(total / baseline - 1, 4)}
                       for stage, total in totals.items()}}
        out[f"{rate:.0f}"] = entry
        if rate == at_comparison:
            out["comparison_load"] = entry
    return out


def totals_of(rows: list[dict]) -> float:
    return round(sum(row["monthly_usd"] for row in rows), 2)


def without_data_transfer(stages: dict) -> dict:
    """The comparison without the largest assumed line: internet data transfer."""
    totals = {stage: round(sum(row["monthly_usd"] for row in entry["on_demand"]["rows"]
                               if not row["item"].startswith("Data transfer")), 2) for stage, entry in stages.items()}
    baseline = next(iter(totals.values()))
    return {stage: {"total": total, "change_vs_baseline": round(total / baseline - 1, 4)} for stage, total in totals.items()}


def aurora_io_optimized(stages: dict, prices: dict, usage: dict) -> dict:
    """What each configuration would pay for Aurora on the I/O-Optimized storage
    configuration, where I/O is not billed and instances and storage cost more, next to
    Aurora Standard as in the bill. List-price arithmetic; nothing was run on it."""
    out = {}
    for stage, entry in stages.items():
        rows = {row["item"].split(":")[0]: row for row in entry["on_demand"]["rows"]}
        instance_class, count = entry["shape"]["database"]
        standard = sum(rows[name]["monthly_usd"] for name in
                       ("Aurora MySQL writer and reader", "Aurora I/O requests", "Aurora storage"))
        optimized = (count * HOURS_PER_MONTH * prices["aurora_mysql"][instance_class]["io_optimized"]["usd"]
                     + usage["aurora_storage_gb"] * prices["aurora_io_optimized_storage_gb_month"]["usd"])
        out[stage] = {"standard": round(standard, 2), "io_optimized": round(optimized, 2),
                      "difference": round(optimized - standard, 2),
                      "io_share_of_standard": round(rows["Aurora I/O requests"]["monthly_usd"] / standard, 4),
                      "total_with_io_optimized": round(entry["on_demand"]["total"] - standard + optimized, 2)}
    baseline = next(iter(stages.values()))["on_demand"]["total"]
    for entry in out.values():
        entry["total_with_io_optimized_vs_baseline_standard"] = round(entry["total_with_io_optimized"] / baseline - 1, 4)
    return out


def commitment_scenarios(stages: dict, prices: dict) -> dict:
    """Two facts behind the committed bill, and one what-if: the discount each instance type
    gets, and the committed totals if the Graviton5 Aurora classes got the same Reserved
    Instance discount as the Graviton2 classes. The what-if is not a price AWS published."""
    discounts = {}
    for name, price in prices["ec2"].items():
        if price.get("ec2_instance_sp_1yr_no_upfront_usd"):
            discounts[name] = round(1 - price["ec2_instance_sp_1yr_no_upfront_usd"] / price["usd"], 4)
    for name, price in prices["aurora_mysql"].items():
        reserved = price["commitments"].get("reserved_1yr_no_upfront_usd")
        discounts[name] = round(1 - reserved / price["standard"]["usd"], 4) if reserved else None
    known = [d for name, d in discounts.items() if name.startswith("db.") and d]
    assumed = sum(known) / len(known) if known else None
    what_if = {}
    if assumed:
        for stage, entry in stages.items():
            total = 0.0
            for row in entry["committed"]["rows"]:
                amount = row["monthly_usd"]
                if row["item"].startswith("Aurora MySQL writer") and row["note"].startswith("On-Demand"):
                    amount *= 1 - assumed
                total += amount
            what_if[stage] = round(total, 2)
        baseline = next(iter(what_if.values()))
        what_if = {stage: {"total": total, "change_vs_baseline": round(total / baseline - 1, 4)}
                   for stage, total in what_if.items()}
    return {"discount_by_instance_type": discounts, "assumed_aurora_discount": assumed and round(assumed, 4),
            "if_graviton5_aurora_had_the_same_reserved_discount": what_if}


def io_sensitivity(stages: dict, usage: dict, prices: dict) -> dict:
    """The On-Demand totals with Aurora I/O priced at the lowest and the highest ratio of
    billed I/Os to write operations that a single block of the billed metric showed. The
    ratio used in the bill is the one over all blocks that are kept (io_ratio); this shows
    how much of the comparison rests on it."""
    if not usage.get("aurora_io", {}).get("billed_per_operation_by_block"):
        return {}
    spread = io_ratio(usage)
    out = {}
    for label, ratio in (("lowest_block", spread["lowest"]), ("highest_block", spread["highest"])):
        repriced = {}
        for stage, entry in stages.items():
            operations = write_operations(stage, usage)
            if not operations:
                continue
            line = next(row for row in entry["on_demand"]["rows"] if row["item"] == "Aurora I/O requests")
            cost = operations[0] * ratio * SECONDS_PER_MONTH * prices["aurora_io_request"]["usd"]
            repriced[stage] = {"aurora_io": round(cost, 2),
                               "total": round(entry["on_demand"]["total"] - line["monthly_usd"] + cost, 2)}
        baseline = next(iter(repriced.values()), None)
        for stage, entry in repriced.items():
            entry["change_vs_baseline"] = round(entry["total"] / baseline["total"] - 1, 4)
        out[label] = {"billed_per_operation": ratio, "stages": repriced}
    # The two scenarios above give every configuration the same ratio. If the ratio differed
    # between configurations as much as single blocks differ, the comparison would move more:
    # the baseline at one extreme and each other configuration at the other.
    first = next(iter(stages))
    low, high = out["lowest_block"]["stages"], out["highest_block"]["stages"]
    out["different_ratio_per_configuration"] = {
        stage: {"least_favourable": round(high[stage]["total"] / low[first]["total"] - 1, 4),
                "most_favourable": round(low[stage]["total"] / high[first]["total"] - 1, 4)}
        for stage in low if stage != first}
    return out


if __name__ == "__main__":
    main()

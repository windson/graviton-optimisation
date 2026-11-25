#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Architecture diagrams of the stack, drawn from the parameter files of each configuration.

    uv run analysis/architecture.py      # writes report/figures/architecture*.svg

Three figures:

  architecture.svg              the Graviton2 baseline as deployed on AWS
  architecture-right-sized.svg  the right-sized Graviton5 stack, with what changed marked
  architecture-comparison.svg   both side by side, tier by tier, with the measured figures

Instance types, node counts and pod counts are read from infra/stages/<configuration>, the
address ranges, Availability Zones and versions from the CloudFormation templates, vCPUs
and memory from the price snapshot, and the measured figures from results/rated.json and
results/ceiling.json, so a diagram cannot disagree with what was deployed and measured.

The icons are the AWS Architecture Icons (report/assets/aws-icons, release of 31 July 2026),
which AWS provides for building architecture diagrams.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from svg import COLORS, INK, MUTED, Figure, esc  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "report/figures"
ICONS = ROOT / "report/assets/aws-icons"
WIDTH = 760

# Group colours of the AWS architecture icon set.
CLOUD, REGION, VPC, PUBLIC, PRIVATE, ZONE, NODES = "#242F3E", "#00A4A6", "#8C4FFF", "#7AA116", "#00A4A6", "#147EBA", "#ED7100"
EXTRA_STYLE = (
    f".gu-fig .gu-s{{font-size:10.5px;fill:{MUTED}}}"
    f".gu-fig .gu-g{{font-size:11.5px;font-weight:600}}"
    f".gu-fig .gu-b{{font-size:12px;font-weight:600}}"
    f".gu-fig .gu-n{{font-size:11px}}"
)
STAGES = {
    "A": ("a-graviton2-baseline", "Graviton2 baseline"),
    "B": ("b-graviton5-same-size", "Graviton5, same size"),
    "C": ("c-graviton5-right-sized", "Graviton5, right-sized"),
}


def shape(letter: str, prices: dict) -> dict:
    """What a configuration deploys: per tier the instance type, count, vCPUs, memory and pods."""
    stage = STAGES[letter][0]
    eks = json.loads((ROOT / "infra/stages" / stage / "eks.json").read_text())["Parameters"]
    database = json.loads((ROOT / "infra/stages" / stage / "database.json").read_text())["Parameters"]
    values = (ROOT / "infra/stages" / stage / "values.yaml").read_text()
    web_pods, api_pods = (int(n) for n in re.findall(r"^\s+replicas:\s*(\d+)", values, re.M)[:2])

    def ec2(kind: str) -> dict:
        name, count = eks[f"{kind}InstanceType"], int(eks[f"{kind}NodeCount"])
        price = prices["ec2"][name]
        memory = float(str(price["memory"]).split()[0])
        return {"type": name, "count": count, "vcpu": price["vcpu"], "memory_gib": memory}

    name = database["DBInstanceClass"]
    out = {"web": ec2("Web"), "api": ec2("Api"), "system": ec2("System"),
           "database": {"type": name, "count": 2, "vcpu": prices["aurora_mysql"][name]["standard"]["vcpu"],
                        "memory_gib": float(str(prices["aurora_mysql"][name]["standard"]["memory"]).split()[0])}}
    out["web"]["pods"], out["api"]["pods"] = web_pods, api_pods
    return out


def default(template: str, parameter: str) -> str:
    """The default of a parameter of one of the CloudFormation templates (no configuration overrides these)."""
    text = (ROOT / "infra/cfn" / template).read_text()
    block = text[text.index(f"\n  {parameter}:\n"):]
    return re.search(r"^\s+Default:\s*\"?([^\"\n]+)\"?\s*$", block, re.M).group(1)


def network() -> dict:
    """The VPC's address range, its two zones and the subnets of each, as infra/cfn/network.yaml cuts them:
    sixteen /20 ranges, of which numbers 0 and 1 are public, 4 and 5 private, 8 and 9 isolated."""
    vpc = ipaddress.ip_network(default("network.yaml", "VpcCidr"))
    ranges = list(vpc.subnets(new_prefix=vpc.prefixlen + 4))
    zones = [default("network.yaml", "AvailabilityZoneA"), default("network.yaml", "AvailabilityZoneB")]
    return {"vpc": str(vpc), "zones": [(zone, tuple(str(ranges[first + index]) for first in (0, 4, 8)))
                                       for index, zone in enumerate(zones)]}


def gib(value: float) -> str:
    return f"{value:g} GiB"


class Diagram(Figure):
    """A figure with the AWS icons available as symbols."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.used: set[str] = set()
        self.add("<!--icons-->")
        self.add(f'<defs><marker id="{self.ident}-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
                 f'markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{MUTED}"/></marker></defs>')

    def icon(self, name: str, x: float, y: float, size: float) -> None:
        self.used.add(name)
        self.add(f'<use href="#{self.ident}-{name}" x="{x:.1f}" y="{y:.1f}" width="{size}" height="{size}"/>')

    def group(self, x: float, y: float, w: float, h: float, colour: str, label: str, icon: str | None = None,
              dash: str = "", fill: str = "none", label_class: str = "gu-g") -> None:
        attrs = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{colour}" stroke-width="1.2"{attrs}/>')
        offset = 6
        if icon:
            self.icon(icon, x, y, 22)
            offset = 28
        self.text(x + offset, y + 15, label, label_class, fill=colour)

    def arrow(self, points: list[tuple[float, float]], dash: str = "") -> None:
        d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f} {y:.1f}" for i, (x, y) in enumerate(points))
        attrs = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<path d="{d}" fill="none" stroke="{MUTED}" stroke-width="1.4"{attrs} '
                 f'marker-end="url(#{self.ident}-arrow)"/>')

    def card(self, x: float, y: float, w: float, h: float, icon: str, title: str, lines: list[str],
             accent: str | None = None, icon_size: float = 26) -> None:
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="#fff" stroke="#c9ced6"/>')
        if accent:
            self.add(f'<rect x="{x}" y="{y}" width="4" height="{h}" rx="2" fill="{accent}"/>')
        self.icon(icon, x + 9, y + (h - icon_size) / 2, icon_size)
        self.text(x + 16 + icon_size, y + 17, title, "gu-b")
        for index, line in enumerate(lines):
            self.text(x + 16 + icon_size, y + 31 + index * 13.5, line, "gu-n")

    def render(self, extra_style: str = "") -> str:
        symbols = []
        for name in sorted(self.used):
            data = (ICONS / f"{name}.svg").read_bytes()
            box = re.search(rb'viewBox="0 0 (\d+) (\d+)"', data)
            side = int(box.group(1)) if box else 48
            symbols.append(f'<symbol id="{self.ident}-{name}" viewBox="0 0 {side} {side}"><image width="{side}" '
                           f'height="{side}" href="data:image/svg+xml;base64,{base64.b64encode(data).decode()}"/></symbol>')
        text = super().render(EXTRA_STYLE + extra_style)
        notice = "<!-- The icons are AWS Architecture Icons of Amazon Web Services: report/assets/aws-icons/README.md -->\n"
        return text.replace("<!--icons-->", notice + "<defs>" + "".join(symbols) + "</defs>")


def stack_diagram(letter: str, prices: dict, mix: dict, baseline: dict | None = None) -> str:
    """One configuration as deployed. With a baseline, what differs from it is marked."""
    s = shape(letter, prices)
    right_sized = baseline is not None
    changed = (lambda tier: right_sized and baseline[tier]["type"] != s[tier]["type"])
    mark = COLORS[letter]
    title = "The right-sized stack: Graviton5 at half the size in three tiers" if right_sized \
        else "The stack under test: the Graviton2 baseline on AWS"
    subtitle = ("The same network, cluster, load balancer and database volume. A green bar marks what changed from the baseline."
                if right_sized else
                "One Region, two Availability Zones, three subnet tiers. Every request enters through the load balancer.")
    height = 884
    figure = Diagram(WIDTH, height, title, subtitle,
                     "AWS architecture diagram: load generators, an internet gateway and an Application Load Balancer, "
                     "the web, API and system node groups of an Amazon EKS cluster in two Availability Zones, an Aurora "
                     "MySQL writer and reader, and the delivery pipeline.", f"gu-arch-{letter.lower()}")
    pages = round(mix["pages_share"] * 100)

    figure.group(0, 52, 760, height - 56, CLOUD, "AWS Cloud", "group-aws-cloud")
    figure.group(8, 80, 744, height - 92, REGION, "Region: US West (Oregon), us-west-2", "group-region", dash="4 3")

    # ---- the VPC, its two zones and three subnet tiers --------------------------------------
    vx, vy, vw, vh = 196, 172, 546, 566
    centre = vx + vw / 2
    zone_w, gap = 247, 32
    net = network()
    zones = [(name, vx + 10 + index * (zone_w + gap), cidrs) for index, (name, cidrs) in enumerate(net["zones"])]
    kubernetes = default("eks.yaml", "KubernetesVersion")
    aurora = re.search(r"aurora\.(\d+\.\d+)", default("database.yaml", "EngineVersion")).group(1)
    card_w = zone_w - 36

    # Load generators, outside the VPC: their requests come in through the internet gateway.
    figure.icon("fargate", 214, 104, 30)
    figure.text(250, 116, "Load generators: Distributed Load Testing on AWS", "gu-b")
    figure.text(250, 130, f"k6 on AWS Fargate at a fixed arrival rate: {pages}% page requests, {100 - pages}% direct API calls", "gu-s")
    figure.arrow([(centre, 138), (centre, vy - 14)])

    figure.group(vx, vy, vw, vh, VPC, f"VPC {net['vpc']}", "group-vpc")
    figure.add(f'<rect x="{centre - 15}" y="{vy - 15}" width="30" height="30" fill="#fff"/>')
    figure.icon("internet-gateway", centre - 13, vy - 13, 26)
    figure.text(centre + 19, vy - 5, "Internet gateway", "gu-s")
    for name, zx, cidrs in zones:
        figure.add(f'<rect x="{zx}" y="{vy + 30}" width="{zone_w}" height="{vh - 38}" fill="none" stroke="{ZONE}" '
                   f'stroke-width="1" stroke-dasharray="6 3"/>')
        figure.text(zx + zone_w / 2, vy + 45, f"Availability Zone {name}", "gu-g", "middle", fill=ZONE)
        figure.group(zx + 6, vy + 54, zone_w - 12, 80, PUBLIC, f"Public subnet {cidrs[0]}", "group-public-subnet",
                     fill="#f4f8ea", label_class="gu-s")
        figure.group(zx + 6, vy + 142, zone_w - 12, 298, PRIVATE, f"Private subnet {cidrs[1]}", "group-private-subnet",
                     fill="#eef9f9", label_class="gu-s")
        figure.group(zx + 6, vy + 448, zone_w - 12, 104, PRIVATE, f"Private subnet {cidrs[2]} (isolated)",
                     "group-private-subnet", fill="#eef9f9", label_class="gu-s")

    # The load balancer has a node in each public subnet; it is drawn across the two.
    figure.arrow([(centre, vy + 14), (centre, vy + 72)])
    figure.add(f'<rect x="{centre - 136}" y="{vy + 73}" width="272" height="56" rx="5" fill="#fff" stroke="#c9ced6"/>')
    figure.icon("alb", centre - 129, vy + 79, 30)
    figure.text(centre - 92, vy + 91, "Application Load Balancer", "gu-b")
    figure.text(centre - 92, vy + 105, "internet-facing, HTTP on port 80", "gu-s")
    figure.text(centre - 92, vy + 118, "/api/* to API pods, the rest to web pods", "gu-s")
    figure.icon("nat-gateway", zones[0][1] + 14, vy + 82, 24)
    figure.text(zones[0][1] + 42, vy + 93, "NAT gateway", "gu-n")
    figure.text(zones[0][1] + 42, vy + 106, "one for both", "gu-s")
    figure.text(zones[0][1] + 42, vy + 118, "zones", "gu-s")

    # Node groups: one row per tier, spanning both zones. EKS puts three nodes into two zones as 1 + 2.
    rows = [
        ("web", "Web", vy + 166, 68,
         lambda n: [f"{n['vcpu']} vCPUs, {gib(n['memory_gib'])}", f"{n['pods'] // n['count']} web pods: React pages",
                    "rendered on Node.js 24"],
         lambda n: f"was {n['type']}, {n['vcpu']} vCPUs"),
        ("api", "API", vy + 260, 68,
         lambda n: [f"{n['vcpu']} vCPUs, {gib(n['memory_gib'])}",
                    f"{n['pods'] // n['count']} API pod{'s' if n['pods'] // n['count'] != 1 else ''}: Java 21, Spring",
                    "Boot, CPU limit 1.75 vCPUs"],
         lambda n: f"was {n['type']}, {n['vcpu']} vCPUs"),
        ("system", "System", vy + 354, 54,
         lambda n: [f"{n['vcpu']} vCPUs, {gib(n['memory_gib'])}", "CoreDNS and controllers"],
         lambda n: f"was {n['type']} (same size)"),
    ]
    middle = {}
    for tier, name, y, h, describe, before in rows:
        node = s[tier]
        figure.add(f'<rect x="{zones[0][1] + 12}" y="{y}" width="{zone_w * 2 + gap - 24}" height="{h + 20}" rx="4" '
                   f'fill="none" stroke="{NODES}" stroke-dasharray="3 3"/>')
        figure.text(zones[0][1] + 18, y + 11, f"{name} node group: {node['count']} x {node['type']}", "gu-s")
        for (zone, zx, _), count in zip(zones, (1, node["count"] - 1)):
            lines = describe(node)
            if changed(tier) and tier == "system":
                lines = [lines[0], before(baseline[tier])]
            elif changed(tier):
                lines = [lines[0], lines[1].split(":")[0], before(baseline[tier])]
            if count > 1:   # the card stands for several nodes: its figures are for each of them
                lines = [lines[0] + " each"] + [re.sub(r"^(\d+ (?:web|API) pods?)", r"\1 each", line) for line in lines[1:]]
            figure.card(zx + 18, y + 16, card_w, h, "instance",
                        f"{f'{count} x ' if count > 1 else ''}{name} node{'s' if count > 1 else ''}: {node['type']}", lines,
                        accent=mark if changed(tier) else (COLORS["A"] if not right_sized else None))
        middle[tier] = y + 16 + h / 2

    database = s["database"]
    for (zone, zx, _), role in zip(zones, ("writer", "reader")):
        lines = [database["type"], f"{database['vcpu']} vCPUs, {gib(database['memory_gib'])}",
                 "serves every query" if role == "writer" else "failover standby"]
        if changed("database"):
            lines[2] = f"was {baseline['database']['type']}, {baseline['database']['vcpu']} vCPUs"
        figure.card(zx + 18, vy + 472, card_w, 68, "aurora-instance", f"Aurora MySQL {aurora} {role}", lines,
                    accent=mark if changed("database") else (COLORS["A"] if not right_sized else None))
    figure.icon("aurora", centre - 13, vy + 493, 26)

    # ---- the path of a request, in the lane between the two zones -----------------------------
    left_edge, right_edge = zones[0][1] + 18 + card_w + 2, zones[1][1] + 16
    solid, dashed = centre - 8, centre + 8
    figure.add(f'<path d="M{solid} {vy + 129} L{solid} {middle["web"]}" fill="none" stroke="{MUTED}" stroke-width="1.4"/>')
    figure.arrow([(solid, middle["web"]), (left_edge, middle["web"])])
    figure.arrow([(solid, middle["web"]), (right_edge, middle["web"])])
    figure.add(f'<path d="M{dashed} {vy + 129} L{dashed} {middle["api"] - 8}" fill="none" stroke="{MUTED}" '
               f'stroke-width="1.4" stroke-dasharray="4 3"/>')
    figure.arrow([(dashed, middle["api"] - 8), (left_edge, middle["api"] - 8)], dash="4 3")
    figure.arrow([(dashed, middle["api"] - 8), (right_edge, middle["api"] - 8)], dash="4 3")
    for zone, zx, _ in zones:                                       # each rendered page calls the API once
        x = zx + 18 + card_w - 22
        figure.arrow([(x, vy + 166 + 16 + 68), (x, vy + 260 + 16)])
    figure.arrow([(centre, vy + 260 + 88), (centre, vy + 484), (left_edge, vy + 484)])

    # ---- services next to the VPC ----------------------------------------------------------
    side = [
        ("eks", "Amazon EKS", ["control plane,", f"Kubernetes {kubernetes}"], vy + 150),
        ("ecr", "Amazon ECR", ["arm64 images", "of both tiers"], vy + 240),
        ("cloudwatch", "Amazon CloudWatch", ["load balancer and", "Aurora metrics"], vy + 330),
        ("secrets-manager", "AWS Secrets Manager", ["database password,", "read by the API pods"], vy + 420),
    ]
    for icon, name, lines, y in side:
        figure.icon(icon, 18, y, 30)
        figure.text(54, y + 12, name, "gu-b")
        for index, line in enumerate(lines):
            figure.text(54, y + 25 + index * 12.5, line, "gu-s")

    ly = vy + vh + 16
    figure.text(18, ly, f"Solid arrows: page requests ({pages}%); each rendered page makes one main call to the API. Dashed arrows: direct API calls "
                        f"({100 - pages}%).", "gu-s")
    figure.text(18, ly + 13, "Every query goes to the Aurora writer. The three node groups each span both zones.", "gu-s")

    # ---- the pipeline ---------------------------------------------------------------------------
    py = ly + 36
    figure.line(18, py - 8, 742, py - 8)
    figure.icon("codepipeline", 18, py, 24)
    figure.text(48, py + 16, "Every change is a commit that AWS CodePipeline applies, in six steps:", "gu-b")
    steps = [
        ("codecommit", "CodeCommit", ["the parameter", "files, pushed"]),
        ("codebuild", "CodeBuild", ["tests; arm64", "images to ECR"]),
        ("cloudformation", "CloudFormation", ["network, cluster,", "database stacks"]),
        ("codebuild", "CodeBuild", ["load balancer", "controller"]),
        ("eks", "EKS deploy", ["Helm release", "of both tiers"]),
        ("codebuild", "CodeBuild", ["data set and", "smoke test"]),
    ]
    offsets = [0, 121, 239, 380, 498, 610]
    for index, (icon, name, lines) in enumerate(steps):
        x = 18 + offsets[index]
        figure.icon(icon, x, py + 32, 26)
        figure.text(x + 31, py + 43, name, "gu-n", weight="600")
        for row, line in enumerate(lines):
            figure.text(x + 31, py + 56 + row * 12, line, "gu-s")
        if index:
            figure.arrow([(x - 11, py + 45), (x - 3, py + 45)])
    return figure.render()


def comparison_diagram(prices: dict, rated: dict | None, ceiling: dict | None) -> str:
    """The baseline and the right-sized stack side by side, tier by tier."""
    a, c = shape("A", prices), shape("C", prices)
    figure = Diagram(WIDTH, 600, "Graviton2 baseline and right-sized Graviton5 stack, tier by tier",
                     "The same request rate, request mix and container images, on half the vCPUs in three tiers.",
                     "Side-by-side comparison of the Graviton2 baseline and the right-sized Graviton5 stack: instance "
                     "types, vCPUs and pods of each tier, and the measured CPU utilization, capacity and cost.",
                     "gu-arch-cmp")
    left, right, bar = 222, 492, 176
    figure.text(left, 70, "A: Graviton2 baseline", "gu-title", fill=COLORS["A"])
    figure.text(right, 70, "C: Graviton5, right-sized", "gu-title", fill=COLORS["C"])
    stage_a = (rated or {}).get("stages", {}).get("a-graviton2-baseline")
    stage_c = (rated or {}).get("stages", {}).get("c-graviton5-right-sized")
    rate = (rated or {}).get("rate_rps")
    tiers = [
        ("web", "instances", "Web tier", "web", "share of the nodes' vCPUs",
         lambda n: f"{n['count'] * n['vcpu']} vCPUs, {n['pods']} web pods"),
        ("api", "instances", "API tier", "api", "share of the pods' CPU limits",
         lambda n: f"{n['count'] * n['vcpu']} vCPUs, {n['pods']} API pods at 1.75 vCPUs"),
        ("database", "aurora", "Aurora MySQL", "db", "share of the writer's vCPUs",
         lambda n: f"writer and reader, {n['vcpu']} vCPUs each"),
        ("system", "instances", "System nodes", None, "", lambda n: f"{n['count'] * n['vcpu']} vCPUs, cluster add-ons"),
    ]
    y = 88
    for tier, icon, name, key, basis, describe in tiers:
        h = 98 if key else 56
        figure.add(f'<rect x="0" y="{y}" width="{WIDTH}" height="{h}" rx="5" fill="#f6f7f9"/>')
        figure.icon(icon, 12, y + 12, 32)
        figure.text(54, y + 24, name, "gu-b")
        if key:
            figure.text(54, y + 54, "CPU utilization at", "gu-s")
            figure.text(54, y + 67, f"{rate:,.0f} requests per second," if rate else "the same request rate,", "gu-s")
            figure.text(54, y + 80, basis, "gu-s")
        for x, node, letter, stage in ((left, a[tier], "A", stage_a), (right, c[tier], "C", stage_c)):
            figure.text(x, y + 24, f"{node['count']} x {node['type']}", "gu-b")
            figure.text(x, y + 40, describe(node), "gu-n")
            if key and stage and stage["utilization"][key]["median"] is not None:
                value = stage["utilization"][key]["median"]
                figure.rect(x, y + 56, bar, 13, "#e3e6ea")
                figure.rect(x, y + 56, bar * min(value, 1.0), 13, COLORS[letter])
                figure.line(x + bar * 0.8, y + 52, x + bar * 0.8, y + 73, "gu-base")
                figure.text(x + bar + 8, y + 67, f"{value:.0%}", "gu-val", weight="600")
                figure.text(x + bar + 8, y + 86, "CPU utilization", "gu-s")
                figure.text(x + bar * 0.8, y + 86, "80% ceiling", "gu-s", "middle")
            elif key:
                figure.text(x, y + 67, "not measured at this rate", "gu-s")
        y += h + 8
    rows = []
    if ceiling:
        ra = ceiling["stages"]["a-graviton2-baseline"]
        rc = ceiling["stages"]["c-graviton5-right-sized"]
        rows.append(("Rated load", "request rate at 80% CPU utilization", f"about {ra['rated_rps']:,.0f} requests per second",
                     f"about {rc['rated_rps']:,.0f} requests per second", f"{rc['rated_rps'] / ra['rated_rps'] - 1:+.0%} against the baseline"))
        rows.append(("Instance cost", "EC2 and Aurora, On-Demand prices",
                     f"${ra['cost']['compute_database']:,.0f} per month", f"${rc['cost']['compute_database']:,.0f} per month",
                     f"{rc['cost']['compute_database'] / ra['cost']['compute_database'] - 1:+.0%} against the baseline"))
    if stage_a and stage_c and rate:
        before, after = stage_a["latency_ms"]["p99"]["median"], stage_c["latency_ms"]["p99"]["median"]
        rows.insert(1, ("p99 response time", f"at {rate:,.0f} requests per second",
                        f"{before:.1f} ms", f"{after:.1f} ms", f"{after / before - 1:+.0%} against the baseline"))
    y += 4
    for label, detail, value_a, value_c, note in rows:
        figure.line(0, y - 4, WIDTH, y - 4)
        figure.text(0, y + 13, label, "gu-n", weight="600")
        figure.text(0, y + 27, detail, "gu-s")
        figure.text(left, y + 13, value_a, "gu-val", weight="600")
        figure.text(right, y + 13, value_c, "gu-val", weight="600", fill=COLORS["C"])
        figure.text(right, y + 27, note, "gu-s")
        y += 38
    figure.height = int(y + 2)
    return figure.render().replace(f'viewBox="0 0 {WIDTH} 600"', f'viewBox="0 0 {WIDTH} {figure.height}"')


def main() -> None:
    prices = json.loads((ROOT / "results/pricing/us-west-2.json").read_text())
    mix = json.loads((ROOT / "loadtest/mix.json").read_text())
    weights = mix["weights"]
    mix_facts = {"pages_share": sum(w for name, w in weights.items() if name.startswith("page_")) / sum(weights.values())}
    rated = ROOT / "results/rated.json"
    ceiling = ROOT / "results/ceiling.json"
    figures = {
        "architecture": stack_diagram("A", prices, mix_facts),
        "architecture-right-sized": stack_diagram("C", prices, mix_facts, baseline=shape("A", prices)),
        "architecture-comparison": comparison_diagram(prices, json.loads(rated.read_text()) if rated.exists() else None,
                                                      json.loads(ceiling.read_text()) if ceiling.exists() else None),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in figures.items():
        (OUT / f"{name}.svg").write_text(text)
        print(f"wrote report/figures/{name}.svg ({len(text):,} bytes)")


if __name__ == "__main__":
    main()

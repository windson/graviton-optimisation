#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Draws the report's charts from the comparison data.

    uv run analysis/charts.py             # writes report/figures/*.svg

Each chart is a stand-alone SVG with its numbers as text. One colour per configuration
is used throughout (analysis/svg.py).
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from dlthist import Distribution, layout  # noqa: E402
from svg import COLORS, GRID, INK, MUTED, Figure, Linear, Log, esc, fmt, nice_ticks  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "report/figures"
WIDTH = 760

SHORT = {
    "A": "A  Graviton2 baseline",
    "B": "B  Graviton5, same size",
    "C": "C  Graviton5, right-sized",
}


def stages(comparison: dict, need: str) -> list[dict]:
    return [entry for entry in comparison["stages"].values() if entry.get(need)]


# ---- Figure: the configurations at the baseline's rated load -----------------------------------


def rated_load_chart() -> str:
    """Every configuration at the comparison rate: the CPU utilization of each tier against the
    80% ceiling, and the response time."""
    import ceiling as rule

    path = ROOT / "results/rated.json"
    if not path.exists():
        return ""
    rated = json.loads(path.read_text())
    entries = sorted(rated["stages"].values(), key=lambda e: e["letter"])
    rate, limit = rated["rate_rps"], rated["ceiling"]
    described: dict[str, list[str]] = {}
    for entry in entries:
        seconds = entry["seconds_per_run"][0]
        if entry["source"] == "runs":
            count = len(entry["runs"])
            text = f"median of {count} run{'s' if count != 1 else ''} of {seconds:.0f} seconds"
        else:
            text = f"one {seconds:.0f}-second step at {fmt(entry['target_rps'], 0)} requests per second"
        described.setdefault(text, []).append(entry["letter"])
    # Configurations that were measured the same way share one note.
    notes = [f"{' and '.join(letters)}: {text}." for text, letters in described.items()]
    row_height, bar, gap = 54, 15, 6
    cpu_top = 92
    cpu_bottom = cpu_top + len(entries) * (bar + gap)
    time_top = cpu_bottom + 96
    height = time_top + row_height * len(entries) + 34
    figure = Figure(
        WIDTH, height, f"Graviton2 and Graviton5 at the comparison load of {fmt(rate, 0)} requests per second",
        " ".join(notes),
        f"Bar chart of the CPU utilization of the web tier, the API tier and the database writer of the "
        f"configurations measured at {fmt(rate, 0)} requests per second and of those shown from a staircase step "
        f"near it, against the ceiling of 80% CPU utilization, and a dot plot of their p50, p95 and p99 response time.",
        "gu-rated")

    # ---- CPU utilization: one group per tier, one bar per configuration -------------------------
    figure.text(0, 62, "CPU utilization of each tier", weight="600")
    group = WIDTH / 3
    basis = {"web": "of the web nodes' vCPUs", "api": "of the API pods' CPU limits", "db": "of the writer's vCPUs"}
    for column, (tier, title) in enumerate(rule.TIERS.items()):
        x0 = column * group
        x = Linear(0, 1.0, x0 + 20, x0 + group - 70)
        figure.text(x0, cpu_top - 12, f"{title}, share {basis[tier]}", "gu-note")
        for tick in (0, 0.5, 1.0):
            figure.line(x(tick), cpu_top - 4, x(tick), cpu_bottom)
            figure.text(x(tick), cpu_bottom + 14, f"{tick:.0%}", "gu-tick", "middle")
        for index, entry in enumerate(entries):
            letter, value = entry["letter"], entry["utilization"][tier]["median"]
            y = cpu_top + index * (bar + gap)
            figure.text(x0, y + 12, letter, "gu-val", fill=COLORS[letter], weight="600")
            if value is None:
                continue
            if entry["source"] == "runs":
                figure.rect(x(0), y, x(min(value, 1.0)) - x(0), bar, COLORS[letter])
            else:   # a capacity step, not a run at this rate: drawn hollow
                figure.add(f'<rect x="{x(0) + 0.75:.1f}" y="{y + 0.75:.1f}" width="{x(min(value, 1.0)) - x(0) - 1.5:.1f}" '
                           f'height="{bar - 1.5}" rx="2" fill="#fff" stroke="{COLORS[letter]}" stroke-width="1.5"/>')
            # The values stand in a column to the right of the bars, clear of the ceiling line.
            figure.text(x(1.0) + 44, y + 12, f"{value:.0%}", "gu-val", "end",
                        weight="600" if entry["busiest_tier"] == tier else None)
        figure.line(x(limit), cpu_top - 4, x(limit), cpu_bottom + 3, "gu-base", f"stroke:{INK};stroke-dasharray:4 3")
        figure.text(x(limit), cpu_bottom + 28, f"{limit:.0%} ceiling", "gu-note", "middle")

    # ---- Response time: one row per configuration ----------------------------------------------------
    figure.text(0, time_top - 30, "Response time", weight="600")
    figure.text(100, time_top - 30, "log scale; lower is better", "gu-note")
    left, right = 190, WIDTH - 24
    values = [entry["latency_ms"][p][k] for entry in entries for p in ("p50", "p95", "p99") for k in ("min", "max")]
    lo, hi = min(values) * 0.78, max(values) * 1.3
    x = Log(lo, hi, left, right)
    bottom = time_top + row_height * len(entries) - 10
    for tick in (t for t in (1, 2, 3, 5, 10, 20, 30, 50, 100, 200) if lo <= t <= hi):
        figure.line(x(tick), time_top - 14, x(tick), bottom)
        figure.text(x(tick), bottom + 16, f"{tick} ms", "gu-tick", "middle")
    for index, entry in enumerate(entries):
        letter = entry["letter"]
        y = time_top + index * row_height + 14
        figure.text(0, y - 4, SHORT[letter], weight="600", fill=COLORS[letter])
        figure.text(0, y + 12, f"{len(entry['runs'])} x {entry['seconds_per_run'][0]:.0f} seconds"
                    if entry["source"] == "runs" else f"one {entry['seconds_per_run'][0]:.0f}-second step", "gu-note")
        latency = entry["latency_ms"]
        points = [(x(latency[p]["median"]), y) for p in ("p50", "p95", "p99")]
        figure.path(points, COLORS[letter], 1.5)
        for name, (px, py) in zip(("p50", "p95", "p99"), points):
            spread = latency[name]
            figure.line(x(spread["min"]), py, x(spread["max"]), py, "gu-base",
                        f"stroke:{COLORS[letter]};stroke-width:5;stroke-opacity:.3;stroke-linecap:round")
            if entry["source"] == "runs":
                figure.circle(px, py, 5, COLORS[letter])
            else:
                figure.add(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4.5" fill="#fff" stroke="{COLORS[letter]}" stroke-width="2"/>')
            # The middle label goes under the line, so that neighbours cannot run into each other.
            figure.text(px, py + (22 if name == "p95" else -11), f"{name} {spread['median']:.1f} ms", "gu-val", "middle")
    return figure.render()


# ---- Figure: capacity staircase ------------------------------------------------------------


def capacity_chart(comparison: dict) -> str:
    rows = stages(comparison, "capacity")
    slo = comparison["slo"]
    left, right, top, bottom = 70, WIDTH - 20, 76, 380
    all_steps = [s for e in rows for s in e["capacity"]["steps"]]
    x_hi = max(s["achieved_rps"] for s in all_steps) * 1.04
    x_lo = min(s["target_rps"] for s in all_steps) * 0.9
    y_hi = max(1000.0, max((s["p99_ms"] or 0) for s in all_steps) * 1.3)
    x = Linear(x_lo, x_hi, left, right)
    y = Log(8, y_hi, bottom, top)
    figure = Figure(
        WIDTH, bottom + 82 + 20 * len(rows), "p99 response time as the request rate rises",
        "Each point is one 110-second step of a configuration's capacity run. Log scale.",
        "Line chart of the p99 response time against the request rate for each configuration, with the limit of "
        "100 ms, the comparison load, and the highest step each configuration passed.",
        "gu-capacity")
    for tick in (10, 20, 50, 100, 200, 500, 1000, 2000, 5000):
        if tick <= y_hi:
            figure.line(left, y(tick), right, y(tick))
            figure.text(left - 8, y(tick) + 4, f"{fmt(tick, 0)} ms", "gu-tick", "end")
    for tick in nice_ticks(x_lo, x_hi, 6):
        figure.line(x(tick), bottom, x(tick), bottom + 5, "gu-base")
        figure.text(x(tick), bottom + 20, fmt(tick, 0), "gu-tick", "middle")
    figure.text((left + right) / 2, bottom + 42, "requests per second achieved", "gu-axis", "middle")
    figure.line(left, bottom, right, bottom, "gu-base")
    # The p99 limit of a passing step.
    figure.line(left, y(slo["max_p99_ms"]), right, y(slo["max_p99_ms"]), "gu-base",
                f"stroke:{INK};stroke-dasharray:5 4")
    figure.text(right, y(slo["max_p99_ms"]) - 6, f"limit of a passing step: p99 response time {fmt(slo['max_p99_ms'], 0)} ms",
                "gu-note", "end")
    compared_path = ROOT / "results/rated.json"
    if compared_path.exists():
        rate = json.loads(compared_path.read_text())["rate_rps"]
        figure.line(x(rate), top - 6, x(rate), bottom, "gu-base", f"stroke:{MUTED};stroke-dasharray:2 4")
        figure.text(x(rate) + 5, top - 2, f"comparison load: {fmt(rate, 0)} requests per second", "gu-note")
    for entry in rows:
        letter = entry["letter"]
        steps = entry["capacity"]["steps"]
        points = [(x(s["achieved_rps"]), y(max(s["p99_ms"] or y_hi, 8))) for s in steps]
        figure.path(points, COLORS[letter])
        for step, (px, py) in zip(steps, points):
            if step["within_slo"]:
                figure.circle(px, py, 3.5, COLORS[letter])
            else:
                figure.add(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="#fff" stroke="{COLORS[letter]}" '
                           f'stroke-width="1.75"/>')
    # What each line shows, listed underneath in the configurations' colours.
    for index, entry in enumerate(rows):
        letter, capacity = entry["letter"], entry["capacity"]
        ly = bottom + 56 + 20 * index
        figure.rect(left, ly, 10, 10, COLORS[letter])
        # A staircase that passed its last step gives a lower bound, not a limit.
        if capacity["limit_not_reached"]:
            text = f"passed every step, up to {fmt(capacity['mst_rps'], 0)} requests per second"
        else:
            text = (f"highest passing step {fmt(capacity['mst_rps'], 0)} requests per second, "
                    f"first failing step {fmt(capacity['first_failing_step']['target_rps'], 0)}")
        figure.text(left + 15, ly + 9, f"{SHORT[letter].split('  ')[1]}: {text}", "gu-val", fill=COLORS[letter], weight="600")
    figure.text(left, bottom + 56 + 20 * len(rows) + 12,
                "Filled point: the step met all four limits (request rate, errors, p95 and p99 response time). Hollow point: it did not.",
                "gu-note")
    return figure.render()


# ---- Figure: the busiest tier's CPU as load rises, and the 80% ceiling ---------------------


def ceiling_chart(comparison: dict) -> str:
    """Where each configuration reaches the CPU ceiling: the utilization of its busiest
    tier at every capacity step that stayed within the latency and error limits."""
    import ceiling as rule

    rated_path = ROOT / "results/ceiling.json"
    if not rated_path.exists():
        return ""
    rated = json.loads(rated_path.read_text())["stages"]
    rows = []
    for stage, entry in comparison["stages"].items():
        if not entry.get("capacity") or stage not in rated:
            continue
        prefix = entry["letter"].lower()
        steps = [(step["rate"], max(step.get(tier, 0.0) for tier in rule.TIERS)) for step in rule.estimate(prefix)["steps"]]
        rows.append((entry["letter"], steps, rated[stage]))
    if not rows:
        return ""
    left, right, top, bottom = 58, WIDTH - 20, 76, 372
    x_hi = max(rate for _, steps, _ in rows for rate, _ in steps) * 1.04
    x = Linear(0, x_hi, left, right)
    y = Linear(0, 1.0, bottom, top)
    limit = rule.CEILING
    # The rated capacities are listed under the chart, one to a row.
    rated_rows = len([row for row in rows if row[2]["rated_rps"]])
    figure = Figure(
        WIDTH, bottom + 78 + 20 * rated_rows, "CPU utilization of the busiest tier as the request rate rises",
        "Lines: each passing 110-second step of the capacity run. Diamonds: the 80% ceiling, from a 10-minute run near it.",
        "Line chart of the busiest tier's CPU utilization against request rate for each configuration, with the 80% "
        "ceiling, the rate at which each configuration reaches it, and each configuration's utilization at the "
        "comparison load.", "gu-ceiling")
    figure.add(f'<text class="gu-axis" transform="translate(14 {(top + bottom) / 2:.0f}) rotate(-90)" text-anchor="middle">'
               f'CPU utilization of the busiest tier</text>')
    for tick in (0, 0.2, 0.4, 0.6, 0.8, 1.0):
        figure.line(left, y(tick), right, y(tick))
        figure.text(left - 8, y(tick) + 4, f"{tick:.0%}", "gu-tick", "end")
    for tick in nice_ticks(0, x_hi, 7):
        figure.line(x(tick), bottom, x(tick), bottom + 5, "gu-base")
        figure.text(x(tick), bottom + 20, fmt(tick, 0), "gu-tick", "middle")
    figure.line(left, bottom, right, bottom, "gu-base")
    figure.text((left + right) / 2, bottom + 42, "requests per second", "gu-axis", "middle")
    figure.line(left, y(limit), right, y(limit), "gu-base", f"stroke:{INK};stroke-dasharray:5 4")
    # The comparison load: the rate of the baseline's ceiling run, at which every configuration
    # is marked (a square where it was run at that rate, a ring where a capacity step stands in).
    compared_path = ROOT / "results/rated.json"
    compared = json.loads(compared_path.read_text()) if compared_path.exists() else None
    if compared:
        rate = compared["rate_rps"]
        figure.line(x(rate), top - 6, x(rate), bottom, "gu-base", f"stroke:{MUTED};stroke-dasharray:2 4")
        figure.text(x(rate) - 5, top - 10, f"comparison load: {fmt(rate, 0)} requests per second", "gu-note", "end")
    for letter, steps, entry in rows:
        points = [(x(rate), y(min(value, 1.0))) for rate, value in steps]
        figure.path(points, COLORS[letter])
        for px, py in points:
            figure.circle(px, py, 3, COLORS[letter])
    if compared:
        for entry in compared["stages"].values():
            letter, value = entry["letter"], entry["busiest_utilization"]
            px, py = x(entry.get("target_rps") or compared["rate_rps"]), y(value)   # a capacity step is drawn at its own rate
            if entry["source"] == "runs":
                figure.add(f'<rect x="{px - 5:.1f}" y="{py - 5:.1f}" width="10" height="10" fill="{COLORS[letter]}" '
                           f'stroke="#fff" stroke-width="1.5"/>')
            else:
                figure.add(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="5" fill="#fff" stroke="{COLORS[letter]}" stroke-width="2"/>')
            if letter == "A":   # its mark sits under the diamond of its own ceiling: the label goes above the line
                figure.text(px - 9, y(limit) - 9, f"{letter}: {value:.0%} CPU utilization", "gu-val", "end", fill=COLORS[letter], weight="600")
            else:
                figure.text(px + 10, py + 16, f"{letter}: {value:.0%} CPU utilization", "gu-val", fill=COLORS[letter], weight="600")
    # The rate at which each configuration is at the ceiling, marked on the ceiling line and
    # listed underneath in the configurations' colours.
    rows = [row for row in rows if row[2]["rated_rps"]]
    for letter, steps, entry in rows:
        px = x(entry["rated_rps"])
        figure.add(f'<path d="M{px:.1f} {y(limit) - 7:.1f} l6 7 l-6 7 l-6 -7z" fill="{COLORS[letter]}" stroke="#fff" '
                   f'stroke-width="1.5"/>')
        figure.line(px, y(limit) + 7, px, bottom, "gu-base", f"stroke:{COLORS[letter]};stroke-dasharray:1 3")
    for index, (letter, steps, entry) in enumerate(sorted(rows, key=lambda row: row[2]["rated_rps"])):
        lx, ly = left, bottom + 55 + 20 * index
        figure.rect(lx, ly, 10, 10, COLORS[letter])
        figure.text(lx + 15, ly + 9, f"{SHORT[letter].split('  ')[1]}: reaches 80% CPU utilization at about "
                                     f"{fmt(entry['rated_rps'], 0)} requests per second", "gu-val", fill=COLORS[letter], weight="600")
    if compared:
        marks = {entry["source"] for entry in compared["stages"].values()}
        note = "At the comparison load: " + " ".join(
            text for kind, text in (("runs", "squares are 10-minute runs at that rate."),
                                    ("capacity step", "A ring is a 110-second capacity step next to it."))
            if kind in marks)
        figure.text(left, bottom + 55 + 20 * len(rows) + 12, note, "gu-note")
    return figure.render()


# ---- Figure: CPU per request, Graviton2 against Graviton5 ----------------------------------


def cpu_per_request_chart(comparison: dict) -> str:
    by_letter = {e["letter"]: e for e in stages(comparison, "steady")}
    if "A" not in by_letter or "B" not in by_letter:
        return ""
    a, b = by_letter["A"], by_letter["B"]
    tiers = (("web", "Web tier (React rendering on Node.js)", "c6g", "c9g"),
             ("api", "API tier (Java 21, Spring Boot)", "m6g", "m9g"),
             ("db_writer", "Database (Aurora MySQL writer)", "db.r6g", "db.r9g"))
    left, top, block = 0, 74, 78
    highest = max(a["steady"]["tiers"][t]["cpu_ms_per_request"]["median"] for t, *_ in tiers)
    x = Linear(0, highest * 1.02, 150, WIDTH - 190)
    figure = Figure(
        WIDTH, top + block * len(tiers) + 26, "CPU time spent per request, at the same instance size",
        "Milliseconds of CPU time per request at 8,000 requests per second: median of three 590-second runs. Lower is better.",
        "Bar chart comparing CPU milliseconds per request on Graviton2 and Graviton5 for each tier.", "gu-cpureq")
    for index, (tier, title, old, new) in enumerate(tiers):
        y = top + index * block
        figure.text(left, y, title, weight="600")
        before = a["steady"]["tiers"][tier]["cpu_ms_per_request"]["median"]
        after = b["steady"]["tiers"][tier]["cpu_ms_per_request"]["median"]
        for offset, (letter, family, value) in enumerate((("A", old, before), ("B", new, after))):
            yy = y + 10 + offset * 26
            figure.text(left, yy + 15, f"Graviton{'2' if letter == 'A' else '5'}  {family}", "gu-val",
                        fill=COLORS[letter])
            figure.rect(x(0), yy, x(value) - x(0), 20, COLORS[letter])
            figure.text(x(value) + 6, yy + 15, f"{fmt(value, 2)} ms", "gu-val")
        figure.text(WIDTH - 4, y + 38, f"{1 - after / before:.0%} less", "gu-title", "end", fill=COLORS["B"])
        figure.text(WIDTH - 4, y + 54, "CPU time on Graviton5", "gu-note", "end")
    return figure.render()


# ---- Figure: monthly cost -----------------------------------------------------------------

SEGMENTS = (
    ("Aurora MySQL", lambda r: r["item"].startswith("Aurora MySQL writer")),
    ("Web nodes", lambda r: r["item"].startswith("Web tier")),
    ("API nodes", lambda r: r["item"].startswith("API tier")),
    ("System nodes", lambda r: r["item"].startswith("System nodes")),
    ("Rest of the stack", lambda r: r["group"] == "Rest of the stack"),
)
SEGMENT_OPACITY = (1.0, 0.72, 0.5, 0.34, 0.16)


def cost_chart(bom: dict, pricing: str = "on_demand") -> str:
    entries = list(bom["stages"].items())
    left, top, row_height = 190, 92, 62
    totals = [entry[pricing]["total"] for _, entry in entries]
    x = Linear(0, max(totals) * 1.0, left, WIDTH - 120)
    baseline = totals[0]
    basis = "On-Demand" if pricing == "on_demand" else "one-year, no-upfront commitments where offered"
    figure = Figure(
        WIDTH, top + row_height * len(entries) + 34,
        f"Modelled monthly cost of the whole stack at an average of {fmt(bom['usage']['average_rps'], 0)} requests per second",
        f"US dollars per month of 730 hours, US West (Oregon), {basis}. Prices of {bom['prices_retrieved_at'][:10]}.",
        "Stacked bar chart of the modelled monthly bill of each configuration, in US dollars: Aurora MySQL instances, "
        "web nodes, API nodes, system nodes and the rest of the stack.", f"gu-cost-{pricing}")
    # Legend as a labelled sample bar, in the baseline's colour.
    lx = left
    for (name, _), opacity in zip(SEGMENTS, SEGMENT_OPACITY):
        figure.rect(lx, 52, 14, 14, COLORS["A"], opacity)
        figure.text(lx + 19, 64, name, "gu-note")
        lx += 26 + len(name) * 6.6
    for tick in nice_ticks(0, max(totals), 5):
        figure.line(x(tick), top - 6, x(tick), top + row_height * len(entries) - 14)
        figure.text(x(tick), top + row_height * len(entries) + 2, f"${fmt(tick, 0)}", "gu-tick", "middle")
    figure.text(x(max(totals)), top + row_height * len(entries) + 20, "US dollars per month", "gu-axis", "end")
    for index, (stage, entry) in enumerate(entries):
        letter = entry["title"][0]
        y = top + index * row_height
        figure.text(0, y + 14, SHORT[letter], weight="600", fill=COLORS[letter])
        shape = entry["shape"]
        figure.text(0, y + 29, f"{shape['web'][0]} / {shape['api'][0]}", "gu-note")
        figure.text(0, y + 43, shape["database"][0], "gu-note")
        cursor = 0.0
        for (name, match), opacity in zip(SEGMENTS, SEGMENT_OPACITY):
            amount = sum(r["monthly_usd"] for r in entry[pricing]["rows"] if match(r))
            figure.rect(x(cursor), y + 4, x(cursor + amount) - x(cursor) - 1, 30, COLORS[letter], opacity, 1)
            if x(cursor + amount) - x(cursor) > 52:
                figure.text((x(cursor) + x(cursor + amount)) / 2, y + 24, f"${fmt(amount, 0)}", "gu-val", "middle",
                            fill="#fff" if opacity > 0.45 else INK)
            cursor += amount
        total = entry[pricing]["total"]
        figure.text(x(total) + 6, y + 18, f"${fmt(total, 0)}", "gu-val", weight="600")
        if index:
            figure.text(x(total) + 6, y + 33, f"{total / baseline - 1:+.1%} against A", "gu-note")
    return figure.render()


# ---- Figure: a configuration change as clients saw it --------------------------------------


def _minutes(stamp: str, origin: dt.datetime) -> float:
    return (dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")) - origin).total_seconds() / 60


# The two recorded changes: where their recordings are, and how the instances before and
# after are named and coloured (the colours of the configurations they belong to).
CHANGES = {
    "ab": {"stage": "a-graviton2-baseline", "old": ("Graviton2", COLORS["A"]), "new": ("Graviton5", COLORS["B"])},
    "bc": {"stage": "b-graviton5-same-size", "old": ("Graviton5, baseline size", COLORS["B"]),
           "new": ("Graviton5, half the size", COLORS["C"])},
}


def change_data(stage: str, label: str) -> dict | None:
    """Everything recorded while the pipeline applied one configuration change."""
    base = ROOT / "results" / stage
    events_path, inventory_path = base / f"{label}-events.json", base / f"{label}-inventory.jsonl"
    if not events_path.exists() or not inventory_path.exists():
        return None
    events = json.loads(events_path.read_text())["events"]
    pushes = [e for e in events if e["source"] == "pipeline" and e["subject"] == "Source/Source" and e["event"] == "started"]
    origin = dt.datetime.fromisoformat(pushes[0]["at"].replace("Z", "+00:00"))
    inventory = [json.loads(line) for line in inventory_path.read_text().splitlines() if line.strip()]
    timeline_path = base / f"{label}-probe" / "timeline.json"
    timeline = json.loads(timeline_path.read_text()) if timeline_path.exists() else None
    done = [e for e in events if e["source"] == "pipeline" and e["subject"].startswith("Verify/") and e["event"] == "succeeded"]
    # Instance types of each tier, and database classes, that existed before the change:
    # everything else is new. Per tier, because one tier's new type can be another's old one.
    first = inventory[0]
    before = {"database": {i["class"] for i in first.get("database", [])}}
    for node in first.get("nodes", []):
        before.setdefault(node["tier"], set()).add(node["type"])
    return {"origin": origin, "events": events, "inventory": inventory, "timeline": timeline, "before": before,
            "end_minutes": _minutes(done[-1]["at"], origin) if done else _minutes(events[-1]["at"], origin)}


def pipeline_spans(events: list[dict], origin: dt.datetime) -> list[tuple[str, float, float]]:
    """The pipeline's steps as (name, start, end) in minutes after the start of the first pipeline run, for each
    pipeline run of the change. Steps that did nothing (under 30 seconds) are left out, so
    a run that only redeploys the pods shows as build and deploy."""
    names = {"Cluster": "node groups", "Database": "database", "Build": "build"}
    spans: dict[tuple[int, str], list[float]] = {}
    run = 0
    for event in sorted((e for e in events if e["source"] == "pipeline"), key=lambda e: e["at"]):
        stage_name, action = event["subject"].split("/")
        if stage_name == "Source" and event["event"] == "started":
            run += 1
        name = names.get(action, "deploy" if stage_name in ("Platform", "Deploy", "Verify") else None)
        if not name:
            continue
        minute = _minutes(event["at"], origin)
        span = spans.setdefault((run, name), [minute, minute])
        span[0], span[1] = min(span[0], minute), max(span[1], minute)
    return [(name, start, end) for (_, name), (start, end) in spans.items() if end - start >= 0.5]


def probe_buckets(timeline: dict, origin: dt.datetime, seconds: int = 10) -> list[dict]:
    """The probe's requests in fixed buckets: totals, failures and mean response time."""
    start = dt.datetime.fromtimestamp(timeline["start_epoch"], dt.timezone.utc)
    length = timeline["seconds"]
    buckets = []
    for offset in range(0, length, seconds):
        ok = failed = 0
        weighted = 0.0
        for series in timeline["series"].values():
            for i in range(offset, min(offset + seconds, length)):
                ok += series["ok"][i]
                failed += series["failed"][i]
                if series["mean_ms"][i] is not None:
                    weighted += series["mean_ms"][i] * (series["ok"][i] + series["failed"][i])
        total = ok + failed
        buckets.append({"minute": ((start - origin).total_seconds() + offset) / 60, "ok": ok, "failed": failed,
                        "mean_ms": weighted / total if total else None})
    return buckets


def _runs(samples: list[tuple[float, object]], end: float) -> list[tuple[float, float, object]]:
    """Merges consecutive samples with the same value into (start, end, value) runs."""
    runs: list[list] = []
    for minute, value in samples:
        if runs and runs[-1][2] == value:
            continue
        if runs:
            runs[-1][1] = minute
        runs.append([minute, end, value])
    return [tuple(run) for run in runs]


def change_chart(stage: str, label: str, title: str, subtitle: str, ident: str) -> str:
    data = change_data(stage, label)
    if not data:
        return ""
    origin, events, inventory, timeline = data["origin"], data["events"], data["inventory"], data["timeline"]
    left, right = 196, WIDTH - 12
    x_lo, x_hi = -3.0, data["end_minutes"] + 3.0
    x = Linear(x_lo, x_hi, left, right)
    (old_name, old_color), (new_name, new_color) = CHANGES[label]["old"], CHANGES[label]["new"]
    before, bad, gold = data["before"], "#c62828", "#e0a100"
    figure = Figure(WIDTH, 600, title, subtitle,
                    "Timeline of a configuration change: failed requests, response time, pods by processor "
                    "generation, database instances and pipeline steps.", ident)
    y = 104.0
    chart_top = y - 8

    def lane(name: str, note: str, height: int) -> tuple[float, float]:
        nonlocal y
        top = y
        figure.text(0, top + 13, name, weight="600")
        if note:
            figure.text(0, top + 28, note, "gu-note")
        figure.line(left, top + height, right, top + height, "gu-base", f"stroke:{GRID}")
        y += height + 18
        return top, top + height

    snapshots = [(_minutes(s["at"], origin), s) for s in inventory if x_lo <= _minutes(s["at"], origin) <= x_hi]
    last = snapshots[-1][0] + 1 / 6

    # ---- probe: failures and response time ----
    if timeline:
        buckets = [b for b in probe_buckets(timeline, origin) if x_lo <= b["minute"] <= x_hi]
        top, bottom = lane("Failed requests", "probe, per 10 seconds", 58)
        peak = max(max(b["failed"] for b in buckets), 1)
        scale = Linear(0, peak, bottom, top + 16)
        width = max(1.5, x(10 / 60) - x(0))
        for b in buckets:
            if b["failed"]:
                figure.rect(x(b["minute"]), scale(b["failed"]), width, bottom - scale(b["failed"]), bad, rx=0)
        # Counted from the start to the end of the pipeline run, not over the margins of the plot:
        # the same figures as analysis/change_summary.py reports.
        import change_summary

        during = change_summary.summarize(stage, label)["probe"]["during_the_change"]
        figure.text(0, 60, f"{during['failed']:,} of the {during['requests']:,} probe requests that finished during the "
                           "change had failed, all at the two failovers.", "gu-val", weight="600")
        figure.text(left - 6, scale(peak) + 4, str(peak), "gu-tick", "end")
        figure.text(left - 6, bottom + 1, "0", "gu-tick", "end")

        top, bottom = lane("Response time", "probe mean, log scale", 58)
        values = [b["mean_ms"] for b in buckets if b["mean_ms"]]
        low, high = max(min(values) * 0.7, 1), max(values) * 1.3
        scale = Log(low, high, bottom, top + 4)
        figure.path([(x(b["minute"]), scale(b["mean_ms"])) for b in buckets if b["mean_ms"]], INK, 1.3)
        ticks = [t for t in (2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000) if low <= t <= high]
        for tick in ticks[:: max(1, len(ticks) // 3)]:
            figure.text(left - 6, scale(tick) + 4, f"{tick} ms", "gu-tick", "end")

    # ---- pods, on the nodes from before the change and on the new ones ----
    summary = None
    if timeline:
        import change_summary

        summary = change_summary.summarize(stage, label)["pods"]
    for tier, name in (("web", "Web pods ready"), ("api", "API pods ready")):
        top, bottom = lane(name, "on old and new nodes", 46)
        counts = []
        for minute, snapshot in snapshots:
            nodes = [n for n in snapshot.get("nodes", []) if n["tier"] == tier]
            counts.append((minute, (sum(n["ready_pods"] for n in nodes if n["type"] in before.get(tier, ())),
                                    sum(n["ready_pods"] for n in nodes if n["type"] not in before.get(tier, ())))))
        if not counts:
            continue
        most = max(old + new for _, (old, new) in counts) or 1
        scale = Linear(0, most, bottom, top + 4)
        for start, end, (old, new) in _runs(counts, last):
            width = x(end) - x(start) + 0.4
            figure.rect(x(start), scale(old), width, bottom - scale(old), old_color, rx=0)
            figure.rect(x(start), scale(old + new), width, scale(old) - scale(old + new), new_color, rx=0)
        figure.text(left - 6, scale(most) + 9, str(most), "gu-tick", "end")
        pods = (summary or {}).get(tier, {})
        if "lowest_while_nodes_were_replaced" in pods:
            note = (f"lowest while nodes were replaced: {pods['lowest_while_nodes_were_replaced']} of "
                    f"{pods['at_start_of_node_replacement']}")
            if pods["samples_at_zero"]:
                note += f"; none ready in {pods['samples_at_zero']} samples at a failover"
        else:
            note = f"lowest: {min(old + new for _, (old, new) in counts)} of {most} ready"
        figure.text(right, top - 3, note, "gu-note", "end")

    # ---- database instances ----
    top, bottom = lane("Database", "", 56)
    for row, name in enumerate(("instance1", "instance2")):
        row_top = top + 2 + row * 27
        figure.text(left - 6, row_top + 15, name.replace("instance", "instance "), "gu-tick", "end")
        states = []
        for minute, snapshot in snapshots:
            instance = next((i for i in snapshot.get("database", []) if i["id"] == name), None)
            if instance:
                states.append((minute, (instance["class"], instance["status"] == "available", instance["writer"])))
        shown = None
        for start, end, (instance_class, available, writer) in _runs(states, last):
            color = old_color if instance_class in before["database"] else new_color
            width = x(end) - x(start) + 0.4
            figure.rect(x(start), row_top, width, 21, color, 1.0 if available else 0.35, rx=0)
            if writer:
                figure.rect(x(start), row_top + 17, width, 4, gold, rx=0)
            if instance_class != shown and available and width > 62:
                figure.text(x(start) + 5, row_top + 14, instance_class.replace("db.", ""), "gu-note", fill="#fff")
                shown = instance_class
    figure.text(0, top + 28, "lighter: restarting", "gu-note")
    figure.text(0, top + 43, "gold: writer", "gu-note")

    # ---- pipeline ----
    lanes_bottom = y - 18
    top, bottom = lane("Pipeline", "", 28)
    for name, start, end in pipeline_spans(events, origin):
        figure.rect(x(start) + 1, top + 2, max(2, x(end) - x(start) - 2), 22, "#e9ecf0", rx=3)
        # The name only: the durations are in the change's summary (analysis/change_summary.py).
        if x(end) - x(start) > 90:
            figure.text((x(start) + x(end)) / 2, top + 17, name, "gu-note", "middle")
        elif x(end) - x(start) > 34:
            figure.text((x(start) + x(end)) / 2, top + 17, name.split(" ")[0], "gu-note", "middle")

    # ---- failovers, drawn across every lane ----
    failovers = [e for e in events if e["source"] == "rds" and e["event"].startswith("Started cross AZ failover")]
    for number, event in enumerate(failovers, start=1):
        minute = _minutes(event["at"], origin)
        figure.line(x(minute), chart_top - 6, x(minute), lanes_bottom, "gu-base",
                    f"stroke:{gold};stroke-dasharray:3 3;stroke-width:1.5")
        figure.text(x(minute), chart_top - 10, f"failover {number}", "gu-note", "middle")

    # ---- later pushes of the same change (a change made in two commits) ----
    pushes = sorted(_minutes(e["at"], origin) for e in events
                    if e["source"] == "pipeline" and e["subject"] == "Source/Source" and e["event"] == "started")
    for number, minute in enumerate(pushes[1:], start=2):
        figure.line(x(minute), chart_top - 6, x(minute), lanes_bottom + 46, "gu-base",
                    f"stroke:{MUTED};stroke-dasharray:1 3")
        figure.text(x(minute), chart_top - 10, f"pipeline run {number}", "gu-note", "middle")

    # ---- time axis ----
    for tick in range(0, int(x_hi) + 1, 5):
        figure.line(x(tick), y - 18, x(tick), y - 13, "gu-base")
        clock = (origin + dt.timedelta(minutes=tick)).strftime("%H:%M")
        figure.text(x(tick), y, f"+{tick} min" if tick else "start", "gu-tick", "middle")
        figure.text(x(tick), y + 14, f"{clock} UTC" if tick == 0 else clock, "gu-note", "middle")
    y += 32
    lx = left
    for color, text in ((old_color, old_name), (new_color, new_name)):
        figure.rect(lx, y, 12, 12, color, rx=2)
        figure.text(lx + 18, y + 11, text, "gu-note")
        lx += 40 + len(text) * 6.4
    figure.height = int(y + 24)
    return figure.render()


def main() -> None:
    comparison = json.loads((ROOT / "results/comparison.json").read_text())
    bom = json.loads((ROOT / "results/bom.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    charts = {
        "rated-load": rated_load_chart(),
        "capacity": capacity_chart(comparison),
        "cpu-per-request": cpu_per_request_chart(comparison),
        "ceiling": ceiling_chart(comparison),
        "cost-on-demand": cost_chart(bom, "on_demand"),
        "cost-committed": cost_chart(bom, "committed"),
        "upgrade": change_chart(
            "a-graviton2-baseline", "ab", "The upgrade to Graviton5 as clients saw it",
            "Background load: 4,000 requests per second. Probe: 100 requests per second, counted by outcome every second.",
            "gu-upgrade"),
        "rightsize": change_chart(
            "b-graviton5-same-size", "bc", "The right-sizing as clients saw it",
            "Background load: 4,000 requests per second. Probe: 100 requests per second, counted by outcome every second.",
            "gu-rightsize"),
    }
    for name, markup in charts.items():
        if markup:
            (OUT / f"{name}.svg").write_text(markup)
            print(f"wrote report/figures/{name}.svg ({len(markup):,} bytes)")


if __name__ == "__main__":
    main()

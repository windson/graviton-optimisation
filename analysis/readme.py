#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Fills the results section of README.md from the recorded data.

    uv run analysis/readme.py

Input:  report/readme-results.md   the section, with {{placeholders}} for every number and its
                                   links relative to report/
        report/tables/*.md         tables generated from the data (analysis/tables.py)
        results/comparison.json  results/ceiling.json  results/rated.json  results/bom.json
        results/*/*-summary.json
Output: README.md, between its two results markers

Numbers in the text are never typed by hand: a placeholder such as
{{c.at_rated.latency_ms.p99.median|.1f}} is looked up in the data when the section is
built, and {{= expression |format}} computes one from several values, so the text cannot
drift from the results. The build fails on a placeholder that does not resolve.
"""
from __future__ import annotations

import functools
import json
import math
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPORT = ROOT / "report"


# ---- The data, under short names ------------------------------------------------------


@functools.cache
def context() -> dict:
    """The result files under the names the placeholders use. `a`, `b` and `c` are the
    configurations (results/comparison.json), each with its rating as <letter>.ceiling
    (results/ceiling.json) and its figures at the comparison rate as <letter>.at_rated
    (results/rated.json). `rated` is that last file as a whole, `bom` the bill, and
    `changes` what clients saw during each configuration change (analysis/change_summary.py)."""
    data: dict = {"bom": json.loads((ROOT / "results/bom.json").read_text()),
                  "rated": json.loads((ROOT / "results/rated.json").read_text())}
    for entry in json.loads((ROOT / "results/comparison.json").read_text())["stages"].values():
        data[entry["letter"].lower()] = entry
    for entry in json.loads((ROOT / "results/ceiling.json").read_text())["stages"].values():
        data[entry["letter"].lower()]["ceiling"] = entry
    for entry in data["rated"]["stages"].values():
        data[entry["letter"].lower()]["at_rated"] = entry
    data["changes"] = {path.name.split("-")[0]: json.loads(path.read_text())
                       for path in sorted(ROOT.glob("results/*/*-summary.json"))}
    return data


def lookup(data: dict, path: str):
    node = data
    for key in path.split("."):
        if isinstance(node, list):
            node = node[int(key)]
        elif isinstance(node, dict) and key in node:
            node = node[key]
        else:
            raise KeyError(path)
    return node


SAFE_NAMES = {"abs": abs, "min": min, "max": max, "round": round, "sum": sum, "len": len}


def fill(text: str, data: dict) -> str:
    """Replaces {{path|format}} and {{= expression |format}} with values from the data."""

    def replace(match: re.Match) -> str:
        body = match.group(1).strip()
        spec = ""
        if "|" in body:
            body, spec = (part.strip() for part in body.rsplit("|", 1))
        try:
            if body.startswith("="):
                # Arithmetic on data values, e.g. {{= c.cost.on_demand_total - a.cost.on_demand_total |,.0f}}
                names = {key: Namespace(value) for key, value in data.items()}
                value = eval(body[1:], {"__builtins__": {}}, {**SAFE_NAMES, **names})  # noqa: S307
                if isinstance(value, Namespace):
                    value = value._wrapped
            else:
                value = lookup(data, body)
        except Exception as error:
            raise SystemExit(f"placeholder {{{{{match.group(1)}}}}} does not resolve: {error!r}") from error
        if spec == "$":
            # Whole dollars, halves rounded up, as the tables do (analysis/tables.py, money).
            return f"${math.floor(value + 0.5):,}"
        return format(value, spec) if spec else str(value)

    return re.sub(r"\{\{(.+?)\}\}", replace, text)


class Namespace:
    """Lets expressions use dotted access into the nested data: a.steady.latency_ms.p99.median

    The wrapped object is kept under a name no data key uses, so that keys such as
    "value" or "items" resolve to the data and not to an attribute of this class."""

    def __init__(self, wrapped) -> None:
        object.__setattr__(self, "_wrapped", wrapped)

    def __getattribute__(self, key: str):
        wrapped = object.__getattribute__(self, "_wrapped")
        if key == "_wrapped":
            return wrapped
        if isinstance(wrapped, dict):
            if key in wrapped:
                value = wrapped[key]
            elif key in ("values", "keys", "items"):
                return getattr(wrapped, key)
            else:
                raise KeyError(key)
        else:
            value = getattr(wrapped, key)
        return Namespace(value) if isinstance(value, (dict, list)) else value

    def __getitem__(self, key):
        value = object.__getattribute__(self, "_wrapped")[key]
        return Namespace(value) if isinstance(value, (dict, list)) else value

    def __len__(self) -> int:
        return len(object.__getattribute__(self, "_wrapped"))


# ---- Tables generated from the data ------------------------------------------------------


def include(markdown: str) -> str:
    """Replaces `::include <path>` lines with the file's contents (tables generated from data)."""

    def replace(match: re.Match) -> str:
        path = REPORT / match.group(1).strip()
        if not path.exists():
            raise SystemExit(f"::include {match.group(1)}: file not found")
        return path.read_text().rstrip("\n")

    return re.sub(r"^::include (.+)$", replace, markdown, flags=re.M)


def main() -> None:
    text = fill(include((REPORT / "readme-results.md").read_text()), context()).strip()
    # The section's own links are relative to report/, where it is written; README.md is one level up.
    text = re.sub(r"\]\((?![a-z]+:|/|#)([^)\s]+)\)", r"](report/\1)", text)
    readme = ROOT / "README.md"
    new, count = re.subn(r"(<!-- results:[^>]*-->\n).*?(<!-- /results -->)",
                         lambda match: match.group(1) + text + "\n" + match.group(2), readme.read_text(), flags=re.S)
    if count != 1:
        raise SystemExit("README.md: the results markers were not found exactly once")
    readme.write_text(new)
    print("wrote the results section of README.md")


if __name__ == "__main__":
    main()

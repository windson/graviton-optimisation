#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Replaces account-specific identifiers in the recorded files with placeholders.

    uv run tools/redact.py --account <12-digit account ID>            # report what would change
    uv run tools/redact.py --account <12-digit account ID> --apply    # rewrite the files
    uv run tools/redact.py --account <ID> --dlt-stack <name> --apply  # and the load-testing stack's name

The results of a study hold identifiers of the account it ran in: the account ID (in
container image URIs and ARNs), EC2 instance IDs, the IDs of the load generator's tasks,
the generated suffixes of database instances and node groups, the load balancer's DNS
name and the names of its target groups, pipeline execution IDs and other UUIDs, the name
of an IAM role and of the load-testing stack. None of them is needed to read or to
re-analyse the results. This script replaces each with a placeholder of the same length,
so that tables and aligned listings keep their shape, and replaces the same identifier
the same way everywhere, so that files still refer to each other.

It was run on this repository before publication. Run it on your own results before you
publish them. It can be run again when results are added: identifiers that are still
there as recorded get the numbers after the highest placeholder already in the files, so
a new identifier cannot share a placeholder with an old one. The account ID has to be
told, and the name of the load-testing stack if the results mention it; everything else
is found by its form. Node names and pod addresses are left as they are: they come from
the address range that this repository's own network template defines.

It rewrites text files under results/, docs/ and report/. It does not touch infra/, where
scripts/set-admin-role.sh manages the one account-specific value.
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
FOLDERS = ("results", "docs", "report")
TEXT = {".json", ".jsonl", ".txt", ".md", ".log", ".html", ".js", ".yaml", ".yml", ".csv", ".svg"}


def files() -> list[pathlib.Path]:
    out = []
    for folder in FOLDERS:
        for path in sorted((ROOT / folder).rglob("*")):
            if path.is_file() and path.suffix in TEXT and "__pycache__" not in path.parts:
                out.append(path)
    return out


def build_rules(account: str, dlt_stack: str | None, corpus: list[str]) -> list[tuple[re.Pattern, object, str]]:
    """Rules as (pattern, replacement, name). Identifiers that must stay distinct (instance
    IDs, execution IDs) are numbered in the order of their sorted values, starting after
    the highest placeholder of their kind that the files already hold. A second run over
    the same files therefore changes nothing, and a run over files with new results gives
    the new identifiers numbers of their own."""

    def numbered(form: str, placeholder: str) -> tuple[list[str], int]:
        """The identifiers of one kind still to be replaced, sorted, and the first free number."""
        found = {m for text in corpus for m in re.findall(form, text)}
        taken = [int(m[-12:]) for m in found if re.fullmatch(placeholder, m)]
        return sorted(m for m in found if not re.fullmatch(placeholder, m)), max(taken, default=0) + 1

    instance_ids, first = numbered(r"\bi-[0-9a-f]{17}\b", r"i-0{10}\d{7}")
    instance_map = {old: f"i-{n:017d}" for n, old in enumerate(instance_ids, start=first)}
    uuids, first = numbered(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
                            r"00000000-0000-0000-0000-\d{12}")
    uuid_map = {old: f"00000000-0000-0000-0000-{n:012d}" for n, old in enumerate(uuids, start=first)}
    task_ids, first = numbered(r'"task":\s*"([0-9a-f]{32})"', r"0{20}\d{12}")
    task_map = {old: f"{n:032d}" for n, old in enumerate(task_ids, start=first)}
    # Target groups made by the AWS Load Balancer Controller: k8s-<namespace>-<service>-<10 hex>.
    group_form = r"\b(k8s-[a-z0-9]{1,8}-[a-z0-9]{1,8}-)([0-9a-f]{10})\b"
    groups, first = numbered(r"\bk8s-[a-z0-9]{1,8}-[a-z0-9]{1,8}-([0-9a-f]{10})\b", r"0{6}\d{4}")
    group_map = {old: f"{n:010d}" for n, old in enumerate(groups, start=first)}
    return [
        # An IAM role of the account: the name goes as well as the account.
        (re.compile(rf"arn:aws:iam::(?:{account}|<account-id>):role/[A-Za-z0-9+=,.@_-]+"),
         "arn:aws:iam::<account-id>:role/<admin-role>", "IAM role ARN"),
        (re.compile(account), "<account-id>", "account ID"),
        (re.compile(r"\bi-[0-9a-f]{17}\b"), lambda m: instance_map.get(m.group(0), m.group(0)), "EC2 instance ID"),
        (re.compile(r"\b(instance\d)-(?!x{12})[a-z0-9]{12}\b"), r"\1-xxxxxxxxxxxx", "database instance suffix"),
        (re.compile(r"\b((?:Api|Web|System)NodeGroup)-(?!x{12})[A-Za-z0-9]{12}\b"), r"\1-xxxxxxxxxxxx", "node group suffix"),
        (re.compile(r"\b(graviton-uplift-)(\d{6,12})(\.[a-z0-9-]+\.elb\.amazonaws\.com)"),
         lambda m: m.group(1) + "0" * len(m.group(2)) + m.group(3), "load balancer DNS name"),
        (re.compile(r"\b((?:app|net|targetgroup)/[A-Za-z0-9-]+/)(?!0{16})([0-9a-f]{16})\b"),
         lambda m: m.group(1) + "0" * 16, "load balancer ID"),
        (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
         lambda m: uuid_map.get(m.group(0), m.group(0)), "execution ID"),
        (re.compile(r'("task":\s*")([0-9a-f]{32})(")'),
         lambda m: m.group(1) + task_map.get(m.group(2), m.group(2)) + m.group(3), "load generator task ID"),
        (re.compile(group_form), lambda m: m.group(1) + group_map.get(m.group(2), m.group(2)), "target group name"),
    ] + ([(re.compile(re.escape(dlt_stack)), "<dlt-stack>", "load-testing stack name")] if dlt_stack else [])


def substitute(pattern: re.Pattern, replacement, text: str) -> tuple[str, int]:
    """The text with the rule applied, and how many identifiers it actually replaced
    (a placeholder that is already there matches some rules and is left as it is)."""
    replaced = 0

    def swap(match: re.Match) -> str:
        nonlocal replaced
        new = replacement(match) if callable(replacement) else match.expand(replacement)
        replaced += new != match.group(0)
        return new

    return pattern.sub(swap, text), replaced


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--account", required=True, help="the 12-digit ID of the account the study ran in")
    parser.add_argument("--dlt-stack", help="the name of the load-testing stack, if the results mention it")
    parser.add_argument("--apply", action="store_true", help="rewrite the files (default: only report)")
    arguments = parser.parse_args()
    if not re.fullmatch(r"\d{12}", arguments.account):
        raise SystemExit("--account must be a 12-digit AWS account ID")

    paths = files()
    texts = {path: path.read_text(errors="surrogateescape") for path in paths}
    rules = build_rules(arguments.account, arguments.dlt_stack, list(texts.values()))
    counts: collections.Counter = collections.Counter()
    changed = 0
    for path, text in texts.items():
        new = text
        for pattern, replacement, name in rules:
            new, n = substitute(pattern, replacement, new)
            counts[name] += n
        if new != text:
            changed += 1
            if arguments.apply:
                path.write_text(new, errors="surrogateescape")
    for name, n in counts.most_common():
        print(f"{n:6d}  {name}")
    print(f"{changed} of {len(paths)} files {'rewritten' if arguments.apply else 'would change'}")


if __name__ == "__main__":
    main()

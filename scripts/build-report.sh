#!/usr/bin/env bash
# Rebuilds every computed file from the recorded runs, in dependency order: run summaries,
# usage and bill, comparison, ceiling and the comparison at the rated load, tables, charts,
# architecture diagrams, the recorded analysis listings, the CloudWatch graphs, and the
# results section of README.md.
#
#   scripts/build-report.sh                # everything
#   SKIP_AWS=1 scripts/build-report.sh     # without the steps that query AWS (usage, CloudWatch graphs)
#
# The steps that query AWS only read metrics. Do not run this while a benchmark is in
# progress: it summarizes every run directory it finds.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
step() { echo "== $*"; }

step "run summaries"
for run in results/calibration/*/ results/[a-c]-*/*/; do
  [ -f "$run/dlt.json" ] && [ -f "$run/kubelet.jsonl" ] && uv run -q analysis/summarize.py "${run%/}" > /dev/null
done

step "what clients saw during the changes"
[ -f results/a-graviton2-baseline/ab-events.json ] && uv run -q analysis/change_summary.py a-graviton2-baseline ab > /dev/null
[ -f results/b-graviton5-same-size/bc-events.json ] && uv run -q analysis/change_summary.py b-graviton5-same-size bc > /dev/null

if [ -z "${SKIP_AWS:-}" ]; then
  step "usage-priced quantities (CloudWatch, Enhanced Monitoring)"
  uv run -q analysis/usage.py > /dev/null
fi

step "bill, comparison, ceiling, the comparison at the rated load"
uv run -q analysis/bom.py > /dev/null
uv run -q analysis/compare.py > /dev/null
uv run -q analysis/ceiling.py > /dev/null
uv run -q analysis/rated.py > /dev/null

step "tables, charts, architecture diagrams"
uv run -q analysis/tables.py > /dev/null
uv run -q analysis/charts.py > /dev/null
uv run -q analysis/architecture.py > /dev/null

step "recorded analysis listings"
scripts/capture-analysis-evidence.sh > /dev/null

if [ -z "${SKIP_AWS:-}" ]; then
  step "CloudWatch graphs"
  # Each <name>.period.txt holds the arguments of a capture: name, start, end and the labelled pushes.
  for period in results/evidence/cloudwatch/*.period.txt; do
    [ -f "$period" ] && xargs -a "$period" scripts/capture-cloudwatch-images.sh > /dev/null
  done
fi

step "the results in the README"
# README.md shows its table and its numbers from the data (report/readme-results.md): they
# are filled in, not typed.
uv run -q analysis/readme.py > /dev/null

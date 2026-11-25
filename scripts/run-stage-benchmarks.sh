#!/usr/bin/env bash
# Runs the protocol's benchmark sequence against the configuration that is deployed:
# a discarded warm-up, one capacity run, then three steady runs at the operating load
# (docs/02-experiment-protocol.md).
#
#   scripts/run-stage-benchmarks.sh a            # run names a-cap, a-r1, a-r2, a-r3
#   FACTORS=1.0,1.5,2.0 CAPACITY_TASKS=110 scripts/run-stage-benchmarks.sh b
#   RUNS=r1 scripts/run-stage-benchmarks.sh c    # one steady run instead of three
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${1:?usage: run-stage-benchmarks.sh <run name prefix>}"
RATE="${RATE:-8000}"
STEADY_TASKS="${STEADY_TASKS:-28}"
CAPACITY_TASKS="${CAPACITY_TASKS:-60}"
FACTORS="${FACTORS:-1.0,1.2,1.4,1.5,1.6,1.7,1.8,1.9,2.0,2.1,2.2}"
RUNS="${RUNS:-r1 r2 r3}"
STAGE="$(cat "$ROOT/infra/config/ACTIVE_STAGE")"

cd "$ROOT"
# Pods restart whenever a configuration is deployed. Give the JVMs and the database cache
# three minutes at half the operating load before anything is measured.
uv run -q tools/bench.py steady --name "$PREFIX-warmup" --rate "$((RATE / 2))" --tasks 14 --hold 180
uv run -q tools/bench.py capacity --name "$PREFIX-cap" --rate "$RATE" --tasks "$CAPACITY_TASKS" --factors "$FACTORS"
uv run -q analysis/summarize.py "results/$STAGE/$PREFIX-cap"
for run in $RUNS; do
  uv run -q tools/bench.py steady --name "$PREFIX-$run" --rate "$RATE" --tasks "$STEADY_TASKS"
  uv run -q analysis/summarize.py "results/$STAGE/$PREFIX-$run"
done

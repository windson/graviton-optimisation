#!/usr/bin/env bash
# Configuration A, deployed again at the end of the first session: the change back to it
# (not observed), the recordings, one steady run at 8,000 requests per second to see
# whether the baseline reproduces, and the ceiling run the baseline did not have the
# first time.
#
# This is the script that ran this phase of the study on 23 and 24 November 2026, copied from the
# working directory it was written in. Changed for the repository: the line that changed to the
# study's checkout now finds the repository from the script's location; the console logs go to
# ./tmp, which the script now creates; one line that copied the console log of the first
# deployment's runs from this machine's scratch directory is now a comment; and the change back is
# no longer recorded, so its commit message is shortened and two lines that stored its record are gone.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
mkdir -p tmp
STAGE=a-graviton2-baseline

scripts/apply-stage.sh "$STAGE" "Back to the Graviton2 baseline (configuration A, deployed again)

The same parameter files as the first deployment of the baseline." 2>&1 | tee tmp/change-da.log

grep -q "applied from" tmp/change-da.log || { echo "the change did not complete"; exit 1; }

# The placement of the first deployment: one of the three API nodes in the writer's zone.
scripts/align-writer-zone.sh 1 2>&1 | tee tmp/align-a2.log

scripts/snapshot-environment.sh again
scripts/capture-evidence.sh deployed-again
cp tmp/align-a2.log "results/$STAGE/evidence/deployed-again/writer-zone.txt"

{
  uv run -q tools/bench.py steady --name a2-warmup --rate 4000 --tasks 14 --hold 180
  uv run -q tools/bench.py steady --name a2-r1 --rate 8000 --tasks 28
  uv run -q analysis/summarize.py "results/$STAGE/a2-r1"
} 2>&1 | tee tmp/stage-a2.log
scripts/run-ceiling.sh a2 a 2>&1 | tee tmp/ceiling-a2.log

# The other placement: two of the three API nodes in the writer's zone, as configuration B
# had it. The instance that becomes the writer has served no reads, so it gets its own
# warm-up before the measured run.
scripts/align-writer-zone.sh 2 2>&1 | tee tmp/align-a2p.log
scripts/capture-evidence.sh deployed-again-other-placement
cp tmp/align-a2p.log "results/$STAGE/evidence/deployed-again-other-placement/writer-zone.txt"
{
  uv run -q tools/bench.py steady --name a2p-warmup --rate 4000 --tasks 14 --hold 180
  uv run -q tools/bench.py steady --name a2p-r1 --rate 8000 --tasks 28
  uv run -q analysis/summarize.py "results/$STAGE/a2p-r1"
} 2>&1 | tee tmp/stage-a2p.log

mkdir -p "results/$STAGE/evidence"
# (The console log of the first deployment's runs was copied here from the working directory
# it had been written to; that file is already in results/.)
cp tmp/stage-a2.log "results/$STAGE/evidence/benchmark-again.log"
cp tmp/ceiling-a2.log "results/$STAGE/evidence/ceiling-again.log"
cp tmp/stage-a2p.log "results/$STAGE/evidence/benchmark-again-other-placement.log"
echo "configuration A (again) done"

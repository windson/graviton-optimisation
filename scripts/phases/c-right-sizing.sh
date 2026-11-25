#!/usr/bin/env bash
# Configuration C: the change from B with its observation, the recordings, the benchmark
# sequence and the ceiling run. Console output of each part is kept as evidence.
#
# This is the script that ran this phase of the study on 23 and 24 November 2026, copied from the
# working directory it was written in. Two things were changed for the repository: the line that
# changed to the study's checkout now finds the repository from the script's location, and the
# console logs go to ./tmp, which the script now creates.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
mkdir -p tmp
STAGE=c-graviton5-right-sized
BEFORE="$(git rev-parse HEAD)"

OBSERVE_SECONDS=3600 LEAD_SECONDS=60 scripts/change-stage.sh "$STAGE" bc "Right-size every tier on Graviton5 to half the baseline's vCPUs (configuration C)

Web nodes c9g.4xlarge to c9g.2xlarge, API nodes m9g.xlarge to m9g.large, Aurora
db.r9g.8xlarge to db.r9g.4xlarge. Node counts are unchanged. Web pods 32 to 16
and API pods 6 to 3, with the connection pool per pod doubled, were applied in
the commit before this one, while the nodes were still large." --pods-first 2>&1 | tee tmp/change-bc.log

LINE="$(grep "observed from" tmp/change-bc.log | tail -1)"
[ -n "$LINE" ] || { echo "the change did not complete"; exit 1; }
START="$(sed -E 's/.*observed from ([^ ]+) to ([^ ]+).*/\1/' <<< "$LINE")"
END="$(sed -E 's/.*observed from ([^ ]+) to ([^ ]+).*/\2/' <<< "$LINE")"

scripts/snapshot-environment.sh
scripts/capture-evidence.sh deployed
scripts/capture-change-evidence.sh "$BEFORE" HEAD "$START" "$END"
scripts/capture-failover-logs.sh b-graviton5-same-size bc

scripts/run-stage-benchmarks.sh c 2>&1 | tee tmp/stage-c.log
scripts/run-ceiling.sh c 2>&1 | tee tmp/ceiling-c.log

mkdir -p "results/$STAGE/evidence"
cp tmp/change-bc.log "results/$STAGE/evidence/change/console.log"
cp tmp/stage-c.log "results/$STAGE/evidence/benchmark.log"
cp tmp/ceiling-c.log "results/$STAGE/evidence/ceiling.log"
echo "configuration C done"

#!/usr/bin/env bash
# The second session of the study: the comparison at the baseline's rated load.
#
# The first session rated each configuration at an 80% CPU ceiling. This one holds the
# Graviton2 baseline (A) and the right-sized Graviton5 stack (C) at one and the same
# request rate, the rate of the baseline's ceiling run, so that latency, errors and CPU
# utilization are compared at equal load:
#
#   A, as it was parked:  warm-up, two 10-minute runs at 11,800 requests per second
#                         (the baseline's ceiling run of the first session is the third)
#   A -> C through the pipeline, pods first; not observed under load
#   C:  warm-up, three 10-minute runs at 11,800 requests per second, one at 8,000 (to
#       compare with the first session), and one at 8,000 with one of the two web nodes
#       out of service
#
# Before it: scripts/unpark.sh, then wait for the database and the pods. After it:
# scripts/park.sh. Console output of each part is kept as evidence.
#
# This is the script that ran this session on 24 November 2026, unchanged.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
mkdir -p tmp
: "${DLT_STACK:?set DLT_STACK to the name of the load-testing stack}"
RATE="${RATE:-11800}"
TASKS="${TASKS:-42}"
PROJECT="${PROJECT:-graviton-uplift}"
REGION="${AWS_REGION:-us-west-2}"
A=a-graviton2-baseline
C=c-graviton5-right-sized
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# run <stage> <name> <requests per second> <load generator tasks>
run() {
  uv run -q tools/bench.py steady --name "$2" --rate "$3" --tasks "$4"
  uv run -q analysis/summarize.py "results/$1/$2"
}

# Pushes the commit just made and waits until the pipeline has applied it.
apply() {
  local commit status
  commit="$(git rev-parse HEAD)"
  scripts/push.sh > /dev/null 2>&1
  echo "$(now) waiting for the pipeline to apply $commit"
  while true; do
    status="$(aws codepipeline list-pipeline-executions --region "$REGION" --pipeline-name "$PROJECT" \
      --query "pipelineExecutionSummaries[?sourceRevisions[0].revisionId=='$commit'] | [0].status" --output text)"
    case "$status" in
      Succeeded) echo "$(now) pipeline succeeded"; return 0 ;;
      Failed|Stopped|Cancelled|Superseded) echo "$(now) pipeline $status" >&2; return 1 ;;
    esac
    sleep 20
  done
}

# ---- 1. Configuration A at its rated load ------------------------------------------------
[ "$(cat infra/config/ACTIVE_STAGE)" = "$A" ] || { echo "the active stage is not $A" >&2; exit 1; }
{
  # The placement of the first session: one of the three API nodes in the writer's zone.
  scripts/align-writer-zone.sh 1
  scripts/snapshot-environment.sh session2
  scripts/capture-evidence.sh deployed-session2
  uv run -q tools/bench.py steady --name a3-warmup --rate 4000 --tasks 14 --hold 180
  run "$A" a3-rated-1 "$RATE" "$TASKS"
  run "$A" a3-rated-2 "$RATE" "$TASKS"
} 2>&1 | tee tmp/session2-a.log
cp tmp/session2-a.log "results/$A/evidence/benchmark-session2.log"

# ---- 2. From A to C in one change, pods first ---------------------------------------------
{
  BEFORE="$(git rev-parse HEAD)"
  START="$(now)"
  # C has half the node capacity. Its replica counts go first, while the nodes are large,
  # so that the pods of a node being replaced fit on the new, smaller nodes.
  cp "infra/stages/$C/values.yaml" deploy/values/active.yaml
  git add deploy/values/active.yaml
  git commit --quiet -m "Scale pods to the $C replica counts before resizing nodes"
  apply
  scripts/set-stage.sh "$C"
  git add infra/config deploy/values/active.yaml
  git commit --quiet -m "Upgrade to Graviton5 and right-size in one change (configuration C, from A)

Web nodes c6g.4xlarge to c9g.2xlarge, API nodes m6g.xlarge to m9g.large, Aurora
db.r6g.8xlarge to db.r9g.4xlarge. Node counts are unchanged. Web pods 32 to 16
and API pods 6 to 3, with the connection pool per pod doubled, were applied in
the commit before this one, while the nodes were still large."
  apply
  END="$(now)"
  echo "$(now) change $A -> $C applied from $START to $END"
  scripts/align-writer-zone.sh 1
  scripts/snapshot-environment.sh session2
  scripts/capture-evidence.sh deployed-session2
  scripts/capture-change-evidence.sh "$BEFORE" HEAD "$START" "$END" change-session2
} 2>&1 | tee tmp/session2-change.log
mkdir -p "results/$C/evidence/change-session2"
cp tmp/session2-change.log "results/$C/evidence/change-session2/console.log"

# ---- 3. Configuration C at the same load, and at the first session's load -----------------
{
  uv run -q tools/bench.py steady --name c2-warmup --rate 4000 --tasks 14 --hold 180
  for n in 1 2 3; do
    run "$C" "c2-rated-$n" "$RATE" "$TASKS"
  done
  run "$C" c2-r1 8000 28
} 2>&1 | tee tmp/session2-c.log
cp tmp/session2-c.log "results/$C/evidence/benchmark-session2.log"

# ---- 4. Configuration C with one of its two web nodes out of service ----------------------
# A drain would stop at the pod disruption budget, which is what protects a planned
# change. A lost node does not ask: the node is cordoned and its web pods are deleted.
# Their replacements find no room on the other node and stay pending for the run.
{
  node="$(kubectl get nodes -l tier=web -o jsonpath='{.items[0].metadata.name}')"
  echo "$(now) taking web node $node out of service"
  kubectl cordon "$node"
  kubectl -n storefront delete pods -l app=storefront-web --field-selector "spec.nodeName=$node"
  sleep 90
  scripts/capture-evidence.sh one-web-node
  run "$C" c2n-r1 8000 28
  kubectl uncordon "$node"
  kubectl -n storefront wait --for=condition=Ready pods -l app=storefront-web --timeout=900s
  echo "$(now) web node $node is back in service"
} 2>&1 | tee tmp/session2-node.log
cp tmp/session2-node.log "results/$C/evidence/one-web-node/console.log"
echo "$(now) second session done"

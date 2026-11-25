#!/usr/bin/env bash
# Moves the deployed stack to another configuration through the pipeline, while two DLT
# tests watch what clients see (docs/02-experiment-protocol.md, section 9):
#
#   - a background load at half the operating rate;
#   - a probe whose per-request output is kept for a second-by-second timeline;
#   - a sampler that records which nodes and database instances exist, and their state.
#
#   scripts/change-stage.sh <target stage> <label> "<commit message>" [--pods-first]
#
# --pods-first applies the target's replica counts in a first pipeline run, before the
# node sizes change. It is needed when the target has less node capacity: pods evicted
# from a node being replaced must fit on the new, smaller nodes, or the node group
# update stalls on the pod disruption budget.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:?target stage}"
LABEL="${2:?label for the observation runs}"
MESSAGE="${3:?commit message}"
PODS_FIRST="${4:-}"
PROJECT="${PROJECT:-graviton-uplift}"
REGION="${AWS_REGION:-us-west-2}"
LOGS="${LOGS:-$ROOT/tmp}"
# Must cover the whole change: the tests run for this long and are not cut short.
# 3,600 seconds is the longest test Distributed Load Testing on AWS accepts.
OBSERVE_SECONDS="${OBSERVE_SECONDS:-3600}"
# Undisturbed traffic before the first push. Shorter when the change needs two pipeline
# runs, so that both fit into the observation.
LEAD_SECONDS="${LEAD_SECONDS:-180}"
FROM="$(cat "$ROOT/infra/config/ACTIVE_STAGE")"
RUNS="$ROOT/results/$FROM"

cd "$ROOT"
mkdir -p "$LOGS"
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

wait_for_pipeline() {
  local commit status
  commit="$(git rev-parse HEAD)"
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

# ---- 1. observers -----------------------------------------------------------------------
uv run -q tools/bench.py steady --name "$LABEL-load" --rate 4000 --tasks 14 --hold "$OBSERVE_SECONDS" \
  --no-reset --pause 0 > "$LOGS/$LABEL-load.log" 2>&1 &
load_pid=$!
uv run -q tools/bench.py probe --name "$LABEL-probe" --rate 100 --tasks 2 --seconds "$OBSERVE_SECONDS" \
  > "$LOGS/$LABEL-probe.log" 2>&1 &
probe_pid=$!
until grep -q ": running" "$LOGS/$LABEL-load.log" && grep -q ": running" "$LOGS/$LABEL-probe.log"; do
  kill -0 "$load_pid" "$probe_pid" 2>/dev/null || { echo "an observer exited early" >&2; exit 1; }
  sleep 10
done
# Which nodes and database instances exist, sampled every 10 seconds for the whole change.
uv run -q tools/inventory.py "$RUNS/$LABEL-inventory.jsonl" 10 > "$LOGS/$LABEL-inventory.log" 2>&1 &
inventory_pid=$!
echo "$(now) observers running; $LEAD_SECONDS seconds of undisturbed traffic first"
sleep "$LEAD_SECONDS"

# ---- 2. the change ----------------------------------------------------------------------
started="$(now)"
if [ "$PODS_FIRST" = "--pods-first" ]; then
  cp "infra/stages/$TARGET/values.yaml" deploy/values/active.yaml
  git add deploy/values/active.yaml
  git commit --quiet -m "Scale pods to the $TARGET replica counts before resizing nodes"
  scripts/push.sh >/dev/null 2>&1
  wait_for_pipeline
fi
scripts/set-stage.sh "$TARGET"
git add infra/config deploy/values/active.yaml
git commit --quiet -m "$MESSAGE"
scripts/push.sh >/dev/null 2>&1
wait_for_pipeline
# Kubernetes keeps events for an hour. Save them now, while those from the database
# failovers are still there: they say why a pod was reported not ready.
kubectl -n storefront get events -o json 2>/dev/null | jq -c '[.items[] | {at: (.lastTimestamp // .eventTime), type, reason,
  object: (.involvedObject.kind + "/" + .involvedObject.name), message, count}] | sort_by(.at)' \
  > "$RUNS/$LABEL-kubernetes-events.json" || true
echo "$(now) three minutes of traffic on the new configuration"
sleep 180
finished="$(now)"

# ---- 3. let the observers finish and collect --------------------------------------------
# The tests are not cancelled: a cancelled task has two minutes to reduce and upload its
# results, which is not enough for an hour of per-request output.
kill "$inventory_pid" 2>/dev/null || true
echo "$(now) waiting for the observation tests to end"
wait "$load_pid" || true
wait "$probe_pid" || true

uv run -q tools/change_events.py "$started" "$finished" "$RUNS/$LABEL-events.json" > "$LOGS/$LABEL-events.log"
probe_test="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['test_id'])" "$RUNS/$LABEL-probe/config.json")"
uv run -q tools/timeline.py "$probe_test" "$RUNS/$LABEL-probe/timeline.json"
uv run -q tools/bench.py delete-raw "$RUNS/$LABEL-probe" || true
echo "$(now) change $FROM -> $TARGET observed from $started to $finished"

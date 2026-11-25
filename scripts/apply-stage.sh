#!/usr/bin/env bash
# Moves the deployed stack to another configuration through the pipeline, without the
# observation tests that scripts/change-stage.sh runs. Used for the changes whose effect
# on clients is not part of the study (the return to the baseline at the end of a session).
#
#   scripts/apply-stage.sh <target stage> "<commit message>"
#
# Prints the period of the change as "applied from <start> to <end>".
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:?target stage}"
MESSAGE="${2:?commit message}"
PROJECT="${PROJECT:-graviton-uplift}"
REGION="${AWS_REGION:-us-west-2}"
FROM="$(cat "$ROOT/infra/config/ACTIVE_STAGE")"
cd "$ROOT"
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

started="$(now)"
scripts/set-stage.sh "$TARGET"
git add infra/config deploy/values/active.yaml
git commit --quiet -m "$MESSAGE"
scripts/push.sh >/dev/null 2>&1
commit="$(git rev-parse HEAD)"
echo "$(now) waiting for the pipeline to apply $commit"
while true; do
  status="$(aws codepipeline list-pipeline-executions --region "$REGION" --pipeline-name "$PROJECT" \
    --query "pipelineExecutionSummaries[?sourceRevisions[0].revisionId=='$commit'] | [0].status" --output text)"
  case "$status" in
    Succeeded) break ;;
    Failed|Stopped|Cancelled|Superseded) echo "$(now) pipeline $status" >&2; exit 1 ;;
  esac
  sleep 20
done
echo "$(now) change $FROM -> $TARGET applied from $started to $(now)"

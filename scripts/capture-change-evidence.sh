#!/usr/bin/env bash
# Records a configuration change after it has been applied: what was committed, what
# the pipeline did and when, and what CloudFormation and Amazon RDS reported.
#
#   scripts/capture-change-evidence.sh <commit before> <commit after> <start> <end> [directory name]
#
#   <start>, <end>   the period of the change in UTC, e.g. 2026-11-23T17:07:37Z
#
# Output goes to results/<active stage>/evidence/change/ (or the given name, for a
# configuration that is deployed a second time), one file per command: the
# command line, then its unedited output, with the AWS account ID replaced by <account-id>.
# All commands are read-only.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BEFORE="${1:?commit before the change}"
AFTER="${2:?commit after the change}"
START="${3:?start of the change, UTC}"
END="${4:?end of the change, UTC}"
PROJECT="${PROJECT:-graviton-uplift}"
export AWS_REGION="${AWS_REGION:-us-west-2}"
export AWS_PAGER=""
STAGE="$(cat "$ROOT/infra/config/ACTIVE_STAGE")"
OUT="$ROOT/results/$STAGE/evidence/${5:-change}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
CONFIG_PATHS="infra/config deploy/values/active.yaml"
mkdir -p "$OUT"
cd "$ROOT"

record() {
  local file="$OUT/$1.txt" command="$2"
  {
    echo "\$ $command"
    bash -c "$command" 2>&1
  } | sed "s/$ACCOUNT/<account-id>/g" > "$file"
  echo "wrote ${file#"$ROOT"/} ($(wc -l < "$file") lines)"
}

BEFORE="$(git rev-parse --short "$BEFORE")"
AFTER="$(git rev-parse --short "$AFTER")"

record commits \
  "git log --reverse --stat --format='commit %h  %cI%n    %s%n' $BEFORE..$AFTER -- $CONFIG_PATHS"

record diff "git diff $BEFORE $AFTER -- $CONFIG_PATHS"

# The same change without context lines: only what was removed and added.
record changed-lines "git diff -U0 $BEFORE $AFTER -- $CONFIG_PATHS | grep -E '^(diff|[-+][^-+])'"

# One pipeline execution per commit that changed the configuration.
index=0
for commit in $(git log --reverse --format=%H "$BEFORE..$AFTER" -- $CONFIG_PATHS); do
  index=$((index + 1))
  execution="$(aws codepipeline list-pipeline-executions --pipeline-name "$PROJECT" \
    --query "pipelineExecutionSummaries[?sourceRevisions[0].revisionId=='$commit'] | [0].pipelineExecutionId" --output text)"
  [ "$execution" = "None" ] && continue
  record "pipeline-$index" \
    "aws codepipeline list-action-executions --pipeline-name $PROJECT --filter pipelineExecutionId=$execution --query 'reverse(actionExecutionDetails)[].[stageName,actionName,status,startTime,lastUpdateTime]' --output text | sed -E 's/\.[0-9]+\+00:00//g' | column -t"
done

for stack in eks database; do
  record "stack-events-$stack" \
    "aws cloudformation describe-stack-events --stack-name $PROJECT-$stack --output json | jq -r '.StackEvents[] | select(.Timestamp >= \"$START\" and .Timestamp <= \"$END\") | [.Timestamp[0:19], .LogicalResourceId, .ResourceStatus] | @tsv' | sort | column -t"
done

# Timestamps are cut to the second and the instance names to their last part, to keep the
# lines short: graviton-uplift-database-instance1-abc becomes instance1-abc.
SHORTEN="sed -E 's/\.[0-9]+\+00:00//; s/$PROJECT-database-//g'"

record database-events \
  "aws rds describe-events --source-type db-instance --start-time $START --end-time $END --query 'Events[].[Date,SourceIdentifier,Message]' --output text | $SHORTEN"

record cluster-events \
  "aws rds describe-events --source-type db-cluster --start-time $START --end-time $END --query 'Events[].[Date,Message]' --output text | $SHORTEN"

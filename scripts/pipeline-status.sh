#!/usr/bin/env bash
# Prints the state of every action in the latest pipeline execution.
set -euo pipefail
PROJECT="${PROJECT:-graviton-uplift}"
REGION="${AWS_REGION:-us-west-2}"
aws codepipeline get-pipeline-state --region "$REGION" --name "$PROJECT" --output json |
  jq -r '.stageStates[] | .stageName as $s | .actionStates[] |
    [$s, .actionName, (.latestExecution.status // "-"), (.latestExecution.lastStatusChange // "-" | tostring | .[0:19]),
     ((.latestExecution.errorDetails.message // "") | .[0:160])] | @tsv' | column -t -s $'\t'

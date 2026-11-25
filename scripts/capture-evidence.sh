#!/usr/bin/env bash
# Records what is deployed, as the commands a reader could run and their unedited output.
#
#   scripts/capture-evidence.sh                 # the active stage, label "deployed"
#   scripts/capture-evidence.sh <label>         # another label, e.g. "before-change"
#
# Each command goes to its own file under results/<active stage>/evidence/<label>/, as
# the command line followed by what it printed, so that a listing shown anywhere is a
# recording, not a retyping.
#
# Every command is read-only. All but one talk to the Kubernetes or AWS control plane only,
# and none runs inside a pod or on a node under test. The exception is data-size, a query of
# information_schema on the database writer through the RDS Data API.
#
# The AWS account ID is replaced by <account-id> in the recorded output. Nothing else is
# changed.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${PROJECT:-graviton-uplift}"
export AWS_REGION="${AWS_REGION:-us-west-2}"
export AWS_PAGER=""
LABEL="${1:-deployed}"
STAGE="$(cat "$ROOT/infra/config/ACTIVE_STAGE")"
OUT="$ROOT/results/$STAGE/evidence/$LABEL"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
mkdir -p "$OUT"
cd "$ROOT"

# record <file> <command line>: runs the command line and stores it with its output.
record() {
  local file="$OUT/$1.txt" command="$2"
  {
    echo "\$ $command"
    bash -c "$command" 2>&1
  } | sed "s/$ACCOUNT/<account-id>/g" > "$file"
  echo "wrote ${file#"$ROOT"/} ($(wc -l < "$file") lines)"
}

date -u +%Y-%m-%dT%H:%M:%SZ > "$OUT/recorded-at.txt"

record nodes \
  "kubectl get nodes --sort-by=.metadata.labels.tier -o custom-columns='NODE:.metadata.name,TIER:.metadata.labels.tier,TYPE:.metadata.labels.node\.kubernetes\.io/instance-type,ZONE:.metadata.labels.topology\.kubernetes\.io/zone,VCPU:.status.capacity.cpu,KUBELET:.status.nodeInfo.kubeletVersion'"

record deployments \
  "kubectl -n storefront get deployments -o custom-columns='NAME:.metadata.name,READY:.status.readyReplicas,REPLICAS:.spec.replicas,CPU_REQUEST:.spec.template.spec.containers[0].resources.requests.cpu,CPU_LIMIT:.spec.template.spec.containers[0].resources.limits.cpu,MEMORY:.spec.template.spec.containers[0].resources.requests.memory'"

record images \
  "kubectl -n storefront get deployments -o custom-columns='NAME:.metadata.name,IMAGE:.spec.template.spec.containers[0].image'"

record pods-per-node \
  "kubectl -n storefront get pods -o custom-columns='NODE:.spec.nodeName' --no-headers | sort | uniq -c"

# Each pod with the number of times its container was restarted, and since when it runs.
record pods \
  "kubectl -n storefront get pods --sort-by=.metadata.name -o custom-columns='POD:.metadata.name,READY:.status.containerStatuses[0].ready,RESTARTS:.status.containerStatuses[0].restartCount,RUNNING_SINCE:.status.containerStatuses[0].state.running.startedAt,NODE:.spec.nodeName'"

record database \
  "aws rds describe-db-instances --filters Name=db-cluster-id,Values=$PROJECT --query 'DBInstances[].{Instance:DBInstanceIdentifier,Class:DBInstanceClass,Status:DBInstanceStatus,Zone:AvailabilityZone,Engine:EngineVersion}' --output table"

record database-roles \
  "aws rds describe-db-clusters --db-cluster-identifier $PROJECT --query 'DBClusters[0].DBClusterMembers[].{Instance:DBInstanceIdentifier,Writer:IsClusterWriter}' --output table"

record instance-types \
  "aws ec2 describe-instances --filters Name=tag:eks:cluster-name,Values=$PROJECT Name=instance-state-name,Values=running --query 'Reservations[].Instances[].{Type:InstanceType,Zone:Placement.AvailabilityZone,Architecture:Architecture,NodeGroup:Tags[?Key==\`eks:nodegroup-name\`]|[0].Value}' --output table"

# Table sizes as MySQL estimates them (information_schema), through the RDS Data API.
record data-size \
  "uv run -q tools/bench.py sql \"SELECT table_name, table_rows, ROUND((data_length + index_length) / 1e9, 2) AS gb FROM information_schema.tables WHERE table_schema = DATABASE() ORDER BY (data_length + index_length) DESC\" | jq -r '.[] | [.TABLE_NAME, .TABLE_ROWS, .gb] | @tsv' | column -t"

record stacks \
  "aws cloudformation describe-stacks --query 'Stacks[?starts_with(StackName,\`$PROJECT\`)].{Stack:StackName,Status:StackStatus,LastUpdated:LastUpdatedTime}' --output table"

record pipeline "scripts/pipeline-status.sh"

record pipeline-commit \
  "aws codepipeline list-pipeline-executions --pipeline-name $PROJECT --query 'pipelineExecutionSummaries[0].{Status:status,Started:startTime,Commit:sourceRevisions[0].revisionId,Message:sourceRevisions[0].revisionSummary}' --output json"

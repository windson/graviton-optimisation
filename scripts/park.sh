#!/usr/bin/env bash
# Stops what the study pays for by the hour without deleting anything: the node groups go
# to zero nodes and the Aurora cluster is stopped. scripts/unpark.sh brings both back.
#
#   scripts/park.sh
#
# What stays and keeps costing: the EKS control plane, the NAT gateway, the load balancer,
# the Aurora volume, the container images and the pipeline. An Aurora cluster that is
# stopped starts again by itself after seven days.
#
# The sizes found are written to results/evidence/parked.json, which unpark.sh reads.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${PROJECT:-graviton-uplift}"
export AWS_REGION="${AWS_REGION:-us-west-2}"
export AWS_PAGER=""
STATE="$ROOT/results/evidence/parked.json"
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

groups="$(aws eks list-nodegroups --cluster-name "$PROJECT" --query nodegroups --output json)"
sizes="$(for group in $(jq -r '.[]' <<< "$groups"); do
  aws eks describe-nodegroup --cluster-name "$PROJECT" --nodegroup-name "$group" \
    --query 'nodegroup.{name:nodegroupName,scaling:scalingConfig}' --output json
done | jq -s .)"
if jq -e 'all(.[]; .scaling.desiredSize == 0)' <<< "$sizes" > /dev/null && [ -f "$STATE" ]; then
  echo "$(now) node groups are already at zero; keeping the sizes recorded in ${STATE#"$ROOT"/}"
else
  mkdir -p "$(dirname "$STATE")"
  jq -n --arg at "$(now)" --arg stage "$(cat "$ROOT/infra/config/ACTIVE_STAGE")" --argjson groups "$sizes" \
    '{parked_at: $at, active_stage: $stage, node_groups: $groups}' > "$STATE"
  echo "$(now) recorded the node group sizes in ${STATE#"$ROOT"/}"
fi

for group in $(jq -r '.[]' <<< "$groups"); do
  max="$(jq -r --arg g "$group" '.[] | select(.name == $g) | .scaling.maxSize' <<< "$sizes")"
  aws eks update-nodegroup-config --cluster-name "$PROJECT" --nodegroup-name "$group" \
    --scaling-config "minSize=0,maxSize=$max,desiredSize=0" --query 'update.status' --output text > /dev/null
  echo "$(now) node group $group: scaling to 0 nodes"
done

status="$(aws rds describe-db-clusters --db-cluster-identifier "$PROJECT" --query 'DBClusters[0].Status' --output text)"
if [ "$status" = "available" ]; then
  aws rds stop-db-cluster --db-cluster-identifier "$PROJECT" --query 'DBCluster.Status' --output text > /dev/null
  echo "$(now) Aurora cluster $PROJECT: stopping"
else
  echo "$(now) Aurora cluster $PROJECT is $status; not stopping it"
fi

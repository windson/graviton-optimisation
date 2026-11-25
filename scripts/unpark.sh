#!/usr/bin/env bash
# Brings back what scripts/park.sh stopped: starts the Aurora cluster and restores the node
# groups to the sizes recorded in results/evidence/parked.json.
#
#   scripts/unpark.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${PROJECT:-graviton-uplift}"
export AWS_REGION="${AWS_REGION:-us-west-2}"
export AWS_PAGER=""
STATE="$ROOT/results/evidence/parked.json"
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
[ -f "$STATE" ] || { echo "no ${STATE#"$ROOT"/}: nothing was parked by scripts/park.sh" >&2; exit 1; }

status="$(aws rds describe-db-clusters --db-cluster-identifier "$PROJECT" --query 'DBClusters[0].Status' --output text)"
if [ "$status" = "stopped" ]; then
  aws rds start-db-cluster --db-cluster-identifier "$PROJECT" --query 'DBCluster.Status' --output text > /dev/null
  echo "$(now) Aurora cluster $PROJECT: starting"
fi
jq -c '.node_groups[]' "$STATE" | while read -r group; do
  name="$(jq -r .name <<< "$group")"
  aws eks update-nodegroup-config --cluster-name "$PROJECT" --nodegroup-name "$name" \
    --scaling-config "$(jq -r '.scaling | "minSize=\(.minSize),maxSize=\(.maxSize),desiredSize=\(.desiredSize)"' <<< "$group")" \
    --query 'update.status' --output text > /dev/null
  echo "$(now) node group $name: back to $(jq -r .scaling.desiredSize <<< "$group") nodes"
done
echo "$(now) wait for the cluster to be available and the pods to be ready before measuring:"
echo "  aws rds wait db-cluster-available --db-cluster-identifier $PROJECT"
echo "  kubectl -n storefront wait --for=condition=Ready pods --all --timeout=900s"

#!/usr/bin/env bash
# Puts the Aurora writer in the Availability Zone that holds the wanted number of API
# nodes, by failing the writer over to the other instance if it is not there already.
#
#   scripts/align-writer-zone.sh 1      # one API node in the writer's zone
#
# Why: every API request makes two to three round trips to the writer, and a round trip
# within a zone is shorter than one between zones. Amazon EKS spreads three API nodes
# over two zones as 1 + 2, and which zone holds the writer is left to chance after a
# change. The baseline was measured with one of its three API nodes in the writer's
# zone; this script gives the configurations measured after it the same placement, so
# that response times are not compared across different placements.
#
# Prints what it found and did. Exits 1 if the wanted placement cannot be reached.
set -euo pipefail

WANT="${1:?number of API nodes that should be in the zone of the writer}"
PROJECT="${PROJECT:-graviton-uplift}"
export AWS_REGION="${AWS_REGION:-us-west-2}"
export AWS_PAGER=""
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

member() {  # member true|false: identifier of the writer (true) or the reader (false)
  aws rds describe-db-clusters --db-cluster-identifier "$PROJECT" \
    --query "DBClusters[0].DBClusterMembers[?IsClusterWriter==\`$1\`] | [0].DBInstanceIdentifier" --output text
}
zone_of() {
  aws rds describe-db-instances --db-instance-identifier "$1" --query 'DBInstances[0].AvailabilityZone' --output text
}
api_nodes_in() {
  kubectl get nodes -l tier=api -o json |
    jq --arg zone "$1" '[.items[] | select(.metadata.labels["topology.kubernetes.io/zone"] == $zone)] | length'
}

writer="$(member true)"
zone="$(zone_of "$writer")"
have="$(api_nodes_in "$zone")"
echo "$(now) writer $writer is in $zone, with $have API node(s) in that zone; wanted: $WANT"
if [ "$have" -eq "$WANT" ]; then
  echo "$(now) placement is as wanted; no failover"
  exit 0
fi

reader="$(member false)"
other="$(zone_of "$reader")"
if [ "$(api_nodes_in "$other")" -ne "$WANT" ]; then
  echo "$(now) neither zone holds $WANT API node(s); not failing over" >&2
  exit 1
fi

echo "$(now) failing over to $reader in $other"
aws rds failover-db-cluster --db-cluster-identifier "$PROJECT" --target-db-instance-identifier "$reader" > /dev/null
until [ "$(member true)" = "$reader" ]; do sleep 5; done
aws rds wait db-instance-available --db-instance-identifier "$writer"
aws rds wait db-instance-available --db-instance-identifier "$reader"
# The API pods reconnect on their own; give them time and make sure all are ready again.
sleep 60
kubectl -n storefront wait --for=condition=Ready pods -l app=storefront-api --timeout=300s > /dev/null
echo "$(now) writer $reader is in $other, with $(api_nodes_in "$other") API node(s) in that zone"

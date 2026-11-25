#!/usr/bin/env bash
# Records the software and hardware the deployed configuration is running on:
# processor model as the pods see it, JVM and Node.js versions and ergonomics, node
# operating system, Kubernetes and add-on versions, image digests.
#
#   scripts/snapshot-environment.sh              # writes results/<active stage>/environment.json
#   scripts/snapshot-environment.sh again        # writes environment-again.json: a configuration deployed a second time
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${PROJECT:-graviton-uplift}"
REGION="${AWS_REGION:-us-west-2}"
STAGE="$(cat "$ROOT/infra/config/ACTIVE_STAGE")"
OUT="$ROOT/results/$STAGE/environment${1:+-$1}.json"
mkdir -p "$(dirname "$OUT")"
k() { kubectl --namespace storefront "$@"; }

api="pod/$(k get pods -l app=storefront-api -o jsonpath='{.items[0].metadata.name}')"
web="pod/$(k get pods -l app=storefront-web -o jsonpath='{.items[0].metadata.name}')"

java_version="$(k exec "$api" -- java -version 2>&1 | grep -v 'Picked up' | sed -n 2p)"
jvm_flags="$(k exec "$api" -- java -XX:+PrintFlagsFinal -version 2>/dev/null |
  awk '$1 ~ /^(u?intx?|bool|size_t|uint64_t|ccstr)$/ && $2 ~ /^(UseG1GC|MaxHeapSize|ParallelGCThreads|ConcGCThreads|CICompilerCount|UseLSE|UseAES|UseSVE|UseCRC32Intrinsics|TieredCompilation|ReservedCodeCacheSize)$/ {printf "%s%s=%s", sep, $2, $4; sep=","}')"
api_cpu="$(k exec "$api" -- sh -c "grep -m1 -E 'CPU part|model name' /proc/cpuinfo; grep -m1 Features /proc/cpuinfo" | tr '\n\t' '; ')"
node_info="$(k exec "$web" -- node -p 'JSON.stringify({node: process.version, arch: process.arch, cpuModel: require("os").cpus()[0].model, cpus: require("os").cpus().length, react: require("react/package.json").version, fastify: require("fastify/package.json").version})')"

jq -n \
  --arg stage "$STAGE" \
  --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg java "$java_version" --arg jvm "$jvm_flags" --arg api_cpu "$api_cpu" \
  --argjson web "$node_info" \
  --argjson nodes "$(kubectl get nodes -o json | jq '[.items[] | {tier: .metadata.labels.tier, type: .metadata.labels["node.kubernetes.io/instance-type"], zone: .metadata.labels["topology.kubernetes.io/zone"], kubelet: .status.nodeInfo.kubeletVersion, runtime: .status.nodeInfo.containerRuntimeVersion, os: .status.nodeInfo.osImage, kernel: .status.nodeInfo.kernelVersion, allocatable_cpu: .status.allocatable.cpu}] | sort_by(.tier)')" \
  --argjson images "$(k get pods -o json | jq '[.items[] | .status.containerStatuses[]? | {image, imageID}] | unique')" \
  --argjson addons "$(for a in $(aws eks list-addons --region "$REGION" --cluster-name "$PROJECT" --query addons --output text); do aws eks describe-addon --region "$REGION" --cluster-name "$PROJECT" --addon-name "$a" --query 'addon.{name:addonName,version:addonVersion}' --output json; done | jq -s .)" \
  --arg lbc "$(kubectl -n kube-system get deploy aws-load-balancer-controller -o jsonpath='{.spec.template.spec.containers[0].image}')" \
  --argjson database "$(aws rds describe-db-clusters --region "$REGION" --db-cluster-identifier "$PROJECT" --query 'DBClusters[0].{engine:Engine,version:EngineVersion,storage:StorageType,members:DBClusterMembers[].{id:DBInstanceIdentifier,writer:IsClusterWriter}}' --output json)" \
  '{stage: $stage, at: $at, api: {java: $java, jvm_flags: $jvm, cpu: $api_cpu}, web: $web, nodes: $nodes,
    images: $images, addons: $addons, load_balancer_controller: $lbc, database: $database}' > "$OUT"
echo "wrote ${OUT#"$ROOT"/}"

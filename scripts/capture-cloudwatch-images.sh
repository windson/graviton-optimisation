#!/usr/bin/env bash
# Asks Amazon CloudWatch to render graphs of one period of the study (GetMetricWidgetImage)
# and stores them with the request that produced each one. The images are drawn by AWS
# from its own metrics, not by this repository's charting code.
#
#   scripts/capture-cloudwatch-images.sh <period name> <start> <end> [label=time ...]
#   scripts/capture-cloudwatch-images.sh session1 2026-11-23T15:15:00Z 2026-11-23T23:05:00Z \
#       "B: upgrade=2026-11-23T17:07:52Z" "C: right-sizing=2026-11-23T20:08:56Z"
#
# Each label=time pair becomes a vertical line on the graphs.
# Output: results/evidence/cloudwatch/<period name>-<graph>.png, .json (the widget
# definition) and .txt (the command), and <period name>.period.txt with the arguments. The
# account ID does not appear in any of them.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="${1:?period name}"
START="${2:?start, UTC}"
END="${3:?end, UTC}"
ARGUMENTS=("$@")
shift 3
PROJECT="${PROJECT:-graviton-uplift}"
export AWS_REGION="${AWS_REGION:-us-west-2}"
export AWS_PAGER=""
OUT="$ROOT/results/evidence/cloudwatch"
mkdir -p "$OUT"
cd "$ROOT"
# Kept so that scripts/build-report.sh can render the same period again.
printf '"%s"\n' "${ARGUMENTS[@]}" > "$OUT/$NAME.period.txt"

ANNOTATIONS="$(printf '%s\n' "$@" | jq -R 'select(length > 0) | split("=") | {label: .[0], value: .[1]}' | jq -s '{vertical: .}')"
INSTANCES="$(aws rds describe-db-clusters --db-cluster-identifier "$PROJECT" \
  --query 'DBClusters[0].DBClusterMembers[].DBInstanceIdentifier' --output json)"
LOAD_BALANCER="$(aws elbv2 describe-load-balancers --query "LoadBalancers[?starts_with(LoadBalancerName, \`$PROJECT\`)] | [0].LoadBalancerArn" \
  --output text | sed 's#.*:loadbalancer/##')"

render() {
  local name="$NAME-$1" widget="$2"
  echo "$widget" | jq . > "$OUT/$name.json"
  aws cloudwatch get-metric-widget-image --metric-widget "file://$OUT/$name.json" --output-format png \
    --query MetricWidgetImage --output text | base64 -d > "$OUT/$name.png"
  echo "\$ aws cloudwatch get-metric-widget-image --metric-widget file://results/evidence/cloudwatch/$name.json --output-format png --query MetricWidgetImage --output text | base64 -d > results/evidence/cloudwatch/$name.png" > "$OUT/$name.txt"
  echo "wrote results/evidence/cloudwatch/$name.png ($(wc -c < "$OUT/$name.png") bytes)"
}

common() {
  jq -n --arg start "$START" --arg end "$END" --arg title "$1" --argjson annotations "$ANNOTATIONS" \
    '{view: "timeSeries", stacked: false, width: 1520, height: 480, start: $start, end: $end, period: 60,
      timezone: "+0000", title: $title, annotations: $annotations}'
}

# ---- Aurora: CPU of both instances -------------------------------------------------------------
render database-cpu "$(common "Aurora MySQL: CPU utilization of both instances, percent of their vCPUs (UTC)" | jq --argjson ids "$INSTANCES" \
  '. + {stat: "Average", yAxis: {left: {min: 0, max: 100, label: "CPU utilization, percent", showUnits: false}},
        metrics: [$ids | sort[] | ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", ., {label: ("instance " + capture("instance(?<n>[0-9]+)").n)}]]}')"

# ---- Load balancer: requests per second and failed responses -------------------------------------
render load-balancer-requests "$(common "Application Load Balancer: requests per second (UTC)" | jq --arg lb "$LOAD_BALANCER" \
  '. + {stat: "Sum", yAxis: {left: {min: 0, label: "requests per second", showUnits: false}},
        metrics: [["AWS/ApplicationELB", "RequestCount", "LoadBalancer", $lb, {id: "m1", visible: false}],
                  [{expression: "m1/60", label: "requests per second", id: "e1"}]]}')"

render load-balancer-errors "$(common "Application Load Balancer: 5xx responses per minute (UTC)" | jq --arg lb "$LOAD_BALANCER" \
  '. + {stat: "Sum", yAxis: {left: {min: 0, label: "5xx responses per minute", showUnits: false}},
        metrics: [["AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count", "LoadBalancer", $lb, {label: "from the load balancer"}],
                  ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", $lb, {label: "from the targets"}]]}')"

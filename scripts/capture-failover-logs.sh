#!/usr/bin/env bash
# Records what the API pods logged around each database failover of a configuration
# change, and the Kubernetes events of the namespace if they are still retained.
#
#   scripts/capture-failover-logs.sh <stage the change started from> <label>
#   scripts/capture-failover-logs.sh a-graviton2-baseline ab
#
# The failover times come from results/<stage>/<label>-events.json. For each failover
# and each API pod that exists now, the log from 20 seconds before the failover started
# to 70 seconds after is reduced to one line per second and kind of message, with a
# count: stack traces are dropped, and numbers and object IDs in messages are replaced
# by "#". The result goes to results/<stage>/<label>-api-logs/. Read-only; run it while
# no benchmark is running, because it reads log files on the API nodes.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE="${1:?stage}"
LABEL="${2:?label}"
OUT="$ROOT/results/$STAGE/$LABEL-api-logs"
mkdir -p "$OUT"
cd "$ROOT"

kubectl -n storefront get events -o json | jq -c '[.items[] | {at: (.lastTimestamp // .eventTime), type, reason,
  object: (.involvedObject.kind + "/" + .involvedObject.name), message, count}] | sort_by(.at)' > "$OUT/kubernetes-events.json"
echo "wrote ${OUT#"$ROOT"/}/kubernetes-events.json ($(jq length "$OUT/kubernetes-events.json") events still retained)"

number=0
for started in $(jq -r '.events[] | select(.source == "rds" and (.event | startswith("Started cross AZ failover"))) | .at' \
    "results/$STAGE/$LABEL-events.json"); do
  number=$((number + 1))
  from="$(date -u -d "$started - 20 seconds" +%Y-%m-%dT%H:%M:%SZ)"
  to="$(date -u -d "$started + 70 seconds" +%Y-%m-%dT%H:%M:%SZ)"
  for pod in $(kubectl -n storefront get pods -l app=storefront-api -o jsonpath='{.items[*].metadata.name}'); do
    file="$OUT/failover-$number-$pod.log"
    {
      echo "\$ kubectl -n storefront logs $pod --timestamps --since-time=$from   # up to $to, counted per second and kind of message"
      kubectl -n storefront logs "$pod" --timestamps --since-time="$from" 2>&1 |
        awk -v end="$to" '{ if (substr($1, 1, 20) > end) exit; print }' | python3 -c '
import collections, re, sys
counts = collections.OrderedDict()
for line in sys.stdin:
    match = re.match(r"(\S+) \S+\s+(TRACE|DEBUG|INFO|WARN|ERROR)\s+\S+ --- (?:\[[^\]]*\]\s*)*(\S+)\s*: (.*)", line)
    if not match:
        continue  # a stack trace line, or a blank one
    stamp, level, logger, message = match.groups()
    message = re.sub(r"@[0-9a-f]+|\b\d+\b", "#", message)[:150]
    key = (stamp[11:19], level, logger.rsplit(".", 1)[-1], message)
    counts[key] = counts.get(key, 0) + 1
for (second, level, logger, message), count in counts.items():
    print(f"{second} {level:5s} {count:5d} x  {logger}: {message}")
'
    } > "$file"
    echo "wrote ${file#"$ROOT"/} ($(($(wc -l < "$file") - 1)) lines)"
  done
done

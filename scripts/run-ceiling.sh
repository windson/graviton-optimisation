#!/usr/bin/env bash
# Ceiling run of the deployed configuration (docs/02-experiment-protocol.md, section 12):
# one steady run at the rate at which the capacity run put the busiest tier at 80% CPU.
#
#   scripts/run-ceiling.sh c            # estimate from c-cap, run c-ceiling
#   scripts/run-ceiling.sh a2 a         # configuration deployed again: estimate from a-cap, run a2-ceiling
#
# If the busiest tier of the ceiling run is outside 75% to 85%, the run is repeated once
# at the corrected rate as <prefix>-ceiling2.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${1:?usage: run-ceiling.sh <run prefix> [prefix of the capacity run to estimate from]}"
FROM="${2:-$PREFIX}"
STAGE="$(cat "$ROOT/infra/config/ACTIVE_STAGE")"
cd "$ROOT"

# The capacity run was summarized before this configuration had steady runs. Summarize it
# again, so that its database CPU uses the metric offset measured in those runs.
uv run -q analysis/summarize.py "results/$STAGE/$FROM-cap" > /dev/null
uv run -q analysis/ceiling.py estimate "$FROM"
read -r RATE TASKS < <(uv run -q analysis/ceiling.py estimate "$FROM" --plain)

NAME="$PREFIX-ceiling"
for attempt in 1 2; do
  uv run -q tools/bench.py steady --name "$NAME" --rate "$RATE" --tasks "$TASKS"
  uv run -q analysis/summarize.py "results/$STAGE/$NAME"
  set +e
  CORRECTED="$(uv run -q analysis/ceiling.py check "$PREFIX")"
  code=$?
  set -e
  [ "$code" -eq 0 ] && break
  [ "$code" -eq 3 ] || exit "$code"
  [ "$attempt" -eq 2 ] && { echo "the repeat is still outside 75% to 85%; using it as measured" >&2; break; }
  read -r RATE TASKS <<< "$CORRECTED"
  NAME="$PREFIX-ceiling2"
  echo "busiest tier outside 75% to 85%: repeating at $RATE req/s with $TASKS tasks"
done

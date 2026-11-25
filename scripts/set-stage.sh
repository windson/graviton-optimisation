#!/usr/bin/env bash
# Makes one of the study's configurations the active one.
#
#   scripts/set-stage.sh b-graviton5-same-size
#
# It copies the configuration's parameter files to the paths the pipeline reads. Commit
# and push the result; the pipeline then applies it: CloudFormation changes the node
# groups and the Aurora instance class, and Helm sets the replica counts.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE="${1:?usage: set-stage.sh <stage>   (one of: $(ls "$ROOT/infra/stages" | tr '\n' ' '))}"
SRC="$ROOT/infra/stages/$STAGE"
[ -d "$SRC" ] || { echo "unknown stage: $STAGE" >&2; exit 1; }

cp "$SRC/eks.json" "$ROOT/infra/config/eks.json"
cp "$SRC/database.json" "$ROOT/infra/config/database.json"
cp "$SRC/values.yaml" "$ROOT/deploy/values/active.yaml"
echo "$STAGE" > "$ROOT/infra/config/ACTIVE_STAGE"
echo "active stage: $STAGE"

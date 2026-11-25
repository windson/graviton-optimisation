#!/usr/bin/env bash
# One-time setup: creates the repository, registries and pipeline, then pushes this
# repository to it. Everything else (network, cluster, database, application) is created
# by the pipeline from that push.
#
#   scripts/set-admin-role.sh                  # once: the role that may administer the cluster
#   AWS_PROFILE=my-profile scripts/bootstrap.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${PROJECT:-graviton-uplift}"
REGION="${AWS_REGION:-us-west-2}"

# The pipeline deploys what is committed, so the committed parameter file is the one that counts.
if git -C "$ROOT" show HEAD:infra/config/eks.json | grep -q REPLACE_WITH_YOUR_ADMIN_ROLE; then
  echo "the committed infra/config/eks.json has the placeholder administrator role: run scripts/set-admin-role.sh first" >&2
  exit 1
fi

aws cloudformation deploy \
  --region "$REGION" \
  --stack-name "$PROJECT-cicd" \
  --template-file "$ROOT/infra/cfn/cicd.yaml" \
  --parameter-overrides "ProjectName=$PROJECT" \
  --capabilities CAPABILITY_IAM \
  --tags "Project=$PROJECT" \
  --no-fail-on-empty-changeset

"$ROOT/scripts/push.sh"

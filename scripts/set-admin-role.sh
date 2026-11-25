#!/usr/bin/env bash
# Writes the IAM role that gets administrator access to the EKS cluster into the parameter
# files of every configuration. The repository ships a placeholder: the role is yours.
#
#   scripts/set-admin-role.sh                       # the role of the credentials in use
#   scripts/set-admin-role.sh arn:aws:iam::<account>:role/<name>
#
# Run it once, before scripts/bootstrap.sh. kubectl then works for whoever assumes that role.
# The change is committed, because the pipeline deploys what is committed. The ARN contains
# your account ID: keep that clone private, or put the placeholder back before publishing it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROLE="${1:-}"
if [ -z "$ROLE" ]; then
  # The role behind the caller: arn:aws:sts::<account>:assumed-role/<name>/<session> -> role ARN.
  caller="$(aws sts get-caller-identity --query Arn --output text)"
  case "$caller" in
    *:assumed-role/*)
      account="$(cut -d: -f5 <<< "$caller")"
      name="$(cut -d/ -f2 <<< "$caller")"
      ROLE="$(aws iam get-role --role-name "$name" --query Role.Arn --output text 2>/dev/null || echo "arn:aws:iam::$account:role/$name")" ;;
    *) echo "the credentials in use are not a role ($caller); pass a role ARN" >&2; exit 1 ;;
  esac
fi
[[ "$ROLE" =~ ^arn:aws[a-z-]*:iam::[0-9]{12}:role/.+$ ]] || { echo "not an IAM role ARN: $ROLE" >&2; exit 1; }

for file in "$ROOT/infra/config/eks.json" "$ROOT"/infra/stages/*/eks.json; do
  tmp="$(mktemp)"
  jq --arg role "$ROLE" '.Parameters.AdminRoleArn = $role' "$file" > "$tmp"
  mv "$tmp" "$file"
  echo "set AdminRoleArn in ${file#"$ROOT"/}"
done

cd "$ROOT"
if git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
  if git diff --quiet HEAD -- infra/config/eks.json infra/stages; then
    echo "nothing to commit: the role was already set"
  else
    git commit --quiet -m "Set the cluster administrator role" -- infra/config/eks.json infra/stages/*/eks.json
    echo "committed as $(git rev-parse --short HEAD)"
  fi
fi

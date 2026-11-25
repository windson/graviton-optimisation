#!/usr/bin/env bash
# Pushes the current branch to the study's CodeCommit repository, which starts the
# pipeline. The AWS CLI credential helper is passed on the command line, so no git
# configuration is changed.
set -euo pipefail

PROJECT="${PROJECT:-graviton-uplift}"
REGION="${AWS_REGION:-us-west-2}"
BRANCH="${BRANCH:-main}"

git \
  -c credential.helper='!aws codecommit credential-helper $@' \
  -c credential.UseHttpPath=true \
  push "https://git-codecommit.$REGION.amazonaws.com/v1/repos/$PROJECT" "HEAD:refs/heads/$BRANCH"

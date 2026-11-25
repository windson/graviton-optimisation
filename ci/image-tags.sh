#!/usr/bin/env bash
# Image tags are a hash of each application's source tree, not of the commit. A commit
# that only changes infrastructure parameters therefore reuses the existing images, and
# every configuration of the study runs exactly the same image digests.
#
# Source this file; it sets API_IMAGE_TAG and WEB_IMAGE_TAG.
_tree_hash() {
  (cd "$1" && find . -type f -not -path './target/*' -not -path './node_modules/*' -not -path './dist/*' -print0 |
    LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -c1-16)
}

_ci_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_IMAGE_TAG="src-$(_tree_hash "$_ci_root/app/api")"
WEB_IMAGE_TAG="src-$(_tree_hash "$_ci_root/app/web")"
export API_IMAGE_TAG WEB_IMAGE_TAG

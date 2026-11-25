#!/usr/bin/env bash
# Tests and builds both application tiers, pushes arm64 images tagged with a hash of their
# source, and assembles the Helm chart artifact that the pipeline's deploy action releases.
set -euo pipefail

: "${API_REPOSITORY_URI:?}" "${WEB_REPOSITORY_URI:?}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MYSQL_IMAGE="public.ecr.aws/docker/library/mysql:8.0"
# shellcheck source=ci/image-tags.sh
source "$ROOT/ci/image-tags.sh"

# Tags are immutable. If this source was already built, the existing image is reused.
image_exists() {
  aws ecr describe-images --repository-name "${1#*/}" --image-ids "imageTag=$2" >/dev/null 2>&1
}

build_api() {
  # The API's integration tests run against a real MySQL 8.0 server, the engine version
  # Aurora MySQL 3 is compatible with.
  docker run --detach --rm --name it-mysql --publish 3306:3306 \
    --env MYSQL_ROOT_PASSWORD=integration --env MYSQL_DATABASE=storefront "$MYSQL_IMAGE" >/dev/null
  trap 'docker stop it-mysql >/dev/null 2>&1 || true' RETURN
  for _ in $(seq 1 60); do
    if docker exec it-mysql mysqladmin ping --host 127.0.0.1 --user root --password=integration --silent 2>/dev/null; then
      break
    fi
    sleep 2
  done

  (
    cd "$ROOT/app/api"
    IT_DB_HOST=127.0.0.1 DB_HOST=127.0.0.1 DB_USERNAME=root DB_PASSWORD=integration DB_SSL_MODE=PREFERRED \
      mvn --batch-mode --no-transfer-progress package
    docker build --tag "$API_REPOSITORY_URI:$API_IMAGE_TAG" .
  )
  docker push "$API_REPOSITORY_URI:$API_IMAGE_TAG"
}

build_web() {
  # The Dockerfile's build stage runs npm ci, the bundler and the tests.
  docker build --tag "$WEB_REPOSITORY_URI:$WEB_IMAGE_TAG" "$ROOT/app/web"
  docker push "$WEB_REPOSITORY_URI:$WEB_IMAGE_TAG"
}

if image_exists "$API_REPOSITORY_URI" "$API_IMAGE_TAG"; then
  echo "api image $API_IMAGE_TAG already exists, not rebuilding"
else
  build_api
fi
if image_exists "$WEB_REPOSITORY_URI" "$WEB_IMAGE_TAG"; then
  echo "web image $WEB_IMAGE_TAG already exists, not rebuilding"
else
  build_web
fi

# ---- chart artifact ---------------------------------------------------------------------
OUT="$ROOT/build-output"
rm -rf "$OUT"
mkdir -p "$OUT"
cp -R "$ROOT/deploy/chart/storefront" "$OUT/chart"
cp "$ROOT/deploy/values/active.yaml" "$OUT/chart/values-stage.yaml"
cat > "$OUT/chart/values-image.yaml" <<VALUES
image:
  apiRepository: $API_REPOSITORY_URI
  apiTag: "$API_IMAGE_TAG"
  webRepository: $WEB_REPOSITORY_URI
  webTag: "$WEB_IMAGE_TAG"
VALUES

helm lint "$OUT/chart" --values "$OUT/chart/values-stage.yaml" --values "$OUT/chart/values-image.yaml"
echo "stage: $(cat "$ROOT/infra/config/ACTIVE_STAGE")"

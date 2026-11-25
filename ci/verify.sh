#!/usr/bin/env bash
# Waits for the release to roll out, loads the data set if this is a new database, and
# smoke tests every page and endpoint through the load balancer.
set -euo pipefail

: "${PROJECT_NAME:?}" "${AWS_REGION:?}" "${API_REPOSITORY_URI:?}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=ci/image-tags.sh
source "$ROOT/ci/image-tags.sh"
NAMESPACE="storefront"
SEED_VERSION="${SEED_VERSION:-v1}"

aws eks update-kubeconfig --name "$PROJECT_NAME" --region "$AWS_REGION" >/dev/null
k() { kubectl --namespace "$NAMESPACE" "$@"; }

k rollout status deployment/storefront-api --timeout=20m
k rollout status deployment/storefront-web --timeout=20m

# ---- data set ---------------------------------------------------------------------------
job="storefront-seed-$SEED_VERSION"
if ! k get job "$job" >/dev/null 2>&1; then
  sed -e "s|__IMAGE__|$API_REPOSITORY_URI:$API_IMAGE_TAG|" -e "s|__VERSION__|$SEED_VERSION|g" \
    "$ROOT/deploy/seed-job.yaml" | kubectl apply --filename -
fi
for _ in $(seq 1 270); do
  succeeded="$(k get job "$job" --output jsonpath='{.status.succeeded}')"
  failed="$(k get job "$job" --output jsonpath='{.status.failed}')"
  if [ "${succeeded:-0}" -ge 1 ]; then break; fi
  if [ "${failed:-0}" -ge 2 ]; then k logs "job/$job" --tail 50 || true; echo "seed job failed" >&2; exit 1; fi
  sleep 10
done
[ "${succeeded:-0}" -ge 1 ] || { echo "seed job did not finish in time" >&2; exit 1; }
k logs "job/$job" --tail 20 | grep -E "SeedRunner" || true

# ---- smoke test -------------------------------------------------------------------------
host=""
for _ in $(seq 1 60); do
  host="$(k get ingress storefront --output jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)"
  [ -n "$host" ] && curl --silent --fail --output /dev/null --max-time 5 "http://$host/healthz" && break
  sleep 10
done
[ -n "$host" ] || { echo "the ingress has no load balancer address" >&2; exit 1; }
echo "endpoint: http://$host"

# check <path> <text the body must contain>
check() {
  local body
  body="$(curl --silent --show-error --fail --compressed --max-time 15 "http://$host$1")"
  grep --quiet --fixed-strings -- "$2" <<<"$body" || { echo "FAIL $1: body does not contain '$2'" >&2; exit 1; }
  echo "ok   $1"
}
# Categories are cached for a minute; wait for pods that started before the data was loaded.
for _ in $(seq 1 15); do
  curl --silent --fail --output /dev/null --max-time 10 "http://$host/api/catalog?category=1" && break
  sleep 10
done

check "/" "New arrivals"
check "/c/1" 'class="card"'
check "/c/1?sort=price&page=2" 'class="card"'
check "/p/1" "Latest reviews"
check "/search?q=Compact" "Results for"
check "/api/meta" '"products":'
check "/api/categories" '"productCount":'
check "/api/home" '"newArrivals":'
check "/api/catalog?category=1" '"priceBands":'
check "/api/products/1" '"alsoBought":'
check "/api/search?q=Compact%20Oak" '"items":'
check "/api/customers/1/orders" '"lines":'
check "/api/cart/1" '"subtotal":'

status="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 15 --request PUT \
  --header 'content-type: application/json' --data '{"qty":2}' "http://$host/api/cart/1/items/7")"
[ "$status" = 200 ] || { echo "FAIL PUT /api/cart: $status" >&2; exit 1; }
echo "ok   PUT /api/cart/1/items/7"
status="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 15 --request POST \
  --header 'content-type: application/json' \
  --data '{"customerId":1,"items":[{"productId":7,"qty":1},{"productId":9,"qty":2}]}' "http://$host/api/orders")"
[ "$status" = 201 ] || { echo "FAIL POST /api/orders: $status" >&2; exit 1; }
echo "ok   POST /api/orders"

kubectl get nodes --label-columns tier,node.kubernetes.io/instance-type --no-headers | awk '{print $6, $7}' | sort | uniq -c

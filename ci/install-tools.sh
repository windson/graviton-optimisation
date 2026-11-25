#!/usr/bin/env bash
# Installs pinned kubectl and Helm releases into /usr/local/bin, verifying checksums.
set -euo pipefail

KUBECTL_VERSION="${KUBECTL_VERSION:-v1.37.2}"
HELM_VERSION="${HELM_VERSION:-v4.3.2}"

case "$(uname -m)" in
  aarch64) arch=arm64 ;;
  x86_64) arch=amd64 ;;
  *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"

curl -fsSLO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${arch}/kubectl"
curl -fsSLO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${arch}/kubectl.sha256"
echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check --quiet
install -m 0755 kubectl /usr/local/bin/kubectl

helm_archive="helm-${HELM_VERSION}-linux-${arch}.tar.gz"
curl -fsSLO "https://get.helm.sh/${helm_archive}"
curl -fsSLO "https://get.helm.sh/${helm_archive}.sha256sum"
sha256sum --check --quiet "${helm_archive}.sha256sum"
tar -xzf "$helm_archive"
install -m 0755 "linux-${arch}/helm" /usr/local/bin/helm

kubectl version --client | head -1
helm version --short

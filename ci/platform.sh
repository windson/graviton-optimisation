#!/usr/bin/env bash
# Prepares the cluster for the application: installs the AWS Load Balancer Controller and
# publishes the database connection settings to the application's namespace.
set -euo pipefail

: "${PROJECT_NAME:?}" "${AWS_REGION:?}"
NAMESPACE="storefront"
# Controller release. The controller's IAM policy in infra/cfn/eks.yaml is the one
# published with this release.
LBC_CHART_VERSION="3.6.3"

aws eks update-kubeconfig --name "$PROJECT_NAME" --region "$AWS_REGION" >/dev/null
VPC_ID="$(aws eks describe-cluster --name "$PROJECT_NAME" --query 'cluster.resourcesVpcConfig.vpcId' --output text)"

# Region and VPC are passed explicitly because pods cannot reach the instance metadata
# service (hop limit 1); the controller's AWS credentials come from EKS Pod Identity.
helm repo add eks https://aws.github.io/eks-charts >/dev/null
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
  --version "$LBC_CHART_VERSION" \
  --namespace kube-system \
  --set clusterName="$PROJECT_NAME" \
  --set region="$AWS_REGION" \
  --set vpcId="$VPC_ID" \
  --set serviceAccount.create=true \
  --set serviceAccount.name=aws-load-balancer-controller \
  --set replicaCount=2 \
  --set nodeSelector.tier=system \
  --wait --timeout 10m

kubectl create namespace "$NAMESPACE" --dry-run=client --output yaml | kubectl apply --filename -
# Pods become ready only once the load balancer reports them healthy, which keeps
# rollouts and node replacements from dropping requests.
kubectl label namespace "$NAMESPACE" elbv2.k8s.aws/pod-readiness-gate-inject=enabled --overwrite

output() {
  aws cloudformation describe-stacks --stack-name "$PROJECT_NAME-database" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
kubectl --namespace "$NAMESPACE" create configmap storefront-env \
  --from-literal=DB_HOST="$(output WriterEndpoint)" \
  --from-literal=DB_NAME="$(output DatabaseName)" \
  --from-literal=DB_SECRET_ARN="$(output SecretArn)" \
  --from-literal=AWS_REGION="$AWS_REGION" \
  --dry-run=client --output yaml | kubectl apply --filename -

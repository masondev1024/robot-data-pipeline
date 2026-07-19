#!/usr/bin/env bash
# ADOT Operator + Collector + Instrumentation 1회 셋업 (Task 5.1).
#
# 순서:
#   1. cert-manager helm install (ADOT Operator webhook TLS 의존성)
#   2. terraform apply -target=aws_eks_addon.adot (Operator 설치)
#   3. ADOT Collector + Instrumentation CR apply (k8s/monitoring/adot/)
#   4. Generator/API pod restart 로 OTEL init container 주입
#   5. /api/chat 호출 → X-Ray Service Map 확인 (5분 대기)
#
# 사용:
#   bash scripts/setup_adot.sh
#
# 사전 조건: AWS 자격증명, kubectl + terraform + helm CLI.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

REGION="${AWS_REGION:-eu-west-1}"
CLUSTER="${EKS_CLUSTER_NAME:-${EKS_CLUSTER:-robot-telemetry-cluster}}"
: "${AWS_ACCOUNT_ID:?AWS_ACCOUNT_ID must be set to the intended 12-digit account ID}"
: "${S3_BUCKET_NAME:?S3_BUCKET_NAME must be set}"

# External mutations require an explicit intended account, then an STS match.
export EXPECTED_AWS_ACCOUNT_ID="$AWS_ACCOUNT_ID"
bash "$REPO_ROOT/scripts/require_aws_account.sh"

export AWS_REGION="$REGION"
export EKS_CLUSTER_NAME="$CLUSTER"
export IMAGE_TAG="$(git -C "$REPO_ROOT" rev-parse HEAD)"
export TF_VAR_aws_region="$REGION"
export TF_VAR_eks_cluster_name="$CLUSTER"
export TF_VAR_s3_bucket_name="$S3_BUCKET_NAME"
RENDER_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/robot-adot-render.XXXXXX")"
trap 'rm -rf "$RENDER_ROOT"' EXIT
python3 "$REPO_ROOT/scripts/render_deployment.py" --output "$RENDER_ROOT"

echo "[adot-setup] cluster=$CLUSTER region=$REGION"

# 1) cert-manager (ADOT Operator webhook 의존성)
echo "[adot-setup] step 1/5: cert-manager helm install"
helm repo add jetstack https://charts.jetstack.io 2>/dev/null || true
helm repo update jetstack
if kubectl get ns cert-manager >/dev/null 2>&1; then
  echo "[adot-setup]   cert-manager namespace 이미 존재 — skip helm install"
else
  helm install cert-manager jetstack/cert-manager \
    -n cert-manager --create-namespace \
    --set crds.enabled=true \
    --wait
fi
kubectl -n cert-manager wait --for=condition=ready pod -l app.kubernetes.io/name=cert-manager --timeout=120s

# 2) ADOT EKS Add-on (terraform 으로 IRSA + add-on 동시 설치)
echo "[adot-setup] step 2/5: terraform apply ADOT add-on"
cd "$REPO_ROOT/terraform"
terraform plan -target=aws_iam_role.adot_collector \
               -target=aws_iam_role_policy_attachment.adot_xray \
               -target=aws_iam_role_policy_attachment.adot_cloudwatch \
               -target=aws_eks_addon.adot \
               -out=/tmp/adot.tfplan
read -rp "위 plan 적용? (y/N) " yn
[[ "$yn" =~ ^[Yy]$ ]] || { echo "[adot-setup] aborted"; exit 1; }
terraform apply /tmp/adot.tfplan
cd - >/dev/null

# 3) Collector + Instrumentation CR apply
echo "[adot-setup] step 3/5: ADOT Collector + Instrumentation CR apply"
# Collector ServiceAccount IRSA annotation 의 role-arn 을 terraform output 으로 갱신
ROLE_ARN=$(terraform -chdir="$REPO_ROOT/terraform" output -raw adot_collector_irsa_role_arn)
echo "[adot-setup]   IRSA role: $ROLE_ARN"
grep -Fq "$ROLE_ARN" "$RENDER_ROOT/k8s/monitoring/adot/collector.yaml" || {
  echo "[adot-setup] rendered collector IRSA role does not match Terraform output" >&2
  exit 1
}

kubectl apply -f "$RENDER_ROOT/k8s/monitoring/adot/collector.yaml"
kubectl apply -f "$RENDER_ROOT/k8s/monitoring/adot/instrumentation.yaml"

kubectl -n opentelemetry-operator-system wait --for=condition=ready \
  pod -l app.kubernetes.io/name=adot-collector --timeout=180s || true

# 4) Generator/API pod restart (init container 주입 활성)
echo "[adot-setup] step 4/5: Generator + API pod restart"
kubectl -n robot-telemetry rollout restart deploy/robot-telemetry-generator || echo "  (generator 미배포)"
kubectl -n robot-telemetry rollout restart deploy/robot-telemetry-api || echo "  (api 미배포)"

# 5) X-Ray Service Map 확인 안내
echo "[adot-setup] step 5/5: X-Ray Service Map 검증"
echo "[adot-setup]   ① /api/chat 호출 1회 — curl https://<API-ALB>/api/chat -d '{\"question\":\"test\"}'"
echo "[adot-setup]   ② 5분 대기 후 'bash scripts/xray_service_map_check.sh' 실행"
echo "[adot-setup]   ③ 또는 AWS Console → CloudWatch → X-Ray traces → Service Map"

echo "[adot-setup] 완료."

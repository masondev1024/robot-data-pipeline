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

# .env 의 SLACK_WEBHOOK_URL → TF_VAR_ 자동 주입 (terraform plan/apply 가 webhook 변수 요구 시 fallback CHANGEME 회피)
ENV_FILE="$(cd "$(dirname "$0")/.." && pwd)/.env"
if [ -f "$ENV_FILE" ]; then
  set -a; source "$ENV_FILE"; set +a
  if [ -n "${SLACK_WEBHOOK_URL:-}" ]; then
    export TF_VAR_slack_webhook_url="$SLACK_WEBHOOK_URL"
  fi
fi

REGION="${AWS_REGION:-eu-west-1}"
CLUSTER="${EKS_CLUSTER:-robot-telemetry-cluster}"

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
cd "$(dirname "$0")/../terraform"
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
ROLE_ARN=$(terraform -chdir=terraform output -raw adot_collector_irsa_role_arn)
echo "[adot-setup]   IRSA role: $ROLE_ARN"
sed -i.bak "s|arn:aws:iam::[0-9]*:role/robot-telemetry-adot-collector-irsa|$ROLE_ARN|" \
  k8s/monitoring/adot/collector.yaml
rm -f k8s/monitoring/adot/collector.yaml.bak

kubectl apply -f k8s/monitoring/adot/collector.yaml
kubectl apply -f k8s/monitoring/adot/instrumentation.yaml

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

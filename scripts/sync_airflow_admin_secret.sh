#!/usr/bin/env bash
# AWS Secrets Manager의 Airflow bootstrap 비밀번호를 Kubernetes Secret으로 전달한다.
# 비밀번호는 프로세스 인자, stdout, 임시 파일에 기록하지 않는다.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROBOT_ENV_FILE:-$REPO_ROOT/.env}"
if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

: "${AWS_ACCOUNT_ID:?AWS_ACCOUNT_ID must be set to the intended 12-digit account ID}"

REGION="${AWS_REGION:-eu-west-1}"
SECRET_ID="${AIRFLOW_ADMIN_SECRET_ID:-/robot-telemetry/airflow-admin-password}"
NAMESPACE="${AIRFLOW_NAMESPACE:-airflow}"

export EXPECTED_AWS_ACCOUNT_ID="$AWS_ACCOUNT_ID"
bash "$REPO_ROOT/scripts/require_aws_account.sh"

AIRFLOW_ADMIN_PASSWORD="$(
  aws secretsmanager get-secret-value \
    --region "$REGION" \
    --secret-id "$SECRET_ID" \
    --query SecretString \
    --output text
)"
trap 'unset AIRFLOW_ADMIN_PASSWORD' EXIT

if [ -z "$AIRFLOW_ADMIN_PASSWORD" ] || [ "$AIRFLOW_ADMIN_PASSWORD" = "None" ]; then
  echo "Airflow admin secret is empty; refusing Kubernetes changes" >&2
  exit 5
fi

kubectl create namespace "$NAMESPACE" \
  --dry-run=client \
  -o yaml \
  | kubectl apply -f -

printf '%s' "$AIRFLOW_ADMIN_PASSWORD" \
  | kubectl -n "$NAMESPACE" create secret generic airflow-admin-bootstrap \
      --from-file=password=/dev/stdin \
      --dry-run=client \
      -o yaml \
  | kubectl -n "$NAMESPACE" apply -f -

echo "Airflow admin bootstrap secret synchronized in namespace: $NAMESPACE"

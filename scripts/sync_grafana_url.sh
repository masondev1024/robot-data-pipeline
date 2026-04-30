#!/usr/bin/env bash
# Grafana ALB hostname 을 SSM Parameter (/robot-telemetry/grafana-url) 에 동기화한다.
#
# Helm 으로 Grafana 가 재배포되거나 ingress 가 재생성되면 ALB hostname 이 바뀐다.
# Terraform 은 SSM 파라미터 value 를 ignore_changes 로 잠가두므로,
# 이 스크립트로 런타임 갱신 → API Pod 재시작이 표준 절차.
#
# Usage:
#   ./scripts/sync_grafana_url.sh                  # SSM 갱신만
#   ./scripts/sync_grafana_url.sh --restart-api    # SSM 갱신 + API rollout restart
#
# Env (override 가능):
#   AWS_REGION (default: eu-west-1)
#   PROJECT_NAME (default: robot-telemetry)
#   GRAFANA_NS (default: monitoring)
#   GRAFANA_INGRESS (default: grafana-ingress)
#   API_NS (default: robot-telemetry)
#   API_DEPLOY (default: robot-telemetry-api)

set -euo pipefail

REGION="${AWS_REGION:-eu-west-1}"
PROJECT="${PROJECT_NAME:-robot-telemetry}"
GRAFANA_NS="${GRAFANA_NS:-monitoring}"
GRAFANA_INGRESS="${GRAFANA_INGRESS:-grafana-ingress}"
API_NS="${API_NS:-robot-telemetry}"
API_DEPLOY="${API_DEPLOY:-robot-telemetry-api}"
SSM_NAME="/${PROJECT}/grafana-url"

RESTART_API=0
for arg in "$@"; do
  case "$arg" in
    --restart-api) RESTART_API=1 ;;
    -h|--help)
      sed -n '2,18p' "$0"
      exit 0
      ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

echo "→ Grafana ingress hostname 조회 (ns=${GRAFANA_NS}, ingress=${GRAFANA_INGRESS})"
HOST=$(kubectl get ingress -n "$GRAFANA_NS" "$GRAFANA_INGRESS" \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)

if [[ -z "$HOST" ]]; then
  echo "[FAIL] ingress hostname 이 비어있음. ALB 프로비저닝이 끝났는지 확인:" >&2
  echo "  kubectl describe ingress -n ${GRAFANA_NS} ${GRAFANA_INGRESS}" >&2
  exit 1
fi

URL="http://${HOST}/"
echo "  hostname = ${HOST}"
echo "  URL      = ${URL}"

echo "→ SSM put-parameter (${SSM_NAME})"
aws ssm put-parameter \
  --name "$SSM_NAME" \
  --value "$URL" \
  --type String \
  --overwrite \
  --region "$REGION" \
  --output text --query '{Version:Version,Tier:Tier}'

if [[ "$RESTART_API" -eq 1 ]]; then
  echo "→ API Pod rollout restart (ns=${API_NS}, deploy=${API_DEPLOY})"
  kubectl rollout restart "deployment/${API_DEPLOY}" -n "$API_NS"
  kubectl rollout status  "deployment/${API_DEPLOY}" -n "$API_NS" --timeout=180s
else
  echo "ⓘ API Pod 캐시는 옛 값 유지 중. 즉시 반영하려면 다음 명령:"
  echo "  kubectl rollout restart deployment/${API_DEPLOY} -n ${API_NS}"
fi

echo "DONE"

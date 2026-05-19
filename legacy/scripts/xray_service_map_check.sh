#!/usr/bin/env bash
# X-Ray Service Map 트레이스 수신 검증 (Task 5.3 line 416).
#
# ADOT setup 후 5-10분 경과해야 X-Ray Service Map 에 노드 등장.
# 본 스크립트는 최근 10분 service graph + segment 수 출력.
#
# 사용:
#   bash scripts/xray_service_map_check.sh
#
# 사전 조건: AWS 자격증명 (eu-west-1), xray:GetServiceGraph + xray:GetTraceSummaries 권한.
set -euo pipefail

REGION="${AWS_REGION:-eu-west-1}"
WINDOW_MIN="${WINDOW_MIN:-10}"

echo "[xray-check] region=$REGION window=${WINDOW_MIN}min"

# macOS / Linux 양쪽 호환 timestamp 계산
if date -u -d "now" +%s >/dev/null 2>&1; then
  END_TS=$(date -u +%s)
  START_TS=$(date -u -d "-${WINDOW_MIN} minutes" +%s)
else
  END_TS=$(date -u +%s)
  START_TS=$(( END_TS - WINDOW_MIN * 60 ))
fi

echo "[xray-check] window: $(date -u -r "$START_TS" 2>/dev/null || date -u -d "@$START_TS") → $(date -u -r "$END_TS" 2>/dev/null || date -u -d "@$END_TS")"

# 1) Service Graph (노드 + 엣지)
echo ""
echo "[xray-check] 1/3: Service Graph (노드 목록)"
NODES=$(aws xray get-service-graph \
  --region "$REGION" \
  --start-time "$START_TS" \
  --end-time "$END_TS" \
  --query 'Services[].{Name:Name,Type:Type,State:State,Origin:Origin}' \
  --output json 2>&1 || echo "[]")

if [ "$NODES" = "[]" ] || [ -z "$NODES" ]; then
  echo "[xray-check]   ⚠️  Service Graph 빈 결과. ADOT Collector 미배포 또는 trace 미전송."
  echo "[xray-check]   확인 명령:"
  echo "[xray-check]     kubectl -n opentelemetry-operator-system get pods"
  echo "[xray-check]     kubectl -n robot-telemetry get pods -o jsonpath='{.items[*].spec.initContainers[*].name}'"
else
  echo "$NODES" | python3 -m json.tool
fi

# 2) Trace Summaries (최근 trace ID + duration)
echo ""
echo "[xray-check] 2/3: 최근 Trace Summaries (최대 10건)"
SUMMARIES=$(aws xray get-trace-summaries \
  --region "$REGION" \
  --start-time "$START_TS" \
  --end-time "$END_TS" \
  --query 'TraceSummaries[:10].{Id:Id,Duration:Duration,HasError:HasError,Http:Http.HttpStatus}' \
  --output table 2>&1 || echo "no traces")
echo "$SUMMARIES"

# 3) 검증 verdict
echo ""
SVC_COUNT=$(echo "$NODES" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else 0)" 2>/dev/null || echo "0")
echo "[xray-check] 3/3: verdict — service node 개수 = $SVC_COUNT"

if [ "$SVC_COUNT" -ge 2 ]; then
  echo "[xray-check] ✅ PASS — Service Map 에 $SVC_COUNT 개 서비스 노드 등록 (Generator/API/Kinesis 등)"
  exit 0
else
  echo "[xray-check] ❌ FAIL — Service Map 에 노드 < 2"
  echo "[xray-check]   가능 원인:"
  echo "[xray-check]     ① ADOT Collector 미배포: kubectl -n opentelemetry-operator-system get pods"
  echo "[xray-check]     ② Pod 에 init container 미주입: kubectl -n robot-telemetry describe pod <api-pod>"
  echo "[xray-check]     ③ /api/chat 호출 0건: 트래픽 발생 후 5분 대기 필요"
  exit 1
fi

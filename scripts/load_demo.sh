#!/usr/bin/env bash
set -euo pipefail

# Robot Telemetry Pipeline — 부하 시연 E2E 스크립트
# 흐름: API 부하 → Generator ROBOT_COUNT ↑ → Karpenter 신규 노드 → 자동 회수
#
# 사용법:
#   bash scripts/load_demo.sh
#
# 환경변수 override:
#   NAMESPACE          기본 robot-telemetry
#   API_DEPLOY         기본 robot-telemetry-api
#   GEN_DEPLOY         기본 robot-telemetry-generator
#   API_INGRESS        기본 robot-telemetry-api
#   LOAD_DURATION      기본 5m   (hey -z)
#   LOAD_CONCURRENCY   기본 50   (hey -c)

NAMESPACE="${NAMESPACE:-robot-telemetry}"
API_DEPLOY="${API_DEPLOY:-robot-telemetry-api}"
GEN_DEPLOY="${GEN_DEPLOY:-robot-telemetry-generator}"
API_INGRESS="${API_INGRESS:-robot-telemetry-api}"
LOAD_DURATION="${LOAD_DURATION:-5m}"
LOAD_CONCURRENCY="${LOAD_CONCURRENCY:-50}"

# ─── 사전 점검 ─────────────────────────────────────────────────
command -v hey >/dev/null || { echo "ERROR: hey 미설치 (https://github.com/rakyll/hey)"; exit 1; }
command -v kubectl >/dev/null || { echo "ERROR: kubectl 미설치"; exit 1; }

API_ALB=$(kubectl get ingress -n "$NAMESPACE" "$API_INGRESS" \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
[[ -z "$API_ALB" ]] && { echo "ERROR: API ALB 미생성 (ingress=$API_INGRESS, ns=$NAMESPACE)"; exit 1; }

echo "▶ 대상 ALB: http://${API_ALB}"
echo "▶ Namespace: ${NAMESPACE}  /  API: ${API_DEPLOY}  /  Generator: ${GEN_DEPLOY}"
echo

# ─── 1단계 — API 부하 ─────────────────────────────────────────
echo "=== Phase 1: API 부하 (hey ${LOAD_DURATION} @ ${LOAD_CONCURRENCY} concurrent) ==="
echo "  대상: http://${API_ALB}/api/predict"
hey -z "$LOAD_DURATION" -c "$LOAD_CONCURRENCY" \
    -m POST -H "Content-Type: application/json" \
    -d '{"robot_id":"ROBOT-00001","avg_motor_temp":85.0,"max_motor_temp":92.0,"battery_drain":12.0,"active_hours":8.0}' \
    "http://${API_ALB}/api/predict" &
HEY_PID=$!
echo "  hey PID: ${HEY_PID} (백그라운드)"

read -rp "Phase 2로 진행 [Enter]"

# ─── 2단계 — Generator ROBOT_COUNT 50 → 300 ───────────────────
echo "=== Phase 2: Generator ROBOT_COUNT 50 → 300 ==="
kubectl set env -n "$NAMESPACE" "deploy/${GEN_DEPLOY}" ROBOT_COUNT=300
echo "  10초 후 Generator pod CPU 추이:"
sleep 10
kubectl top pods -n "$NAMESPACE" -l app=robot-telemetry-generator || true
echo
echo "  HPA 현황:"
kubectl get hpa -n "$NAMESPACE"

read -rp "Phase 3로 진행 [Enter]"

# ─── 3단계 — Karpenter 신규 노드 프로비저닝 관찰 ──────────────
echo "=== Phase 3: Karpenter 신규 노드 프로비저닝 관찰 ==="
echo "  현재 노드(capacity-type / nodepool / instance-type 라벨 가시화):"
kubectl get nodes -L karpenter.sh/capacity-type,karpenter.sh/nodepool,node.kubernetes.io/instance-type
echo
echo "  Karpenter controller 로그(최근 50줄, launched/provisioned/nominated 매칭):"
kubectl logs -n karpenter deploy/karpenter --tail=50 2>/dev/null | grep -E "launched|provisioned|nominated" || true

read -rp "Phase 4로 진행(부하 종료) [Enter]"

# ─── 4단계 — 부하 제거 + 노드 자동 회수 ────────────────────────
echo "=== Phase 4: 부하 제거 + 노드 자동 회수 ==="
kill "$HEY_PID" 2>/dev/null || true
wait "$HEY_PID" 2>/dev/null || true
kubectl set env -n "$NAMESPACE" "deploy/${GEN_DEPLOY}" ROBOT_COUNT=50
echo "  consolidation 대기(최대 5분, 10초 간격 폴링)..."
for i in {1..30}; do
  sleep 10
  NODE_COUNT=$(kubectl get nodes -l karpenter.sh/nodepool -o name 2>/dev/null | wc -l | tr -d ' ')
  echo "  [${i}/30] Karpenter 노드 수: ${NODE_COUNT}"
  [[ "${NODE_COUNT}" -le 1 ]] && break
done

echo
echo "=== 시연 종료 ==="
echo "  최종 노드 상태:"
kubectl get nodes -L karpenter.sh/capacity-type,karpenter.sh/nodepool
echo
echo "  최종 HPA 상태:"
kubectl get hpa -n "$NAMESPACE"

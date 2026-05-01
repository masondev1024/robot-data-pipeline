#!/usr/bin/env bash
# DLQ CloudWatch Alarm → Lambda(alert_handler) → Slack 직접 POST E2E 검증 (Task 5.3 line 418).
#
# 동작:
#   1. firehose_delivery_errors alarm 강제 ALARM state 전이 (CloudWatch set-alarm-state).
#   2. Lambda alarm_invoke_alert permission 으로 자동 invoke (alarm_actions = Lambda ARN).
#   3. CloudWatch Alarm event schema 가 _handle_cloudwatch_alarm 분기로 진입 → Slack POST.
#   4. 60초 후 Lambda CloudWatch Logs 마지막 호출 결과 확인.
#   5. OK state 로 복원 (자동 회복 신호 — Slack에 ✅ 메시지 추가 도달).
#
# 사용:
#   bash scripts/dlq_alarm_e2e.sh
#
# 사전 조건: AWS 자격증명 (eu-west-1), CloudWatch + Lambda IAM 권한.
set -euo pipefail

REGION="${AWS_REGION:-eu-west-1}"
ALARM_NAME="${ALARM_NAME:-robot-telemetry-firehose-delivery-errors}"
LAMBDA_NAME="${LAMBDA_NAME:-robot-anomaly-alert-lambda}"

echo "[dlq-e2e] alarm=$ALARM_NAME lambda=$LAMBDA_NAME region=$REGION"

# 1) 강제 ALARM 발화
echo "[dlq-e2e] step 1/4: set-alarm-state ALARM"
aws cloudwatch set-alarm-state \
  --region "$REGION" \
  --alarm-name "$ALARM_NAME" \
  --state-value ALARM \
  --state-reason "manual e2e test (scripts/dlq_alarm_e2e.sh)"

# 2) Lambda invoke 대기 (CloudWatch Alarm action 전파 ~5-10초)
echo "[dlq-e2e] step 2/4: 60s 대기 (Lambda invoke + Slack POST 전파)"
sleep 60

# 3) Lambda 최근 로그에서 CloudWatch Alarm 처리 흔적 확인
echo "[dlq-e2e] step 3/4: Lambda CloudWatch Logs 최근 1분 검사"
END_MS=$(date +%s)000
START_MS=$(( $(date +%s) - 120 ))000
LOGS=$(aws logs filter-log-events \
  --region "$REGION" \
  --log-group-name "/aws/lambda/$LAMBDA_NAME" \
  --start-time "$START_MS" \
  --end-time "$END_MS" \
  --query 'events[].message' \
  --output text 2>/dev/null || echo "")

if echo "$LOGS" | grep -q "$ALARM_NAME"; then
  echo "[dlq-e2e] ✅ Lambda 가 alarm event 수신 확인"
else
  echo "[dlq-e2e] ⚠️  Lambda log 에 alarm name 미발견 (전파 지연 또는 permission 누락 가능성)"
  echo "[dlq-e2e]    수동 확인: aws logs tail /aws/lambda/$LAMBDA_NAME --since 2m --region $REGION"
fi

# 4) OK state 복원 (Slack 에 회복 메시지 추가 — 양방향 검증)
echo "[dlq-e2e] step 4/4: set-alarm-state OK (회복 신호)"
aws cloudwatch set-alarm-state \
  --region "$REGION" \
  --alarm-name "$ALARM_NAME" \
  --state-value OK \
  --state-reason "manual e2e test recovery"

echo "[dlq-e2e] 완료. Slack 채널에서 🚨 (ALARM) + ✅ (OK) 두 메시지 도달 확인 권장."

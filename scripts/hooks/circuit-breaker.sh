#!/bin/bash
# Circuit Breaker Hook — PostToolUseFailure
# 같은 도구가 60초 내에 반복 실패하면 전략 변경을 강제.
# 3회: 경고 + 다른 접근 제안
# 5회: 강제 중단 + 에스컬레이션

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // "unknown"')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')

if [ -z "$SESSION_ID" ]; then
  exit 0
fi

# 상태 저장 디렉토리
STATE_DIR="/tmp/harness-circuit-breaker/${SESSION_ID}"
FAILURE_FILE="${STATE_DIR}/failures.json"
mkdir -p "$STATE_DIR"

NOW=$(date +%s)
WINDOW=60

# 기존 상태 읽기 또는 초기화
if [ -f "$FAILURE_FILE" ]; then
  STATE=$(cat "$FAILURE_FILE")
else
  STATE='{"failures":[]}'
fi

# 현재 실패 추가
STATE=$(echo "$STATE" | jq --arg tool "$TOOL_NAME" --argjson ts "$NOW" \
  '.failures += [{"tool": $tool, "ts": $ts}]')

# 윈도우 밖 항목 제거
CUTOFF=$((NOW - WINDOW))
STATE=$(echo "$STATE" | jq --argjson cutoff "$CUTOFF" \
  '.failures = [.failures[] | select(.ts >= $cutoff)]')

# 이 도구의 실패 횟수
COUNT=$(echo "$STATE" | jq --arg tool "$TOOL_NAME" \
  '[.failures[] | select(.tool == $tool)] | length')

# 상태 저장
echo "$STATE" > "$FAILURE_FILE"

# 에스컬레이션
if [ "$COUNT" -ge 5 ]; then
  jq -n --arg ctx "CIRCUIT BREAKER: ${TOOL_NAME}이 60초 내 ${COUNT}회 실패했습니다. 같은 방법을 반복하고 있습니다. 즉시 멈추고 다른 전략을 사용하세요: (1) 관련 파일을 다시 읽고 현재 상태를 파악하세요 (2) 완전히 다른 접근법을 시도하세요 (3) 해결이 안 되면 blocked로 보고하세요." '{
    hookSpecificOutput: {
      hookEventName: "PostToolUseFailure",
      additionalContext: $ctx
    }
  }'
elif [ "$COUNT" -ge 3 ]; then
  jq -n --arg ctx "반복 실패 감지: ${TOOL_NAME}이 ${COUNT}회 실패했습니다. 현재 접근법이 맞는지 재검토하세요. 파일을 다시 읽고 다른 방법을 시도해 보세요." '{
    hookSpecificOutput: {
      hookEventName: "PostToolUseFailure",
      additionalContext: $ctx
    }
  }'
fi

exit 0

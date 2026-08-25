#!/usr/bin/env bash
# Grafana 데이터 미출력 진단 — read-only.
#
# 사용자 가설(plan.md 2026-04-30 PM 항목 참조) 3종을 순서대로 검증한다.
# 진짜 원인 후보:
#   (1순위) Gold 파티션 비어있음(Airflow DAG 미실행/실패)
#   (부수1) source dashboard JSON ↔ ConfigMap drift (이미 본 PR에서 수정)
#   (부수2) Bronze HIVE_BAD_DATA(Catalog vs Parquet 타입 불일치)
#
# Usage: ./scripts/diagnose_grafana.sh

set -uo pipefail

REGION="${AWS_DEFAULT_REGION:-ap-northeast-2}"
BUCKET="${S3_BUCKET_NAME:-robot-telemetry-data}"
WORKGROUP="${ATHENA_WORKGROUP:-robot-telemetry-workgroup}"
DATABASE="${ATHENA_DATABASE:-robot_telemetry_db}"
RESULT_LOC="s3://${BUCKET}/project-athena-results/"

hr() { printf '\n──────── %s ────────\n' "$1"; }

run_athena() {
  local label="$1" query="$2"
  hr "$label"
  local exec_id
  exec_id=$(aws athena start-query-execution \
    --region "$REGION" \
    --query-string "$query" \
    --work-group "$WORKGROUP" \
    --query-execution-context "Database=${DATABASE}" \
    --result-configuration "OutputLocation=${RESULT_LOC}" \
    --output text --query 'QueryExecutionId' 2>&1) || {
      echo "  [FAIL] start-query-execution: $exec_id"
      return 1
    }
  echo "  exec_id=$exec_id"
  for _ in $(seq 1 30); do
    local state
    state=$(aws athena get-query-execution --region "$REGION" \
      --query-execution-id "$exec_id" \
      --output text --query 'QueryExecution.Status.State')
    case "$state" in
      SUCCEEDED) break ;;
      FAILED|CANCELLED)
        local reason
        reason=$(aws athena get-query-execution --region "$REGION" \
          --query-execution-id "$exec_id" \
          --output text --query 'QueryExecution.Status.StateChangeReason')
        echo "  [FAIL] state=$state reason=$reason"
        return 1
        ;;
    esac
    sleep 2
  done
  aws athena get-query-results --region "$REGION" \
    --query-execution-id "$exec_id" \
    --output table --query 'ResultSet.Rows[].Data[].VarCharValue' 2>/dev/null \
    | head -40
}

hr "0. Grafana Pod IRSA 환경변수 확인"
kubectl -n monitoring get pod -l app=grafana \
  -o jsonpath='{.items[*].spec.containers[*].env[?(@.name=="AWS_ROLE_ARN")].value}{"\n"}' \
  2>/dev/null \
  || echo "  kubectl 컨텍스트 없음 또는 pod 미존재 (cost shutdown 가능성)"

run_athena "1. Gold 어제+최근 3일 파티션 카운트 (1순위 원인)" \
"SELECT dt, COUNT(*) AS rows FROM ${DATABASE}.gold_robot_daily_stats
 WHERE dt >= CURRENT_DATE - INTERVAL '3' DAY
 GROUP BY dt ORDER BY dt DESC"

run_athena "2. Bronze 어제 분량 + 타입 충돌 트리거" \
"SELECT COUNT(*) AS rows,
        APPROX_DISTINCT(robot_id) AS robots
 FROM ${DATABASE}.bronze_robot_telemetry
 WHERE year = date_format(current_date - interval '1' day, '%Y')
   AND month = date_format(current_date - interval '1' day, '%m')
   AND day = date_format(current_date - interval '1' day, '%d')"

run_athena "3. Bronze battery_level 직접 SELECT (HIVE_BAD_DATA 트리거)" \
"SELECT MIN(battery_level) AS min_b, MAX(battery_level) AS max_b
 FROM ${DATABASE}.bronze_robot_telemetry
 WHERE year = date_format(current_date - interval '1' day, '%Y')
   AND month = date_format(current_date - interval '1' day, '%m')
   AND day = date_format(current_date - interval '1' day, '%d')
 LIMIT 100"

hr "4. Airflow DAG 최근 실행 상태"
kubectl -n airflow exec deploy/airflow-webserver -- \
  airflow dags list-runs -d robot_daily_etl --limit 5 2>/dev/null \
  | head -10 \
  || echo "  airflow 컨텍스트 없음 또는 webserver 미기동"

hr "DONE"
echo "1번 결과가 0건/없음 → 1순위 원인 확정 (DAG 트리거 필요: airflow dags trigger -d robot_daily_etl)"
echo "3번이 HIVE_BAD_DATA 에러 → Generator float cast 정정 효과 발휘 (본 PR 적용 후 새로 수신되는 record부터 자동 해결)"

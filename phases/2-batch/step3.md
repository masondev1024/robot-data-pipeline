# Step 3: dag-silver-gold

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/sql/silver_ddl.sql`
- `/sql/gold_ddl.sql`
- `/dags/robot_daily_etl.py`

## 작업

`dags/robot_daily_etl.py`에 **2개의 Task를 추가**하여 DAG를 완성하라.

### Task: `silver_to_gold` (AthenaOperator)

```sql
ALTER TABLE robot_telemetry_db.gold_robot_daily_stats
DROP IF EXISTS PARTITION (dt='{{ ds }}');

INSERT INTO robot_telemetry_db.gold_robot_daily_stats
SELECT
    DATE('{{ ds }}')                                              AS dt,
    robot_id,
    AVG(motor_temp)                                               AS avg_motor_temp,
    MAX(motor_temp)                                               AS max_motor_temp,
    MAX_BY(battery_level, timestamp)                              AS battery_start,
    MIN_BY(battery_level, timestamp)                              AS battery_end,
    MAX_BY(battery_level, timestamp) - MIN_BY(battery_level, timestamp) AS battery_drain,
    COUNT(DISTINCT HOUR(FROM_ISO8601_TIMESTAMP(timestamp)))       AS active_hours
FROM robot_telemetry_db.silver_robot_telemetry
WHERE dt = DATE('{{ ds }}')
GROUP BY robot_id
```

- `database="robot_telemetry_db"`
- `workgroup="robot-telemetry-workgroup"`
- `output_location="s3://de-ai-06-827913617635-ap-northeast-2-an/project-athena-results/"`

### Task: `generate_bedrock_report` (PythonOperator)

callable `_generate_report(ds, **context)` 구현:

1. Athena `boto3` 클라이언트로 Gold 테이블 최신 파티션 조회:
   ```python
   query = f"SELECT * FROM robot_telemetry_db.gold_robot_daily_stats WHERE dt = DATE('{ds}') ORDER BY avg_motor_temp DESC LIMIT 10"
   # workgroup="robot-telemetry-workgroup"
   # output_location="s3://.../project-athena-results/"
   ```
2. Bedrock 호출:
   ```python
   model_id = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
   prompt = f"다음은 오늘({ds}) 공장 로봇들의 상태 지표야.\n\n{gold_data}\n\n이를 분석해서 가장 점검이 시급한 로봇 3대와 그 이유를 정비반장에게 보내는 형식으로 300자 이내로 요약해."
   ```
   - `bedrock-runtime` 클라이언트, Messages API 형식, `max_tokens=512`
3. S3 저장: `s3://.../reports/{ds}.txt`

### 의존성 체인
```python
bronze_to_silver >> silver_to_gold >> generate_bedrock_report
```

## Acceptance Criteria

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from dags.robot_daily_etl import dag
assert 'bronze_to_silver' in dag.task_ids
assert 'silver_to_gold' in dag.task_ids
assert 'generate_bedrock_report' in dag.task_ids
t = dag.get_task('silver_to_gold')
assert any(u.task_id == 'bronze_to_silver' for u in t.upstream_list)
t2 = dag.get_task('generate_bedrock_report')
assert any(u.task_id == 'silver_to_gold' for u in t2.upstream_list)
print('OK. Task IDs:', dag.task_ids)
"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - `battery_drain = battery_start - battery_end` 계산이 있는가?
   - `active_hours`가 집계되는가?
   - DB/Workgroup/output_location이 모두 plan.md 확정값인가?
   - Bedrock `BEDROCK_MODEL_ID`를 환경변수에서 읽는가?
   - S3 리포트 경로에 `ds`(날짜)가 포함되는가?
3. `phases/2-batch/index.json` step 3 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "robot_daily_etl.py 완성: silver_to_gold(일별 집계 4지표) + generate_bedrock_report(Bedrock Claude → S3 reports/) 체인"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- 기존 `bronze_to_silver` Task를 수정하지 마라. 이유: step 2에서 완성된 로직이다
- `BEDROCK_MODEL_ID`를 코드에 하드코딩하지 마라. 이유: 환경변수로 관리
- Slack 전송 코드를 이 step에서 추가하지 마라. 이유: Phase 4 전담

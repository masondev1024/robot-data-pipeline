# Step 2: dag-bronze-silver

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md`
- `/sql/bronze_ddl.sql`
- `/sql/silver_ddl.sql`

## 작업

`dags/robot_daily_etl.py`를 새로 작성하라. 이 step에서는 DAG 선언과 **Bronze → Silver** Task만 구현한다.

### DAG 선언
```python
dag = DAG(
    dag_id="robot_daily_etl",
    schedule_interval="0 15 * * *",  # 매일 00:00 KST = UTC 15:00
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=5)},
)
```

### Task: `bronze_to_silver` (AthenaOperator)

**멱등성 필수**: `{{ ds }}` 기준 파티션만 처리, 재실행 시 기존 데이터 덮어씀.

```sql
-- 1. 기존 silver 파티션 삭제 (멱등성)
ALTER TABLE robot_telemetry_db.silver_robot_telemetry
DROP IF EXISTS PARTITION (dt='{{ ds }}');

-- 2. Bronze → Silver
INSERT INTO robot_telemetry_db.silver_robot_telemetry
SELECT
    robot_id,
    pos_x, pos_y,
    CAST(battery_level AS INTEGER)  AS battery_level,
    CAST(current_load AS INTEGER)   AS current_load,
    CAST(motor_temp    AS DOUBLE)   AS motor_temp,
    timestamp,
    DATE('{{ ds }}')                AS dt
FROM robot_telemetry_db.bronze_robot_telemetry
WHERE year  = YEAR(DATE('{{ ds }}'))
  AND month = MONTH(DATE('{{ ds }}'))
  AND day   = DAY(DATE('{{ ds }}'))
  AND motor_temp < 500        -- 이상치 제거
  AND robot_id IS NOT NULL
QUALIFY ROW_NUMBER() OVER (PARTITION BY robot_id, timestamp ORDER BY timestamp) = 1
```

- `AthenaOperator` (apache-airflow-providers-amazon)
- `database="robot_telemetry_db"`
- `workgroup="robot-telemetry-workgroup"`
- `output_location="s3://de-ai-06-827913617635-ap-northeast-2-an/project-athena-results/"`
- `aws_conn_id="aws_default"`

## Acceptance Criteria

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from dags.robot_daily_etl import dag
assert 'bronze_to_silver' in dag.task_ids
assert dag.schedule_interval == '0 15 * * *', f'Wrong schedule: {dag.schedule_interval}'
print('OK. Task IDs:', dag.task_ids)
"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - DB명이 `robot_telemetry_db`인가?
   - Workgroup이 `robot-telemetry-workgroup`인가?
   - output_location이 `project-athena-results/`인가?
   - schedule이 `"0 15 * * *"` (= KST 자정)인가?
   - SQL에 `motor_temp < 500` 이상치 제거가 있는가?
   - XCom을 사용하지 않는가?
3. `phases/2-batch/index.json` step 2 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "robot_daily_etl.py 생성: bronze_to_silver(이상치/중복 제거, Workgroup=robot-telemetry-workgroup)"`
   - airflow 미설치 → `"status": "blocked"`, `"blocked_reason": "apache-airflow 없음. docker compose up 후 재실행"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- `database="default"`로 쓰지 마라. 이유: Athena DB는 `robot_telemetry_db`
- `output_location`에 `athena-results/` prefix를 쓰지 마라. 이유: 확정값은 `project-athena-results/`
- XCom으로 Task 간 데이터를 전달하지 마라. 이유: S3 경로를 파라미터로 전달하는 것이 원칙
- silver to gold Task를 이 step에서 작성하지 마라. 이유: step 3 전담

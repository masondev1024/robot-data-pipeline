# Step 0: athena-ddl

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md` (ADR-003: Partition Projection)
- `/docs/research.md`
- `/terraform/modules/data_pipeline/glue.tf`

## 작업

아래 4개의 SQL 파일과 Athena Workgroup Terraform 리소스를 작성하라.

### `terraform/modules/data_pipeline/athena.tf` (신규)
```hcl
resource "aws_athena_workgroup" "main" {
  name  = "robot-telemetry-workgroup"
  state = "ENABLED"
  configuration {
    result_configuration {
      output_location = "s3://de-ai-06-827913617635-ap-northeast-2-an/project-athena-results/"
    }
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
  }
}
```

### `sql/bronze_ddl.sql` — Raw 데이터 External Table
```sql
CREATE EXTERNAL TABLE IF NOT EXISTS robot_telemetry_db.bronze_robot_telemetry (
    robot_id      STRING,
    pos_x         DOUBLE,
    pos_y         DOUBLE,
    battery_level INT,
    current_load  INT,
    motor_temp    DOUBLE,
    `timestamp`   STRING
)
PARTITIONED BY (year INT, month INT, day INT, hour INT)
STORED AS PARQUET
LOCATION 's3://de-ai-06-827913617635-ap-northeast-2-an/bronze/'
TBLPROPERTIES (
    'projection.enabled'              = 'true',
    'projection.year.type'            = 'integer',
    'projection.year.range'           = '2024,2030',
    'projection.month.type'           = 'integer',
    'projection.month.range'          = '1,12',
    'projection.month.digits'         = '2',
    'projection.day.type'             = 'integer',
    'projection.day.range'            = '1,31',
    'projection.day.digits'           = '2',
    'projection.hour.type'            = 'integer',
    'projection.hour.range'           = '0,23',
    'projection.hour.digits'          = '2',
    'storage.location.template'       =
        's3://de-ai-06-827913617635-ap-northeast-2-an/bronze/year=${year}/month=${month}/day=${day}/hour=${hour}/'
);
```

### `sql/silver_ddl.sql` — 정제 테이블
- Table: `robot_telemetry_db.silver_robot_telemetry`
- 컬럼: bronze와 동일 + `dt DATE` (파티션 키)
- `STORED AS PARQUET` with Snappy
- `LOCATION 's3://de-ai-06-827913617635-ap-northeast-2-an/silver/'`

### `sql/gold_ddl.sql` — 일별 집계 테이블
- Table: `robot_telemetry_db.gold_robot_daily_stats`
- 컬럼: `dt DATE`, `robot_id STRING`, `avg_motor_temp DOUBLE`, `max_motor_temp DOUBLE`, `battery_start INT`, `battery_end INT`, `battery_drain INT`, `active_hours INT`
- `STORED AS PARQUET` with Snappy
- `LOCATION 's3://de-ai-06-827913617635-ap-northeast-2-an/gold/'`

## Acceptance Criteria

```bash
ls sql/bronze_ddl.sql sql/silver_ddl.sql sql/gold_ddl.sql
grep -q "robot_telemetry_db.bronze_robot_telemetry" sql/bronze_ddl.sql && echo "OK: DB+table name"
grep -q "projection.enabled.*true" sql/bronze_ddl.sql && echo "OK: partition projection"
grep -q "robot_telemetry_db.gold_robot_daily_stats" sql/gold_ddl.sql && echo "OK: gold table"
grep -q "robot-telemetry-workgroup" terraform/modules/data_pipeline/athena.tf && echo "OK: workgroup"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - DB 이름이 `robot_telemetry_db`인가? (glue.tf와 일치)
   - Bronze 테이블 이름이 `bronze_robot_telemetry`인가?
   - Gold 테이블 이름이 `gold_robot_daily_stats`인가?
   - Partition Projection이 bronze_ddl에 있는가?
   - Athena Workgroup 이름이 `robot-telemetry-workgroup`인가?
   - Athena 결과 경로가 `project-athena-results/`인가?
3. `phases/2-batch/index.json` step 0 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "sql/ DDL 3개(bronze Partition Projection, silver, gold). athena.tf: robot-telemetry-workgroup, project-athena-results/"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- Bronze 테이블에 `MSCK REPAIR TABLE`을 추가하지 마라. 이유: Partition Projection이 활성화되면 MSCK REPAIR 불필요
- Athena 결과 경로를 `athena-results/`로 쓰지 마라. 이유: plan.md 확정값 `project-athena-results/`
- `gold_robot_stats`처럼 축약 이름을 쓰지 마라. 이유: plan.md 확정값 `gold_robot_daily_stats`

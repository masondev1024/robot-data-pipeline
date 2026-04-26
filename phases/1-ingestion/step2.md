# Step 2: glue-catalog

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/terraform/variables.tf`
- `/terraform/modules/data_pipeline/kinesis.tf`

## 작업

`terraform/modules/data_pipeline/glue.tf`를 작성하라.

**이 step은 kinesis-firehose(step 3) 이전에 반드시 완료되어야 한다.** KDF의 Parquet 변환 시 이 Glue Table을 schema_configuration으로 참조하므로, Glue Table이 없으면 KDF 프로비저닝이 실패한다.

### `aws_glue_catalog_database`
```hcl
resource "aws_glue_catalog_database" "main" {
  name = "robot_telemetry_db"
}
```

### `aws_glue_catalog_table` (Bronze 테이블 스키마)
```hcl
resource "aws_glue_catalog_table" "bronze" {
  name          = "bronze_robot_telemetry"
  database_name = aws_glue_catalog_database.main.name

  storage_descriptor {
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      # 아래 7개 컬럼을 순서대로 선언
      # robot_id     (string)
      # pos_x        (double)
      # pos_y        (double)
      # battery_level(int)
      # current_load (int)
      # motor_temp   (double)
      # timestamp    (string)
    }
  }

  partition_keys {
    # year  (string)
    # month (string)
    # day   (string)
    # hour  (string)
  }
}
```

### Outputs
```hcl
output "glue_database_name"     { value = aws_glue_catalog_database.main.name }
output "glue_bronze_table_name" { value = aws_glue_catalog_table.bronze.name }
```

## Acceptance Criteria

```bash
terraform fmt -check -recursive terraform/modules/
grep -q "robot_telemetry_db" terraform/modules/data_pipeline/glue.tf && echo "OK: DB name"
grep -q "bronze_robot_telemetry" terraform/modules/data_pipeline/glue.tf && echo "OK: table name"
grep -q "robot_id" terraform/modules/data_pipeline/glue.tf && echo "OK: schema columns"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - DB 이름이 정확히 `"robot_telemetry_db"`인가?
   - 테이블 이름이 정확히 `"bronze_robot_telemetry"`인가?
   - 컬럼 7개(robot_id, pos_x, pos_y, battery_level, current_load, motor_temp, timestamp) 모두 선언?
   - 파티션 키 4개(year, month, day, hour) 선언?
3. `phases/1-ingestion/index.json` step 2 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "glue.tf: robot_telemetry_db DB, bronze_robot_telemetry 테이블(7컬럼+4파티션키) 생성"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- DB 이름을 `"${var.project_name}_bronze"` 처럼 변수 조합으로 만들지 마라. 이유: plan.md 확정값 `robot_telemetry_db`로 고정
- 테이블 이름을 `"robot_telemetry"`로만 쓰지 마라. 이유: 계층 구분을 위해 반드시 `bronze_robot_telemetry`
- KDF 리소스를 이 step에서 작성하지 마라. 이유: step 3 전담이다

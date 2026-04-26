# Step 3: kinesis-firehose

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md`
- `/terraform/modules/data_pipeline/kinesis.tf`
- `/terraform/modules/data_pipeline/glue.tf`
- `/terraform/modules/data_pipeline/iam.tf`

## 작업

`terraform/modules/data_pipeline/kinesis.tf`에 **Kinesis Data Firehose Delivery Stream**을 추가하라.

### `aws_kinesis_firehose_delivery_stream`
```hcl
resource "aws_kinesis_firehose_delivery_stream" "main" {
  name        = "robot-telemetry-firehose"
  destination = "extended_s3"

  kinesis_source_configuration {
    kinesis_stream_arn = aws_kinesis_stream.main.arn
    role_arn           = aws_iam_role.firehose_delivery_role.arn
  }

  extended_s3_configuration {
    bucket_arn          = data.aws_s3_bucket.existing.arn
    role_arn            = aws_iam_role.firehose_delivery_role.arn
    prefix              = "bronze/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"
    error_output_prefix = "bronze-errors/!{firehose:error-output-type}/year=!{timestamp:yyyy}/month=!{timestamp:MM}/"
    buffering_interval  = 60
    buffering_size      = 64

    # Parquet 변환 (핵심)
    data_format_conversion_configuration {
      enabled = true
      input_format_configuration {
        deserializer { open_x_json_ser_de {} }
      }
      output_format_configuration {
        serializer { parquet_ser_de { compression = "SNAPPY" } }
      }
      schema_configuration {
        database_name = aws_glue_catalog_database.main.name
        table_name    = aws_glue_catalog_table.bronze.name
        role_arn      = aws_iam_role.firehose_delivery_role.arn
      }
    }
  }
}
```

`data "aws_s3_bucket"` 는 `iam.tf`에서 이미 선언되어 있으므로 중복 선언하지 말고 참조만 한다.

## Acceptance Criteria

```bash
terraform fmt -check -recursive terraform/modules/
grep -q "robot-telemetry-firehose" terraform/modules/data_pipeline/kinesis.tf && echo "OK: firehose name"
grep -q "parquet_ser_de" terraform/modules/data_pipeline/kinesis.tf && echo "OK: parquet conversion"
grep -q '!{timestamp:yyyy}' terraform/modules/data_pipeline/kinesis.tf && echo "OK: dynamic partitioning"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - Firehose 이름이 정확히 `"robot-telemetry-firehose"`인가?
   - `data_format_conversion_configuration.enabled = true` 인가?
   - S3 prefix에 `!{timestamp:...}` Dynamic Partitioning 패턴이 있는가?
   - `schema_configuration`이 glue.tf의 DB/테이블을 참조하는가?
   - `compression = "SNAPPY"`인가?
3. `phases/1-ingestion/index.json` step 3 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "kinesis.tf: robot-telemetry-firehose(KDS→S3 Bronze, Parquet/Snappy, Dynamic Partitioning, Glue 스키마 참조)"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- Glue Table 리소스를 이 파일에 작성하지 마라. 이유: step 2(glue-catalog)에서 이미 생성됨
- S3 prefix를 정적 문자열로 하드코딩하지 마라. 이유: `!{timestamp:...}` 없으면 Dynamic Partitioning 미작동
- `compression = "GZIP"`을 쓰지 마라. 이유: Parquet 내부 압축은 Snappy (ARCHITECTURE.md 명시)

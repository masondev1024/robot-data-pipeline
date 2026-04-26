# Step 0: flink-terraform

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md`
- `/terraform/variables.tf`
- `/terraform/modules/data_pipeline/kinesis.tf`
- `/terraform/modules/data_pipeline/iam.tf`

## 작업

`terraform/modules/data_pipeline/flink.tf`를 작성하라.

### Flink IAM Role
```hcl
resource "aws_iam_role" "flink" {
  name = "${var.project_name}-flink-role"
  assume_role_policy = # managed-flink.amazonaws.com 신뢰
}

resource "aws_iam_role_policy" "flink" {
  # Kinesis Read (메인 스트림): GetRecords, GetShardIterator, DescribeStream, ListStreams
  # Kinesis Write (alert 스트림): PutRecord, PutRecords  ← Phase 3 핵심
  # S3 Write (alerts/ prefix): PutObject
}
```

### `aws_kinesisanalyticsv2_application`
```hcl
resource "aws_kinesisanalyticsv2_application" "detector" {
  name                   = "robot-anomaly-detector"
  runtime_environment    = "FLINK-1_18"
  service_execution_role = aws_iam_role.flink.arn

  application_configuration {
    flink_application_configuration {
      checkpoint_configuration { checkpointing_enabled = true }
      parallelism_configuration { parallelism = 1, parallelism_per_kpu = 1 }
    }
    environment_properties {
      property_group {
        property_group_id = "app-config"
        property_map = {
          "kinesis.main.stream"  = "robot-telemetry-stream"
          "kinesis.alert.stream" = "robot-anomaly-alert-stream"
          "s3.alerts.path"       = "s3://de-ai-06-827913617635-ap-northeast-2-an/alerts/"
          "aws.region"           = var.aws_region
        }
      }
    }
  }
}
```

## Acceptance Criteria

```bash
terraform fmt -check -recursive terraform/modules/
grep -q "robot-anomaly-detector" terraform/modules/data_pipeline/flink.tf && echo "OK: app name"
grep -q "robot-anomaly-alert-stream" terraform/modules/data_pipeline/flink.tf && echo "OK: alert stream"
grep -q "PutRecord" terraform/modules/data_pipeline/flink.tf && echo "OK: alert stream write permission"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - Flink 앱 이름이 `"robot-anomaly-detector"`인가?
   - Flink IAM Role에 Alert Stream Write 권한(`PutRecord`, `PutRecords`)이 있는가?
   - `property_map`에 `kinesis.alert.stream = "robot-anomaly-alert-stream"`이 있는가?
3. `phases/3-realtime/index.json` step 0 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "flink.tf: robot-anomaly-detector Flink 앱, IAM(KDS Read + Alert Write + S3 Write)"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- Flink IAM Role에 Alert Stream Write 권한을 빠뜨리지 마라. 이유: Flink가 이상 감지 결과를 `robot-anomaly-alert-stream`으로 Sink해야 한다
- S3 버킷 리소스를 신규 생성하지 마라. 이유: 기존 버킷 사용

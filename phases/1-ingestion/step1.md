# Step 1: kinesis-streams

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/terraform/variables.tf`
- `/terraform/modules/data_pipeline/iam.tf`
- `/terraform/modules/data_pipeline/variables.tf`

## 작업

`terraform/modules/data_pipeline/kinesis.tf`에 **KDS 2개**를 작성하라.

### ① 메인 스트림 (데이터 수집용)
```hcl
resource "aws_kinesis_stream" "main" {
  name             = "robot-telemetry-stream"
  shard_count      = 10          # 10,000 로봇 × 1 rec/sec = 10,000 rec/sec = 10 Shards
  retention_period = 24
  stream_mode_details { stream_mode = "PROVISIONED" }
  tags = { project = var.project_name, environment = var.environment }
}
```
**Shard 산출 근거 (주석 포함 필수)**: KDS Shard 1개 한도 = 1,000 rec/sec 또는 1 MB/sec. 10,000 rec/sec ÷ 1,000 = 10 Shards.

### ② Alert 스트림 (Flink 이상 탐지 결과 → Lambda 트리거용)
```hcl
resource "aws_kinesis_stream" "alert" {
  name             = "robot-anomaly-alert-stream"
  shard_count      = 1
  retention_period = 24
  stream_mode_details { stream_mode = "PROVISIONED" }
  tags = { project = var.project_name, environment = var.environment }
}
```

### `iam.tf` 업데이트
Step 0에서 placeholder로 남긴 `var.kinesis_main_stream_arn`, `var.kinesis_alert_stream_arn`을
이 step에서 생성한 두 스트림의 ARN으로 연결하도록 `iam.tf`의 policy를 업데이트하라.

### Outputs
```hcl
output "kinesis_main_stream_arn"  { value = aws_kinesis_stream.main.arn }
output "kinesis_main_stream_name" { value = aws_kinesis_stream.main.name }
output "kinesis_alert_stream_arn" { value = aws_kinesis_stream.alert.arn }
output "kinesis_alert_stream_name"{ value = aws_kinesis_stream.alert.name }
```

## Acceptance Criteria

```bash
terraform fmt -check -recursive terraform/modules/
grep -q '"robot-telemetry-stream"' terraform/modules/data_pipeline/kinesis.tf && echo "OK: main stream"
grep -q '"robot-anomaly-alert-stream"' terraform/modules/data_pipeline/kinesis.tf && echo "OK: alert stream"
grep -q 'shard_count.*=.*10' terraform/modules/data_pipeline/kinesis.tf && echo "OK: 10 shards"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - 메인 스트림 이름이 정확히 `"robot-telemetry-stream"`인가?
   - Alert 스트림 이름이 정확히 `"robot-anomaly-alert-stream"`인가?
   - 메인 스트림 Shard가 10인가? (1이면 10,000 로봇 처리 불가)
   - `retention_period = 24` 양쪽 모두?
   - iam.tf의 ARN 참조가 placeholder가 아닌 실제 resource ARN인가?
3. `phases/1-ingestion/index.json` step 1 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "kinesis.tf: robot-telemetry-stream(10 Shards), robot-anomaly-alert-stream(1 Shard), iam.tf ARN 연결"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- 메인 스트림 Shard를 1로 설정하지 마라. 이유: 10,000 rec/sec 처리에 10 Shards가 필요하다 (산출 근거 참조)
- `stream_mode = "ON_DEMAND"`를 사용하지 마라. 이유: 비용 예측 불가
- Alert 스트림을 생략하지 마라. 이유: Phase 3 Flink Sink와 Phase 4 Lambda 트리거에 필수다

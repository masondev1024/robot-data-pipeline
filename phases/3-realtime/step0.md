# Step 0: flink-terraform

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md` (ADR-007, ADR-009, ADR-010 필수)
- `/docs/research.md` §4 실시간 이상 탐지 고도화 알고리즘
- `/terraform/variables.tf`
- `/terraform/modules/data_pipeline/kinesis.tf` (메인 + Alert KDS 참조)
- `/terraform/modules/data_pipeline/iam.tf` (IRSA 패턴 참조)

## 작업

`terraform/modules/data_pipeline/flink.tf`를 작성하라. Application 모드 + PyFlink + 코드 ZIP S3 업로드 + CloudWatch Logging + 외부화된 threshold property_map 까지 포함한다.

### 포함해야 할 리소스

1. **`aws_iam_role.flink`** — `kinesisanalytics.amazonaws.com` 신뢰 정책.
2. **`aws_iam_role_policy.flink`** — 다음 4개 권한 블록:
   - **KDS Read** (메인 스트림 `aws_kinesis_stream.main.arn`): `GetRecords`, `GetShardIterator`, `DescribeStream`, `DescribeStreamSummary`, `ListShards`, `ListStreams`, `SubscribeToShard`
   - **KDS Write** (alert 스트림 `aws_kinesis_stream.alert.arn`): `PutRecord`, `PutRecords` ← ADR-007 핵심
   - **S3 Write** (`alerts/*` prefix 한정): `PutObject`, `PutObjectAcl`, `AbortMultipartUpload`
   - **S3 Read** (`flink-code/*` prefix): `GetObject` — 앱 코드 ZIP 다운로드용
   - **CloudWatch Logs**: `CreateLogGroup`, `CreateLogStream`, `PutLogEvents`, `DescribeLogGroups`, `DescribeLogStreams`
3. **`aws_cloudwatch_log_group.flink`** — `/aws/kinesis-analytics/${var.project_name}-anomaly-detector`, retention 14일.
4. **`aws_cloudwatch_log_stream.flink`** — log_group은 위 리소스.
5. **`aws_s3_object.flink_code`** — 앱 ZIP을 S3에 업로드. 버킷은 `data.aws_s3_bucket.existing` (이미 다른 모듈에 정의됨), key는 `flink-code/anomaly_detection.zip`. `source = "${path.module}/../../../flink/anomaly_detection.zip"`, `etag = filemd5(...)` — 코드 변경 시 자동 재배포.
6. **`aws_kinesisanalyticsv2_application.detector`** — 앱명 `${var.project_name}-anomaly-detector`, runtime `FLINK-1_18`:
   - `application_code_configuration.code_content.s3_content_location` → 위 S3 오브젝트
   - `application_code_configuration.code_content_type = "ZIPFILE"`
   - `flink_application_configuration.checkpoint_configuration` (configuration_type = "CUSTOM", checkpointing_enabled = true, checkpoint_interval = 60000)
   - `flink_application_configuration.monitoring_configuration` (configuration_type = "CUSTOM", log_level = "INFO", metrics_level = "APPLICATION")
   - `flink_application_configuration.parallelism_configuration` (configuration_type = "CUSTOM", parallelism = 1, parallelism_per_kpu = 1, auto_scaling_enabled = true)
   - **Property Group 1 — `kinesis.analytics.flink.run.options`:**
     - `python = "anomaly_detection.py"`
     - `jarfile = "lib/flink-sql-connector-kinesis-1.18.1.jar"` (ZIP 내 lib/ 경로)
   - **Property Group 2 — `robot-app-config`:**
     - `kinesis.main.stream  = aws_kinesis_stream.main.name`
     - `kinesis.alert.stream = aws_kinesis_stream.alert.name`
     - `s3.alerts.path       = "s3://${data.aws_s3_bucket.existing.bucket}/alerts/"`
     - `aws.region           = var.aws_region`
     - `zscore.threshold     = "3.0"`
     - `zscore.sigma.floor   = "0.5"`
     - `load.ratio.threshold = "1.8"`
     - `load.ratio.min.temp  = "85.0"`
   - `cloudwatch_logging_options.log_stream_arn` → 위 log stream
   - `start_application = true`

### 빌드 산출물 의존성

- `flink/anomaly_detection.zip`은 step 1에서 빌드되어 존재한다고 가정한다. **terraform plan 단계에서 ZIP이 없을 수 있으므로**, `aws_s3_object.flink_code` 리소스 위에 다음 주석을 달아라:
  ```hcl
  # NOTE: anomaly_detection.zip is built by `flink/build.sh` (step 1).
  # Run `bash flink/build.sh` before `terraform apply`.
  ```

## Acceptance Criteria

```bash
terraform fmt -check -recursive terraform/modules/
grep -q "robot-anomaly-detector" terraform/modules/data_pipeline/flink.tf && echo "OK: app name"
grep -q "robot-anomaly-alert-stream\|aws_kinesis_stream.alert" terraform/modules/data_pipeline/flink.tf && echo "OK: alert stream wiring"
grep -q "PutRecord" terraform/modules/data_pipeline/flink.tf && echo "OK: alert stream write permission"
grep -q "ZIPFILE" terraform/modules/data_pipeline/flink.tf && echo "OK: code packaging type"
grep -q "zscore.threshold" terraform/modules/data_pipeline/flink.tf && echo "OK: zscore threshold externalized"
grep -q "load.ratio.threshold" terraform/modules/data_pipeline/flink.tf && echo "OK: load ratio threshold externalized"
grep -q "cloudwatch_logging_options" terraform/modules/data_pipeline/flink.tf && echo "OK: cloudwatch logging"
grep -q "start_application" terraform/modules/data_pipeline/flink.tf && echo "OK: application auto-start"
```

## 검증 절차

1. 위 AC 커맨드를 모두 실행하여 9건 모두 OK 확인.
2. 아키텍처 체크리스트:
   - Flink 앱 이름이 `${var.project_name}-anomaly-detector` (= `robot-telemetry-anomaly-detector`)인가?
   - IAM Role에 KDS Read(메인) + KDS Write(alert) + S3 Write(alerts/) + S3 Read(flink-code/) + CloudWatch Logs 5종 권한이 모두 있는가?
   - `code_content_type = "ZIPFILE"`이고 S3 오브젝트가 `flink-code/anomaly_detection.zip`을 가리키는가?
   - `robot-app-config` property group에 6개 외부화 threshold/설정 키가 모두 있는가?
   - CloudWatch Log Group/Stream이 정의되고 application의 `cloudwatch_logging_options`가 이를 참조하는가?
3. `phases/3-realtime/index.json` step 0 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "flink.tf: Application 모드 + PyFlink + S3 코드 ZIP + CloudWatch + 외부화 threshold(zscore=3.0, load_ratio=1.8)"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- Flink IAM Role에 Alert Stream Write 권한을 빠뜨리지 마라. 이유: Flink가 이상 감지 결과를 `robot-anomaly-alert-stream`으로 Sink해야 한다 (ADR-007).
- threshold 값(`3.0`, `1.8`, `85.0` 등)을 **PyFlink 코드 안에 hardcoding 하지 마라**. 이유: 운영 튜닝 시 코드 재빌드/재배포 발생. property_map으로 외부화하는 것이 ADR-009의 명시 결정.
- S3 버킷 리소스를 신규 생성하지 마라. 이유: 기존 버킷(`de-ai-06-827913617635-ap-northeast-2-an`) 사용. `data "aws_s3_bucket"` 참조만 한다.
- Studio Notebook(`aws_kinesisanalyticsv2_application` runtime `ZEPPELIN-FLINK-3_0`) 모드를 쓰지 마라. 이유: ADR-010이 Application 모드 + PyFlink로 결정.
- `start_application = false`로 두지 마라. 이유: 인프라 배포 즉시 스트림 처리 시작이 운영 의도. 수동 시작은 운영 휴먼 에러 위험.

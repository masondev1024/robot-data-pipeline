# Step 0: data-pipeline-iam

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md`
- `/terraform/variables.tf`
- `/terraform/eks_and_iam.tf`
- `/terraform/modules/data_pipeline/variables.tf`

## 작업

`terraform/modules/data_pipeline/iam.tf`를 작성하라.

### Generator IRSA Role (EKS Pod → Kinesis)
- `aws_iam_role`: OIDC Provider 신뢰 Assume Role Policy
  - `eks_oidc_provider_arn`, `eks_oidc_issuer_url`은 모듈 변수로 수신
  - Condition: `sub = "system:serviceaccount:**robot-telemetry**:generator-sa"` (네임스페이스 주의)
- `aws_iam_role_policy`: 아래 두 스트림 모두에 권한 부여
  - `robot-telemetry-stream`: `kinesis:PutRecord`, `kinesis:PutRecords`, `kinesis:DescribeStream`
  - `robot-anomaly-alert-stream`: `kinesis:PutRecord`, `kinesis:PutRecords`
  - Resource ARN은 placeholder 변수 사용 (`var.kinesis_main_stream_arn`, `var.kinesis_alert_stream_arn`)

### Firehose Delivery Role (Firehose → S3)
- `aws_iam_role` (`firehose_delivery_role`): `firehose.amazonaws.com` 신뢰
- `aws_iam_role_policy`:
  - S3: `s3:PutObject`, `s3:GetBucketLocation`, `s3:ListBucket`, `s3:AbortMultipartUpload`
  - Glue: `glue:GetTable`, `glue:GetTableVersion`, `glue:GetTableVersions` (Format Conversion 필수)
  - S3 버킷은 `data "aws_s3_bucket" "existing" { bucket = "de-ai-06-827913617635-ap-northeast-2-an" }`로 참조

### `modules/data_pipeline/variables.tf` 업데이트
```hcl
variable "eks_oidc_provider_arn"      {}
variable "eks_oidc_issuer_url"        {}
variable "kinesis_main_stream_arn"    { default = "" }
variable "kinesis_alert_stream_arn"   { default = "" }
```

## Acceptance Criteria

```bash
terraform fmt -check -recursive terraform/modules/
grep -q "robot-telemetry:generator-sa" terraform/modules/data_pipeline/iam.tf && echo "OK: namespace"
grep -q "robot-anomaly-alert" terraform/modules/data_pipeline/iam.tf && echo "OK: alert stream IAM"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - IRSA Condition 네임스페이스가 `robot-telemetry`인가? (`default`가 아닌가?)
   - Generator IAM Policy에 alert stream 권한이 포함되어 있는가?
   - Firehose Role Policy에 Glue 권한이 있는가?
   - S3 버킷이 `data` 소스로 참조되는가?
3. `phases/1-ingestion/index.json` step 0 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "iam.tf: Generator IRSA(ns=robot-telemetry, main+alert stream), Firehose Role(S3+Glue)"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- IRSA Condition 네임스페이스를 `default`로 쓰지 마라. 이유: 앱 배포 네임스페이스는 `robot-telemetry`이므로 `default`로 하면 IRSA 인증이 실패한다
- S3 버킷을 `aws_s3_bucket` 리소스로 생성하지 마라. 이유: 사전 생성된 버킷이다
- Alert Stream IAM 권한을 생략하지 마라. 이유: Flink가 이상 감지 시 Generator가 아닌 별도 경로지만, 추후 확장성을 위해 Generator SA에도 Alert Stream 쓰기 권한을 부여한다

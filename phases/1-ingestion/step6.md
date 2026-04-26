# Step 6: s3-lifecycle-athena

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md`
- `/terraform/modules/data_pipeline/variables.tf`
- `/terraform/modules/data_pipeline/kinesis.tf`

## 작업

두 가지 Terraform 리소스를 추가하라.

---

### 1. `terraform/modules/data_pipeline/s3_lifecycle.tf` (신규 파일)

S3 버킷은 사전 생성된 `de-ai-06-827913617635-ap-northeast-2-an`을 `data "aws_s3_bucket"` 으로 참조한다.

```hcl
data "aws_s3_bucket" "main" {
  bucket = var.s3_bucket_name
}

resource "aws_s3_bucket_lifecycle_configuration" "data_lake" {
  bucket = data.aws_s3_bucket.main.id

  rule {
    id     = "bronze-glacier"
    status = "Enabled"
    filter { prefix = "bronze/" }
    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }
  }

  rule {
    id     = "silver-glacier"
    status = "Enabled"
    filter { prefix = "silver/" }
    transition {
      days          = 365
      storage_class = "GLACIER_IR"
    }
  }

  rule {
    id     = "dlq-expire"
    status = "Enabled"
    filter { prefix = "bronze-dlq/" }
    expiration { days = 30 }
  }
}
```

`variables.tf`에 `s3_bucket_name` 변수가 없으면 추가하라:
```hcl
variable "s3_bucket_name" {
  description = "사전 생성된 S3 버킷명 (Terraform으로 생성하지 않음)"
  type        = string
  default     = "de-ai-06-827913617635-ap-northeast-2-an"
}
```

`terraform/main.tf`의 `module "data_pipeline"` 블록에 `s3_bucket_name` 전달이 빠져있다면 추가하라:
```hcl
s3_bucket_name = "de-ai-06-827913617635-ap-northeast-2-an"
```

---

### 2. `terraform/modules/data_pipeline/glue.tf` 업데이트 — Athena Workgroup 추가

기존 `glue.tf` 파일 하단에 아래 리소스를 **추가**한다 (기존 내용 변경 금지):

```hcl
resource "aws_athena_workgroup" "main" {
  name = "robot-telemetry-workgroup"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${var.s3_bucket_name}/project-athena-results/"
    }
  }

  tags = {
    Project = var.project_name
  }
}
```

---

## Acceptance Criteria

```bash
terraform fmt -check -recursive terraform/modules/data_pipeline/

test -f terraform/modules/data_pipeline/s3_lifecycle.tf && echo "OK: s3_lifecycle.tf exists"
grep -q "bronze-glacier" terraform/modules/data_pipeline/s3_lifecycle.tf && echo "OK: bronze rule"
grep -q "silver-glacier" terraform/modules/data_pipeline/s3_lifecycle.tf && echo "OK: silver rule"
grep -q "dlq-expire" terraform/modules/data_pipeline/s3_lifecycle.tf && echo "OK: dlq rule"
grep -q "aws_athena_workgroup" terraform/modules/data_pipeline/glue.tf && echo "OK: athena workgroup"
grep -q "robot-telemetry-workgroup" terraform/modules/data_pipeline/glue.tf && echo "OK: workgroup name"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - S3 버킷이 `data "aws_s3_bucket"` 참조인가? (`aws_s3_bucket` 리소스로 생성하지 않음)
   - Lifecycle 규칙 3개가 모두 있는가? (bronze@90d, silver@365d, dlq@30d)
   - Athena Workgroup 이름이 `robot-telemetry-workgroup`인가?
   - `output_location`이 `project-athena-results/` prefix를 가리키는가?
3. `phases/1-ingestion/index.json` step 6 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "s3_lifecycle.tf: bronze@90d/silver@365d/dlq@30d. glue.tf+: Athena Workgroup robot-telemetry-workgroup"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- S3 버킷을 `aws_s3_bucket` 리소스로 재생성하지 마라. 이유: 사전 생성된 버킷이다
- `gold/` prefix에 Lifecycle 규칙을 추가하지 마라. 이유: Gold 데이터는 영구 보관
- 기존 `glue.tf` 내용을 지우거나 변경하지 마라. 이유: Glue DB/Table은 이미 완성됨

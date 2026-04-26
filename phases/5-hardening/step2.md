# Step 2: observability-completion (Generator OTEL + X-Ray Group)

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/k8s/api/deployment.yaml` (`instrumentation.opentelemetry.io/inject-python` 어노테이션 패턴 확인 — step 0 산출물)
- `/k8s/generator/` 디렉토리 (Generator Deployment 위치)
- `/terraform/modules/data_pipeline/iam.tf` (xray IAM 패턴 — step 0 산출물)
- `/plan.md` Task 5.1 — **읽기만, 수정 금지**

## 작업

### A) Generator Deployment에 OTEL inject-python 어노테이션 추가

`k8s/generator/Deployment.yaml`(또는 `deployment.yaml` — 실제 파일명 확인) Pod template metadata.annotations에 다음 추가 (기존 어노테이션 보존):

```yaml
spec:
  template:
    metadata:
      annotations:
        instrumentation.opentelemetry.io/inject-python: "true"
        # ... 기존 어노테이션 유지 ...
```

step 0에서 API에는 이미 적용됐으나 Generator는 누락된 상태. Generator 트래픽이 X-Ray Service Map에 포함되어야 KDS → Flink → Lambda 전 구간 추적 가능.

### B) AWS X-Ray Group Terraform 리소스 신규

`terraform/modules/data_pipeline/xray.tf` 신규 생성 (또는 `iam.tf`에 추가):

```hcl
resource "aws_xray_group" "main" {
  group_name        = "robot-telemetry-traces"
  filter_expression = "service(\"robot-telemetry-api\") OR service(\"robot-telemetry-generator\")"

  insights_configuration {
    insights_enabled      = true
    notifications_enabled = false
  }
}

# Sampling rule — 샘플링 비율 명시 (default보다 보수적)
resource "aws_xray_sampling_rule" "main" {
  rule_name      = "robot-telemetry-sampling"
  priority       = 1000
  reservoir_size = 1
  fixed_rate     = 0.05  # 5% 샘플링 — 10,000 rec/sec 환경에서 비용 통제
  url_path       = "*"
  host           = "*"
  http_method    = "*"
  service_name   = "*"
  service_type   = "*"
  resource_arn   = "*"
  version        = 1
}
```

신규 파일을 만든다면 별도 `xray.tf`로 분리하라 (iam.tf 비대 방지). `data_pipeline/` 모듈 하위에 둔다.

## Acceptance Criteria

```bash
# 1) Generator OTEL annotation
grep -r "instrumentation.opentelemetry.io/inject-python" k8s/generator/ && echo "OK: generator OTEL"
grep -r "instrumentation.opentelemetry.io/inject-python" k8s/api/ && echo "OK: api OTEL (회귀 — step 0에서 적용됨)"

# 2) X-Ray Group Terraform
ls terraform/modules/data_pipeline/xray.tf 2>/dev/null || grep -q "aws_xray_group" terraform/modules/data_pipeline/iam.tf
grep -rq "aws_xray_group" terraform/modules/data_pipeline/ && echo "OK: xray group resource"
grep -rq "robot-telemetry-traces" terraform/modules/data_pipeline/ && echo "OK: group name"
grep -rq "aws_xray_sampling_rule" terraform/modules/data_pipeline/ && echo "OK: sampling rule"
grep -rq 'fixed_rate.*0\.0[0-9]' terraform/modules/data_pipeline/ && echo "OK: low sample rate (cost control)"

# 3) terraform fmt
terraform fmt -check -recursive terraform/modules/data_pipeline/
```

## 검증 절차

1. 위 AC 모두 OK.
2. 아키텍처 체크리스트:
   - Generator + API 둘 다 `inject-python: "true"` 어노테이션이 있는가?
   - X-Ray Group filter_expression이 두 서비스를 모두 커버하는가?
   - Sampling rule fixed_rate ≤ 0.1 (10%) 인가? (비용 통제)
3. `phases/5-hardening/index.json` step 2 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "k8s/generator OTEL inject-python annotation + xray.tf (Group robot-telemetry-traces + sampling 5%)"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

### 🚨 메타 파일 보호 (반드시 준수)

- **`/plan.md`(프로젝트 루트의 master plan)을 절대 수정/덮어쓰기/삭제하지 마라.** 본 step의 출력 산출물은 오직 `k8s/generator/Deployment.yaml`(또는 `deployment.yaml` — 어노테이션 추가만), `terraform/modules/data_pipeline/xray.tf`(신규 또는 `iam.tf`에 통합), 그리고 `phases/5-hardening/index.json`(step 2 entry만) 3종이다.
- 프로젝트 루트의 `*.md` 어떤 것도 수정하지 마라.
- 다른 step 디렉토리나 docs를 수정하지 마라.
- `iam.tf`의 기존 IRSA Role/Policy를 삭제하지 마라 — 어떤 변경이든 *추가*만.

### 구현 규칙

- Sampling rule을 `fixed_rate = 1.0`(100%)으로 두지 마라. 이유: 10,000 rec/sec 환경에서 X-Ray 비용 폭증. 5~10%가 권장.
- `aws_xray_group` 리소스를 Generator/API 외 다른 서비스명으로 한정하지 마라. 이유: 본 프로젝트의 추적 대상은 두 서비스 + 그 사이 KDS/Flink/Lambda.
- Generator OTEL annotation을 `inject-java: "true"`로 두지 마라. 이유: Generator는 Python(`asyncio` 기반).
- 기존 step 0의 API OTEL annotation을 변경하거나 제거하지 마라.

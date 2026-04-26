# Step 0: observability

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/terraform/addons.tf` (기존 Helm 배포 패턴 확인)
- `/k8s/api/deployment.yaml` (기존 Pod 어노테이션 패턴 확인)
- `/k8s/generator/` (Generator Deployment 구조 확인)

## 작업

ADOT Operator Helm 배포 + X-Ray 연동 + Grafana Observability 대시보드를 구성하라.

### `terraform/addons.tf` — ADOT Operator 추가

```hcl
resource "helm_release" "adot_operator" {
  name             = "adot-operator"
  repository       = "https://aws.github.io/eks-charts"
  chart            = "aws-otel-operator"
  namespace        = "monitoring"
  create_namespace = false
  version          = "0.3.0"

  set {
    name  = "manager.env.AWS_REGION"
    value = var.aws_region
  }
}
```

### `terraform/modules/data_pipeline/iam.tf` — X-Ray 권한 추가

기존 Generator IRSA Role과 API IRSA Role에 아래 정책을 추가하라:

```hcl
resource "aws_iam_role_policy" "xray" {
  name = "robot-telemetry-xray-policy"
  role = aws_iam_role.generator_irsa.id  # API IRSA에도 동일 적용

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = [
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords",
        "xray:GetSamplingRules",
        "xray:GetSamplingTargets"
      ]
      Resource = "*"
    }]
  })
}
```

### K8s Deployment 어노테이션 추가

`k8s/api/deployment.yaml`과 `k8s/generator/deployment.yaml`의 Pod 템플릿에 추가:

```yaml
annotations:
  instrumentation.opentelemetry.io/inject-python: "true"
```

### `grafana/dashboards/observability.json`

아래 패널을 포함하는 Grafana 대시보드 JSON을 작성하라:
- **Endpoint Latency**: `/api/chat`, `/api/predict` P50/P95/P99 레이턴시 시계열
- **Error Rate**: 5xx 응답 비율 (%)
- **Generator → Kinesis 전송 지연**: PutRecords 레이턴시 평균
- **Service Map**: X-Ray 서비스 맵 iframe 또는 패널

## Acceptance Criteria

```bash
terraform fmt -check -recursive terraform/
grep -q "adot-operator" terraform/addons.tf && echo "OK: ADOT Helm"
grep -q "xray:PutTraceSegments" terraform/modules/data_pipeline/iam.tf && echo "OK: X-Ray IAM"
grep -q "inject-python" k8s/api/deployment.yaml && echo "OK: API ADOT annotation"
grep -q "inject-python" k8s/generator/deployment.yaml && echo "OK: Generator ADOT annotation"
ls grafana/dashboards/observability.json && echo "OK: Observability dashboard"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - ADOT Operator가 `monitoring` 네임스페이스에 배포되는가?
   - Generator와 API Pod 모두 OTEL 자동 계측 어노테이션이 있는가?
   - IAM Role에 X-Ray 4개 액션이 포함되어 있는가?
   - Grafana 대시보드에 레이턴시 + 에러율 패널이 있는가?
3. `phases/5-hardening/index.json` step 0 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "ADOT Operator Helm + X-Ray IAM + OTEL 어노테이션 + observability.json 대시보드 작성"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- X-Ray SDK를 코드에 직접 임포트하지 마라. 이유: ADOT 사이드카가 자동 계측하므로 코드 변경 없음
- `monitoring` 네임스페이스를 새로 생성하지 마라. 이유: Phase 4에서 Grafana 배포 시 이미 생성됨

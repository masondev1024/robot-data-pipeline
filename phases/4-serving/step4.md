# Step 4: alb-ingresses (Grafana + API ALB Ingress + admin 비밀번호 sensitive 변수화)

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md` (네임스페이스 표준: `robot-telemetry`, `monitoring`)
- `/docs/ADR.md` (ADR-006: Grafana Helm)
- `/terraform/addons.tf` (step 1 산출물 — Grafana Helm release 위치, 보강 대상)
- `/terraform/variables.tf` (sensitive 변수 패턴 참조)
- `/k8s/api/deployment.yaml` (step 2 산출물 — API Service 이름·port 확인)
- `/plan.md` Task 4.2/4.3 ALB Ingress 섹션 — **읽기만, 수정 금지**

## 작업

### A) `k8s/monitoring/grafana-ingress.yaml` 신규 작성

- 네임스페이스: `monitoring`
- annotation:
  - `kubernetes.io/ingress.class: alb`
  - `alb.ingress.kubernetes.io/scheme: internet-facing`
  - `alb.ingress.kubernetes.io/target-type: ip`
  - `alb.ingress.kubernetes.io/listen-ports: '[{"HTTP":80}]'`
- backend service: Grafana Helm chart가 만드는 Service 이름 (보통 `grafana`), port 80
- path: `/` (전체 경로 forward)
- `k8s/monitoring/` 디렉토리가 없으면 신규 생성.

### B) `k8s/api/api-ingress.yaml` 신규 작성

- 네임스페이스: `robot-telemetry`
- 동일 ALB annotation 패턴
- backend service: step 2의 `deployment.yaml`이 만든 Service 이름 (`robot-telemetry-api` 또는 그에 준하는 명칭) — `deployment.yaml`을 직접 읽고 일치시켜라
- path: `/`

### C) `terraform/addons.tf` Grafana Helm release 보강

기존 `aws_helm_release "grafana"` 블록을 찾아 다음 두 가지를 정정:

1. **adminPassword sensitive 변수화** — 현재 하드코딩(예: `"admin"`)이라면 다음으로 교체:
   ```hcl
   set {
     name  = "adminPassword"
     value = var.grafana_admin_password
   }
   ```

2. **`terraform/variables.tf`에 변수 선언 추가** (없을 경우):
   ```hcl
   variable "grafana_admin_password" {
     description = "Grafana admin password (loaded from Secrets Manager via External Secrets Operator in production)"
     type        = string
     sensitive   = true
   }
   ```

기존 다른 set 블록(`service.type`, `grafana.ini.security.allow_embedding` 등)은 **삭제하지 말고 그대로 보존**.

## Acceptance Criteria

```bash
# 1) 파일 존재
ls k8s/monitoring/grafana-ingress.yaml k8s/api/api-ingress.yaml

# 2) ALB annotation
grep -q "kubernetes.io/ingress.class: alb" k8s/monitoring/grafana-ingress.yaml && echo "OK: grafana ingress class"
grep -q "kubernetes.io/ingress.class: alb" k8s/api/api-ingress.yaml && echo "OK: api ingress class"
grep -q "internet-facing" k8s/monitoring/grafana-ingress.yaml && echo "OK: grafana scheme"
grep -q "internet-facing" k8s/api/api-ingress.yaml && echo "OK: api scheme"

# 3) namespace
grep -q "namespace: monitoring" k8s/monitoring/grafana-ingress.yaml && echo "OK: grafana ns"
grep -q "namespace: robot-telemetry" k8s/api/api-ingress.yaml && echo "OK: api ns"

# 4) sensitive 변수
grep -q "var.grafana_admin_password" terraform/addons.tf && echo "OK: addons.tf var ref"
grep -A 3 'variable "grafana_admin_password"' terraform/variables.tf | grep -q "sensitive\s*=\s*true" && echo "OK: sensitive variable"

# 5) terraform fmt
terraform fmt -check terraform/addons.tf terraform/variables.tf
```

## 검증 절차

1. 위 AC 커맨드 모두 OK.
2. 아키텍처 체크리스트:
   - 두 Ingress가 모두 ALB + internet-facing인가?
   - backend service 이름이 step 1/2 산출물의 실제 Service 이름과 일치하는가?
   - `grafana_admin_password`가 `sensitive = true`로 선언됐는가?
   - 기존 addons.tf 다른 set 블록(allow_embedding 등)이 보존됐는가?
3. `phases/4-serving/index.json` step 4 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "ALB Ingress 2종(Grafana monitoring ns + API robot-telemetry ns) + grafana_admin_password sensitive 변수화"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

### 🚨 메타 파일 보호 (반드시 준수)

- **`/plan.md` 절대 수정/덮어쓰기/삭제 금지.** 본 step의 출력 산출물은 오직 `k8s/monitoring/grafana-ingress.yaml`(신규), `k8s/api/api-ingress.yaml`(신규), `terraform/addons.tf`(set 블록 정정만), `terraform/variables.tf`(변수 추가만), 그리고 `phases/4-serving/index.json`(step 4 entry만) 5종이다.
- 프로젝트 루트의 `*.md` 어떤 것도 수정하지 마라.
- 다른 step 디렉토리나 docs를 수정하지 마라.
- `terraform/addons.tf`의 EKS addon 다른 helm_release(예: ALB Controller, ArgoCD)를 삭제하지 마라.

### 구현 규칙

- Grafana Service를 `LoadBalancer`로 노출하지 마라. 이유: ClusterIP + ALB Ingress 패턴 (비용 절약 + ALB 일관성).
- `adminPassword`를 `"admin"` 같은 default literal로 두지 마라. 이유: production 환경에서 사용자 컨트롤. 단, 본 step에서 var 참조까지만 — Secrets Manager 연동(External Secrets Operator)은 향후 별도 step.
- ingress.class를 `nginx`나 다른 controller로 두지 마라. 이유: 본 클러스터는 AWS Load Balancer Controller 기반.
- TLS/HTTPS listener는 본 step에 포함하지 마라. 이유: ACM cert 발급은 도메인 등록 후 별도 단계. 일단 HTTP listener로 시작 — `listen-ports: '[{"HTTP":80}]'`.

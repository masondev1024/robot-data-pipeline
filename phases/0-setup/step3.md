# Step 3: karpenter-addons

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/terraform/variables.tf`
- `/terraform/eks_and_iam.tf`

## 작업

두 파일을 작성하라.

### `terraform/karpenter.tf`
- Karpenter Controller용 IRSA Role 생성 (EC2, SQS, EKS 관련 권한)
- Karpenter SQS Queue 및 EventBridge Rules 생성 (스팟 인터럽션 핸들링용)
- Karpenter Helm Chart 배포 (`aws_helm_release` 리소스)
  - `interruptionQueue` 설정 포함
- `KarpenterNodePool` 및 `EC2NodeClass` 매니페스트는 별도 YAML로 관리하지 말고 `kubectl_manifest` 또는 `helm_release` values로 인라인 처리

### `terraform/addons.tf`
- **AWS Load Balancer Controller**: Helm Chart 배포 + IRSA Role 생성
- **ArgoCD**: Helm Chart 배포 (기본 설정)
- **Airflow**: Helm Chart 배포 (최소 사양)
  - executor: KubernetesExecutor
  - webserver / scheduler: 각 1 replica
  - dags: Git-sync 또는 ConfigMap 방식 선택 가능

모든 Helm Release에 아래 두 가지를 반드시 적용하라:

1. **`depends_on`**: EKS 클러스터·노드그룹 생성 완료 보장
2. **[Karpenter 레이스 컨디션 방지] `timeout` + `wait` 설정**:
   ```hcl
   # 모든 aws_helm_release 리소스에 공통 적용
   wait             = true   # Pod Ready 상태까지 대기
   timeout          = 600    # 10분 — Karpenter가 신규 노드를 띄우는 시간 포함
   wait_for_jobs    = true   # Job 완료까지 대기 (Airflow DB 마이그레이션 등)
   ```
   이유: `depends_on`은 Terraform 리소스 생성만 보장하며 EC2 노드 Ready는 보장하지 않는다.
   초기 2노드로 Airflow+Grafana+ArgoCD를 동시 스케줄하면 Karpenter 노드 프로비저닝(~2~3분)
   동안 Pod이 Pending 상태에 머물고, 기본 timeout(300초) 안에 완료되지 않아 Helm 설치가 실패한다.

## Acceptance Criteria

```bash
terraform fmt -check -recursive terraform/
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트를 확인한다:
   - Karpenter IRSA Role이 OIDC Provider ARN을 참조하는가?
   - ALB Controller IRSA Role에 `AWSLoadBalancerControllerIAMPolicy` 상당의 권한이 있는가?
   - Airflow Helm Release에 `depends_on = [aws_eks_node_group.*]`가 있는가?
3. 결과에 따라 `phases/0-setup/index.json`의 step 3을 업데이트한다:
   - 성공 → `"status": "completed"`, `"summary": "terraform/karpenter.tf + addons.tf 생성: Karpenter, ALB Controller, ArgoCD, Airflow Helm"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- `helm_release`에 `create_namespace = true`와 함께 `kubernetes_namespace` 리소스를 중복 생성하지 마라. 이유: 충돌 발생
- Airflow DAG 코드를 이 step에서 작성하지 마라. 이유: Phase 2에서 별도 작성한다

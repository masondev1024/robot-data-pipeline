# Step 2: eks-iam

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md`
- `/terraform/variables.tf`
- `/terraform/network.tf`

## 작업

`terraform/eks_and_iam.tf`를 작성하라.

### EKS 클러스터
- `aws_eks_cluster`: 이름 `var.eks_cluster_name` (`"robot-telemetry-cluster"`)
- Kubernetes 버전 `"1.29"`
- 서브넷: network.tf의 private 서브넷 2개
- `endpoint_public_access = true`, `endpoint_private_access = true`
- **OIDC Provider 필수**: `aws_iam_openid_connect_provider` (IRSA 전제조건)

### EKS 노드그룹
- `aws_eks_node_group`
- 인스턴스 타입: `var.node_instance_type` (`"t3.large"`)
- 스케일링: `desired_size = 2`, `min_size = 2`, `max_size = 4`
- 서브넷: private 서브넷
- 노드그룹 디스크: 50GB

### Kubernetes 네임스페이스 (kubectl_manifest 또는 주석 처리)
아래 네임스페이스를 `kubernetes_namespace` 리소스로 선언하라:
- `robot-telemetry` (Generator, API 서버)
- `airflow`
- `monitoring` (Grafana)

### IAM Roles
- **EKS Cluster Role**: `AmazonEKSClusterPolicy`
- **Node Group Role**: `AmazonEKSWorkerNodePolicy`, `AmazonEKS_CNI_Policy`, `AmazonEC2ContainerRegistryReadOnly`

### Outputs
```hcl
output "eks_cluster_name"     { value = aws_eks_cluster.main.name }
output "eks_cluster_endpoint" { value = aws_eks_cluster.main.endpoint }
output "eks_oidc_provider_arn"{ value = aws_iam_openid_connect_provider.eks.arn }
output "eks_oidc_issuer_url"  { value = aws_eks_cluster.main.identity[0].oidc[0].issuer }
```

## Acceptance Criteria

```bash
terraform fmt -check -recursive terraform/
grep -q "robot-telemetry-cluster" terraform/eks_and_iam.tf && echo "OK: cluster name"
grep -q "t3.large" terraform/eks_and_iam.tf && echo "OK: node type"
grep -q "openid_connect_provider" terraform/eks_and_iam.tf && echo "OK: OIDC provider"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - OIDC Provider 리소스가 있는가? (IRSA 전제조건)
   - 노드 타입이 `t3.large`인가?
   - desired_size가 2인가? (Airflow + Grafana 최소 2노드 필요)
   - output에 `eks_oidc_provider_arn`, `eks_oidc_issuer_url`이 있는가?
3. `phases/0-setup/index.json` step 2 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "eks_and_iam.tf: robot-telemetry-cluster, t3.large×2, OIDC Provider, 네임스페이스 3개"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- 노드 타입을 `t3.medium`으로 쓰지 마라. 이유: Airflow Scheduler + Webserver + Grafana를 동시에 구동하려면 t3.large(8GB) 필요
- OIDC Provider를 생략하지 마라. 이유: Phase 1의 IRSA(Generator/API → AWS 서비스)가 이를 전제로 한다
- `desired_size = 1`로 설정하지 마라. 이유: 단일 노드면 Airflow + Grafana가 리소스 경합으로 Pending 상태가 된다

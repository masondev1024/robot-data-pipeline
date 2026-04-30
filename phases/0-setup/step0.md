# Step 0: terraform-root

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md`
- `/docs/PRD.md`

## 작업

`terraform/` 디렉토리를 생성하고 아래 두 파일을 작성하라.

### `terraform/providers.tf`
- AWS Provider 설정. `var.aws_region` 참조
- `required_version >= "1.5.0"`, `required_providers { aws = "~> 5.0" }` 포함
- Backend 블록은 작성하지 않는다 (로컬 state 사용)

### `terraform/variables.tf`
아래 변수를 **확정값 그대로** 선언하라:

```hcl
variable "aws_region"          { default = "eu-west-1" }
variable "project_name"        { default = "robot-telemetry" }
variable "eks_cluster_name"    { default = "robot-telemetry-cluster" }
variable "vpc_cidr"            { default = "10.0.32.0/16" }
variable "node_instance_type"  { default = "t3.large" }
variable "environment"         { default = "dev" }
variable "github_owner"        { default = "masondev1024" }
variable "github_repo"         { default = "robot-data-pipeline" }
variable "github_branch"       { default = "main" }
```

AWS 자격증명(`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)은 **변수로 선언하지 마라**. `.env`의 환경변수로만 관리한다.

## Acceptance Criteria

```bash
terraform fmt -check -recursive terraform/
grep -q 'robot-telemetry-cluster' terraform/variables.tf && echo "OK: cluster name"
grep -q '10.0.32.0/16' terraform/variables.tf && echo "OK: VPC CIDR"
grep -q 't3.large' terraform/variables.tf && echo "OK: node type"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - `variables.tf`에 하드코딩된 AWS 자격증명이 없는가?
   - `eks_cluster_name` = `"robot-telemetry-cluster"` 인가?
   - `vpc_cidr` = `"10.0.32.0/16"` 인가?
   - `node_instance_type` = `"t3.large"` 인가?
3. `phases/0-setup/index.json` step 0 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "terraform/providers.tf + variables.tf 생성: cluster=robot-telemetry-cluster, vpc=10.0.32.0/16, node=t3.large"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- `eks_cluster_name`을 `"robot-telemetry-eks"`나 다른 값으로 쓰지 마라. 이유: plan.md 확정값 `robot-telemetry-cluster`로 고정
- `vpc_cidr`을 `"10.0.0.0/16"`으로 쓰지 마라. 이유: plan.md 확정값 `10.0.32.0/16`
- `node_instance_type`을 `t3.medium`으로 쓰지 마라. 이유: Airflow + Grafana 상시 구동 위해 `t3.large` 필요
- AWS 자격증명을 어떤 `.tf` 파일에도 하드코딩하지 마라

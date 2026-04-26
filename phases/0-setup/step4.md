# Step 4: cicd-module-scaffold

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/terraform/variables.tf`
- `/terraform/eks_and_iam.tf`

## 작업

### `terraform/cicd_gitops.tf`

**ECR Repositories** — 2개 생성:
```hcl
# Generator 컨테이너
resource "aws_ecr_repository" "generator" {
  name = "robot-telemetry-generator"
}

# AI Query API 컨테이너
resource "aws_ecr_repository" "api" {
  name = "robot-telemetry-api"
}
```

**GitHub Actions OIDC**:
- `aws_iam_openid_connect_provider`: `token.actions.githubusercontent.com`
- `aws_iam_role` (GitHub Actions Role): `AssumeRoleWithWebIdentity` 조건
  - `sub` 조건: `"repo:${var.github_owner}/${var.github_repo}:ref:refs/heads/${var.github_branch}"`
- Policy: 두 ECR repo 모두에 Push 권한
  - `ecr:GetAuthorizationToken`, `ecr:BatchCheckLayerAvailability`, `ecr:PutImage`, `ecr:InitiateLayerUpload`, `ecr:UploadLayerPart`, `ecr:CompleteLayerUpload`

**Outputs**:
```hcl
output "ecr_generator_url" { value = aws_ecr_repository.generator.repository_url }
output "ecr_api_url"       { value = aws_ecr_repository.api.repository_url }
```

### `terraform/modules/data_pipeline/` 스캐폴딩

아래 파일들을 생성하되 **내용은 주석만** 포함한다. Phase 1에서 채운다:
- `terraform/modules/data_pipeline/iam.tf`     — `# Phase 1 Step 0에서 작성`
- `terraform/modules/data_pipeline/kinesis.tf` — `# Phase 1 Step 1~3에서 작성`
- `terraform/modules/data_pipeline/glue.tf`    — `# Phase 1 Step 2에서 작성`
- `terraform/modules/data_pipeline/variables.tf` — 빈 파일 또는 기본 변수 선언

### `terraform/main.tf`
`module "data_pipeline"` 블록을 선언하되, 아직 구현되지 않은 변수는 주석 처리:
```hcl
module "data_pipeline" {
  source = "./modules/data_pipeline"
  # eks_oidc_provider_arn = module.eks.eks_oidc_provider_arn
  # eks_oidc_issuer_url   = module.eks.eks_oidc_issuer_url
}
```

## Acceptance Criteria

```bash
terraform fmt -check -recursive terraform/
ls terraform/modules/data_pipeline/
# iam.tf kinesis.tf glue.tf variables.tf 네 파일이 있어야 한다
grep -q "robot-telemetry-generator" terraform/cicd_gitops.tf && echo "OK: generator ECR"
grep -q "robot-telemetry-api" terraform/cicd_gitops.tf && echo "OK: api ECR"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - ECR repo가 generator + api 2개 모두 있는가?
   - GitHub Actions OIDC의 `sub` 조건이 `masondev1024/robot-telemetry-platform`으로 제한되는가?
   - `modules/data_pipeline/` 하위 4개 파일이 존재하는가? (glue.tf 포함)
3. `phases/0-setup/index.json` step 4 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "cicd_gitops.tf: ECR(generator+api), GitHub OIDC. modules/data_pipeline/ 4파일 스캐폴드"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- ECR repo를 generator 1개만 생성하지 마라. 이유: Phase 4의 AI Query API도 `robot-telemetry-api` ECR이 필요하다
- `modules/data_pipeline/glue.tf` 스캐폴드를 생략하지 마라. 이유: Phase 1 Step 2가 이 파일을 편집한다
- 실제 리소스를 `iam.tf`, `kinesis.tf`, `glue.tf`에 작성하지 마라. 이유: Phase 1 전담 작업이다

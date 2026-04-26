# Step 5: github-actions-workflows

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md`
- `/terraform/cicd_gitops.tf`
- `/terraform/variables.tf`

## 작업

GitHub Actions CI/CD 워크플로우 3개를 작성하라. 모든 AWS 자격증명은 OIDC 방식으로 처리하며, 하드코딩 금지.

---

### `.github/workflows/terraform.yml`

**트리거**: PR에서 `terraform/` 경로 변경 시 plan 실행 + PR 코멘트 게시. `main` 브랜치 push 시 apply 실행.

```yaml
name: terraform

on:
  push:
    branches: [main]
    paths: ['terraform/**']
  pull_request:
    paths: ['terraform/**']

permissions:
  id-token: write
  contents: read
  pull-requests: write

jobs:
  plan:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: eu-west-1
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.7.0"
      - name: Terraform Init
        run: terraform init
        working-directory: terraform/
      - name: Terraform Plan
        id: plan
        run: terraform plan -no-color 2>&1
        working-directory: terraform/
        continue-on-error: true
      - name: Post Plan Comment
        uses: actions/github-script@v7
        with:
          script: |
            const output = `## Terraform Plan 결과\n\`\`\`\n${{ steps.plan.outputs.stdout }}\n\`\`\`\n*Triggered by: @${{ github.actor }}*`;
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: output
            });
      - name: Plan Status
        if: steps.plan.outcome == 'failure'
        run: exit 1

  apply:
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: eu-west-1
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.7.0"
      - run: terraform init
        working-directory: terraform/
      - run: terraform apply -auto-approve
        working-directory: terraform/
```

---

### `.github/workflows/k8s-deploy.yml`

**트리거**: `main` 브랜치 push 시 `k8s/` 또는 `src/` 경로 변경 감지. Docker 이미지 빌드 → ECR Push → Lambda ZIP 빌드 → kubectl apply.

```yaml
name: k8s-deploy

on:
  push:
    branches: [main]
    paths:
      - 'k8s/**'
      - 'src/**'

permissions:
  id-token: write
  contents: read

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: eu-west-1

      - name: Login to ECR
        id: ecr-login
        uses: aws-actions/amazon-ecr-login@v2

      - name: Build and push Generator image
        env:
          ECR_REGISTRY: ${{ steps.ecr-login.outputs.registry }}
          IMAGE_TAG: ${{ github.sha }}
        run: |
          if [ -f src/generator/Dockerfile ]; then
            docker build -t $ECR_REGISTRY/robot-telemetry-generator:$IMAGE_TAG src/generator/
            docker push $ECR_REGISTRY/robot-telemetry-generator:$IMAGE_TAG
            docker tag $ECR_REGISTRY/robot-telemetry-generator:$IMAGE_TAG $ECR_REGISTRY/robot-telemetry-generator:latest
            docker push $ECR_REGISTRY/robot-telemetry-generator:latest
          fi

      - name: Build and push API image
        env:
          ECR_REGISTRY: ${{ steps.ecr-login.outputs.registry }}
          IMAGE_TAG: ${{ github.sha }}
        run: |
          if [ -f src/api/Dockerfile ]; then
            docker build -t $ECR_REGISTRY/robot-telemetry-api:$IMAGE_TAG src/api/
            docker push $ECR_REGISTRY/robot-telemetry-api:$IMAGE_TAG
            docker tag $ECR_REGISTRY/robot-telemetry-api:$IMAGE_TAG $ECR_REGISTRY/robot-telemetry-api:latest
            docker push $ECR_REGISTRY/robot-telemetry-api:latest
          fi

      - name: Build Lambda ZIP
        run: |
          if [ -f src/lambda/alert_handler.py ]; then
            mkdir -p src/lambda/dist
            if [ -f src/lambda/requirements.txt ]; then
              pip install -r src/lambda/requirements.txt -t src/lambda/dist/ --quiet
            fi
            cp src/lambda/alert_handler.py src/lambda/dist/
            cd src/lambda && zip -r alert_handler.zip dist/ -x "*.pyc" -x "*/__pycache__/*"
            echo "Lambda ZIP built: $(du -sh alert_handler.zip | cut -f1)"
          fi

      - name: Update kubeconfig
        run: aws eks update-kubeconfig --name robot-telemetry-cluster --region eu-west-1

      - name: Apply Kubernetes manifests
        run: |
          if [ -d k8s/ ] && [ "$(ls -A k8s/)" ]; then
            kubectl apply -f k8s/ --recursive
          fi

      - name: Restart deployments
        run: |
          kubectl rollout restart deployment/robot-telemetry-generator -n robot-telemetry 2>/dev/null || true
          kubectl rollout restart deployment/robot-telemetry-api -n robot-telemetry 2>/dev/null || true
```

---

### `.github/workflows/post-deploy.yml`

**트리거**: `k8s-deploy` 워크플로우 완료 후 실행. ALB DNS 확정까지 폴링(최대 20회 × 15초) 후 SSM에 저장. Lambda와 API Pod는 런타임에 SSM을 읽으므로 이 단계 이후 서비스가 올바른 URL을 사용한다.

```yaml
name: post-deploy

on:
  workflow_run:
    workflows: ["k8s-deploy"]
    types: [completed]
    branches: [main]

permissions:
  id-token: write
  contents: read

jobs:
  store-dns:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    steps:
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: eu-west-1

      - name: Update kubeconfig
        run: aws eks update-kubeconfig --name robot-telemetry-cluster --region eu-west-1

      - name: Wait for API ALB DNS
        id: api-dns
        run: |
          DNS=""
          for i in $(seq 1 20); do
            DNS=$(kubectl get ingress robot-telemetry-api-ingress \
              -n robot-telemetry \
              -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
            if [ -n "$DNS" ] && [ "$DNS" != "null" ]; then
              echo "dns=$DNS" >> $GITHUB_OUTPUT
              echo "API ALB DNS 확정: $DNS"
              break
            fi
            echo "[$i/20] API ALB 대기 중... (15초)"
            sleep 15
          done
          if [ -z "$DNS" ]; then
            echo "API ALB DNS 확정 실패 (300초 초과)"
            exit 1
          fi

      - name: Wait for Grafana ALB DNS
        id: grafana-dns
        run: |
          DNS=""
          for i in $(seq 1 20); do
            DNS=$(kubectl get ingress grafana-ingress \
              -n monitoring \
              -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
            if [ -n "$DNS" ] && [ "$DNS" != "null" ]; then
              echo "dns=$DNS" >> $GITHUB_OUTPUT
              echo "Grafana ALB DNS 확정: $DNS"
              break
            fi
            echo "[$i/20] Grafana ALB 대기 중... (15초)"
            sleep 15
          done
          if [ -z "$DNS" ]; then
            echo "Grafana ALB DNS 확정 실패 (300초 초과)"
            exit 1
          fi

      - name: Store DNS values to SSM
        run: |
          aws ssm put-parameter \
            --name "/robot-telemetry/portal-url" \
            --value "http://${{ steps.api-dns.outputs.dns }}" \
            --type String \
            --overwrite
          aws ssm put-parameter \
            --name "/robot-telemetry/grafana-url" \
            --value "http://${{ steps.grafana-dns.outputs.dns }}" \
            --type String \
            --overwrite
          echo "SSM 저장 완료:"
          echo "  /robot-telemetry/portal-url = http://${{ steps.api-dns.outputs.dns }}"
          echo "  /robot-telemetry/grafana-url = http://${{ steps.grafana-dns.outputs.dns }}"
```

---

## Acceptance Criteria

```bash
ls .github/workflows/
# terraform.yml  k8s-deploy.yml  post-deploy.yml 세 파일이 있어야 한다

grep -q "role-to-assume" .github/workflows/terraform.yml && echo "OK: OIDC auth in terraform.yml"
grep -q "role-to-assume" .github/workflows/k8s-deploy.yml && echo "OK: OIDC auth in k8s-deploy.yml"
grep -q "role-to-assume" .github/workflows/post-deploy.yml && echo "OK: OIDC auth in post-deploy.yml"
grep -q "ssm put-parameter" .github/workflows/post-deploy.yml && echo "OK: SSM store in post-deploy.yml"
grep -q "terraform apply" .github/workflows/terraform.yml && echo "OK: apply job exists"
grep -q "kubectl apply" .github/workflows/k8s-deploy.yml && echo "OK: kubectl apply exists"
grep -q "AWS_ACCESS_KEY_ID\|AWS_SECRET_ACCESS_KEY" .github/workflows/*.yml && echo "FAIL: hardcoded credentials found" || echo "OK: no hardcoded credentials"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - 모든 AWS 자격증명이 `role-to-assume` (OIDC) 방식인가? (`AWS_ACCESS_KEY_ID` 하드코딩 없음)
   - `terraform.yml`의 apply job에 `environment: production` 설정이 있는가? (사람 승인 Gate)
   - `post-deploy.yml`이 `workflow_run` 트리거로 `k8s-deploy` 완료 후 자동 실행되는가?
   - `post-deploy.yml`에 ALB DNS 폴링 로직이 있는가? (최대 20회 × 15초)
3. `phases/0-setup/index.json`의 step 5 업데이트:
   - 성공 → `"status": "completed"`, `"summary": ".github/workflows/: terraform.yml(plan→PR코멘트→apply), k8s-deploy.yml(ECR빌드+kubectl), post-deploy.yml(ALB DNS폴링→SSM저장)"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`를 workflow에 직접 입력하지 마라. 이유: cicd_gitops.tf에 GitHub OIDC 역할이 이미 설정되어 있으므로 role-to-assume만 사용한다.
- `terraform apply -auto-approve`를 plan job에 넣지 마라. 이유: PR에서 plan만 실행하고, apply는 main 브랜치 push + environment 승인 후에만 동작해야 한다.
- `.github/workflows/` 디렉토리 외 파일을 수정하지 마라. 이유: 이 step의 scope은 워크플로우 파일 3개에 한정된다.

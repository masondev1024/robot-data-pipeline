# AWS account portability and deployment contract

## 목적

이 설계는 특정 AWS 계정에서 만든 포트폴리오 인프라를 새 계정으로 이전할 때 기존 account ID, ARN, ECR 주소, bucket, subnet ID가 배포 파일에 남아 잘못된 리소스를 참조하는 문제를 차단합니다.

첫 단계의 완료 조건은 AWS 인프라를 생성하는 것이 아니라 다음 계약을 로컬과 CI에서 증명하는 것입니다.

1. 추적되는 배포 파일에 과거 AWS account ID와 계정 전용 ARN이 없다.
2. 배포에 필요한 계정 종속값은 하나의 명시적 입력 계약을 통해서만 들어온다.
3. 원본 template은 변경하지 않고 임시 rendered artifact를 생성한다.
4. 필수값 누락, 형식 오류, 미치환 placeholder가 있으면 배포 전에 실패한다.
5. GitHub Actions와 로컬 검증이 같은 렌더링 경로를 사용한다.
6. 실제 AWS 접근이 필요한 bootstrap과 production 검증은 별도 단계로 남긴다.

## 범위

### 이번 로컬 단계에 포함

- 안전한 공개 환경변수 template
- account ID, region, bucket, cluster, resource prefix를 정의하는 배포 입력 계약
- Kubernetes와 Helm template 렌더링
- 기존 계정 식별자와 mutable image tag 회귀 차단
- GitHub Actions가 repository variable과 OIDC identity를 입력으로 사용하는 구조
- 신규 계정에서 legacy 비용 절감 스크립트의 오실행 차단
- 렌더러 단위 테스트와 repository-level contract test

### 이번 로컬 단계에서 제외

- AWS 계정 생성과 IAM Identity Center 설정
- remote state bucket과 locking resource의 실제 생성
- GitHub OIDC provider와 deploy role의 실제 생성
- ACM certificate와 DNS 검증
- EKS, Kinesis, Firehose, SageMaker, Bedrock의 실제 배포
- 실제 부하 테스트, SLO 측정, disaster recovery 훈련

제외 항목은 자격증명 또는 비용이 필요한 실행 증거이며, 로컬 구현 완료를 production 검증으로 표현하지 않습니다.

## 선택한 접근

표준 라이브러리 기반의 중앙 렌더러를 사용합니다. 모든 Kubernetes와 Helm 리소스를 신규 Helm chart로 재작성하지 않고, GitHub Actions 안의 임시 `sed` 명령에도 의존하지 않습니다.

이 방식은 기존 운영 자산의 구조를 유지하면서 다음 장점을 제공합니다.

- 동일한 입력 검증을 로컬과 CI에서 재사용
- 원본 파일과 렌더링 결과의 명확한 분리
- AWS 계정 교체 시 수정 지점 축소
- 렌더링 실패를 배포 이전에 재현
- 신규 외부 Python dependency 없이 테스트 가능

## 구성 요소

### 1. 배포 입력 계약

입력은 아래 이름을 사용합니다.

| 변수 | 형식 | 용도 |
|---|---|---|
| `AWS_ACCOUNT_ID` | 12자리 숫자 | ECR과 IAM ARN 생성 |
| `AWS_REGION` | AWS region 형식 | provider, ECR, workload region |
| `PROJECT_NAME` | DNS-compatible name | resource prefix |
| `EKS_CLUSTER_NAME` | Kubernetes/AWS name | kubeconfig와 dashboard dimension |
| `S3_BUCKET_NAME` | S3 bucket name | data lake와 Athena output |
| `IMAGE_TAG` | commit SHA | immutable workload image |

secret 값과 AWS access key는 이 계약에 포함하지 않습니다. Slack webhook, portal credential, Grafana password는 AWS Secrets Manager에서 관리하고, GitHub Actions는 OIDC role ARN만 secret으로 참조합니다.

### 2. Template과 rendered artifact

추적되는 배포 파일은 `__AWS_ACCOUNT_ID__` 같은 제한된 placeholder를 사용합니다. 렌더러는 허용 목록에 있는 placeholder만 치환하고 결과를 사용자가 지정한 임시 디렉터리에 기록합니다.

렌더러는 다음 조건에서 non-zero로 종료합니다.

- 필수 입력이 없음
- account ID가 12자리 숫자가 아님
- region 또는 bucket 형식이 잘못됨
- image tag가 `latest`이거나 commit SHA 형식이 아님
- 렌더링 결과에 `__...__` placeholder가 남음
- 출력 경로가 repository 원본 배포 디렉터리와 겹침

렌더링 과정은 source file을 수정하지 않습니다.

### 3. GitHub Actions 데이터 흐름

```text
GitHub OIDC identity
  -> sts:GetCallerIdentity(account ID)
Repository variables
  -> region / cluster / bucket / project
Git commit
  -> immutable image tag
Validated inputs
  -> renderer
Temporary rendered directory
  -> kubectl / Helm validation and deployment
```

AWS 연결 전 CI는 example 값으로 렌더링과 schema 검증만 실행합니다. 신규 계정 bootstrap 후 실제 deploy job은 OIDC가 반환한 account ID를 사용하며 정적 account ID를 받지 않습니다.

### 4. Legacy 운영 스크립트 경계

기존 `비용절감플랜/up.sh`와 `down.sh`는 과거 계정의 subnet, route table, cluster state를 전제로 하는 복구 도구입니다. 신규 계정 bootstrap 도구로 재사용하지 않습니다.

스크립트는 실행 전에 현재 STS account가 명시적으로 허용된 legacy account와 일치하는지 확인해야 합니다. 계정이 다르거나 STS 확인이 실패하면 AWS 변경 전에 종료합니다. 장기적으로 신규 계정의 정상 수명주기는 Terraform apply/destroy 경로가 담당합니다.

## 보안 경계

- 장기 AWS access key를 repository `.env`의 표준 인증 방식으로 사용하지 않습니다.
- 로컬 작업자는 AWS IAM Identity Center 또는 명시적 `AWS_PROFILE`을 사용합니다.
- GitHub Actions는 access key secret 대신 OIDC를 사용합니다.
- workload는 IRSA를 사용하며 ARN은 렌더링 입력으로 생성합니다.
- renderer는 secret 값을 읽거나 출력하지 않습니다.
- 기존 local Terraform state와 plan은 신규 account state에 import하지 않습니다.
- rendered artifact는 Git에 커밋하지 않습니다.

## 테스트 전략

### 단위 테스트

- 유효한 입력으로 account-specific ARN, ECR URL, bucket 경로가 정확히 생성됨
- 필수 입력 누락 시 실패
- 잘못된 account ID, region, bucket, image tag 거부
- `latest` tag 거부
- 미치환 placeholder 검출
- source tree 비변경 보장

### Repository contract test

- 추적되는 배포 파일에 과거 account ID가 없음
- account-specific ECR URL과 IAM ARN이 template 밖에 없음
- 공개 `.env.example`에 AWS access key와 실제 secret 값이 없음
- deploy workflow가 commit SHA를 image tag로 사용
- quality workflow가 렌더러 테스트를 실행

### 정적 검증

- Python lint와 전체 deterministic test
- Terraform format/init/validate
- rendered Kubernetes YAML parse
- Helm values YAML parse

AWS API, IAM, EKS admission, ALB, Kinesis 전달은 이 단계의 검증 범위가 아닙니다.

## 단계적 전달

### Phase A — 로컬 계정 이식성

입력 계약, 렌더러, template, 회귀 테스트, CI를 완성합니다. AWS 비용과 자격증명은 필요하지 않습니다.

### Phase B — 보안과 GitOps bootstrap

신규 AWS 계정이 준비되면 remote state, locking, GitHub OIDC plan/deploy role, Secrets Manager 항목을 생성합니다. 이 단계는 EKS와 데이터 파이프라인 전체를 요구하지 않습니다.

### Phase C — 실제 운영 증거

검토된 Terraform plan을 단계적으로 apply하고 immutable image 배포, post-deploy, Kinesis-to-S3, alert, Bedrock, load test를 실행합니다. 결과는 로컬 테스트와 구분해 날짜와 environment를 포함한 증거로 공개합니다.

## 명시적 비목표

- 모든 Kubernetes 리소스를 하나의 신규 Helm chart로 통합하지 않습니다.
- multi-account organization과 landing zone을 이번 단계에서 구현하지 않습니다.
- 과거 Terraform state를 신규 계정의 source of truth로 승격하지 않습니다.
- AWS가 없는 상태에서 production-ready 또는 E2E verified라고 주장하지 않습니다.

# 작업 로그 (Work Log)

> 새 세션에서 컨텍스트 복원용. 현재 진행 단계 → 다음 단계 명확화.

**마지막 업데이트:** 2026-04-27 (DATA-ONLY DEPLOY 성공)
**현재 브랜치:** `feat-data-only-deploy`
**현재 단계:** **데이터 인프라 59개 리소스 배포 완료** → 로컬 Generator로 데이터 흘려보내기 + 검증

---

## 🎯 프로젝트 현황

- ✅ Phase 0~5 모든 코드 구현 완료
- ✅ 누락 기능 정정 완료 (122/122 테스트 통과)
- ✅ **DATA-ONLY 배포 성공** — VPC/S3/KDS/KDF/Glue/Athena/Lambda 등 59개 리소스
- ⏸️ EKS/ECR/SSM/SNS/X-Ray는 권한 부재로 보류
- ⏸️ Flink는 콘솔/CLI 하이브리드로 처리하기로 결정

---

## ✅ 완료 작업 (DATA-ONLY DEPLOY 세션)

### 1. AWS 사전 준비
- ✅ AWS Credentials (Account: 827913617635, User: de-ai-06)
- ✅ Secrets Manager: `/robot-telemetry/slack-webhook-url`, `/robot-telemetry/grafana-admin-password`
- ✅ `terraform init` 완료

### 2. 누락 기능 일제 수정 (커밋 17481bd 즈음)
- API GRAFANA_URL → SSM Late-binding
- Grafana Helm Data Source 자동 프로비저닝 (CloudWatch + Athena + X-Ray)
- Generator → Glue Schema Registry SDK 검증
- ETL 멱등성 (S3 파티션 사전 삭제 + INSERT INTO)
- DAG/SQL 검증 테스트 20건 추가 (`test_dag_structure.py`, `test_sql_filters.py`)
- 옛날 버킷명 9개 파일 일괄 정정

### 3. DATA-ONLY 분기 작업 (`feat-data-only-deploy` 브랜치)
**비활성화한 파일 (.disabled):**
| 파일 | 이유 |
|------|------|
| `terraform/eks_and_iam.tf` | EKS:CreateCluster 권한 없음 |
| `terraform/karpenter.tf` | EKS 의존 |
| `terraform/addons.tf` | EKS Helm 의존 |
| `terraform/cicd_gitops.tf` | ECR/GitHub OIDC 권한 없음 |
| `terraform/modules/data_pipeline/ssm.tf` | SSM:PutParameter 권한 없음 |
| `terraform/modules/data_pipeline/sns.tf` | SNS:CreateTopic 권한 없음 |
| `terraform/modules/data_pipeline/xray.tf` | xray:CreateGroup 권한 없음 |
| `terraform/modules/data_pipeline/iam_eks_irsa_full.tf.disabled` | iam.tf 전체 백업 (EKS IRSA 4종 포함) |

**수정한 파일:**
- `iam.tf`: 비EKS 부분만 (Firehose + Lambda Role) + Firehose KDS 읽기 권한 추가
- `kinesis.tf`: `dynamic_partitioning_configuration` + `s3_backup_mode` 비활성화 (timestamp namespace만 사용)
- `lambda.tf`: SNS env var 제거 + archive_file 우회 (수동 zip 참조)
- `cloudwatch.tf`: SNS alarm_actions 비활성화
- `main.tf` + `variables.tf`: EKS OIDC + grafana_password 더미 default
- `outputs.tf`: EKS IRSA outputs 제거

### 4. 배포 결과 — 59개 리소스
**핵심:**
- ✅ VPC + Subnets + NAT + VPC Endpoints (S3 Gateway, Kinesis Interface)
- ✅ S3 Bucket `de-ai-06-smartfactory-bucket` + Lifecycle + Versioning + Public Access Block
- ✅ Kinesis Data Streams: `robot-telemetry-stream`(10 shards), `robot-anomaly-alert-stream`(2 shards)
- ✅ Kinesis Data Firehose `robot-telemetry-firehose` (Parquet 변환 + Glue Schema 참조)
- ✅ Glue Catalog Database `robot_telemetry_db` + Bronze Table + Schema Registry
- ✅ Athena Workgroup `robot-telemetry-workgroup`
- ✅ Lambda `robot-anomaly-alert-lambda` + Event Source Mapping (alert KDS 트리거)
- ✅ CloudWatch Metric Alarm (Firehose delivery errors)
- ✅ IAM Roles: Firehose, Flink, Lambda, SageMaker (EKS 무관)
- ✅ S3 Object: `flink-code/anomaly_detection.zip` 업로드

---

## 🚀 다음 단계 (내일 계속)

### Step A: Generator 로컬 실행 → KDS 데이터 흘리기
```bash
cd /Users/mason/Desktop/Projects/robot-data-pipeline
source .env

# 200행 합성 데이터 기반 시뮬레이션
ROBOT_COUNT=100 \
SEED_CSV_PATH=data/seed_data_sample.csv \
KINESIS_STREAM_NAME=robot-telemetry-stream \
AWS_DEFAULT_REGION=eu-west-1 \
python -m src.generator.app
# 멈출 때 Ctrl+C
```

### Step B: S3 Bronze 적재 확인
```bash
# Firehose buffer interval = 300s, 5분 후 확인
aws s3 ls s3://de-ai-06-smartfactory-bucket/bronze/ --recursive --region eu-west-1 | head -5
```

### Step C: Athena 콘솔에서 쿼리
```sql
-- AWS Console → Athena → Workgroup: robot-telemetry-workgroup
SELECT robot_id, motor_temp, battery_level, timestamp
FROM bronze_robot_telemetry
WHERE year='2026' AND month='04' AND day='27'
LIMIT 10;
```

### Step D: Flink 애플리케이션 콘솔 생성 (선택)
- AWS Console → Managed Apache Flink → Create application
- Service execution role: `robot-telemetry-flink-role` (이미 만들어져 있음)
- Code: `s3://de-ai-06-smartfactory-bucket/flink-code/anomaly_detection.zip` (이미 업로드됨)
- Property Groups (`robot-app-config`):
  - `kinesis.main.stream = robot-telemetry-stream`
  - `kinesis.alert.stream = robot-anomaly-alert-stream`
  - `s3.alerts.path = s3://de-ai-06-smartfactory-bucket/alerts/`
  - `aws.region = eu-west-1`
  - `zscore.threshold = 3.0`, `zscore.sigma.floor = 0.5`
  - `load.ratio.threshold = 1.8`, `load.ratio.min.temp = 85.0`

### Step E: Lambda 알림 동작 확인 (Slack 도달)
```bash
# Alert KDS에 더미 이상 이벤트 주입
aws kinesis put-record \
  --stream-name robot-anomaly-alert-stream \
  --partition-key ROBOT-00001 \
  --data '{"robot_id":"ROBOT-00001","motor_temp":95.5,"timestamp":"2026-04-27T10:00:00Z"}' \
  --region eu-west-1
# Slack에 알림 도달 확인 (단, 알림 메시지 포맷에 portal_url 미포함 — SSM 비활성)
```

---

## 🛡️ 복구 명령어 (EKS/ECR/SSM/SNS/XRay 권한 받으면)

### 옵션 1: 통째로 복구 (가장 안전)
```bash
git checkout main
# main 브랜치는 이번 변경 없음 — 깨끗한 상태
```

### 옵션 2: 부분 복구 (필요한 것만)
```bash
cd /Users/mason/Desktop/Projects/robot-data-pipeline

# 1. .disabled 파일들을 .tf로 복원
mv terraform/eks_and_iam.tf.disabled terraform/eks_and_iam.tf
mv terraform/karpenter.tf.disabled terraform/karpenter.tf
mv terraform/addons.tf.disabled terraform/addons.tf
mv terraform/cicd_gitops.tf.disabled terraform/cicd_gitops.tf
mv terraform/modules/data_pipeline/ssm.tf.disabled terraform/modules/data_pipeline/ssm.tf
mv terraform/modules/data_pipeline/sns.tf.disabled terraform/modules/data_pipeline/sns.tf
mv terraform/modules/data_pipeline/xray.tf.disabled terraform/modules/data_pipeline/xray.tf

# 2. iam.tf를 EKS IRSA 포함 전체 버전으로 복원
mv terraform/modules/data_pipeline/iam_eks_irsa_full.tf.disabled terraform/modules/data_pipeline/iam.tf

# 3. main.tf, variables.tf, kinesis.tf, lambda.tf, cloudwatch.tf 변경 사항 git revert
git checkout main -- terraform/main.tf \
  terraform/modules/data_pipeline/variables.tf \
  terraform/modules/data_pipeline/kinesis.tf \
  terraform/modules/data_pipeline/lambda.tf \
  terraform/modules/data_pipeline/cloudwatch.tf \
  terraform/modules/data_pipeline/outputs.tf

# 4. terraform plan으로 확인 후 apply
terraform plan
```

---

## 📌 핵심 결정 사항

1. **DATA-ONLY 분기:** `feat-data-only-deploy` 브랜치에서 작업, main은 깨끗
2. **권한 부재 리소스:** EKS, ECR, SSM, SNS, X-Ray (5종)
3. **Lambda zip 워크어라운드:** archive_file 데이터 소스가 빈 zip 생성하는 버그로 수동 zip 사용
4. **Firehose dynamic_partitioning:** timestamp namespace만 쓰므로 비활성화 (충분)
5. **CloudWatch Alarm:** SNS 비활성화로 액션 없음, 콘솔에서만 확인
6. **S3 버킷:** `de-ai-06-smartfactory-bucket` (Terraform 관리, eu-west-1)
7. **Bedrock 모델:** `anthropic.claude-3-5-sonnet-20241022-v2:0` (계정에 활성화 필요)

---

## 🎬 새 세션 시작 시

> "WORK_LOG.md 읽고 Step A부터 진행해줘 (Generator 로컬 실행)"

또는

> "WORK_LOG.md 확인하고 다음 단계 알려줘"

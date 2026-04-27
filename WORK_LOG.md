# 작업 로그 (Work Log)

> 새 세션에서 컨텍스트 복원용. 현재 진행 단계 → 다음 단계 명확화.

**마지막 업데이트:** 2026-04-27
**현재 브랜치:** `main`
**현재 단계:** Phase 0~5 완료 → **Terraform 배포 진행 중** → Flink는 콘솔/CLI로 처리

---

## 🎯 프로젝트 현황

- ✅ Phase 0~5 모든 코드 구현 완료
- ✅ 누락 기능 일제 정정 완료 (122/122 테스트 통과)
- 🚧 **현재**: Terraform plan/apply 단계 — 일부 문법 에러 잔존 (Flink 부분만)
- ⏸️ Flink는 Terraform 대신 **AWS 콘솔/CLI 하이브리드**로 처리하기로 결정 (`aws_kinesisanalyticsv2_application` provider 문법 복잡)

---

## ✅ 이번 세션 완료 작업

### 1️⃣ S3 버킷 Terraform 마이그레이션
- 사전 생성 버킷(`de-ai-06-827913617635-ap-northeast-2-an`) → Terraform 생성(`de-ai-06-smartfactory-bucket`)
- [terraform/modules/data_pipeline/s3.tf](terraform/modules/data_pipeline/s3.tf) 신설 (bucket + lifecycle + versioning + block public)
- 9개 파일에서 옛날 버킷명 일괄 정정 (DAG, ML, API, SQL DDL 3종, 테스트, Flink 주석, K8s deployment)

### 2️⃣ API GRAFANA_URL Late-binding (HIGH)
- **이유:** ALB DNS는 terraform apply 후 결정 → Pod 재배포 없이 SSM에서 런타임 조회로 전환
- [src/api/main.py](src/api/main.py): `_get_grafana_url()` 모듈 캐시 함수 추가
- [k8s/api/configmap.yaml](k8s/api/configmap.yaml): PLACEHOLDER 제거 (`data: {}`)
- [k8s/api/deployment.yaml](k8s/api/deployment.yaml): GRAFANA_URL env var 제거 + ATHENA_OUTPUT_LOCATION 새 버킷 정정
- [terraform/modules/data_pipeline/iam.tf](terraform/modules/data_pipeline/iam.tf): API IRSA에 `ssm:GetParameter` 권한 추가 (단일 ARN)

### 3️⃣ Grafana Data Source 자동 프로비저닝 (MEDIUM)
- [terraform/addons.tf](terraform/addons.tf): Helm values 확장
  - Plugins: `grafana-athena-datasource`, `grafana-x-ray-datasource`
  - Data Sources: CloudWatch (uid=`cloudwatch`), Athena (uid=`athena`), X-Ray (uid=`xray`)
  - ServiceAccount IRSA annotation
- [terraform/modules/data_pipeline/iam.tf](terraform/modules/data_pipeline/iam.tf): Grafana IRSA 신설 (Athena/Glue/S3/CloudWatch/X-Ray 권한)
- [terraform/modules/data_pipeline/outputs.tf](terraform/modules/data_pipeline/outputs.tf) 신설 (module ARN export)

### 4️⃣ Generator Glue Schema Registry 검증 (MEDIUM)
- [src/generator/schema_validator.py](src/generator/schema_validator.py) 신설 (모듈 캐시 + fail-open fallback)
- [src/generator/app.py](src/generator/app.py): batch_sender에서 schema mismatch record drop
- [terraform/modules/data_pipeline/iam.tf](terraform/modules/data_pipeline/iam.tf): Generator IRSA에 `glue:GetSchema*` 권한 추가

### 5️⃣ ETL 멱등성 — INSERT OVERWRITE 대체 패턴 (LOW)
- **방법:** Athena INSERT OVERWRITE 미지원 → "S3 파티션 사전 삭제 + INSERT INTO" 패턴
- [dags/robot_daily_etl.py](dags/robot_daily_etl.py): `_delete_s3_partition()` helper 추가, `_bronze_to_silver`/`_silver_to_gold`에서 INSERT 전 호출
- [terraform/modules/data_pipeline/iam.tf](terraform/modules/data_pipeline/iam.tf): Airflow Worker IRSA 신설 (Athena/S3+`DeleteObject`/SNS/Bedrock)
- [terraform/addons.tf](terraform/addons.tf): Airflow Helm chart에 worker IRSA serviceAccount annotation

### 6️⃣ DAG/SQL 검증 테스트 (LOW)
- [tests/etl/test_dag_structure.py](tests/etl/test_dag_structure.py) (8건): DAG 로딩, task 6종, 토폴로지, cycle, default_args
- [tests/etl/test_sql_filters.py](tests/etl/test_sql_filters.py) (12건): 이상치 필터, NULL 가드, 중복 제거, 멱등성 호출 순서, `_delete_s3_partition` 단위
- **회귀:** 122 PASSED (이전 78 + 신규 44)

### 7️⃣ AWS 사전 준비 완료
- ✅ AWS Credentials 검증 (`aws sts get-caller-identity` Account: 827913617635, User: de-ai-06)
- ✅ Secrets Manager 저장:
  - `/robot-telemetry/slack-webhook-url`
  - `/robot-telemetry/grafana-admin-password`
- ✅ `terraform init` 완료
- ✅ `.env` 파일 ATHENA_OUTPUT_LOCATION 새 버킷명으로 정정

---

## 🚧 현재 막혀있는 부분 — Flink Terraform 문법

`aws_kinesisanalyticsv2_application` 리소스가 AWS provider에서 문법이 매우 복잡하고 우리가 작성한 구조와 불일치. 시도한 수정마다 새로운 에러:
- `service_execution_role_arn` not expected
- `application_code_configuration` insufficient blocks
- `code_configuration`, `flink_run_configuration`, `application_code_configuration_description` not expected

**결정:** Flink 부분은 **AWS 콘솔/CLI로 직접 생성**하는 하이브리드 접근 (실무 표준).
- ✅ Terraform 유지: IAM Role, KDS, S3, CloudWatch Log Group, S3 ZIP 업로드
- ❌ Terraform 제거: `aws_kinesisanalyticsv2_application` 리소스만

---

## 📝 다음 세션에서 할 일

### Step 1: Flink Terraform 리소스 제거
```bash
# flink.tf에서 aws_kinesisanalyticsv2_application "detector" 리소스만 주석/제거
# IAM Role, Log Group, ZIP 업로드는 유지
```

### Step 2: Terraform plan/apply
```bash
cd /Users/mason/Desktop/Projects/robot-data-pipeline/terraform
source ../.env
terraform plan \
  -var="slack_webhook_url=$SLACK_WEBHOOK_URL" \
  -var="grafana_admin_password=$GRAFANA_ADMIN_PASSWORD" \
  -out=tfplan
terraform apply tfplan
# 약 15~20분 소요 (EKS 클러스터 생성)
```

### Step 3: Flink 애플리케이션 콘솔 생성
1. AWS Console → Managed Apache Flink → Create application
2. Runtime: Flink 1.18, Application mode
3. Service execution role: `robot-telemetry-flink-role` (Terraform이 만든 IAM Role)
4. Code location: `s3://de-ai-06-smartfactory-bucket/flink-code/anomaly_detection.zip`
   - **사전 작업:** `bash flink/build.sh && aws s3 cp flink/anomaly_detection.zip s3://de-ai-06-smartfactory-bucket/flink-code/`
5. Properties (Property Groups):
   - `kinesis.analytics.flink.run.options`:
     - `python = anomaly_detection.py`
     - `jarfile = lib/flink-sql-connector-kinesis-1.18.1.jar`
   - `robot-app-config`:
     - `kinesis.main.stream = robot-telemetry-stream`
     - `kinesis.alert.stream = robot-anomaly-alert-stream`
     - `s3.alerts.path = s3://de-ai-06-smartfactory-bucket/alerts/`
     - `aws.region = eu-west-1`
     - `zscore.threshold = 3.0`
     - `zscore.sigma.floor = 0.5`
     - `load.ratio.threshold = 1.8`
     - `load.ratio.min.temp = 85.0`

### Step 4: K8s 배포 + post-deploy
```bash
git push origin main  # GitHub Actions 자동 트리거
# - terraform.yml: 검증
# - k8s-deploy.yml: kubectl apply + ALB Ingress 생성
# - post-deploy.yml: ALB DNS 폴링 → SSM에 저장
```

### Step 5: 더미 데이터 7일치 사전 적재 (선택)
```bash
# Bedrock 리포트가 첫 실행에서 의미있는 데이터를 보려면 필요
BACKFILL_DAYS=7 BACKFILL_INTERVAL_MIN=5 python -m src.generator.backfill
```

---

## 📋 미완 항목 (LOW + 운영 후 검증)

### LOW (배포 후 처리 가능)
- ❌ Bedrock 모델 마이그레이션 (`anthropic.claude-3-haiku-20240307-v1:0` → 최신, AWS 콘솔에서 모델 access 활성화 후)
- ❌ S3 bucket datasource 중복 정리 (`s3_lifecycle.tf`는 이미 삭제됨, 추가 정리 없음)
- ❌ region 일관성 추가 점검 (sagemaker hardcoded 등)

### 운영 배포 후 검증 (지금 못함)
- 🟡 통합 테스트 (KDS 실제 전송 → Bronze 적재 확인)
- 🟡 Flink 통합 검증 (90도 데이터 주입 → Alert KDS 수신)
- 🟡 E2E 알림 (Lambda 트리거 → Slack 메시지 도달)
- 🟡 X-Ray Service Map (Generator → Kinesis → API 경로 표시)
- 🟡 SageMaker Endpoint 테스트 (`/api/predict` 호출 → 고장 확률 > 0.7 식별)
- 🟡 DLQ Alarm 강제 트리거 → Slack 알림 수신

---

## 🔑 핵심 결정 사항 (배경 이해용)

1. **S3 버킷:** `de-ai-06-smartfactory-bucket` (Terraform 관리, eu-west-1)
2. **Bedrock 모델 기본값:** `anthropic.claude-3-5-sonnet-20241022-v2:0` (계정에 활성화 필요)
3. **Flink:** Terraform 대신 콘솔/CLI 하이브리드 — IAM/KDS/S3/Log만 Terraform
4. **멱등성 패턴:** S3 파티션 사전 삭제 + INSERT INTO (Athena INSERT OVERWRITE 미지원)
5. **Late-Binding:** SSM Parameter Store로 ALB DNS 동적 주입 (Lambda + API)
6. **Glue Schema Registry:** Generator가 record drop으로 fail-fast (fail-open fallback)

---

## 🎬 새 세션 시작 시 이렇게 말하면 됨

> "WORK_LOG.md 읽고 Flink Terraform 제거 + terraform apply 진행"

또는

> "WORK_LOG.md 읽어줘. 어디까지 했는지 확인하고 다음 단계 진행"

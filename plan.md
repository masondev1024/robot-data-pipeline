  # Execution Plan & Feedback Board

  **Current Status:** `APPROVED`
  *(AI는 이 상태가 `[APPROVED]`로 변경될 때까지 코드를 작성하지 마십시오.)*

  ---

  ## 🛠️ Human Feedback & Notes
  > **개발자 지시사항:**
  > 1. 완벽한 CI/CD 파이프라인과 데이터 파이프라인(스트림/배치)의 핵심 비즈니스 로직(데이터 가공, 메달리온 아키텍처, LLM 연동) 구현에 리소스를 집중하십시오.
  > 2. Terraform 작업 시 기존 래플 프로젝트의 `vpc.tf`, `eks.tf`를 재사용하며, 데이터 파이프라인 리소스는 `modules/data_pipeline/` 하위에 분리하여 모듈화하십시오.
  > 3. AI 작업자는 작업을 완료할 때마다 `[ ]`를 `[x]`로 변경하고, 하단의 `AI Action Log`에 작업 결과와 특이사항을 기록하십시오.

  ---

  ## 🔗 참조 코드베이스 (기존 래플 프로젝트)(그대로 가져오는 것이 아닌 말그대로 참조만)

  > 기존 AWS 인프라는 **전부 삭제된 상태**. 아래 코드 패턴을 참조하여 **모든 리소스를 신규 생성**한다.
  > 자격증명에 대한 모든 내용(access key, secret key등)은 `.env` 파일에 따로 관리(내가 채워넣을거야)한다.
  > S3 버킷 `de-ai-06-827913617635-ap-northeast-2-an` 은 사전 생성된 버킷으로 **Terraform으로 생성하지 않는다**.

  | 참조할 코드 | 파일 | 활용 방식 |
  |------------|------|----------|
  | VPC / 서브넷 3계층 구조 | `network.tf` | 동일 패턴으로 신규 생성 (리전: `eu-west-1`) |
  | EKS 클러스터 + 노드그룹 + IAM | `eks_and_iam.tf` | 동일 패턴, 리소스명 변경 후 신규 생성 |
  | Karpenter 노드 자동 확장 | `karpenter.tf` | 동일 패턴 적용 |
  | ECR + GitHub Actions OIDC | `cicd_gitops.tf` | repo명 등 변경 후 신규 생성 |
  | EKS 애드온 (ALB, ArgoCD 등) | `addons.tf` | 동일 패턴 적용, Airflow Helm도 여기 추가 |

  ---

  ## 📋 네이밍 & 설정값 결정

  > 모든 Terraform 리소스명, K8s 오브젝트명, 데이터 카탈로그명의 기준표. 코드 작성 시 이 표를 따른다.

  ### 공통
  | 항목 | 확정값 |
  |------|--------|
  | 프로젝트 Prefix | `robot-telemetry` |
  | AWS 리전 | `eu-west-1` |
  | S3 버킷 | `de-ai-06-827913617635-ap-northeast-2-an` (사전 생성, Terraform 관리 제외) |

  ### 인프라 (Terraform `variables.tf`)
  | 항목 | 확정값 |
  |------|--------|
  | VPC CIDR | `10.0.32.0/16` |
  | EKS 클러스터명 | `robot-telemetry-cluster` |
  | EKS 노드 인스턴스 타입 | `t3.large` (Airflow+Grafana 상시 구동 고려, 8GB×2노드) |
  | GitHub Owner | `masondev1024` |
  | GitHub Repo | `robot-telemetry-platform` |
  | GitHub Branch | `main` |

  ### 스트리밍 파이프라인
  | 항목 | 확정값 |
  |------|--------|
  | Kinesis Data Stream (메인) | `robot-telemetry-stream` |
  | Kinesis Data Stream (알림용) | `robot-anomaly-alert-stream` |
  | Kinesis Data Firehose | `robot-telemetry-firehose` |
  | Managed Flink 앱명 | `robot-anomaly-detector` |
  | SNS Topic | `robot-anomaly-alerts` |
  | Lambda 함수명 | `robot-anomaly-alert-lambda` |

  ### 데이터 카탈로그 (Glue / Athena)
  | 항목 | 확정값 |
  |------|--------|
  | Glue 데이터베이스 | `robot_telemetry_db` |
  | Bronze 테이블 | `bronze_robot_telemetry` |
  | Silver 테이블 | `silver_robot_telemetry` |
  | Gold 테이블 | `gold_robot_daily_stats` |
  | Athena Workgroup | `robot-telemetry-workgroup` |
  | Athena 결과 S3 Prefix | `project-athena-results/` |

  ### 컨테이너 (ECR)
  | 항목 | 확정값 | 용도 |
  |------|--------|------|
  | Generator ECR Repo | `robot-telemetry-generator` | AI4I 2020 CSV Seed 기반 로봇 시뮬레이터 → KDS 전송 컨테이너 |
  | AI Query API ECR Repo | `robot-telemetry-api` | FastAPI 채팅 서버 컨테이너 (MSA 패턴 — Generator·API 각각 독립 ECR/Deployment/IRSA로 분리됨) |

  ### Kubernetes
  | 항목 | 확정값 |
  |------|--------|
  | 앱 네임스페이스 | `robot-telemetry` |
  | Airflow 네임스페이스 | `airflow` |
  | Grafana 네임스페이스 | `monitoring` |

  ### Airflow
  | 항목 | 확정값 |
  |------|--------|
  | DAG ID | `robot_daily_etl` |

  ### SSM Parameter Store (Late-Binding 값 — terraform apply 후 CI/CD가 자동 저장)
  | SSM 경로 | 값 | 저장 주체 |
  |---------|-----|---------|
  | `/robot-telemetry/portal-url` | API ALB DNS (`https://k8s-xxx.elb.amazonaws.com`) | GitHub Actions post-deploy |
  | `/robot-telemetry/grafana-url` | Grafana ALB DNS | GitHub Actions post-deploy |
  | `/robot-telemetry/grafana-dashboard-uid` | `robot-fleet-001` (robot_fleet.json uid) | GitHub Actions post-deploy |

  ### `.env` 파일 템플릿 (값은 직접 채울 것)
  ```dotenv
  # AWS Credentials
  AWS_ACCESS_KEY_ID=
  AWS_SECRET_ACCESS_KEY=
  AWS_REGION=eu-west-1

  # S3
  S3_BUCKET_NAME=de-ai-06-827913617635-ap-northeast-2-an

  # Kinesis
  KINESIS_STREAM_NAME=robot-telemetry-stream
  KINESIS_ALERT_STREAM_NAME=robot-anomaly-alert-stream

  # Generator
  ROBOT_COUNT=10000              # 가상 로봇 대수 (KDS 10 Shard 기준 최대 10,000)
  SEED_CSV_PATH=data/seed_data_sample.csv  # 로컬 테스트용(200행). 운영: data/seed_data.csv (Kaggle AI4I 2020 전체)

  # Slack (Incoming Webhook URL)
  SLACK_WEBHOOK_URL=

  # Amazon Bedrock
  BEDROCK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0

  # Athena
  ATHENA_DATABASE=robot_telemetry_db
  ATHENA_WORKGROUP=robot-telemetry-workgroup
  ATHENA_OUTPUT_LOCATION=s3://de-ai-06-827913617635-ap-northeast-2-an/project-athena-results/

  # AI Query API 캐시 갱신 시각 (KST, Airflow DAG 완료 후)
  CACHE_REFRESH_HOUR=1

  # Grafana
  GRAFANA_ADMIN_PASSWORD=
  GRAFANA_URL=http://<ALB-DNS>  # terraform apply 후 ALB DNS 주소로 교체
  ```

  ---

  ## 🔄 배포 4단계 순서 (Late-Binding 의존성 해소)

  > ALB DNS, Grafana URL 등 인프라 구성 후에야 확정되는 값은 `.env`에 미리 채울 수 없다.
  > Lambda와 API Pod는 이 값들을 **런타임에 SSM에서 읽도록** 구현하고, CI/CD가 각 단계 후 SSM에 자동 저장한다.

  ```
  [Step 0] 사람이 직접 — terraform apply 전에
    └─ AWS Secrets Manager에 수동 저장:
         /robot-telemetry/slack-webhook-url      ← SLACK_WEBHOOK_URL
         /robot-telemetry/grafana-admin-password ← GRAFANA_ADMIN_PASSWORD

  [Step 1] terraform apply
    └─ EKS, Lambda, SNS, Kinesis, ALB Controller 생성
       Lambda PORTAL_URL 은 env var 없음 → 콜드스타트 시 SSM 런타임 조회

  [Step 2] GitHub Actions — k8s/apply job
    └─ kubectl apply -f k8s/
       → ALB Ingress 리소스 생성 → AWS가 ALB DNS 자동 할당 (30초~2분)

  [Step 3] GitHub Actions — post-deploy job (ALB DNS 확정 후)
    └─ API ALB DNS polling → SSM /robot-telemetry/portal-url 저장
       Grafana ALB DNS polling → SSM /robot-telemetry/grafana-url 저장

  [Step 4] 서비스 정상 동작
    └─ Lambda 콜드스타트 → SSM /robot-telemetry/portal-url 읽어 딥링크 생성
       API Pod startup → SSM /robot-telemetry/grafana-url 읽어 iframe src 주입
  ```

  ---

  ## 🚀 Milestone Tasks (5/8 Deadline)

  ### Phase 0: 신규 Terraform 프로젝트 기반 구성
  *목표: 래플 프로젝트 코드 패턴을 기반으로 신규 네트워크, EKS, CI/CD 인프라를 처음부터 프로비저닝한다.*

  - [x] **Task 0.1: 신규 Terraform 프로젝트 셋업**
    - [x] `terraform/` 루트에 `providers.tf`, `variables.tf`, `network.tf`, `eks_and_iam.tf`, `karpenter.tf`, `addons.tf`, `cicd_gitops.tf` 작성 (래플 프로젝트 코드 패턴 참조).
    - [x] `variables.tf`에 `aws_region = "eu-west-1"` 로 설정. `.env` 파일에서 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`를 로드하는 방식으로 자격증명 구성 (하드코딩 금지).
    - [x] `modules/data_pipeline/` 디렉토리 생성 — 데이터 파이프라인 전용 리소스(Kinesis, Firehose, Glue, IAM)는 전부 이 모듈 하위에 작성.
    - [x] Bastion + RDS는 이번 프로젝트에서 불필요하므로 생성하지 않는다.
    - [x] **[비용·보안]** `network.tf`에 VPC Endpoint 2개 추가:
      - `aws_vpc_endpoint` type=`Gateway` for **S3** — 무료. EKS Pod → S3 트래픽이 NAT Gateway를 우회해 AWS 내부 네트워크로 처리됨.
      - `aws_vpc_endpoint` type=`Interface` for **Kinesis Streams** (PrivateLink) — Generator의 초당 10,000건 전송 트래픽이 퍼블릭망을 타지 않음. NAT Gateway 데이터 처리 비용 차단.

  - [x] **Task 0.2: CI/CD 자동화 (GitHub Actions)**
    - [x] `.github/workflows/terraform.yml` 작성: `terraform/` 변경 감지 → `terraform plan` 결과를 PR 코멘트로 게시 → 사람 승인(Environment Protection Rule) → `terraform apply`.
    - [x] `.github/workflows/k8s-deploy.yml` 작성: `k8s/` 변경 감지 → EKS 클러스터에 `kubectl apply` 자동 실행.
    - [x] `cicd_gitops.tf`에 이미 GitHub OIDC 설정이 있으므로 Actions workflow에서 `aws-actions/configure-aws-credentials` + OIDC 토큰 방식으로 자격증명 (하드코딩 금지).
    - [x] Generator / API 이미지 변경 시 ECR Push → EKS `kubectl rollout restart` 자동화. (Lambda ZIP 빌드 스텝도 포함)
    - [x] `.github/workflows/post-deploy.yml` 작성 — **ALB DNS 확정 후 SSM 자동 저장** (단, Phase 4의 ALB Ingress 매니페스트 작성 후에만 런타임 동작):
      - [x] API Ingress DNS polling: `kubectl get ingress robot-telemetry-api-ingress -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'` (최대 20회 × 15초 대기).
      - [x] Grafana Ingress DNS polling: 동일 방식.
      - [x] 확정된 DNS → `aws ssm put-parameter --name "/robot-telemetry/portal-url" --overwrite`.
      - [x] 확정된 DNS → `aws ssm put-parameter --name "/robot-telemetry/grafana-url" --overwrite`.

  ---

  ### Phase 1: Ingestion & Data Lake Infrastructure (Terraform & Generator)
  *목표: AI4I 2020 CSV Seed 데이터를 기반으로 가상 로봇 10,000대를 시뮬레이션하여 Kinesis로 전송하고, S3에 Parquet 포맷으로 동적 파티셔닝 적재.*

  - [x] **Task 1.0: Glue Schema Registry (Terraform)**
    - [x] `modules/data_pipeline/glue.tf`에 `aws_glue_registry` (`robot-telemetry-registry`) 추가.
    - [x] `aws_glue_schema` 리소스로 로봇 텔레메트리 JSON 스키마 등록 (`robot_id`, `pos_x`, `pos_y`, `battery_level`, `current_load`, `motor_temp`, `timestamp`).
    - [ ] Generator가 Kinesis에 레코드를 쓰기 전 Glue Schema Registry SDK로 스키마 검증 — upstream 필드명 변경 시 파이프라인 보호.
    - [x] Firehose의 `data_format_conversion_configuration`도 이 Registry 스키마를 참조하도록 연결.
  - [x] **Task 1.0.5: Dead Letter Queue (DLQ) — Firehose 실패 처리 (Terraform)**
    - [x] `aws_kinesis_firehose_delivery_stream` 리소스에 `s3_backup_mode = "FailedDataOnly"` 설정, 실패 데이터를 `bronze-dlq/` prefix로 리다이렉트.
    - [x] CloudWatch Alarm 추가: Firehose `DeliveryToS3.Success` < 95% 시 SNS(`robot-anomaly-alerts`)로 알림. (`modules/data_pipeline/cloudwatch.tf` 작성 완료)
    - [x] `modules/data_pipeline/cloudwatch.tf` 신규 작성.
  - [x] **Task 1.1: IAM & Security Configuration (Terraform)**
    - [x] `modules/data_pipeline/iam.tf` 작성.
    - [x] EKS Pod이 Kinesis에 `PutRecord` 할 수 있도록 **IRSA(IAM Role for Service Accounts)** 신규 생성. Phase 0에서 생성된 EKS 클러스터의 OIDC Issuer URL 참조.
    - [x] Firehose가 S3 버킷 `de-ai-06-827913617635-ap-northeast-2-an`에 쓸 수 있는 `firehose_delivery_role` 신규 작성. 버킷 ARN은 `data "aws_s3_bucket"` 으로 참조 (버킷 자체는 Terraform으로 관리하지 않음).
    - [ ] **[보안 강화]** AWS Secrets Manager에 민감 정보 저장: `robot-telemetry/slack-webhook-url`, `robot-telemetry/grafana-admin-password`.
    - [x] EKS에 **External Secrets Operator** Helm 배포 (`addons.tf`). Secrets Manager 값을 K8s Secret으로 자동 동기화 — `.env` 파일 직접 참조 제거.
    - [ ] Generator, API, Airflow Worker Pod 모두 IRSA 어노테이션 완전 적용 (최소 권한 원칙).
    - [x] **[SSM Parameter Store]** `modules/data_pipeline/ssm.tf` 작성:
      - [x] `aws_ssm_parameter` 플레이스홀더 2개 생성 (`/robot-telemetry/portal-url`, `/robot-telemetry/grafana-url`) — 초기값 `"PENDING"`, Type `String`. CI/CD post-deploy job이 실제 DNS로 덮어씀.
      - [x] Lambda IRSA, API IRSA에 `ssm:GetParameter` 권한 추가 (위 2개 경로만 허용).
      - [ ] Lambda 코드(`src/lambda/alert_handler.py`)에서 `PORTAL_URL` env var 대신 SSM `get_parameter` 런타임 조회로 변경. 콜드스타트당 1회 조회 후 프로세스 내 캐시.
      - [ ] API startup(`src/api/main.py`)에서 `GRAFANA_URL` env var 대신 SSM `get_parameter` 조회 후 전역변수 저장.
  - [x] **Task 1.2: Kinesis Data Streams (KDS) Provisioning (Terraform)**
    - [x] `modules/data_pipeline/kinesis.tf`에 메인 스트림 `aws_kinesis_stream` 리소스 생성 (Provisioned Mode, **Shard Count: 10**, Retention: **24시간**).
      - 산출 근거: 가상 로봇 10,000대 × 1 rec/sec = **10,000 rec/sec**, 레코드당 ~1KB → **10 MB/sec**. KDS Shard 1개 한도(1,000 rec/sec, 1 MB/sec)에서 **10 Shards** 필요.
    - [x] Alert 전용 스트림 `robot-anomaly-alert-stream` 별도 생성 (**Shard Count: 2**, Retention: **24시간**).
      - 산출 근거: Flink 이상 탐지 이벤트 수는 메인 스트림 대비 소량(전체 로봇의 일부). Shard 2개면 충분하며 비용 최소화.
  - [x] **Task 1.3: S3 Data Lake Prefix 정의 및 Lifecycle 설정**
    - [x] **S3 버킷 신규 생성 금지.** 사전 생성된 버킷 `de-ai-06-827913617635-ap-northeast-2-an` 사용.
    - [x] 논리적 Prefix `bronze/`, `silver/`, `gold/`는 S3 오브젝트 키 네이밍 규칙으로만 정의 (별도 Terraform 리소스 불필요).
    - [x] **[비용 최적화]** `aws_s3_bucket_lifecycle_configuration` 리소스 추가 (`modules/data_pipeline/s3_lifecycle.tf`):
      - [x] `bronze/` prefix: 90일 후 Glacier Instant Retrieval로 전환.
      - [x] `silver/` prefix: 365일 후 Glacier Instant Retrieval로 전환.
      - [x] `gold/` prefix: 영구 보관 (Lifecycle 규칙 없음).
      - [x] `bronze-dlq/` prefix: 30일 후 만료 삭제 (비정상 데이터 자동 정리).
  - [x] **Task 1.3.1: Athena Workgroup 생성 (Terraform)**
    - [x] `modules/data_pipeline/glue.tf`에 `aws_athena_workgroup` 추가.
      - Workgroup명: `robot-telemetry-workgroup`
      - `enforce_workgroup_configuration = true`, `publish_cloudwatch_metrics_enabled = true`.
      - 쿼리 결과 S3 위치: `s3://de-ai-06-827913617635-ap-northeast-2-an/project-athena-results/`.
  - [x] **Task 1.3.5: Glue Data Catalog Schema 사전 선언 (Terraform)**
    - [x] `modules/data_pipeline/glue.tf` 작성.
    - [x] `aws_glue_catalog_database` (`robot_telemetry_db`) 생성.
    - [x] `aws_glue_catalog_table` (`bronze_robot_telemetry`) 생성: KDF가 Parquet 변환 시 참조할 컬럼 스키마 선언 (`robot_id`, `pos_x`, `pos_y`, `battery_level`, `current_load`, `motor_temp`, `timestamp`).
    - [x] KDF는 이 Glue Table을 `data_format_conversion_configuration`의 `schema_configuration`으로 참조한다.
  - [x] **Task 1.4: Kinesis Data Firehose (KDF) Configuration (Terraform)**
    - [x] `modules/data_pipeline/kinesis.tf`에 `aws_kinesis_firehose_delivery_stream` 추가.
    - [x] Source: Task 1.2에서 생성한 KDS. Destination: `de-ai-06-827913617635-ap-northeast-2-an` 버킷 (`data "aws_s3_bucket"` 참조).
    - [x] **[핵심]** Data Format Conversion 활성화: AWS Glue Data Catalog 테이블 포맷을 참조하여 원본 JSON을 **Parquet**으로 변환 (Snappy 압축).
    - [x] **[핵심]** Dynamic Partitioning 설정: S3 Prefix를 `bronze/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/` 형태로 구성.
  - [x] **Task 1.5: Generator Implementation (Python — AI4I 2020 CSV Seed 기반)**
    - [x] `data/generate_sample.py` 작성: AI4I 2020 포맷 200행 합성 CSV(`data/seed_data_sample.csv`) 생성 스크립트.
      - 운영 환경에서는 `data/seed_data.csv` (Kaggle AI4I 2020 전체 데이터, 직접 다운로드 필요) 사용.
    - [x] `src/generator/app.py` 작성:
      - [x] `SEED_CSV_PATH` 환경변수로 지정된 AI4I CSV 로드 → `ROBOT_COUNT`개 로봇 프로필 생성 (CSV 행 수 부족 시 순환(cycle)).
        - 컬럼 매핑: `Process temperature [K]` → `motor_temp_base`, `Rotational speed [rpm]` → `load_base`, `Machine failure` → 스파이크 확률(70%).
      - [x] `asyncio` 기반으로 가상 로봇 **`ROBOT_COUNT`(기본 10,000)대** 동시 시뮬레이션. 각 로봇이 독립적인 coroutine으로 초당 1건 센서 데이터 생성.
      - [x] 생성 필드: `robot_id`, `pos_x`, `pos_y`, `battery_level`(0~100), `motor_temp`(60~100°C), `current_load`, `timestamp` (ISO8601 UTC).
      - [x] `boto3` `put_records` (최대 500건/배치)로 묶어 KDS에 전송 → 초당 20회 배치 호출로 10,000 rec/sec 처리.
      - [x] 따릉이 API 호출 코드 일체 포함 금지.
    - [x] Phase 0에서 생성한 EKS 클러스터에 배포하기 위한 `Dockerfile` 및 `k8s/generator/Deployment.yaml` 작성. 일반 `Deployment` 사용 (Argo Rollouts 금지). Pod의 Service Account에 Task 1.1의 IRSA 어노테이션 추가.
  - [ ] **Task 1.6: Ingestion Pipeline Validation (pytest)**
    - [x] `tests/generator/` 생성 및 `pytest` 기반 단위 테스트 작성:
      - [x] 생성된 데이터 스키마가 Glue Table 정의와 일치하는지 검증.
      - [x] `ROBOT_COUNT` 만큼의 태스크가 정상적으로 생성되는지 확인.
    - [ ] **[통합 테스트]** 로컬 또는 Dev 환경에서 KDS로 실제 데이터를 전송하고, AWS CLI를 통해 Shard에서 레코드가 정상 수신되는지 확인.

  ### Phase 2: Batch Processing & Medallion Architecture (Athena + Airflow)
  *목표: Airflow 스케줄링을 통해 Bronze(Raw) 데이터를 Silver(정제), Gold(집계) 테이블로 매일 자정에 자동 가공.*

  - [x] **Task 2.0: Data Quality Gate (Great Expectations + Airflow)**
    - [x] `requirements.txt`에 `great-expectations` 추가.
    - [x] `dags/robot_daily_etl.py`에 Bronze→Silver 진입 전 `PythonOperator` Task 삽입:
      - [x] 검사 항목: `robot_id` null 비율 < 1%, `motor_temp` 범위 0-500, `battery_level` 범위 0-100, 레코드 수 > 0.
      - [x] 검사 실패 시 `AirflowException` 발생 → DAG 중단 + SNS(`robot-telemetry-anomaly-alerts`)로 "데이터 품질 실패" 알림.
    - [x] `tests/etl/test_data_quality.py` 작성 — `evaluate_quality` 순수 함수 7건 단위 테스트.
  - [x] **Task 2.1: Athena / Glue Data Catalog DDL (SQL)**
    - [x] Bronze Table DDL: S3 `/bronze` 경로를 가리키는 External Table 생성. `PROJECTION` 속성을 사용하여 파티션 프로젝션 활성화(Athena 스캔 비용 최적화).
    - [x] Silver Table DDL: Parquet 포맷의 정제용 테이블 스키마 정의. (Partition Projection: dt DATE)
    - [x] Gold Table DDL: 일별 집계 분석용 테이블 스키마 정의. (Partition Projection: dt DATE)
  - [x] **Task 2.2: Airflow Environment Setup**
    - [x] EKS 내에 Helm Chart를 사용하여 Airflow 최소 사양 배포 (`terraform/addons.tf` `helm_release "airflow"`, KubernetesExecutor). 로컬 Docker Compose는 미사용.
    - [x] AWS Athena 및 S3 통신을 위한 Airflow Connection 설정 — boto3 직접 호출 방식 채택 (Airflow Connection 대신).
  - [ ] **Task 2.3: ETL Pipeline DAG 작성 (Python `dags/robot_daily_etl.py`)**
    - [ ] **[멱등성 보장]** 모든 Task는 `execution_date` 기준으로 S3 특정 파티션 경로를 바라보고, 재실행 시 기존 파티션을 덮어쓰도록(`INSERT OVERWRITE`) 로직 구성. (현재 `INSERT INTO` 사용 — 별도 이슈)
    - [x] **Task: Bronze to Silver (Athena Operator):**
      - [x] `motor_temp`가 500도 이상인 이상치(Outlier) 제거.
      - [x] 데이터 품질 필터 추가: `robot_id IS NOT NULL`, `battery_level BETWEEN 0 AND 100`, `motor_temp BETWEEN 0 AND 500`, `timestamp IS NOT NULL`.
      - [x] 중복 수신된 텔레메트리 데이터 제거(Deduplication): `robot_id + timestamp` 기준 `ROW_NUMBER()` 사용.
      - [x] `battery_level` 등 데이터 타입 정확하게 Casting.
      - [x] bronze WHERE 절 파티션 키(`year/month/day`) 사용 — step 4 (dag-fix) 정정 완료.
    - [x] **Task: Silver to Gold (Athena Operator):**
      - [x] 일별/로봇별 집계 쿼리 실행.
      - [x] 지표 도출: 일일 평균/최고 모터 온도, 배터리 소모(`battery_drain`), 가동 시간(`active_hours`). step 4 (dag-fix) 정정 완료.
  - [ ] **Task 2.4: ETL Logic & DAG Validation**
    - [x] `tests/etl/` 생성 (`tests/etl/test_data_quality.py` 7건 통과).
    - [ ] `pytest-airflow` 등을 활용하여 DAG의 순환 참조 및 문법 오류 검사.
    - [ ] **[SQL 검증]** Mock 데이터를 활용하여 Athena ETL 쿼리가 이상치(500도 이상)를 정확히 필터링하는지 단위 테스트.

  ### Phase 3: Real-time Anomaly Detection & AI Insight (Flink + Bedrock)
  *목표: 스트리밍 데이터를 실시간으로 모니터링하고, 배치 집계 결과를 바탕으로 LLM 리포트 생성.*

  - [ ] **Task 3.1: Real-time Processing (Apache Flink) — 고도화된 이상 탐지**
    - [ ] AWS Managed Flink Studio(Zeppelin) 또는 SQL Client를 위한 구성.
    - [ ] KDS를 Source Table로 매핑.
    - [ ] **[필수] Watermark 선언**: Source Table DDL에 `WATERMARK FOR event_time AS event_time - INTERVAL '10' SECOND` 추가. 지연 데이터(Late Data) 최대 10초 허용. Watermark 없이 Event Time 기반 Window를 사용하면 Flink가 Window를 닫지 못하고 상태가 무한히 쌓임.
    - [ ] **[핵심] 실무형 이상 탐지 로직 구현 (Flink SQL):**
      - [ ] **Condition 1 (Moving Z-Score):** 최근 5분간 로봇별 `motor_temp` 평균/표준편차 대비 3시그마를 초과하는 급격한 온도 변화 탐지.
      - [ ] **Condition 2 (Multivariate Correlation):** `current_load` 대비 `motor_temp` 비율이 비정상적으로 높은 경우(부하 대비 과열) 탐지.
      - [ ] 위 두 조건 중 하나라도 만족 시 이상 징후로 판단하여 알람 생성 (알람 피로도 급감 및 AI 추론 신뢰도 확보).
    - [ ] 탐지된 이상 이벤트를 두 곳에 동시 Sink: ① S3 `alerts/` 경로 (이력 로깅), ② **`robot-anomaly-alert-stream`** (Alert 전용 KDS, Native Sink 사용) — SNS 직접 연결 금지 (Flink에 SNS Native Sink 없음).
  - [x] **Task 3.2: LLM 배치 리포트 (Amazon Bedrock)**
    - [x] `dags/robot_daily_etl.py`의 마지막 Task로 Python Operator 추가.
    - [x] Gold Table의 최신 파티션 데이터(일일 상태 요약)를 `boto3` Athena Client로 읽어옴.
    - [x] 프롬프트 엔지니어링: "다음은 오늘 공장 로봇들의 상태 지표야. [데이터] 이를 분석해서 가장 점검이 시급한 로봇 3대와 그 이유를 정비반장에게 보내는 형식으로 300자 이내로 요약해."
    - [x] Bedrock API(`InvokeModel`, Claude 3 Sonnet/Haiku)를 호출하여 텍스트 리포트 생성.
    - [x] 생성된 리포트를 S3 `reports/YYYY-MM-DD.txt` 경로에 저장.
    - [x] SELECT 컬럼 정합성: gold DDL 컬럼(`battery_drain`, `active_hours`)으로 정정 — step 4 (dag-fix) 완료.
  - [ ] **Task 3.3: Real-time & AI Validation**
    - [ ] **[Flink 검증]** 90도 이상의 테스트 데이터를 KDS에 주입하고, Flink가 이를 올바르게 탐지하여 Alert KDS로 Sink 하는지 확인.
    - [ ] **[Bedrock 검증]** Mock 데이터를 기반으로 Bedrock 프롬프트가 예상된 형식의 JSON/Text 리포트를 반환하는지 `pytest`로 검증.

  ### Phase 4: Serving Layer (Slack Alert + Grafana + AI Chat)
  *목표: 파이프라인 결과를 운영자가 실시간으로 확인하고 AI에게 직접 질문할 수 있는 서비스 레이어를 구축한다.*

  - [ ] **Task 4.1: Real-time Slack Alert (Terraform — Alert KDS → Lambda → SNS → Slack)**
    - [x] `modules/data_pipeline/sns.tf` 작성: `aws_sns_topic` (`robot-anomaly-alerts`) 생성. (Note: Slack Webhook 구독은 Chatbot 또는 수동 설정 필요)
    - [x] `modules/data_pipeline/lambda.tf` 작성:
      - [x] `aws_lambda_function` (`robot-anomaly-alert-lambda`) 생성: Python 3.11 런타임. (ZIP 플레이스홀더 `src/lambda/alert_handler.zip` — 코드 구현 별도)
      - [x] `aws_lambda_event_source_mapping`: `robot-anomaly-alert-stream` KDS를 트리거로 연결.
      - [x] Lambda IAM Role: `kinesis:GetRecords` + `sns:Publish` 권한 부여.
    - [x] Lambda ZIP 빌드 프로세스: GitHub Actions `k8s-deploy.yml`에 `pip install -t dist/ && zip -r alert_handler.zip dist/` 빌드 스텝 포함됨.
    - [ ] 알림 메시지 포맷 (딥링크 포함):
      ```
      [⚠️ 이상 감지] robot_id: {id} | motor_temp: {temp}°C | 감지 시각: {timestamp}
      🔗 포털에서 확인: {portal_url}/?robot_id={id}
      ```
      - `portal_url`은 Lambda 콜드스타트 시 SSM `/robot-telemetry/portal-url` 런타임 조회. 하드코딩 금지.
      - `robot_id`가 URL-safe한지 확인: Generator가 `ROBOT-{숫자5자리}` 포맷으로 생성하도록 명시적 패딩(`f"ROBOT-{i:05d}"`).
    - [ ] 아키텍처: **Flink → robot-anomaly-alert-stream(KDS) → Lambda → SNS → Slack**
  - [ ] **Task 4.2: Grafana Dashboard (EKS Helm)**
    - [x] `terraform/addons.tf`에 Grafana Helm release 추가:
      - [x] `grafana.ini.security.allow_embedding: "true"` — 포털 iframe 임베딩 허용.
      - [x] `grafana.ini.auth.anonymous.enabled: "true"`, `grafana.ini.auth.anonymous.org_role: "Viewer"` — 익명 Viewer 접근.
      - [ ] `service.type = ClusterIP`, `grafana_admin_password` sensitive 변수로 관리. (현재 `adminPassword = "admin"` 하드코딩 — 보안 취약, 정정 필요)
    - [ ] **[필수] Grafana ALB Ingress** — `k8s/monitoring/grafana-ingress.yaml` 작성: `kubernetes.io/ingress.class: alb`, `alb.ingress.kubernetes.io/scheme: internet-facing`. ClusterIP만 있으면 외부 접근 불가. (`k8s/monitoring/` 디렉토리 자체 미생성)
    - [ ] Grafana Data Source 설정: ① Athena Plugin (Silver/Gold 테이블 조회), ② CloudWatch (Kinesis 처리량, EKS Pod 메트릭).
    - [ ] `grafana/dashboards/` 하위에 3개 대시보드 JSON 작성:
      - [ ] `robot_fleet.json`: 로봇별 최신 motor_temp · battery_level 상태 카드.
      - [ ] `anomaly_timeline.json`: 시간대별 이상 탐지 건수 시계열 그래프.
      - [ ] `pipeline_health.json`: Kinesis IncomingRecords, Firehose DeliveryToS3 메트릭.
  - [ ] **Task 4.3: 대화형 AI Query API + 통합 관제 포털 (FastAPI + Bedrock)**
    - [ ] `src/api/main.py` 작성 (FastAPI):
      - [x] **in-memory 캐시**: 앱 시작 시 + 매일 `CACHE_REFRESH_HOUR`시(기본 01:00 KST)에 Athena `gold_robot_daily_stats` 최신 파티션을 한 번 조회하여 전역 변수에 저장. `apscheduler` 사용. (단, timezone 미설정 — Task 4.3.5 버그 2A)
      - [x] **Cold Start 처리**: 앱 시작 시 Athena 쿼리가 완료되기 전 요청이 들어오면 503 반환. `_cache_ready` 플래그 사용.
      - [ ] `POST /api/chat` — 요청 바디 `{ "question": "..." }` 수신 → **캐시에서 Gold 데이터 즉시 읽기** → 질문 + 데이터를 Bedrock Claude 3에 전달 → 자연어 답변 반환. (구현됨, 단 아래 sub-bullet 미해결)
        - [ ] **[딥링크]** 응답 JSON에 `links[]` 필드 포함 — 미구현.
      - [ ] **요청 제한(Rate Limiting)**: `slowapi` 라이브러리 사용, `POST /api/chat` 엔드포인트에 IP 기준 분당 10회 제한 적용. (`/api/predict`엔 적용됐으나 `/api/chat`엔 미적용. 또한 `slowapi`가 `requirements.txt`에 누락 — 런타임 ImportError 위험)
      - [ ] `GET /` — `src/api/templates/portal.html` 통합 관제 포털 서빙. (현재 `chat.html`만 서빙)
    - [ ] `src/api/templates/portal.html` 작성 — 통합 관제 포털 (UI_GUIDE Dark Mode 원칙 준수):
      - [ ] **레이아웃**: 12컬럼 그리드. 좌측 8컬럼 = Grafana 대시보드 iframe, 우측 4컬럼 = AI Chat 패널.
      - [ ] **Grafana iframe**: `src="${GRAFANA_URL}/d/robot_fleet?kiosk=tv&orgId=1"` (kiosk=tv 모드로 Grafana 헤더/메뉴 숨김). 대시보드 탭 전환 버튼(Fleet / Anomaly / Pipeline) 포털 상단에 배치.
      - [ ] **Context 공유**: 운영자가 Grafana 패널에서 특정 로봇 ID를 클릭하면 `postMessage`로 포털 JS에 `robot_id` 전달 → AI 채팅 입력란에 `ROBOT-XXXXX의 상태를 분석해줘` 자동 입력.
      - [ ] **AI 답변 딥링크 렌더링**: `links[]` 배열을 버튼(`min-height: 44px`, UI_GUIDE §7 Touch Target 준수)으로 렌더링. 클릭 시 Grafana iframe의 `src`를 해당 URL로 교체 (새 탭 이동 없이 포털 내에서 차트 전환).
    - [x] `modules/data_pipeline/iam.tf` 업데이트: AI API Pod용 IRSA에 Athena 조회 + Bedrock `InvokeModel` 권한 추가.
    - [ ] `k8s/api/deployment.yaml` 작성: EKS Deployment + Service (ClusterIP). IRSA 어노테이션 추가. `GRAFANA_URL` 환경변수 ConfigMap으로 주입. (Deployment + Service ✅, GRAFANA_URL ConfigMap 미주입)
    - [ ] **[필수] AI API ALB Ingress** — `k8s/api/api-ingress.yaml` 작성: `kubernetes.io/ingress.class: alb`, `alb.ingress.kubernetes.io/scheme: internet-facing`. 포털이 브라우저에서 접근 가능해야 하므로 외부 노출 필수. (미작성)
    - [x] `src/api/Dockerfile` 작성 및 ECR Push (k8s-deploy.yml에서 빌드/푸시).
  - [ ] **Task 4.3.5: UX 구조적 버그 수정 (코드 레벨)**
    > 코드 분석에서 발견된 구조적 결함 목록. 신규 기능이 아닌 **기존 구현의 버그**이므로 Task 4.3과 함께 처리한다.

    - [ ] **[버그 1A] 페이지 첫 진입 시 캐시 시각 미표시** (`chat.html`/`portal.html`)
      - `GET /api/status` 엔드포인트 추가: `{"data_date": "2026-04-25", "cached_at": "2026-04-26T01:00:00Z"}` 반환.
      - 페이지 로드 시 이 엔드포인트를 호출해 헤더에 즉시 표시. `cached_at` 응답을 기다릴 필요 없음.
    - [ ] **[버그 1B] "캐시 갱신 시각" ≠ "데이터 기준일" 구분 없음** (`src/api/main.py`)
      - `_cache_updated_at` 외에 `_data_date: str` 전역변수 추가. `refresh_cache()` 안에서 `yesterday` 변수 값을 함께 저장.
      - `/api/status`, `/api/chat` 응답에 `"data_date"` 필드 포함. UI 헤더에 `"2026-04-25 기준 데이터 · 01:00 갱신"` 형태로 표시.
    - [ ] **[버그 2A] APScheduler 타임존 미설정** (`src/api/main.py:111`)
      - `scheduler.add_job(refresh_cache, "cron", hour=hour, minute=0)` →
        `scheduler.add_job(refresh_cache, "cron", hour=hour, minute=0, timezone="Asia/Seoul")` 로 변경.
      - `CACHE_REFRESH_HOUR=1`은 KST 01:00으로 동작. 현재는 UTC 01:00(= KST 10:00)으로 잘못 동작 중.
    - [ ] **[버그 2B] HPA multi-replica + in-memory cache 불일치** (`hpa.yaml`, `main.py`)
      - `_gold_cache`, `_cache_updated_at`, `_data_date` 전역변수가 Pod별로 독립. 운영자가 요청마다 다른 `cached_at`을 받을 수 있음.
      - 해결: **ElastiCache Redis** 도입 대신, `GET /api/status`에서 `cached_at`을 응답하고 HPA `minReplicas`를 2→1로 낮추는 것으로 우선 해결. (Redis 도입은 Phase 5 이후 검토)
      - 단기 해결책으로 `k8s/api/hpa.yaml`의 `minReplicas: 1`로 변경, 메모리 스케일 트리거 유지.
    - [ ] **[버그 3B] FastAPI 딥링크 라우트 없음** (`src/api/main.py`)
      - `GET /?robot_id={id}` URL 파라미터 수신 시 `portal.html`에 robot_id를 template variable로 주입.
      - `portal.html` JS: 페이지 로드 시 `URLSearchParams`로 `robot_id` 파싱 → 존재하면 채팅 입력란에 `"ROBOT-XXXXX의 현재 상태를 분석해줘"` 자동 입력 + 전송.
    - [ ] **[버그 4A] `innerHTML` XSS 리스크** (`portal.html`)
      - Bedrock 응답의 `[ROBOT-XXXXX]` 패턴을 딥링크로 변환 시 `innerHTML` 사용 필요 → `DOMPurify` 라이브러리 추가 (CDN: `https://cdn.jsdelivr.net/npm/dompurify`).
      - 렌더링 전 `DOMPurify.sanitize(html)` 필수 적용.
    - [ ] **[버그 4B] Bedrock 포맷 규칙이 user 메시지에 혼재** (`src/api/main.py:132-138`)
      - 현재: `prompt = f"...질문: {req.question}"` (단일 user 메시지).
      - 수정: Bedrock Messages API `system` 필드에 포맷 규칙 분리:
        ```python
        system = "로봇 ID 언급 시 반드시 [ROBOT-XXXXX] 형식(대괄호+5자리 숫자)으로 표기하라."
        body = {"system": system, "messages": [{"role": "user", "content": prompt}], ...}
        ```
    - [ ] **[버그 5] slowapi + HPA = Rate Limit 무력화** (`src/api/main.py`)
      - slowapi는 in-process 메모리 카운터 → 2개 Pod = IP당 실제 20회/분 허용.
      - 단기 해결: `minReplicas: 1` 조정(버그 2B와 동일). 근본 해결은 Phase 5에서 Redis 백엔드 적용 시 검토.
      - plan.md에 **알려진 제약사항**으로 명시: "HPA 활성화 시 slowapi Rate Limit은 replica 수 배만큼 완화됨."

  - [ ] **Task 4.4: E2E Integration & API Validation**
    - [ ] `tests/api/` 생성:
      - [ ] `TestClient`를 사용하여 `POST /api/chat` 엔드포인트가 Bedrock 호출 결과를 정상 반환하는지 테스트.
      - [ ] 캐시 갱신 로직이 정해진 시간에 작동하는지 검증.
    - [ ] **[E2E 알림 테스트]** Lambda를 직접 트리거 하거나 Alert KDS에 데이터를 넣어 Slack 채널에 최종 메시지가 도달하는지 확인.


  ### Phase 5: Observability & Predictive Maintenance (X-Ray/OTEL + SageMaker)
  *목표: 전구간 분산 추적으로 파이프라인 가시성을 확보하고, Gold 데이터 기반 ML 예측정비 모델로 사후 대응에서 사전 예방으로 전환한다.*

  - [ ] **Task 5.1: 분산 추적 — AWS X-Ray + OpenTelemetry (ADOT)**
    - [x] `terraform/addons.tf`에 **ADOT Operator** Helm 배포 추가 (네임스페이스: `monitoring`).
    - [ ] Generator, API K8s Deployment에 `instrumentation.opentelemetry.io/inject-python: "true"` 어노테이션 추가 → ADOT 사이드카 자동 주입. (API ✅, Generator 미적용)
    - [ ] AWS X-Ray Group 생성: `robot-telemetry-traces`. (IAM 권한은 ✅, X-Ray Group Terraform 리소스 미작성)
      - [x] IAM Role에 `xray:PutTraceSegments` + `xray:PutTelemetryRecords` 권한 추가 (Generator/API IRSA).
    - [ ] Grafana에 X-Ray Data Source 연동:
      - [x] `grafana/dashboards/observability.json` 신규 작성 — 엔드포인트별 레이턴시 P50/P95/P99, 에러율, Generator → Kinesis 전송 지연 시계열.
    - [ ] **[검증]** `/api/chat` 호출 후 X-Ray 콘솔에서 Service Map이 Generator → Kinesis → API 경로로 표시되는지 확인.
  - [ ] **Task 5.2: ML 기반 예측정비 (Amazon SageMaker)**
    - [x] `modules/data_pipeline/sagemaker.tf` 작성:
      - [x] SageMaker IAM Role: Athena 조회 + S3 읽기/쓰기 권한.
      - [x] S3 prefix `ml-models/` 정의 (학습 결과 아티팩트 저장).
    - [ ] `src/ml/train.py` 작성:
      - [x] Gold Table(`gold_robot_daily_stats`)에서 지난 30일 데이터 Athena 조회.
      - [ ] Feature: `avg_motor_temp`, `max_motor_temp`, `battery_drain_rate`, `operation_ratio`. (현재 train.py가 참조하는 컬럼 — gold DDL은 `active_hours`만 보유, `battery_drain_rate`/`operation_ratio`/`machine_failure` 미존재. step 4 (dag-fix) 또는 별도 step에서 정합성 결정 필요)
      - [ ] Label: `machine_failure`(AI4I 2020 기준). XGBoost 분류 모델 학습. (gold 테이블에 `machine_failure` 컬럼 없음 — 별도 join 또는 silver 단계 보존 필요, 미해결)
      - [x] 학습된 모델을 SageMaker S3 아티팩트로 저장.
    - [ ] SageMaker Training Job 실행 스크립트 작성 + SageMaker Endpoint 배포 (`robot-failure-predictor`). (train.py에 deploy 호출 ✅, `train_entry.py` (XGBoost entry point) 미작성)
    - [x] `dags/robot_daily_etl.py` 마지막 Task에 **주간 재학습 분기** 추가 (`execution_date.weekday() == 0` 조건).
    - [x] `src/api/main.py`에 `POST /api/predict` 엔드포인트 추가:
      - [x] 요청 바디: `{ "robot_id": "...", "avg_motor_temp": 88.5, "battery_drain_rate": 12.3, ... }`
      - [x] SageMaker Runtime `invoke_endpoint` 호출 → 고장 확률 반환.
      - [x] Rate Limiting: IP 기준 분당 20회.
    - [x] `k8s/api/deployment.yaml` IRSA에 `sagemaker:InvokeEndpoint` 권한 추가 (iam.tf api_permissions 정책에 포함).
    - [x] **[검증]** `tests/ml/test_predict_endpoint.py` 작성 — Mock SageMaker 응답으로 `/api/predict` 정상 반환 확인.
  - [ ] **Task 5.3: E2E Hardening Validation**
    - [ ] X-Ray Service Map에서 전구간 트레이스 확인.
    - [ ] SageMaker Endpoint에 테스트 데이터 주입 → 고장 확률 > 0.7 로봇 식별 확인.
    - [ ] DLQ CloudWatch Alarm 강제 트리거 → Slack 알림 수신 확인.

  ---

  ## 📝 AI Action Log
  *작업이 완료될 때마다 날짜, 완료된 Task, 변경된 파일, 이슈 사항을 기록하십시오.*

  - `[2026-04-26]`: Phase 0 Task 0.1 완료 — `eu-west-1` 리전 및 `robot-telemetry` 네이밍 규칙으로 신규 terraform 파일 작성 (network.tf, eks_and_iam.tf, karpenter.tf, addons.tf, cicd_gitops.tf). VPC Endpoint(S3 Gateway + Kinesis Interface) 추가. Phase 0 `check_env` pre-gate 실패로 현재 `error` 상태. Task 0.2 (GitHub Actions) 미구현.
  - `[2026-04-26]`: Phase 1 Terraform 모듈 선행 구현 완료 — `modules/data_pipeline/` 하위 kinesis.tf(KDS 10샤드 + Firehose Parquet), glue.tf(Registry+Bronze Table), iam.tf(Generator/API/Lambda IRSA), cloudwatch.tf(알람), lambda.tf(stub), sns.tf, ssm.tf 작성. 체크박스 sync 완료.
  - `[2026-04-26]`: plan.md 품질 검토 완료 — phases/index.json Phase 5 status 오류(`completed`→`pending`) 정정, 오타(`cicd_gitpos.tf`→`cicd_gitops.tf`) 수정, Task 1.3.1(Athena Workgroup) 누락 추가, S3 Lifecycle 미구현 명시.
  - `[2026-04-26]`: Phase 2 Step 0(athena-ddl) 정정 완료 — silver/gold DDL에 Partition Projection 누락 발견, dt DATE 기반 projection TBLPROPERTIES 추가 + `parquet.compression` 키 정정. 이전 실행은 API 429 rate limit으로 status 업데이트 실패했지만 산출물은 커밋된 상태였음. Task 2.1 체크박스 [x] 마킹.
  - `[2026-04-26]`: Phase 2에 Step 4(dag-fix) 신설 — DAG ↔ DDL 정합성 불일치 3건 발견(bronze WHERE 절 파티션 키 불일치, gold INSERT 컬럼 불일치, bedrock SELECT 컬럼 불일치). step0.md spec을 source of truth로 두고 DAG를 DDL에 맞추는 방향. phases/2-batch/step4.md 작성, phases/index.json 2-batch status `error`→`pending`.
  - `[2026-04-26]`: Phase 2 Step 4(dag-fix) 실행 완료 — dags/robot_daily_etl.py의 bronze WHERE 절을 year/month/day 파티션 키 기반으로 변경, gold INSERT를 active_hours로 정정(operation_ratio/battery_drain_rate 제거), bedrock SELECT/data_summary도 동기화. AC 7/7 통과.
  - `[2026-04-26]`: Phase 2 Step 5(data-quality-gate) 신설 + 실행 — Task 2.0 충족. requirements.txt 신규 작성, evaluate_quality 순수 함수 + _quality_check PythonOperator + _publish_dq_failure SNS 알림 추가, DAG chain `quality_check → bronze_to_silver → ...` 로 재배선. tests/etl/test_data_quality.py 7건 통과. tests/conftest.py에 sys.path 추가 (dags/ 임포트 경로). **2-batch phase의 모든 step (0~5) completed**.
  - `[2026-04-26]`: plan.md 전체 sync sweep 완료 — 실 산출물과 체크박스 정합성 검증. **체크박스 잘못 [ ]로 남아있던 항목들을 [x]로 정정**: Task 0.2(워크플로 3종 + Lambda ZIP 빌드 모두 구현됨), Task 1.3(s3_lifecycle.tf 존재), Task 1.3.1(Athena Workgroup glue.tf 포함), Task 1.5(Generator 전체 구현), Task 1.6 단위 테스트, Task 2.2(Airflow Helm), Task 4.2 Grafana Helm 일부, Task 4.3 main.py partial, Task 5.1 ADOT/X-Ray IRSA/observability.json, Task 5.2 거의 전체. **진짜 미구현으로 남은 핵심 gap**: ① Task 4.2 Grafana ALB Ingress + 3개 대시보드 JSON, ② Task 4.3 portal.html(현재 chat.html만) + API ALB Ingress + slowapi requirements 누락, ③ Task 4.3.5 6개 UX 버그 전체, ④ Task 4.4 tests/api, ⑤ Task 3.1 Flink 전체, ⑥ Task 2.0 Great Expectations DQ Gate, ⑦ Task 5.2 train_entry.py 및 ML feature 컬럼 정합성. 발견된 부수 이슈: cloudwatch.tf 알람 `comparison_operator` 논리 반전(`GreaterThanThreshold` → `LessThanThreshold` 필요), main.py/k8s region 불일치(eu-west-1 vs ap-northeast-2), Grafana adminPassword 하드코딩.
  # Execution Plan & Feedback Board

  **Current Status:** `[DRAFT]`
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
  | ECR + GitHub Actions OIDC | `cicd_gitpos.tf` | repo명 등 변경 후 신규 생성 |
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
  | Generator ECR Repo | `robot-telemetry-generator` | 따릉이 폴링 → KDS 전송 컨테이너 |
  | AI Query API ECR Repo | `robot-telemetry-api` | FastAPI 채팅 서버 컨테이너 | -> MSA 아키텍처 사용할 수 있는지 확인하고 알려줘

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

  ### `.env` 파일 템플릿 (값은 직접 채울 것)
  ```dotenv
  # AWS Credentials
  AWS_ACCESS_KEY_ID=
  AWS_SECRET_ACCESS_KEY=
  AWS_REGION=ap-northeast-2

  # S3
  S3_BUCKET_NAME=de-ai-06-827913617635-ap-northeast-2-an

  # Kinesis
  KINESIS_STREAM_NAME=robot-telemetry-stream
  KINESIS_ALERT_STREAM_NAME=robot-anomaly-alert-stream

  # Generator
  ROBOT_COUNT=10000              # 가상 로봇 대수 (KDS 10 Shard 기준 최대 10,000)

  # 따릉이 공공 API (공공데이터포털 발급)
  DDAREUNGI_API_KEY=

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
  ```

  ---

  ## 🚀 Milestone Tasks (5/8 Deadline)

  ### Phase 0: 신규 Terraform 프로젝트 기반 구성
  *목표: 래플 프로젝트 코드 패턴을 기반으로 신규 네트워크, EKS, CI/CD 인프라를 처음부터 프로비저닝한다.*

  - [ ] **Task 0.1: 신규 Terraform 프로젝트 셋업**
    - [ ] `terraform/` 루트에 `providers.tf`, `variables.tf`, `network.tf`, `eks_and_iam.tf`, `karpenter.tf`, `addons.tf`, `cicd_gitops.tf` 작성 (래플 프로젝트 코드 패턴 참조).
    - [ ] `variables.tf`에 `aws_region = "ap-northeast-2"` 로 설정. `.env` 파일에서 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`를 로드하는 방식으로 자격증명 구성 (하드코딩 금지).
    - [ ] `modules/data_pipeline/` 디렉토리 생성 — 데이터 파이프라인 전용 리소스(Kinesis, Firehose, Glue, IAM)는 전부 이 모듈 하위에 작성.
    - [ ] Bastion + RDS는 이번 프로젝트에서 불필요하므로 생성하지 않는다.
    - [ ] **[비용·보안]** `network.tf`에 VPC Endpoint 2개 추가:
      - `aws_vpc_endpoint` type=`Gateway` for **S3** — 무료. EKS Pod → S3 트래픽이 NAT Gateway를 우회해 AWS 내부 네트워크로 처리됨.
      - `aws_vpc_endpoint` type=`Interface` for **Kinesis Streams** (PrivateLink) — Generator의 초당 10,000건 전송 트래픽이 퍼블릭망을 타지 않음. NAT Gateway 데이터 처리 비용 차단.

  ---

  ### Phase 1: Ingestion & Data Lake Infrastructure (Terraform & Generator)
  *목표: 서울시 따릉이 API를 로봇 센서 데이터로 모킹하여 Kinesis로 전송하고, S3에 Parquet 포맷으로 동적 파티셔닝 적재.*

  - [ ] **Task 1.1: IAM & Security Configuration (Terraform)**
    - [ ] `modules/data_pipeline/iam.tf` 작성.
    - [ ] EKS Pod이 Kinesis에 `PutRecord` 할 수 있도록 **IRSA(IAM Role for Service Accounts)** 신규 생성. Phase 0에서 생성된 EKS 클러스터의 OIDC Issuer URL 참조.
    - [ ] Firehose가 S3 버킷 `de-ai-06-827913617635-ap-northeast-2-an`에 쓸 수 있는 `firehose_delivery_role` 신규 작성. 버킷 ARN은 `data "aws_s3_bucket"` 으로 참조 (버킷 자체는 Terraform으로 관리하지 않음).
  - [ ] **Task 1.2: Kinesis Data Streams (KDS) Provisioning (Terraform)**
    - [ ] `modules/data_pipeline/kinesis.tf`에 `aws_kinesis_stream` 리소스 생성 (Provisioned Mode, **Shard Count: 10**).
      - 산출 근거: 가상 로봇 10,000대 × 1 rec/sec = **10,000 rec/sec**, 레코드당 ~1KB → **10 MB/sec**. KDS Shard 1개 한도(1,000 rec/sec, 1 MB/sec)에서 **10 Shards** 필요.
    - [ ] 데이터 보존 기간(Retention Period) 24시간으로 설정.
  - [ ] **Task 1.3: S3 Data Lake Prefix 정의**
    - [ ] **S3 버킷 신규 생성 금지.** 사전 생성된 버킷 `de-ai-06-827913617635-ap-northeast-2-an` 사용.
    - [ ] 논리적 Prefix `bronze/`, `silver/`, `gold/`는 S3 오브젝트 키 네이밍 규칙으로만 정의 (별도 Terraform 리소스 불필요).
  - [ ] **Task 1.3.5: Glue Data Catalog Schema 사전 선언 (Terraform)**
    - [ ] `modules/data_pipeline/glue.tf` 작성 — **Task 1.4(KDF) 이전에 반드시 완료해야 한다.**
    - [ ] `aws_glue_catalog_database` (`robot_telemetry_db`) 생성.
    - [ ] `aws_glue_catalog_table` (`bronze_robot_telemetry`) 생성: KDF가 Parquet 변환 시 참조할 컬럼 스키마 선언 (`robot_id`, `pos_x`, `pos_y`, `battery_level`, `current_load`, `motor_temp`, `timestamp`).
    - [ ] KDF는 이 Glue Table을 `data_format_conversion_configuration`의 `schema_configuration`으로 참조한다. Glue Table이 없으면 KDF 프로비저닝이 실패한다.
  - [ ] **Task 1.4: Kinesis Data Firehose (KDF) Configuration (Terraform)**
    - [ ] `modules/data_pipeline/kinesis.tf`에 `aws_kinesis_firehose_delivery_stream` 추가.
    - [ ] Source: Task 1.2에서 생성한 KDS. Destination: `de-ai-06-827913617635-ap-northeast-2-an` 버킷 (`data "aws_s3_bucket"` 참조).
    - [ ] **[핵심]** Data Format Conversion 활성화: AWS Glue Data Catalog 테이블 포맷을 참조하여 원본 JSON을 **Parquet**으로 변환 (Snappy 압축).
    - [ ] **[핵심]** Dynamic Partitioning 설정: S3 Prefix를 `bronze/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/` 형태로 구성.
  - [ ] **Task 1.5: Data Replayer (Generator) Implementation (Python)**
    - [ ] `src/generator/app.py` 작성:
      - [ ] 따릉이 API(`getBikeStatus`) 최초 1회 호출 → 스테이션 ID·좌표를 로봇 Seed 데이터로 추출.
      - [ ] `asyncio` 기반으로 가상 로봇 **`ROBOT_COUNT`(기본 10,000)대** 동시 시뮬레이션. 각 로봇이 독립적인 async 태스크로 초당 1건 센서 데이터 생성.
      - [ ] 생성 필드: `robot_id`, `pos_x`, `pos_y`, `battery_level`(0~100), `motor_temp`(60~100°C 난수), `current_load`, `timestamp` (ISO8601).
      - [ ] `boto3` `put_records` (최대 500건/배치)로 묶어 KDS에 전송 → 초당 20회 배치 호출로 10,000 rec/sec 처리.
    - [ ] Phase 0에서 생성한 EKS 클러스터에 배포하기 위한 `Dockerfile` 및 `k8s/generator/Deployment.yaml` 작성. 일반 `Deployment` 사용 (Argo Rollouts 금지). Pod의 Service Account에 Task 1.1의 IRSA 어노테이션 추가.
  - [ ] **Task 1.6: Ingestion Pipeline Validation (pytest)**
    - [ ] `tests/generator/` 생성 및 `pytest` 기반 단위 테스트 작성:
      - [ ] 생성된 데이터 스키마가 Glue Table 정의와 일치하는지 검증.
      - [ ] `ROBOT_COUNT` 만큼의 태스크가 정상적으로 생성되는지 확인.
    - [ ] **[통합 테스트]** 로컬 또는 Dev 환경에서 KDS로 실제 데이터를 전송하고, AWS CLI를 통해 Shard에서 레코드가 정상 수신되는지 확인.

  ### Phase 2: Batch Processing & Medallion Architecture (Athena + Airflow)
  *목표: Airflow 스케줄링을 통해 Bronze(Raw) 데이터를 Silver(정제), Gold(집계) 테이블로 매일 자정에 자동 가공.*

  - [ ] **Task 2.1: Athena / Glue Data Catalog DDL (SQL)**
    - [ ] Bronze Table DDL: S3 `/bronze` 경로를 가리키는 External Table 생성. `PROJECTION` 속성을 사용하여 파티션 프로젝션 활성화(Athena 스캔 비용 최적화).
    - [ ] Silver Table DDL: Parquet 포맷의 정제용 테이블 스키마 정의.
    - [ ] Gold Table DDL: 일별 집계 분석용 테이블 스키마 정의.
  - [ ] **Task 2.2: Airflow Environment Setup**
    - [ ] EKS 내에 Helm Chart를 사용하여 Airflow 최소 사양 배포 (또는 로컬 Docker Compose 활용 시 `docker-compose.yaml` 작성).
    - [ ] AWS Athena 및 S3 통신을 위한 Airflow Connection 설정 (AWS Provider).
  - [ ] **Task 2.3: ETL Pipeline DAG 작성 (Python `dags/robot_daily_etl.py`)**
    - [ ] **[멱등성 보장]** 모든 Task는 `execution_date` 기준으로 S3 특정 파티션 경로를 바라보고, 재실행 시 기존 파티션을 덮어쓰도록(`INSERT OVERWRITE`) 로직 구성.
    - [ ] **Task: Bronze to Silver (Athena Operator):**
      - [ ] `motor_temp`가 500도 이상인 이상치(Outlier) 제거.
      - [ ] 중복 수신된 텔레메트리 데이터 제거(Deduplication).
      - [ ] `battery_level` 등 데이터 타입 정확하게 Casting.
    - [ ] **Task: Silver to Gold (Athena Operator):**
      - [ ] 일별/로봇별 집계 쿼리 실행.
      - [ ] 지표 도출: 일일 평균/최고 모터 온도, 배터리 소모율(시작-종료 시점 차이), 가동 시간 비율.
  - [ ] **Task 2.4: ETL Logic & DAG Validation**
    - [ ] `tests/etl/` 생성:
      - [ ] `pytest-airflow` 등을 활용하여 DAG의 순환 참조 및 문법 오류 검사.
      - [ ] **[SQL 검증]** Mock 데이터를 활용하여 Athena ETL 쿼리가 이상치(500도 이상)를 정확히 필터링하는지 단위 테스트.

  ### Phase 3: Real-time Anomaly Detection & AI Insight (Flink + Bedrock)
  *목표: 스트리밍 데이터를 실시간으로 모니터링하고, 배치 집계 결과를 바탕으로 LLM 리포트 생성.*

  - [ ] **Task 3.1: Real-time Processing (Apache Flink)**
    - [ ] AWS Managed Flink Studio(Zeppelin) 또는 SQL Client를 위한 구성.
    - [ ] KDS를 Source Table로 매핑.
    - [ ] 1분 Tumbling Window 기반 이상 탐지 SQL 작성:
      - [ ] 조건: `motor_temp` > 90도 초과 로봇 식별.
    - [ ] 탐지된 이상 이벤트를 두 곳에 동시 Sink: ① S3 `alerts/` 경로 (이력 로깅), ② **`robot-anomaly-alert-stream`** (Alert 전용 KDS, Native Sink 사용) — SNS 직접 연결 금지 (Flink에 SNS Native Sink 없음).
  - [ ] **Task 3.2: LLM 배치 리포트 (Amazon Bedrock)**
    - [ ] `dags/robot_daily_etl.py`의 마지막 Task로 Python Operator 추가.
    - [ ] Gold Table의 최신 파티션 데이터(일일 상태 요약)를 `boto3` Athena Client로 읽어옴.
    - [ ] 프롬프트 엔지니어링: "다음은 오늘 공장 로봇들의 상태 지표야. [데이터] 이를 분석해서 가장 점검이 시급한 로봇 3대와 그 이유를 정비반장에게 보내는 형식으로 300자 이내로 요약해."
    - [ ] Bedrock API(`InvokeModel`, Claude 3 Sonnet/Haiku)를 호출하여 텍스트 리포트 생성.
    - [ ] 생성된 리포트를 S3 `reports/YYYY-MM-DD.txt` 경로에 저장.
  - [ ] **Task 3.3: Real-time & AI Validation**
    - [ ] **[Flink 검증]** 90도 이상의 테스트 데이터를 KDS에 주입하고, Flink가 이를 올바르게 탐지하여 Alert KDS로 Sink 하는지 확인.
    - [ ] **[Bedrock 검증]** Mock 데이터를 기반으로 Bedrock 프롬프트가 예상된 형식의 JSON/Text 리포트를 반환하는지 `pytest`로 검증.

  ### Phase 4: Serving Layer (Slack Alert + Grafana + AI Chat)
  *목표: 파이프라인 결과를 운영자가 실시간으로 확인하고 AI에게 직접 질문할 수 있는 서비스 레이어를 구축한다.*

  - [ ] **Task 4.1: Real-time Slack Alert (Terraform — Alert KDS → Lambda → SNS → Slack)**
    - [ ] `modules/data_pipeline/sns.tf` 작성: `aws_sns_topic` (`robot-anomaly-alerts`) 생성. `aws_sns_topic_subscription`으로 Slack Webhook URL 구독.
    - [ ] `modules/data_pipeline/lambda.tf` 작성:
      - [ ] `aws_lambda_function` (`robot-anomaly-alert-lambda`) 생성: Python 런타임. KDS 레코드 파싱 → SNS Publish 로직.
      - [ ] `aws_lambda_event_source_mapping`: `robot-anomaly-alert-stream` KDS를 트리거로 연결.
      - [ ] Lambda IAM Role: `kinesis:GetRecords` + `sns:Publish` 권한 부여.
    - [ ] 알림 메시지 포맷: `[⚠️ 이상 감지] robot_id: {id} | motor_temp: {temp}°C | 감지 시각: {timestamp}`
    - [ ] 아키텍처: **Flink → robot-anomaly-alert-stream(KDS) → Lambda → SNS → Slack**
  - [ ] **Task 4.2: Grafana Dashboard (EKS Helm)**
    - [ ] `terraform/addons.tf`에 Grafana Helm release 추가.
    - [ ] Grafana Data Source 설정: ① Athena Plugin (Silver/Gold 테이블 조회), ② CloudWatch (Kinesis 처리량, EKS Pod 메트릭).
    - [ ] `grafana/dashboards/` 하위에 3개 대시보드 JSON 작성:
      - [ ] `robot_fleet.json`: 로봇별 최신 motor_temp · battery_level 상태 카드.
      - [ ] `anomaly_timeline.json`: 시간대별 이상 탐지 건수 시계열 그래프.
      - [ ] `pipeline_health.json`: Kinesis IncomingRecords, Firehose DeliveryToS3 메트릭.
  - [ ] **Task 4.3: 대화형 AI Query API (FastAPI + Bedrock)**
    - [ ] `src/api/main.py` 작성 (FastAPI):
      - [ ] **in-memory 캐시**: 앱 시작 시 + 매일 `CACHE_REFRESH_HOUR`시(기본 01:00 KST)에 Athena `gold_robot_daily_stats` 최신 파티션을 한 번 조회하여 전역 변수에 저장. `apscheduler` 사용.
      - [ ] `POST /api/chat` — 요청 바디 `{ "question": "..." }` 수신 → **캐시에서 Gold 데이터 즉시 읽기** → 질문 + 데이터를 Bedrock Claude 3에 전달 → 자연어 답변 JSON 반환 (Athena 실시간 조회 금지).
      - [ ] `GET /` — `src/api/templates/chat.html` 정적 채팅 UI 서빙.
    - [ ] `modules/data_pipeline/iam.tf` 업데이트: AI API Pod용 IRSA에 Athena 조회 + Bedrock `InvokeModel` 권한 추가.
    - [ ] `k8s/api/deployment.yaml` 작성: EKS Deployment + Service (ClusterIP). IRSA 어노테이션 추가.
    - [ ] `src/api/Dockerfile` 작성 및 ECR Push.
  - [ ] **Task 4.4: E2E Integration & API Validation**
    - [ ] `tests/api/` 생성:
      - [ ] `TestClient`를 사용하여 `POST /api/chat` 엔드포인트가 Bedrock 호출 결과를 정상 반환하는지 테스트.
      - [ ] 캐시 갱신 로직이 정해진 시간에 작동하는지 검증.
    - [ ] **[E2E 알림 테스트]** Lambda를 직접 트리거 하거나 Alert KDS에 데이터를 넣어 Slack 채널에 최종 메시지가 도달하는지 확인.


  ---

  ## 📝 AI Action Log
  *작업이 완료될 때마다 날짜, 완료된 Task, 변경된 파일, 이슈 사항을 기록하십시오.*

  - `[YYYY-MM-DD]`: Initial Plan Draft Created. Waiting for Human Approval.
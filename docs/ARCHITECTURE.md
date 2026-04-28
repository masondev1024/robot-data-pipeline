# 아키텍처

## 디렉토리 구조
```
src/
├── generator/             # AI4I 2020 CSV Seed 기반 로봇 시뮬레이터 → KDS 전송 (Python)
│   ├── app.py
│   └── Dockerfile
└── api/                   # 대화형 AI Query 서버 (FastAPI)
    ├── main.py            # POST /api/chat, GET / (채팅 UI)
    ├── templates/
    │   └── chat.html      # 채팅 인터페이스 UI
    └── Dockerfile

dags/
└── robot_daily_etl.py     # Airflow DAG: Bronze→Silver→Gold + Bedrock 배치 리포트

sql/
├── bronze_ddl.sql         # Athena External Table (Partition Projection)
├── silver_ddl.sql         # 정제 테이블
└── gold_ddl.sql           # 일별 집계 테이블

grafana/
└── dashboards/
    ├── robot_fleet.json   # 로봇 Fleet 현황 대시보드
    ├── anomaly_timeline.json  # 이상치 탐지 타임라인
    └── pipeline_health.json   # Kinesis 처리량 · EKS 메트릭

terraform/
├── providers.tf
├── variables.tf
├── network.tf             # VPC / 서브넷 3계층 + S3 Gateway Endpoint + Kinesis Interface Endpoint(PrivateLink)
├── eks_and_iam.tf         # EKS 클러스터 + 노드그룹 + IAM
├── karpenter.tf           # 노드 자동 확장
├── addons.tf              # ALB, ArgoCD, Airflow Helm, Grafana Helm
├── cicd_gitops.tf         # ECR + GitHub Actions OIDC
└── modules/
    └── data_pipeline/
        ├── iam_eks_irsa_full.tf  # IRSA 4종(Generator/API/Airflow/Grafana) + Firehose Delivery Role + Lambda Alert Role + Bedrock/Athena/Bedrock/SageMaker/SSM/X-Ray 정책 통합
        ├── kinesis.tf            # KDS(메인 N Shard + Alert 전용) + KDF (Format Conversion, Parquet)
        ├── glue.tf               # Glue DB + bronze_robot_telemetry 스키마 (Partition Projection)
        ├── sns.tf                # SNS Topic + Slack Webhook 구독
        ├── lambda.tf             # robot-anomaly-alert-lambda (Alert KDS → SNS 브리지)
        ├── flink.tf              # Managed Flink Application + 전용 IAM Role
        ├── sagemaker.tf          # SageMaker Endpoint 리소스
        ├── ssm.tf                # SSM Parameter (portal-url / grafana-url 등)
        ├── xray.tf               # X-Ray sampling rule
        ├── cloudwatch.tf         # Firehose 성공률 알람
        ├── s3.tf                 # Data Lake 버킷
        └── outputs.tf            # IRSA Role ARN 등 root 노출용

k8s/
├── generator/
│   └── deployment.yaml    # Generator Daemon Deployment + IRSA 어노테이션
└── api/
    └── deployment.yaml    # AI Query API Deployment + IRSA 어노테이션
```

## 아키텍처 패턴: Lambda Architecture + Serving Layer

### Speed Layer (실시간)
```
AI4I 2020 CSV Seed (data/seed_data.csv)
    → Generator Pod (robot-telemetry ns, ECR: robot-telemetry-generator, asyncio 10,000 로봇)
    → robot-telemetry-stream (KDS, robot_id Partition Key, 10 Shards, 24h Retention)
    → robot-anomaly-detector (Managed Flink, 1분 Tumbling Window)
    → 이상 탐지: motor_temp > 90°C
        ├── robot-anomaly-alert-stream (Alert KDS, Native Sink)
        │     └── robot-anomaly-alert-lambda (Lambda) → robot-anomaly-alerts (SNS) → Slack
        └── S3 bucket/alerts/ (이상 이벤트 로깅)
```

### Batch Layer (대용량)
```
robot-telemetry-stream (KDS)
    → robot-telemetry-firehose (KDF)
        (Format Conversion: JSON → Parquet/Snappy)
        (Dynamic Partitioning: bronze/year=.../month=.../day=.../hour=...)
    → S3: de-ai-06-.../bronze/year=.../month=.../day=.../hour=.../
        ↓ (Airflow DAG: robot_daily_etl, 매일 00:00 KST)
    → Athena Workgroup: robot-telemetry-workgroup / DB: robot_telemetry_db
        → bronze_robot_telemetry (Partition Projection External Table)
        → silver_robot_telemetry (이상치 제거 + 중복 제거 + 타입 Casting)
        → gold_robot_daily_stats (일별/로봇별 집계)
        → Bedrock Claude 3 Haiku: Gold 데이터 → 정비 리포트 → S3 reports/YYYY-MM-DD.txt
```

### Serving Layer (시각화 + AI 인터페이스)
```
[Grafana — monitoring ns, EKS Helm]
    ├── Data Source: Athena Plugin → robot_telemetry_db (silver/gold 조회)
    ├── Data Source: CloudWatch → robot-telemetry-stream 처리량, EKS 메트릭
    └── Dashboards: Robot Fleet / Anomaly Timeline / Pipeline Health

[AI Query API — robot-telemetry ns, ECR: robot-telemetry-api]
    in-memory cache (매일 CACHE_REFRESH_HOUR 시 갱신 ← Athena gold_robot_daily_stats)
    사용자 질문 (채팅 UI: GET /)
        → POST /api/chat
        → 캐시에서 Gold 데이터 즉시 읽기 (Athena 실시간 조회 없음)
        → Bedrock Claude 3 Haiku (질문 + 데이터 컨텍스트)
        → 자연어 답변 반환
```

## 데이터 스키마 (Data Contract)
| 필드 | 타입 | 설명 |
|------|------|------|
| `robot_id` | String | 로봇 식별자 (KDS Partition Key) |
| `pos_x`, `pos_y` | Float | 위치 좌표 |
| `battery_level` | Integer | 배터리 잔량 (0~100) |
| `current_load` | Integer | 적재 중량 |
| `motor_temp` | Float | 모터 온도 (이상 탐지 핵심 지표) |
| `timestamp` | String | ISO8601 포맷 (예: `2026-04-25T14:00:30Z`) |

## 상태 관리
- **배치 상태**: Airflow DAG Run 관리. Task 간 데이터 전달은 XCom 금지, S3 경로를 파라미터로 전달
- **스트리밍 상태**: Kinesis Shard Iterator (24h retention으로 재처리 가능)
- **인프라 상태**: Terraform Remote State (S3 backend 권장)
- **데이터 레이어**: Medallion 원칙 — Bronze(불변 Raw), Silver(정제), Gold(집계)
- **멱등성**: 모든 Airflow Task는 `execution_date` 기준 파티션을 `INSERT OVERWRITE`로 처리
- **알림 상태**: SNS Topic이 Fan-out 허브 역할. Flink → SNS → Slack. 알림 이력은 S3 `alerts/`에 별도 보관
- **AI Query 상태**: Stateless. 매 요청마다 Athena 최신 파티션 조회 후 Bedrock 호출. 세션/대화 이력 미보관 (초기 구현)

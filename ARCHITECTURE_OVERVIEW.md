# Robot Telemetry Platform — 시스템 아키텍처 완벽 가이드

> **목표**: 이 문서를 읽은 후 다음을 수행할 수 있어야 함
> - 전체 시스템의 데이터 흐름을 그릴 수 있다
> - 각 컴포넌트의 역할을 설명할 수 있다
> - "왜 이 기술을 선택했는가"에 답할 수 있다

#  추천 읽는 순서
                                                            
  ① ARCHITECTURE_OVERVIEW.md  (큰 그림 먼저)
        ↓                                                   
  ② DATA_FLOW_DETAILED.md     (레코드 1개 추적으로 흐름 
  체화)                                                     
        ↓
  ③ PHASE_DEEP_DIVE.md        (왜 이 기술인가 — 기술 결정   
  능력)                                                     
        ↓
  ④ OPERATIONAL_GUIDE.md      (실무 투입 직전 체크리스트) 


---

## 📐 시스템 전체 구조 (End-to-End)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       ROBOT TELEMETRY PLATFORM                          │
│                      (eu-west-1 AWS Region)                             │
└─────────────────────────────────────────────────────────────────────────┘

[INGESTION LAYER] → [STREAMING LAYER] → [BATCH LAYER] → [SERVING LAYER]
     ↓                    ↓                  ↓                 ↓
  Generator          Real-time            ETL Pipeline        Users
  (K8s Pod)         Anomaly              (Airflow)           Portal
                    Detection            Analytics           API
                    (Flink)              (Athena)            Chat

```

### 전체 흐름도 (한 줄 요약)
```
AI4I 2020 CSV → Generator → Kinesis → Firehose → S3 (Bronze)
                                ↓
                          Managed Flink
                          (Real-time)
                                ↓
                         Alert Stream
                                ↓
                          Lambda → SNS
                                ↓
                            Slack

Bronze → Athena ETL → Silver → Athena ETL → Gold
                                              ↓
                                    Bedrock Report
                                    (Daily Batch)
                                              ↓
                                      FastAPI Portal
                                   (Grafana + Chat)
```

---

## 🏗️ 레이어별 상세 설명

### 1️⃣ **INGESTION LAYER** — 데이터 수집

#### 컴포넌트
| 컴포넌트 | 기술 | 목적 | 특징 |
|---------|------|------|------|
| **Generator** | Python + boto3, K8s Deployment | AI4I 2020 CSV 기반으로 가상 로봇 10,000대 시뮬레이션 | async coroutine, 초당 10,000 rec 생성 |
| **Kinesis Data Streams (KDS)** | AWS 서비스, 10 Shard | 고속 수집 스트림 (1차 저장소) | 24시간 보존, 초당 10,000 rec 처리 |
| **Glue Schema Registry** | AWS Glue | 데이터 스키마 버전 관리 & 검증 | upstream 필드 변경 감지 |

#### 데이터 흐름
```
Generator (K8s Pod)
├─ 1. AI4I CSV 로드 (SEED_CSV_PATH)
├─ 2. ROBOT_COUNT개 가상 로봇 프로필 생성
│  └─ robot_id, pos_x, pos_y, battery_level, motor_temp, current_load, timestamp
├─ 3. asyncio로 초당 1건씩 센서 데이터 생성 (각 로봇마다 독립 coroutine)
│  └─ motor_temp: 60~100°C (기본) + spike 이벤트
│  └─ battery_level: 0~100% (감소 추세)
├─ 4. 500건씩 배치로 묶음 (boto3 put_records)
│  └─ 초당 20회 배치 호출 = 10,000 rec/sec
└─ 5. KDS로 전송 (IRSA 권한으로 PutRecord)
   └─ Glue Schema Registry로 검증
   └─ 실패 시 CloudWatch Logs 기록
```

#### 실무 지식 포인트
- **IRSA (IAM Roles for Service Accounts)**
  - Generator Pod의 ServiceAccount에 IAM Role이 연결됨
  - Pod이 AWS API 호출 시 임시 자격증명 자동 주입 (`.env` 파일 불필요)
  - 최소 권한 원칙: `kinesis:PutRecord`, `kinesis:PutRecords`만 허용

- **Schema Registry 검증**
  - Generator가 Kinesis에 보내기 전에 Glue Schema Registry로 JSON 필드 검증
  - 필드명 변경 시 자동 감지 → 파이프라인 보호

---

### 2️⃣ **STREAMING LAYER** — 실시간 처리

#### 컴포넌트
| 컴포넌트 | 기술 | 목적 | 특징 |
|---------|------|------|------|
| **Managed Flink** | Apache Flink (PyFlink) + Table API | 실시간 이상 탐지 | 상태 유지(State), Watermark 처리 |
| **Alert KDS** | AWS Kinesis (2 Shard) | 이상 이벤트 전달 | Lambda 트리거, 24시간 보존 |

#### 이상 탐지 로직 (중핵)

**조건 1: Moving Z-Score (통계 기반)**
```
robot_id별 5분 이동평균 μ, 이동표준편차 σ 계산
Z = |motor_temp - μ| / σ
조건: Z > 3.0 (3-sigma rule) → 이상
```
- 왜? 온도 변화 추세를 감지. 정상인 80°C에서 갑자기 95°C → 이상
- 예: 로봇이 평소 70°C인데 90°C → Z-Score 높음 → Alert

**조건 2: Multivariate Correlation (부하 대비 열**
```
motor_temp >= 85.0 AND (motor_temp / current_load) > 1.8
```
- 왜? 부하가 적은데 온도가 높으면 이상 (엔진 문제)
- 예: 로봇이 일을 별로 안 하는데 모터 온도가 높음 → 과열 → Alert

**최종 로직**
```
IF (Z-Score > 3.0) OR (과열 조건) THEN
  → 1분 Tumbling Window로 robot_id별 집계
  → Alert KDS로 Sink (알람 폭주 방지)
  → S3 alerts/ 경로에 JSON 기록 (이력 추적)
```

#### 데이터 흐름
```
Kinesis Main Stream (robot-telemetry-stream)
       ↓
Managed Flink Application
├─ 1. Source: KDS에서 JSON 읽기
│  └─ Watermark: event_time - 10초 (Late Data 10초까지 허용)
├─ 2. Processing: 5분 Tumbling Window로 통계 계산
│  └─ OVER PARTITION BY robot_id ORDER BY event_time RANGE INTERVAL '5' MINUTE PRECEDING
│  └─ avg_temp, stddev_temp, min_load 계산
├─ 3. 조건 1 & 2 평가
│  └─ Z-Score 계산 (σ > 0.5 가드)
│  └─ 부하 비율 계산 (load > 1 가드)
├─ 4. 이상 레코드 필터링
│  └─ 1분 Tumbling Window로 재집계 (alert_count, avg_temp)
└─ 5. 이중 Sink (동일 트랜잭션)
   ├─ Alert KDS (robot-anomaly-alert-stream)
   └─ S3 alerts/ prefix (JSON, 이력 추적)
```

#### 실무 지식 포인트
- **Watermark의 중요성**
  - Watermark 없이 Event Time Window 사용 → Window가 영원히 닫히지 않음 (상태 폭증)
  - `WATERMARK FOR event_time AS event_time - INTERVAL '10' SECOND` 필수
  
- **Late Data 처리**
  - 네트워크 지연으로 10초 이상 늦게 도착한 데이터 → 이미 닫힌 Window에 버림
  - 10초 이상 지연된 데이터는 신경 쓰지 않음 (로봇 센서 데이터는 최신성 중요)

- **Threshold 외부화**
  - `zscore.threshold=3.0`, `load.ratio.threshold=1.8` 을 코드에 hardcoding하지 않음
  - Flink `environment_properties`의 `property_map`으로 주입 → 재배포 없이 임계값 변경 가능

---

### 3️⃣ **BATCH LAYER** — 일일 ETL + 분석

#### 컴포넌트
| 컴포넌트 | 기술 | 목적 | 특징 |
|---------|------|------|------|
| **Kinesis Firehose (KDF)** | AWS 서비스 | KDS → S3 자동 전달 | Parquet 변환, Dynamic Partitioning |
| **Athena** | SQL 쿼리 엔진 | S3 Parquet 분석 | Serverless, Partition Projection |
| **Airflow** | 오케스트레이션 | DAG 스케줄링 & 모니터링 | KubernetesExecutor |
| **Glue Data Catalog** | 메타데이터 저장소 | 테이블 스키마 정의 | Bronze/Silver/Gold |

#### 메달리온 아키텍처 (Medallion Architecture)

```
┌──────────────────────────────────────────────────────────────┐
│                    S3 Data Lake                              │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  BRONZE (Raw Data)                                            │
│  ├─ Path: s3://bucket/bronze/year=*/month=*/day=*/hour=*/    │
│  ├─ Format: Parquet (Firehose가 변환)                         │
│  ├─ Retention: 90일 후 Glacier (비용 절감)                    │
│  └─ 특징: 원본 데이터 그대로 (스키마 변경 X)                  │
│                                                               │
│  ↓ (Athena ETL — 매일 자정)                                   │
│                                                               │
│  SILVER (Cleaned Data)                                        │
│  ├─ Path: s3://bucket/silver/dt=YYYY-MM-DD/                  │
│  ├─ Format: Parquet (압축: Snappy)                            │
│  ├─ Retention: 365일 후 Glacier                               │
│  └─ 특징: 이상치 제거, 중복 제거, Null 처리                  │
│     └─ motor_temp >= 500 제거                                │
│     └─ robot_id+timestamp 기준 중복 제거                     │
│     └─ battery_level: 0~100 범위 필터                        │
│                                                               │
│  ↓ (Athena ETL — 일 1회)                                      │
│                                                               │
│  GOLD (Business Metrics)                                      │
│  ├─ Path: s3://bucket/gold/dt=YYYY-MM-DD/                    │
│  ├─ Format: Parquet                                           │
│  ├─ Retention: 영구 보관 (분석 자산)                          │
│  └─ 특징: 일별/로봇별 집계                                    │
│     ├─ avg_motor_temp: 일일 평균 온도                         │
│     ├─ max_motor_temp: 최고 온도                              │
│     ├─ battery_drain: 배터리 소모량 (%)                       │
│     └─ active_hours: 가동 시간                                │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

#### Airflow DAG 흐름 (매일 자정)
```
robot_daily_etl (execution_date = 어제)
├─ 1. quality_check
│  └─ Great Expectations로 Bronze 데이터 품질 검증
│  └─ null 비율 < 1%, motor_temp 범위 0-500, battery_level 범위 0-100
│  └─ 실패 시 DAG 중단 + SNS Alert
│
├─ 2. bronze_to_silver
│  └─ Athena 쿼리:
│     SELECT robot_id, pos_x, pos_y, battery_level, motor_temp, 
│             timestamp, ROW_NUMBER() OVER (PARTITION BY robot_id, timestamp)
│     FROM bronze_robot_telemetry
│     WHERE year = {execution_date.year}
│       AND month = {execution_date.month}
│       AND day = {execution_date.day}
│       AND motor_temp < 500
│       AND battery_level BETWEEN 0 AND 100
│       AND robot_id IS NOT NULL
│     HAVING row_num = 1  -- 중복 제거
│  └─ 결과를 silver_robot_telemetry에 INSERT OVERWRITE
│
├─ 3. silver_to_gold
│  └─ Athena 쿼리:
│     SELECT dt, robot_id,
│            AVG(motor_temp) as avg_motor_temp,
│            MAX(motor_temp) as max_motor_temp,
│            100 - MIN(battery_level) as battery_drain,
│            COUNT(DISTINCT HOUR(timestamp)) as active_hours
│     FROM silver_robot_telemetry
│     WHERE dt = execution_date
│     GROUP BY dt, robot_id
│  └─ 결과를 gold_robot_daily_stats에 INSERT OVERWRITE
│
└─ 4. bedrock_report (AI 리포트 생성)
   └─ Gold 테이블의 오늘 데이터를 읽음
   └─ Bedrock Claude API 호출:
      "다음은 오늘 공장 로봇들의 상태 지표야. [데이터]
       이를 분석해서 가장 점검이 시급한 로봇 3대와 그 이유를
       정비반장에게 보내는 형식으로 300자 이내로 요약해."
   └─ 생성된 리포트를 S3 reports/YYYY-MM-DD.txt에 저장
   └─ 캐시된 데이터도 함께 업데이트 (API에서 사용)
```

#### 실무 지식 포인트
- **멱등성 (Idempotency)**
  - Airflow가 같은 DAG를 여러 번 실행해도 결과가 동일해야 함
  - `INSERT OVERWRITE`로 기존 파티션을 덮어씀 (재실행 시 부분 중복 방지)
  - `execution_date` 기준으로 정확히 어느 날 데이터를 처리하는지 명시

- **Partition Projection (비용 절감)**
  - Bronze/Silver/Gold 모두 `dt` 또는 `year/month/day` 파티션 키 사용
  - Athena가 S3 메타데이터 조회 스캔 대신 파티션 프로젝션 사용
  - 비용: 400MB 스캔 → 1MB 스캔 (400배 절감)

- **DLQ (Dead Letter Queue)**
  - Firehose가 S3 쓰기 실패 시 DLQ 경로로 리다이렉트 (bronze-dlq/)
  - 30일 후 자동 삭제 (Lifecycle Rule)
  - CloudWatch Alarm: `DeliveryToS3.Success < 95%` → SNS Alert

---

### 4️⃣ **SERVING LAYER** — 운영자 대면

#### 컴포넌트
| 컴포넌트 | 기술 | 목적 | 특징 |
|---------|------|------|------|
| **Slack Alert** | Lambda + SNS | 실시간 이상 알림 | Alert KDS → Lambda → SNS → Slack |
| **Grafana** | 시계열 대시보드 | 실시간 모니터링 | Athena + CloudWatch 데이터소스 |
| **FastAPI Portal** | Python 웹프레임워크 | 통합 관제 & AI 채팅 | iframe (Grafana + Chat) + SSE |
| **Bedrock Chat** | Claude 3 API | 자연어 분석 | in-memory 캐시 (Gold 데이터) |

#### Slack Alert 흐름
```
Alert KDS (robot-anomaly-alert-stream)
    ↓
Lambda Trigger (이벤트 소비)
    ├─ 1. KDS 레코드 파싱: robot_id, motor_temp, timestamp
    ├─ 2. Slack 메시지 생성:
    │  "⚠️ 이상 감지
    │   🤖 robot_id: ROBOT-00042
    │   🌡️  motor_temp: 95.3°C
    │   🕐 감지 시각: 2026-04-27T12:34:56Z
    │   🔗 포털에서 확인: https://k8s-xxx.elb.amazonaws.com/?robot_id=ROBOT-00042"
    ├─ 3. SSM `/robot-telemetry/portal-url` 런타임 조회 (콜드스타트 캐시)
    ├─ 4. SNS Topic `robot-anomaly-alerts`로 발행
    └─ 5. Slack Webhook으로 채널에 전송
```

#### Portal UI 구조
```
┌─────────────────────────────────────────────────────────┐
│  Robot Telemetry Portal                                 │
│  [2026-04-27 기준 데이터 · 01:00 갱신]                 │
├──────────────────────┬──────────────────────────────────┤
│                      │                                  │
│  [대시보드 탭 선택]   │        AI Chat Panel             │
│  ☐ Fleet Status      │   ┌──────────────────────────┐   │
│  ☐ Anomaly Timeline  │   │ 캐시 갱신: 2026-04-27    │   │
│  ☐ Pipeline Health   │   │ 01:00                    │   │
│                      │   └──────────────────────────┘   │
│                      │                                  │
│  [Grafana iframe]    │   [채팅 히스토리]               │
│  (Fleet 대시보드)    │                                  │
│                      │   사용자: ROBOT-00042의 상태를    │
│  - robot 카드        │   분석해줘                       │
│    (최신 temp)       │                                  │
│                      │   AI: ROBOT-00042는 금일 평균   │
│  - robot 카드        │   온도 82°C로 정상 범위.        │
│    (최신 battery)    │   다만 battery_drain 15% → 점검│
│                      │   권장. [상태보기 ▶]             │
│                      │                                  │
│                      │   사용자: [상태보기] 클릭        │
│                      │   → Grafana iframe src 변경      │
│                      │   → robot=ROBOT-00042 필터 적용  │
└──────────────────────┴──────────────────────────────────┘
```

#### AI Chat 엔드포인트 흐름
```
POST /api/chat
Body: { "question": "ROBOT-00042의 상태를 분석해줘" }

Server-side:
├─ 1. 캐시 상태 확인
│  └─ _gold_cache가 로드되었는가? (안 되면 503 반환)
│
├─ 2. Gold 데이터 즉시 읽기 (in-memory, Athena 쿼리 없음)
│  └─ 캐시에서 robot_id=ROBOT-00042 레코드 찾기
│  └─ data_summary = "robot_id: ROBOT-00042, avg_motor_temp: 82°C, max: 89°C, battery_drain: 15%, active_hours: 22"
│
├─ 3. Bedrock 호출 (프롬프트 + 캐시 데이터)
│  └─ system: "로봇 ID 언급 시 반드시 [ROBOT-XXXXX] 형식으로 표기"
│  └─ user: "현재 데이터: {data_summary}\n질문: {question}"
│  └─ max_tokens: 512, temperature: 0.7
│
├─ 4. 응답 생성 & 딥링크 추출
│  └─ response = "ROBOT-00042는 정상 범위지만 배터리 점검 권장..."
│  └─ regex: /\[ROBOT-\d{5}\]/g → 딥링크 추출
│  └─ links[] = [
│       {"text": "ROBOT-00042 상세보기", "url": "/grafana/d/robot_fleet?var-robot=ROBOT-00042"}
│     ]
│
└─ 5. 응답 반환
   JSON: { "response": "...", "links": [...], "data_date": "2026-04-27", "cached_at": "01:00" }
```

#### 실무 지식 포인트
- **In-Memory 캐시 vs Athena 쿼리**
  - Gold 데이터는 하루 1회 갱신 (자정) → Athena 쿼리할 필요 없음
  - API 시작 시 + 매일 01:00에 Gold 최신 파티션을 메모리에 로드
  - 사용자 채팅 요청 시 캐시에서 즉시 읽음 → 응답 속도 <100ms
  - Redis 없이 단일 Pod (minReplicas=1)로 동일 캐시 보장

- **Cold Start 처리**
  - API Pod 시작 직후 캐시 로드 중 → `_cache_ready` 플래그로 상태 관리
  - 로드 전 요청 → 503 Service Unavailable 반환
  - 보통 15~30초 내에 로드 완료

- **딥링크 & 포맷 규칙**
  - Bedrock 응답에서 `[ROBOT-XXXXX]` 패턴을 자동 감지
  - HTML 렌더링 시 `DOMPurify` 라이브러리로 XSS 방지
  - 버튼 클릭 → Grafana iframe 동적 로딩 (새 탭 열지 않음)

---

## 🔄 데이터 흐름 요약 (시간대별)

### 00:00 ~ 23:59 (실시간 흐름)
```
Generator (매초)
  ↓ (Kinesis 1,000 rec/ms)
KDS (10초 보존)
  ├─ (70ms 지연)
  ├─ Managed Flink → 이상 탐지 (Z-Score, 부하 비율)
  │   ↓
  │   Alert KDS (이상 이벤트만)
  │   ↓
  │   Lambda (Event Source Mapping)
  │   ↓
  │   SNS → Slack (실시간 알림)
  │
  └─ Firehose → S3 Bronze (5분 배치)
```

### 00:01 (자정 직후, Airflow 시작)
```
Airflow DAG (robot_daily_etl, execution_date=어제)
  ├─ 01:00 캐시 갱신 (APScheduler)
  │   └─ Athena: SELECT ... FROM gold_robot_daily_stats WHERE dt=어제
  │   └─ _gold_cache 업데이트
  │
  └─ 전체 ETL 흐름
    ├─ quality_check (Great Expectations)
    ├─ bronze_to_silver (Athena ETL)
    ├─ silver_to_gold (Athena ETL)
    └─ bedrock_report (Claude 분석)
        └─ reports/YYYY-MM-DD.txt 저장
```

---

## 🎯 아키텍처 설계 원칙

| 원칙 | 의미 | 적용 예 |
|-----|------|--------|
| **Serverless First** | 인프라 관리 최소화 | Lambda, Athena, Managed Flink (서버 관리 X) |
| **Idempotency** | 재실행해도 같은 결과 | `INSERT OVERWRITE`, `execution_date` 기반 파티셔닝 |
| **Late Data Tolerance** | 지연 데이터 처리 | Flink Watermark (10초), Bronze 보존 (24시간) |
| **Cost Optimization** | 불필요한 비용 제거 | Partition Projection, VPC Endpoint (NAT 비용 회피), Lifecycle Rules |
| **Security by Default** | 최소 권한 원칙 | IRSA (Pod별 IAM Role), Secrets Manager (민감 정보), SSM Parameter Store |
| **Observability** | 모든 것을 추적 | CloudWatch (Kinesis, Firehose, Airflow), X-Ray (Trace), Grafana (시계열) |

---

## 📚 다음 단계

이 문서에서 배운 개념:
1. ✅ 전체 데이터 흐름 (Generator → KDS → Flink → Athena → Portal)
2. ✅ 각 레이어의 역할 (Ingestion/Streaming/Batch/Serving)
3. ✅ 이상 탐지 로직 (Z-Score + 다변량 상관성)
4. ✅ 메달리온 아키텍처 (Bronze/Silver/Gold)

**다음 문서 읽기:**
- `DATA_FLOW_DETAILED.md` — 각 컴포넌트의 상세 데이터 흐름 (10분)
- `PHASE_DEEP_DIVE.md` — Phase별 구현 내용 및 기술 결정 (20분)
- `OPERATIONAL_GUIDE.md` — 운영/troubleshooting (15분)

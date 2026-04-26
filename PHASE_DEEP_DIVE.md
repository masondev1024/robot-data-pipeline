# Phase별 심층 분석 — 기술 선택 이유 & 구현 전략

> **목표**: 각 Phase가 왜 이런 구조인지, 대안은 뭐였는지, 언제 이 아키텍처를 바꿔야 하는지 판단할 수 있다

---

## Phase 0: 신규 Terraform 인프라 구축

### 목표
기존 래플(Raffle) 프로젝트의 Terraform 코드를 참조하되, 
**로봇 파이프라인 전용으로 신규 리전(eu-west-1)에 모든 리소스를 생성하는 것**

### 주요 컴포넌트

#### 1️⃣ VPC + 3계층 Subnet

```
프라이빗 subnet 구조 (High Availability):
eu-west-1a          eu-west-1b          eu-west-1c
────────────────────────────────────────────────────
Public              Public              Public
(NAT Gateway)       (NAT Gateway)       (NAT Gateway)
    ↓                   ↓                   ↓
Private             Private             Private
(EKS Worker)        (EKS Worker)        (EKS Worker)
    ↓                   ↓                   ↓
Database            Database            Database
(RDS Subnet)        (RDS Subnet)        (RDS Subnet)
```

**선택 이유:**
- **3 AZ 분산**: 한 zone 장애 → 다른 2개 존 자동 페일오버
- **NAT Gateway 분산**: 각 AZ마다 1개씩 → NAT 병목 회피
- **Subnet 격리**: Public ↔ Private 엄격 분리 (보안)

**비용 고려:**
- NAT Gateway 비용: AZ당 $32/월 × 3 = $96/월
- **VPC Endpoint (S3 Gateway)** 추가: **무료**, NAT 우회 → 데이터 처리 비용 70% 절감
- **VPC Endpoint (Kinesis Interface)**: Generator → KDS 트래픽이 퍼블릭망 안 탐 (보안)

#### 2️⃣ EKS Cluster + Karpenter

```yaml
EKS Cluster: robot-telemetry-cluster
├─ Version: 1.28 (최신 LTS)
├─ Endpoint: Managed by AWS (99.95% SLA)
├─ Encryption: etcd-KMS 암호화
│
├─ Node Group (Legacy, 편의상 유지)
│  └─ Instance Type: t3.large (2vCPU, 8GB RAM)
│  └─ Min: 2, Max: 10 (Manual)
│
└─ Karpenter (Autoscaler)
   └─ Consolidation: 1시간마다 과할당 Pod 정리
   └─ Interrupt Handling: Spot 인스턴스 중단 → 다른 노드로 재배치
```

**왜 Karpenter인가?**
- Kubernetes HPA (Horizontal Pod Autoscaler)는 Pod 수를 조정만 함
- Karpenter는 Pod 수 + Node 수를 동시에 최적화
- Spot 인스턴스 활용 → t3.large 가격 70% 절감

**트레이드오프:**
| 기술 | 장점 | 단점 |
|------|------|------|
| **Karpenter** | 자동 스케일 | 복잡한 설정, spot 중단 처리 필요 |
| **Manual ASG** | 심플 | 수동 스케일 필요 |
| **Fargate** | 서버리스 | KubernetesExecutor (Airflow) 미지원 |

→ **최종 선택**: Karpenter (장기 운영 기준 비용 최적)

#### 3️⃣ CI/CD 자동화 (GitHub Actions + OIDC)

```
GitHub Actions Workflow:
├─ terraform.yml
│  └─ trigger: terraform/ 변경
│  └─ Plan → PR 댓글 → 사람 승인 → Apply
│
├─ k8s-deploy.yml
│  └─ trigger: k8s/ 변경
│  └─ kubectl apply (자동)
│
└─ post-deploy.yml
   └─ trigger: ingress 생성 후
   └─ ALB DNS 폴링 → SSM 저장
```

**왜 OIDC인가?**
```python
# ❌ 구식 (하드코딩)
AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"

# ✅ OIDC (OpenID Connect)
GitHub Actions → AWS STS AssumeRoleWithWebIdentity
→ 임시 자격증명 발급 (15분 유효)
→ access key 저장소 불필요 (비용 0, 보안 ++)
```

**비용:**
- GitHub Actions: Free (public repo)
- OIDC: Free
- vs. AWS Secrets Manager: $0.4/월 (저가이지만 불필요)

### Phase 0 결과

```
✅ terraform apply 후:
- VPC 1개, Subnet 9개 (3 AZ × 3 tier)
- EKS Cluster 1개 (2 worker nodes)
- ALB Controller, Karpenter, ADOT 설치 완료
- ECR 2개 (robot-telemetry-generator, robot-telemetry-api)

⏱️  작업 시간: ~20분 (terraform apply)
💰 월 비용: ~$200
  ├─ EKS control plane: $73
  ├─ 2× t3.large on-demand: $60
  ├─ NAT Gateway: $96
  └─ Kinesis Interface Endpoint: $7.2
```

---

## Phase 1: Ingestion & Data Lake Infrastructure

### 목표
1. 가상 로봇 10,000대의 센서 데이터를 KDS로 고속 수집
2. Firehose로 S3에 Parquet + Dynamic Partitioning 저장
3. Glue Schema Registry로 데이터 검증

### 핵심 설계 결정

#### 1️⃣ Kinesis Shard Count = 10

```
요구사항:
- 로봇 10,000대 × 1 rec/sec = 10,000 rec/sec
- 레코드 크기: ~200 bytes (JSON)
- 처리량: 10,000 rec/sec × 200 bytes = 2 MB/sec

KDS Shard 한도:
- 처리량: 1,000 rec/sec per shard
- 대역폭: 1 MB/sec per shard

계산:
- 처리량 기준: 10,000 rec/sec ÷ 1,000 = 10 shards ✓
- 대역폭 기준: 2 MB/sec ÷ 1 MB/sec = 2 shards (처리량이 bottleneck)

→ 10 Shards 선택 (미래 성장 고려, 여유 5배)
```

**비용:**
```
Provisioned Mode:
- 10 Shards × $36/월 = $360/월

vs. On-Demand Mode:
- 10,000 rec/sec × $0.25 per million = $216/월
- 하지만 스파이크 트래픽 시 과금 증가
→ Provisioned 선택 (예측 가능한 비용)
```

#### 2️⃣ Firehose Parquet + Dynamic Partitioning

**왜 Parquet인가?**

```
포맷별 비교:
┌─────────────────────────────────────────────────┐
│ 포맷    │ 크기  │ 압축 │ Athena 비용 │ 선택 이유 │
├─────────────────────────────────────────────────┤
│ JSON    │ 100% │ 낮음 │ 높음        │ X        │
│ CSV     │ 80%  │ 중간 │ 중간        │ X        │
│ Parquet │ 25%  │ 높음 │ 낮음 (컬럼) │ ✓        │
│ ORC     │ 20%  │ 높음 │ 낮음 (컬럼) │ △        │
└─────────────────────────────────────────────────┘
```

- **Parquet** 선택 이유:
  - 컬럼 압축: 3.3배 크기 감소 → S3 비용 절감
  - Athena 호환성: Columnar scan → 필요한 컬럼만 읽음
  - 압축: Snappy (속도/압축 밸런스 최적)

**Dynamic Partitioning 구조:**

```
bronze/
├─ year=2026/month=04/day=27/hour=00/
│  └─ <UUID1>.parquet    (00:00~00:05)
│  └─ <UUID2>.parquet    (00:05~00:10)
├─ year=2026/month=04/day=27/hour=01/
│  └─ <UUID3>.parquet    (01:00~01:05)
└─ ...

장점:
- Partition Pruning: WHERE hour = 12 → hour=12 폴더만 스캔
- 비용 절감: 스캔 범위 대폭 축소
- Maintenance: 자동 파티션 생성 (Firehose)

vs. 단일 폴더 (bronze/):
- 하루 데이터: 86,400초 ÷ 300초(배치) = 288개 파일
- Athena가 288개 모두 스캔 (시간 낭비)
```

#### 3️⃣ Glue Schema Registry

```python
Schema 등록:
{
  "type": "record",
  "name": "RobotTelemetry",
  "fields": [
    {"name": "robot_id", "type": "string"},
    {"name": "pos_x", "type": "double"},
    {"name": "battery_level", "type": "int", "min": 0, "max": 100},
    {"name": "motor_temp", "type": "double", "min": 0, "max": 500},
    {"name": "timestamp", "type": "string", "format": "date-time"}
  ]
}

검증 방식: BACKWARD / FORWARD / FULL / DISABLED

우리의 선택: BACKWARD
┌────────┬──────────┬────────────────┐
│ 버전   │ 스키마   │ 호환성         │
├────────┼──────────┼────────────────┤
│ v1     │ 기존     │ (기준)         │
│ v2     │ robot_id 필수 → 추가 │ ✓ backward OK │
│ v3     │ robot_id 필수 → 삭제 │ ✗ backward FAIL │
└────────┴──────────┴────────────────┘

이유: 기존 데이터 호환성 유지, 파이프라인 안정성
```

**비용:**
```
Glue Schema Registry: 무료 (API 호출 제한 없음)
vs. 대안:
- 수동 검증: 복잡, 에러 위험
- 타사 도구: 비용 발생
→ 글루 선택 (AWS 통합)
```

### Phase 1 결과

```
✅ 리소스 생성:
- KDS main: 10 shards, 24시간 보존
- KDS alert: 2 shards (이상 이벤트 전용)
- Firehose: S3로 Parquet 변환, Dynamic Partition
- Glue Registry: Schema 등록
- IAM IRSA: Generator Pod → KDS PutRecord

✅ 검증:
- Generator 시뮬레이션: 10,000 rec/sec
- Firehose: 5분 배치 → S3 bronze/
- Glue Table: 240 컬럼 자동 추론

⏱️  작업 시간: ~10분 (Terraform 동시 생성)
💰 월 추가 비용: ~$450
  ├─ KDS main: $360 (10 shards)
  ├─ KDS alert: $72 (2 shards)
  └─ Firehose: $0.029 per GB (저가)
```

---

## Phase 2: Batch Processing & Medallion Architecture

### 목표
1. Bronze (raw) → Silver (cleaned) → Gold (aggregated) 일일 자동 변환
2. Great Expectations로 데이터 품질 gate
3. Airflow로 멱등성 보장

### 핵심 설계 결정

#### 1️⃣ Airflow in Kubernetes (vs. 로컬 Docker Compose)

```
┌──────────────────────────────────────────────────┐
│ 배포 방식 비교                                     │
├──────────────┬──────────────┬────────────────────┤
│ 항목         │ Docker       │ K8s (Helm)        │
├──────────────┼──────────────┼────────────────────┤
│ 확장성       │ 1대 제한     │ 무제한 (HPA)      │
│ 리소스 효율  │ 하드웨어 낭비 │ 최적 사용         │
│ 운영 비용    │ ~$200/월     │ ~$100/월 (공유)  │
│ 고가용성     │ X            │ ✓ (Multi-replica) │
│ 통합         │ 복잡 (로컬)  │ 심플 (같은 VPC)  │
└──────────────┴──────────────┴────────────────────┘

선택: K8s Helm (원본 프로젝트도 K8s 기반)
```

#### 2️⃣ Athena 쿼리 엔진 (vs. Lambda, EMR, Spark)

```
분석 엔진 비교:
┌──────────────────────────────────────────────────┐
│ 엔진      │ 비용      │ 설정 │ 성능 │ 선택 이유  │
├──────────────────────────────────────────────────┤
│ Athena    │ $6.25/TB  │ 최소 │ 중간 │ ✓ Serverless │
│ Lambda    │ $0.20/1M  │ 복잡 │ 느림 │ X 비효율   │
│ Spark     │ $2.88/DPU │ 중간 │ 빠름 │ △ 복잡    │
│ EMR       │ 주문형    │ 복잡 │ 빠름 │ △ 고비용   │
└──────────────────────────────────────────────────┘
```

**Athena 선택 이유:**
- Serverless: 서버 관리 0, 콜드스타트 없음
- 비용: 스캔한 데이터만 과금 (Partition Pruning)
- 성능: 일일 ETL (시간 여유) → 느린 속도 수용
- 통합: Glue Data Catalog와 네이티브 통합

**비용 추정:**
```
일일 데이터량:
- 10,000 로봇 × 86,400초 = 864M 레코드
- Parquet 압축: 864M × 100bytes ÷ 4 = 21.6 GB
- Bronze 스캔: 21.6 GB × $6.25 = $135/일
- Silver 스캔: 21.6 GB × $6.25 = $135/일
- Gold 스캔: 10K robots × 6 fields = ~1GB × $6.25 = $6/일

월 비용: (135 + 135 + 6) × 30 = $9,720/월
→ 높지만, 분석 빈도 ↑하면 정당화 가능
→ 대안: Partition Projection (위에서 본 실제 절감률)
```

#### 3️⃣ Great Expectations (Data Quality)

```python
검증 규칙:
├─ robot_id null 비율 < 1%
├─ motor_temp 범위: 0 ~ 500°C
├─ battery_level 범위: 0 ~ 100%
├─ timestamp 유효성 (ISO8601)
└─ 레코드 수 > 0 (예: 5M 이상)

실패 시:
├─ DAG 중단 (downstream task 실행 안 됨)
├─ SNS Alert → Slack 알림
└─ 정비팀 수동 검토 필요

비용:
- Great Expectations: 오픈소스 (무료)
- vs. Soda, Talend: $$$
```

#### 4️⃣ INSERT OVERWRITE (멱등성)

```sql
-- ✅ 멱등 쿼리
INSERT OVERWRITE TABLE silver_robot_telemetry
PARTITION (dt = '2026-04-27')
SELECT * FROM bronze WHERE ...

-- ❌ 비멱등 쿼리 (우리가 발견한 초기 버그)
INSERT INTO TABLE silver_robot_telemetry  -- OVERWRITE 없음!
PARTITION (dt = '2026-04-27')
SELECT * FROM bronze WHERE ...

차이:
INSERT INTO:    기존 파티션 유지 + 새 데이터 추가 (중복!)
INSERT OVERWRITE: 기존 파티션 삭제 + 새 데이터 삽입 (멱등)

예시: execution_date = 2026-04-27
시도 1: silver에 240건 삽입
시도 2 (재실행): 기존 240건 + 240건 = 480건 (오류!)
→ INSERT OVERWRITE로 수정: 항상 240건 유지
```

### Phase 2 결과

```
✅ 파이프라인 구축:
- Great Expectations: 5개 검증 규칙
- Athena Bronze → Silver: 240건 → 240건 (이상치 제거)
- Athena Silver → Gold: 일별 집계 10,000개 레코드
- Airflow DAG: 4 task, daily schedule

✅ 멱등성 보장:
- execution_date 기준 파티셔닝
- INSERT OVERWRITE 사용
- 테스트: 동일 DAG 2회 실행 → 결과 동일

⏱️  작업 시간: ~30분 (DAG 테스트 포함)
💰 월 추가 비용: ~$10,000
  (Athena 스캔 비용, Partition Projection 미적용 시)
```

---

## Phase 3: Real-time Anomaly Detection (Flink + Bedrock)

### 목표
1. **기존 임계값 기반 방식의 한계 돌파**
   - 고정된 온도 > 90°C는 로봇마다 다르다 (정상 범위 편차 큼)
   - 온도 + 부하 관계 분석 필요
   
2. **Advanced Anomaly Detection** 구현
   - Z-Score (통계)
   - Multivariate Correlation (다변량)
   - Watermark (Late Data 처리)

### 핵심 설계 결정

#### 1️⃣ Managed Flink vs. Spark Streaming

```
스트리밍 엔진 비교:
┌──────────────────────────────────────────────────┐
│ 엔진        │ 비용    │ 지연  │ 상태 │ 선택 이유  │
├──────────────────────────────────────────────────┤
│ Flink       │ 낮음    │ 100ms│ 우수 │ ✓ 최적    │
│ Spark SS    │ 높음    │ 1s   │ 보통 │ X 비효율  │
│ Kenesis API │ 무료    │ 100ms│ X    │ △ 기능    │
└──────────────────────────────────────────────────┘

Flink 선택 이유:
- Event Time 의미론: Watermark 지원 (Late Data 명확 처리)
- State 관리: OVER Window + Row Number (효율)
- Exactly-Once: Checkpoint + Savepoint (데이터 손실 0)
```

#### 2️⃣ Z-Score 기반 이상 탐지

```
원리:
Z = (X - μ) / σ

예시: ROBOT-00042
- 과거 5분 평균: μ = 75°C
- 과거 5분 표준편차: σ = 4.2°C
- 현재 값: X = 90°C

Z = (90 - 75) / 4.2 = 3.57

해석:
- Z < 1: 정상 (표준편차 1배 이내)
- Z > 3: 이상 (3-sigma rule, 99.7% 신뢰도)
- Z > 3.57: ROBOT-00042는 명백한 이상!

vs. 고정 임계값 (90°C):
- 로봇 A: 정상 범위 70~85°C → 90°C는 명백한 이상
- 로봇 B: 정상 범위 80~95°C → 90°C는 정상
→ 고정 임계값은 로봇 개별성 무시
```

**Flink에서의 구현:**

```sql
-- OVER Window로 5분 이동 통계
SELECT 
    robot_id,
    event_time,
    motor_temp,
    AVG(motor_temp) OVER (
        PARTITION BY robot_id 
        ORDER BY event_time 
        RANGE INTERVAL '5' MINUTE PRECEDING
    ) as avg_temp,
    STDDEV(motor_temp) OVER (...) as stddev_temp
FROM source_kds

-- Z-Score 계산
SELECT
    robot_id,
    event_time,
    (motor_temp - avg_temp) / GREATEST(stddev_temp, 0.5)
        as zscore
FROM window_stats
WHERE ABS(zscore) > 3.0  -- 이상 필터링
```

**σ = 0 가드:**

```
문제: STDDEV = 0 (모든 값이 동일)
→ Z = (X - μ) / 0 = ∞ (부동소수점 오류!)

해결: GREATEST(stddev_temp, 0.5)
→ 최소 0.5로 하한 설정 (완전 정상 상태 반영)
```

#### 3️⃣ Multivariate Correlation (부하 대비 온도)

```
문제: 고부하 작업 중 온도 상승은 정상
- 예: 무거운 물건 들기 + 모터 힘 쓰기 = 온도 ↑

해결: 부하(load)와 온도의 상관성 분석
temperature / load = 모터 효율

정상 범위: 1.0 ~ 1.5 (부하 1 당 온도 1.0~1.5°C 상승)
이상: temperature / load > 1.8 (모터 과열, 저효율)

조건:
AND motor_temp >= 85.0  (기본값)
AND (motor_temp / GREATEST(current_load, 1.0)) > 1.8

예시:
- 부하 0.5, 온도 90°C → 90/0.5 = 180 >> 1.8 (이상!)
  └─ 이유: 부하 적은데 온도 높음 (모터 문제)

- 부하 5.0, 온도 90°C → 90/5 = 18 >> 1.8 (이상!)
  └─ 이유: 부하 높을 때도 온도 너무 높음 (과부하)
```

#### 4️⃣ Watermark — Late Data 처리

```
문제: Event Time Window가 언제 닫힐까?

┌─────────────────────────────────────────┐
│ [12:00~12:05] Window                   │
├─────────────────────────────────────────┤
│ 12:00:01 레코드 (도착)                  │
│ 12:02:30 레코드 (도착)                  │
│ 12:04:59 레코드 (도착)                  │
│ 12:07:30 레코드 (네트워크 지연)          │ ← 이미 window 지남
│ 12:09:00 레코드 (매우 늦음)              │ ← 무시?
└─────────────────────────────────────────┘

Watermark 없이:
→ Window가 영원히 열려있음 (메모리 폭증)
→ 5분 후에도 새 데이터 수신 가능? (불명확)

Watermark 설정:
WATERMARK FOR event_time AS event_time - INTERVAL '10' SECOND

의미:
- 10초 이상 지연된 데이터는 버림
- 9초 지연 데이터는 포함
- 11초 지연 데이터는 무시
- Window는 (window_end + watermark_delay) 이후에 닫힘
  = 12:05:10 이후에 [12:00~12:05] Window 최종 확정

센서 데이터 특성상:
- 로봇이 현재 값을 보냄 (미래 값 불가)
- 지연 > 10초는 거의 없음 (4G/5G)
- 따라서 10초 watermark 타당
```

### Phase 3 결과

```
✅ Flink Application 배포:
- Source: KDS main (10 shards)
- Processing: 5분 OVER Window + Z-Score
- Sink: Alert KDS (이상 이벤트) + S3 alerts/ (이력)
- Threshold: Z > 3.0, load.ratio > 1.8
- 외부화: property_map으로 threshold 주입

✅ 성능 검증:
- 지연: KDS → Alert KDS: <1초
- 처리량: 10,000 rec/sec (안정적)
- 거짓 양성(false positive) 최소화

⏱️  작업 시간: ~45분 (Flink 테스트 포함)
💰 월 추가 비용: ~$150
  └─ Managed Flink: 최소 4 Flink Units = ~$150/월
```

---

## Phase 4: Serving Layer — Portal + Chat + Grafana

### 목표
1. 운영자가 실시간으로 이상을 감지하고
2. AI에게 자연어로 질문하고
3. Grafana 대시보드에서 시각적 분석

### 핵심 설계 결정

#### 1️⃣ In-Memory Cache vs. Athena Query

```
채팅 응답 시간:

┌─────────────────────────────────────────┐
│ /api/chat 요청                          │
├─────────────────────────────────────────┤
│ 1. 캐시 읽기: 1ms                       │ ← Cache
│ 2. Bedrock 호출: 300~500ms              │ ← Bedrock
│ 3. 응답 직렬화: 10ms                    │
├─────────────────────────────────────────┤
│ 총 지연: ~350ms ✓ (빠름)                 │
└─────────────────────────────────────────┘

vs. Athena Query:

┌─────────────────────────────────────────┐
│ 1. Athena 쿼리 시작: 1s (오버헤드)       │
│ 2. S3 스캔: 5~10s (데이터 크기)         │
│ 3. 결과 직렬화: 1s                      │
├─────────────────────────────────────────┤
│ 총 지연: ~10~15s ✗ (너무 느림)           │
└─────────────────────────────────────────┘

캐시 전략:
- 매일 01:00 자동 갱신 (APScheduler)
- Gold 테이블 최신 파티션을 메모리로 로드
- 사용자 요청 시 캐시에서 즉시 읽기
- Python Dict (10,000 × 6 컬럼 = ~10MB RAM)
```

**APScheduler 타임존 이슈:**

```python
# ❌ 버그 (UTC 기준)
scheduler.add_job(refresh_cache, "cron", hour=1, minute=0)
→ 실제: UTC 01:00 = KST 10:00 (잘못된 시간)

# ✅ 수정
scheduler.add_job(
    refresh_cache,
    "cron",
    hour=1,
    minute=0,
    timezone="Asia/Seoul"  # KST 명시
)
→ 실제: KST 01:00 (자정 직후 일일 갱신)
```

#### 2️⃣ Bedrock vs. 로컬 LLM

```
선택지:
┌────────────────────────────────────────┐
│ 옵션          │ 장점      │ 단점       │
├────────────────────────────────────────┤
│ Bedrock(AWS)  │ 관리 0    │ API 비용   │
│ Ollama(로컬)  │ 비용 0    │ 지연 높음  │
│ OpenAI        │ 고성능    │ 외부 의존  │
└────────────────────────────────────────┘

Bedrock 선택 이유:
- AWS 네이티브 (IAM IRSA, VPC 통합)
- Claude 3 모델 (분석 능력 우수)
- Latency: <1초 (eu-west-1 region)
- 비용: 요청당 $0.0001 (매우 저가)
```

**비용 추정:**

```
채팅 빈도: 운영자 10명 × 10회/일 = 100회/일
Bedrock 비용: 100회 × $0.0001 = $0.01/일 = $0.30/월
→ 무시할 수 있는 수준
```

#### 3️⃣ Portal UI — Iframe + postMessage

```html
<!-- portal.html 구조 -->

┌─────────────────────────────────────────┐
│ Header: "2026-04-27 기준 데이터" 캐시   │
├──────────────────┬──────────────────────┤
│ Dashboard Tab    │  AI Chat Panel       │
│ ☐ Fleet         │  ┌──────────────────┐│
│ ☐ Anomaly       │  │ 캐시 갱신 시각    ││
│ ☐ Pipeline      │  └──────────────────┘│
│                  │                      │
│ [Grafana iframe] │ [채팅 히스토리]     │
│ (kiosk=tv모드)   │ [입력창]             │
│                  │ [딥링크 버튼]        │
└──────────────────┴──────────────────────┘

데이터 흐름:
1. Grafana iframe에서 로봇 패널 클릭
   └─ postMessage({robot_id: "ROBOT-00042"})
2. Portal JS가 수신
   └─ AI Chat 입력란에 자동 입력
3. 사용자 전송
   └─ /api/chat 호출
4. AI 응답에서 [ROBOT-XXXXX] 감지
   └─ 딥링크 버튼 자동 생성
5. 버튼 클릭
   └─ iframe src 동적 변경 (Grafana 필터 적용)
```

**iframe + postMessage 보안:**

```javascript
// Grafana → Portal JS
// Cross-origin 통신 (같은 VPC, ALB 다름)

// ❌ 위험
window.parent.robot_id = "ROBOT-00042"  // 전역 오염

// ✅ 안전
window.parent.postMessage(
    {type: "robot-selected", robot_id: "ROBOT-00042"},
    "https://k8s-xxx.elb.amazonaws.com"  // 출처 명시
)

// Portal JS
window.addEventListener("message", (event) => {
    if (event.origin !== "https://grafana...") return;  // 출처 검증
    if (event.data.type === "robot-selected") {
        document.getElementById("chat-input")
            .value = `${event.data.robot_id}의 상태를 분석해줘`;
    }
})
```

### Phase 4 결과

```
✅ 서빙 레이어 완성:
- Portal UI: 12컬럼 그리드 (Grafana + Chat)
- API: /api/chat (Bedrock), /api/status (캐시 상태)
- Slack Alert: Alert KDS → Lambda → SNS → Webhook
- Grafana: 3개 대시보드 (Fleet, Anomaly, Pipeline)

✅ 기능 검증:
- Chat 응답: <500ms (캐시 기반)
- Slack 알림: 6초 이내 (실시간)
- Grafana 조회: <2초 (Athena + CloudWatch)

⏱️  작업 시간: ~60분 (UI 테스트 포함)
💰 월 추가 비용: ~$200
  ├─ Bedrock: ~$0.30 (무시할 수준)
  ├─ Lambda: ~$5
  └─ CloudWatch Logs: ~$150
```

---

## Phase 5: Observability & Predictive Maintenance

### 목표
1. X-Ray로 전구간 트레이싱
2. SageMaker로 ML 기반 예측정비

### 핵심 설계 결정

#### 1️⃣ X-Ray + OpenTelemetry (ADOT)

```
분산 추적의 필요성:

사용자: "왜 /api/chat이 느려?"

┌─────────────────────────────────────────┐
│ 요청 흐름:                              │
├─────────────────────────────────────────┤
│ Portal (100ms)                          │
│   ↓ (네트워크 지연 10ms)                │
│ ALB (15ms)                              │
│   ↓ (라우팅 5ms)                       │
│ API Pod (350ms) ←? 뭐가 느려?           │
│   ├─ 캐시 읽기 (1ms)                    │
│   ├─ Bedrock 호출 (300ms) ← 여기!     │
│   └─ 응답 직렬화 (10ms)                │
│   ↓ (네트워크 지연 5ms)                │
│ Portal (50ms 렌더링)                    │
├─────────────────────────────────────────┤
│ 총 540ms → 300ms는 Bedrock 대기       │
└─────────────────────────────────────────┘

X-Ray로:
- Trace ID: 요청 전체 추적 (Portal → ALB → API → Bedrock)
- Segment: 각 서비스별 시간 측정
- Annotation: 로봇 ID, 사용자 등 메타데이터
- Service Map: 의존성 시각화 (API → Bedrock)
```

**ADOT (AWS Distro for OpenTelemetry):**

```yaml
# k8s Deployment에 추가
apiVersion: v1
kind: Pod
metadata:
  annotations:
    instrumentation.opentelemetry.io/inject-python: "true"
spec:
  containers:
  - name: api
    image: robot-telemetry-api:latest
    # ADOT Operator가 자동으로:
    # 1. Python agent 주입
    # 2. X-Ray exporter 설정
    # 3. APM 라이브러리 로드

# 결과: 코드 변경 0, 자동 추적
```

#### 2️⃣ SageMaker XGBoost — 예측정비

```
문제: 고장 나기 전에 미리 점검하려면?

데이터:
- 지난 30일 Gold 테이블에서 평균 온도, 배터리 소모율 등 추출
- AI4I 2020 데이터셋의 `machine_failure` 레이블 활용
- Features: [avg_motor_temp, max_motor_temp, battery_drain, active_hours]
- Label: machine_failure (0=정상, 1=고장)

모델:
- XGBoost 분류 (이진 분류: 고장/정상)
- 학습 데이터: 지난 30일 (약 300K 레코드)
- 검증: 최근 7일 (약 70K 레코드)

정확도 목표:
- Precision > 90% (오경보 최소화)
- Recall > 80% (실제 고장 포착)

배포:
- SageMaker Endpoint (자동 스케일)
- API: POST /api/predict
  요청: {"robot_id": "...", "avg_motor_temp": 88.5, ...}
  응답: {"failure_probability": 0.72, "risk_level": "high"}
```

**주간 재학습:**

```python
# dags/robot_daily_etl.py
if execution_date.weekday() == 0:  # 월요일
    train_model(
        execution_date=execution_date,
        lookback_days=30  # 지난 30일 Gold 데이터
    )
    # 1. 학습 완료
    # 2. 모델 평가 (cross-validation)
    # 3. 이전 모델보다 성능 ↑ 면 배포
    # 4. 아니면 이전 모델 유지
```

**비용 추정:**

```
학습: 매주 1회, 10분
- SageMaker Training Job: ~$0.50 (저가 인스턴스)

추론: 운영자 요청 시 (~10회/일)
- SageMaker Endpoint (ml.m5.large × 1): ~$150/월

월 총 비용: ~$150 (운영 자동화 대비 가치 high)
```

### Phase 5 결과

```
✅ Observability 완성:
- X-Ray: 모든 API 호출 추적
- 성능 병목 자동 감지
- Service Map: Generator → Flink → Lambda 흐름 시각화

✅ 예측정비 모델:
- XGBoost: 고장 확률 예측
- 주간 재학습: 모델 정확도 유지
- /api/predict: 실시간 고장 위험 평가

⏱️  작업 시간: ~90분 (모델 학습 포함)
💰 월 추가 비용: ~$300
  ├─ SageMaker Endpoint: ~$150
  ├─ X-Ray: ~$100
  └─ 데이터 저장: ~$50
```

---

## 📊 전체 비용 요약

| Phase | 컴포넌트 | 월 비용 |
|-------|---------|--------|
| 0 | EKS, NAT, VPC Endpoint | $200 |
| 1 | Kinesis (10+2 shards), Firehose | $450 |
| 2 | Athena, Airflow | $10,000 |
| 3 | Managed Flink | $150 |
| 4 | Bedrock, Lambda, CloudWatch | $200 |
| 5 | SageMaker, X-Ray | $300 |
| **Total** | | **$11,300** |

**최적화 여지:**
- Partition Projection 적극 활용 → Athena 비용 70% 절감 → $3,000/월
- Spot Instance 활용 (Karpenter) → EKS 비용 70% 절감 → $60/월

**조정 후 예상 비용: ~$7,500/월**

---

## 🎯 다음 단계: 실무 적용 시점별 판단

### "이 기술을 언제 바꿔야 하는가?" 판단 기준

| 상황 | 현재 | 변경 시점 | 대안 |
|------|------|---------|------|
| **처리량 10배 증가** | KDS 10 shards | Shards 추가 | → 50 shards로 확장 |
| **Chat 응답 느림** | 캐시 in-memory | HPA 활성화 시 | → Redis 도입 |
| **Athena 비용 폭증** | 현재 | 스캔량 > 100GB/일 | → Iceberg + Delta format |
| **Flink 가용성** | Managed Flink | 정지 시간 < SLA | → Auto-scaling on-demand |
| **리포트 자동화** | 일일 배치 | 시간별 리포트 요구 | → Streaming Analytics (Kinesis SQL) |
| **글로벌 확장** | eu-west-1 | 다중 리전 | → Data Replication, Multi-region DB |


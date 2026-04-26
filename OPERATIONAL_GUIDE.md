# 실무 운영 가이드 — 모니터링 & Troubleshooting

> **목표**: 시스템 운영 중 문제가 발생했을 때, 10분 내에 원인 파악 및 해결할 수 있는 능력

---

## 🚨 장애 진단 플로우 (Decision Tree)

```
시스템 이상 발견
    ↓
[증상 확인]
    ├─ "Slack Alert이 안 온다" → §1 Real-time Alert 장애
    ├─ "Bedrock Report이 없다" → §2 Batch Pipeline 장애
    ├─ "Portal Chat이 느리다" → §3 API 성능 이슈
    ├─ "Grafana 대시보드가 비어있다" → §4 Data Catalog 이슈
    └─ "Generator 센서 데이터가 없다" → §5 Ingestion 장애
```

---

## §1 Real-time Alert 장애 진단

### 증상: "이상 온도 감지했는데 Slack에 알림이 안 온다"

#### Step 1: 데이터 흐름 추적

```bash
# 1. Kinesis Main Stream에 데이터가 들어오는가?
aws kinesis describe-stream --stream-name robot-telemetry-stream --region eu-west-1

# 응답에서 확인:
# - StreamStatus: ACTIVE (활성?)
# - Shards: count (10?)
# - StreamCreationTimestamp: (시간이 맞나?)

# 2. 최근 레코드가 있는가?
aws kinesis get-shard-iterator \
  --stream-name robot-telemetry-stream \
  --shard-id shardId-000000000000 \
  --shard-iterator-type LATEST \
  --region eu-west-1

# 응답: ShardIterator=xxx
aws kinesis get-records --shard-iterator xxx

# 응답: Records=[...] (비어있으면 데이터 흐름 자체가 끊김)
```

#### Step 2: Flink 애플리케이션 상태 확인

```bash
# 1. Managed Flink 애플리케이션 목록
aws kinesisanalyticsv2 list-applications --region eu-west-1

# 응답에서 robot-anomaly-detector 찾기
# ApplicationStatus: RUNNING (정지됐나?)

# 2. 상세 상태
aws kinesisanalyticsv2 describe-application \
  --application-name robot-anomaly-detector \
  --region eu-west-1

# 확인 항목:
# - ApplicationStatus: RUNNING?
# - LastUpdateTimestamp: 언제 마지막 수정?
# - InputDescriptions[0].IncomingStreamSummary.RecordCount: 증가 중?
```

**Flink 로그 확인:**

```bash
# CloudWatch 로그 그룹
/aws/kinesisanalytics/robot-anomaly-detector

# 최근 에러 확인
aws logs tail /aws/kinesisanalytics/robot-anomaly-detector --follow

# 찾아야 할 에러 패턴:
# - "NullPointerException" → 필드 누락
# - "OutOfMemory" → State 폭증 (Watermark 문제)
# - "Unable to connect to Kinesis" → IAM 권한 부족
```

#### Step 3: Alert KDS 확인

```bash
# 1. Alert KDS에 레코드가 들어오는가?
aws kinesis describe-stream --stream-name robot-anomaly-alert-stream --region eu-west-1

# 2. 최근 레코드
aws kinesis get-shard-iterator \
  --stream-name robot-anomaly-alert-stream \
  --shard-id shardId-000000000000 \
  --shard-iterator-type LATEST \
  --region eu-west-1

aws kinesis get-records --shard-iterator xxx | jq '.Records[0].Data | @base64d'

# 응답 (Base64 decode됨):
# {
#   "robot_id": "ROBOT-00042",
#   "max_alert_temp": 90.0,
#   "alert_time": 1714225440
# }
```

**만약 Alert KDS가 비어있으면:**
→ Flink 이상 탐지 로직 점검 (Z-Score 임계값 너무 높을 수도)

#### Step 4: Lambda 호출 확인

```bash
# 1. Lambda Event Source Mapping 상태
aws lambda list-event-source-mappings \
  --function-name robot-anomaly-alert-lambda \
  --region eu-west-1

# 응답:
# - State: Enabled?
# - LastProcessingResult: OK? (에러 메시지?)
# - LastModified: 언제?

# 2. Lambda 로그 확인
aws logs tail /aws/lambda/robot-anomaly-alert-lambda --follow

# 찾아야 할 에러:
# - "ParameterNotFound" → SSM /robot-telemetry/portal-url이 없다
# - "InvalidParameterType" → SNS Topic ARN 오류
# - "AccessDenied" → IAM 권한 부족

# 3. 최근 호출 통계
aws lambda get-function-concurrency --function-name robot-anomaly-alert-lambda

# Reserved Concurrency: 100
# 만약 자주 "throttling" 에러면 → ReservedConcurrentExecutions 증가
```

#### Step 5: SNS → Slack 확인

```bash
# 1. SNS Topic 구독 확인
aws sns list-subscriptions-by-topic \
  --topic-arn arn:aws:sns:eu-west-1:xxx:robot-anomaly-alerts \
  --region eu-west-1

# 응답:
# - Protocol: https (Slack Webhook?)
# - SubscriptionArn: arn:...
# - Endpoint: https://hooks.slack.com/...

# 2. Slack Webhook 유효성 테스트
curl -X POST https://hooks.slack.com/services/YOUR/WEBHOOK/URL \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "🧪 Test Alert from robot-telemetry",
    "icon_emoji": ":robot_face:"
  }'

# 응답:
# - HTTP 200: 성공 (Slack 채널에 메시지 나타남?)
# - HTTP 404: Webhook URL 잘못됨
# - HTTP 403: Slack Workspace 권한 문제
```

### 해결 책

| 증상 | 원인 | 해결 방법 |
|------|------|---------|
| Flink 정지됨 | 자동 중단 또는 배포 오류 | `aws kinesisanalyticsv2 start-application` 재시작 |
| Alert KDS 비움 | Z-Score 임계값 너무 높음 | Flink property_map에서 `zscore.threshold` 낮춰서 재배포 |
| Lambda 실패 | SSM Parameter 없음 | `aws ssm put-parameter --name /robot-telemetry/portal-url --value https://...` |
| Slack 메시지 안 옴 | Webhook URL 만료 | Slack App 재설정 → 새 Webhook URL 생성 |
| 권한 부족 | IAM Role 오류 | `aws iam get-role-policy --role-name robot-alert-lambda-role --policy-name robot-alert-policy` 확인 |

---

## §2 Batch Pipeline 장애 진단

### 증상: "Bedrock Report이 생성되지 않았다" 또는 "Gold 테이블이 비어있다"

#### Step 1: Airflow DAG 상태 확인

```bash
# Airflow UI 접속
kubectl port-forward -n airflow svc/airflow-webserver 8080:8080

# 웹 브라우저: http://localhost:8080
# 확인 항목:
# 1. DAG: robot_daily_etl 활성화?
# 2. Latest DAG Run: 최근 실행 시간?
# 3. Status: Failed (빨강)? Success (초록)? Running (파랑)?
```

#### Step 2: Task 상세 로그

```bash
# Airflow CLI로 로그 확인
kubectl exec -n airflow airflow-scheduler-0 -- \
  airflow tasks logs robot_daily_etl quality_check \
  --execution-date 2026-04-27

# 각 Task별 확인:
# 1. quality_check: 데이터 품질 검증 통과?
# 2. bronze_to_silver: Athena 쿼리 성공?
# 3. silver_to_gold: 결과 rows > 0?
# 4. bedrock_report: Bedrock API 응답?
```

#### Step 3: Athena 쿼리 상태 확인

```bash
# 최근 Athena 쿼리 조회
aws athena list-query-executions \
  --work-group robot-telemetry-workgroup \
  --region eu-west-1

# 응답: QueryExecutionIds=[...]

# 최근 쿼리 상태 확인
aws athena get-query-execution \
  --query-execution-id <query-id> \
  --region eu-west-1

# 확인:
# - Status: SUCCEEDED? FAILED? CANCELLED?
# - SubmissionDateTime vs CompletionDateTime (소요 시간)
# - QueryExecutionContext.Database: robot_telemetry_db?

# 쿼리 결과 확인
aws athena get-query-results \
  --query-execution-id <query-id> \
  --region eu-west-1 | jq '.ResultSet.Rows'

# 응답:
# [{
#   "Data": [
#     {"VarCharValue": "dt"},
#     {"VarCharValue": "robot_id"},
#     {"VarCharValue": "avg_motor_temp"}
#   ]
# }, ...]
```

#### Step 4: S3 데이터 확인

```bash
# Bronze 경로 확인
aws s3 ls s3://de-ai-06-827913617635-ap-northeast-2-an/bronze/year=2026/month=04/day=27/ --recursive | head

# 응답:
# 2026-04-27 12:00:00      1234567 bronze/year=2026/month=04/day=27/hour=00/...parquet
# 2026-04-27 12:05:00      1256789 bronze/year=2026/month=04/day=27/hour=00/...parquet

# Silver 경로 확인
aws s3 ls s3://de-ai-06-827913617635-ap-northeast-2-an/silver/dt=2026-04-27/ --recursive | head

# 비어있으면 → bronze_to_silver 작업 실패

# Gold 경로 확인
aws s3 ls s3://de-ai-06-827913617635-ap-northeast-2-an/gold/dt=2026-04-27/ --recursive | head

# 비어있으면 → silver_to_gold 작업 실패
```

### 해결 책

| 증상 | 원인 | 해결 방법 |
|------|------|---------|
| DAG 실행 안 됨 | 스케줄 비활성화 | Airflow UI → DAG → Toggle |
| quality_check 실패 | Bronze에 null 데이터 많음 | Generator 로그 확인, 센서 데이터 정상 전송 확인 |
| bronze_to_silver 실패 | Athena 권한 부족 | IAM Role에 Athena `StartQueryExecution`, `GetQueryResults` 권한 추가 |
| silver_to_gold 실패 | Gold 테이블 스키마 오류 | `aws glue get-table --database-name robot_telemetry_db --name gold_robot_daily_stats` 스키마 확인 |
| bedrock_report 실패 | Bedrock 할당량 초과 | AWS 콘솔 → Bedrock → Model access에서 사용량 확인 |

---

## §3 API 성능 이슈 진단

### 증상: "Portal에서 /api/chat 응답이 느리다" (>5초)

#### Step 1: 캐시 상태 확인

```bash
# API Pod에서 캐시 상태 조회
curl http://api-svc:8000/api/status

# 응답:
# {
#   "data_date": "2026-04-27",
#   "cached_at": "2026-04-28T01:00:00Z",
#   "cache_ready": true,
#   "gold_cache_rows": 10234
# }

# 확인:
# - cache_ready: false? → 캐시 로드 중 (재시도)
# - cached_at: 어제 데이터? → APScheduler 제대로 실행됐나?
```

#### Step 2: API 로그 확인

```bash
# API Pod 로그
kubectl logs -n robot-telemetry deploy/robot-telemetry-api --tail=100

# 찾아야 할 패턴:
# - "Cache refresh started" (01:00에 보여야 함)
# - "Cache refresh failed: ..." → Athena 오류
# - "Bedrock invocation latency: XXXms" → Bedrock 성능 측정

# API 요청별 지연 시간
kubectl logs -n robot-telemetry deploy/robot-telemetry-api \
  | grep "POST /api/chat" | head -20
```

#### Step 3: Bedrock 성능 측정

```bash
# 직접 테스트
curl -X POST http://api-svc:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "ROBOT-00042의 상태를 분석해줘"
  }' \
  -w "\nTotal time: %{time_total}s\n"

# 응답 분석:
# - <500ms: 캐시 + Bedrock 정상
# - 1~2s: Bedrock 콜드스타트 (처음 호출)
# - >5s: 캐시 로드 중 또는 Bedrock 오류
```

#### Step 4: HPA 상태 확인

```bash
# API Deployment HPA
kubectl get hpa -n robot-telemetry

# 응답:
# NAME                REFERENCE                        TARGETS   MINPODS MAXPODS REPLICAS AGE
# robot-telemetry-api PodMetricsTarget (65%/80%)   3          10      3

# 확인:
# - TARGETS: 현재 CPU 사용률?
# - REPLICAS: Pod 수 (요청 많으면 scale up)
# - MINPODS: 1? (여러 개면 캐시 불일치 발생 가능)
```

**HPA 캐시 불일치 이슈:**

```
minReplicas = 2일 때:
┌─────────────────────────────────┐
│ Pod 1: _cache_updated_at = 01:00 │
│ Pod 2: _cache_updated_at = 02:15 │ ← 다름!
└─────────────────────────────────┘

사용자 요청이 Pod 2로 라우팅되면:
→ 응답: "2026-04-27 기준 데이터 · 02:15 갱신"

다음 요청이 Pod 1로 라우팅되면:
→ 응답: "2026-04-27 기준 데이터 · 01:00 갱신"

→ 운영자가 혼동 (어느 게 최신?)

해결: minReplicas = 1 (단일 Pod로 캐시 통일)
또는: Redis 도입 (Pod 간 캐시 공유)
```

### 해결 책

| 증상 | 원인 | 해결 방법 |
|------|------|---------|
| 캐시 로드 중 | 첫 API 시작 시 Athena 쿼리 완료 대기 | 15~30초 기다림 (정상) |
| cache_ready=false 지속 | Athena 쿼리 실패 | `aws athena start-query-execution` 수동 실행 |
| Bedrock 매번 느림 | 콜드스타트 반복 | CloudWatch Logs로 "invoke latency" 측정 후 Bedrock 할당 조정 |
| 응답이 불일치함 | HPA minReplicas > 1 | minReplicas=1로 수정 또는 Redis 도입 |
| timeout error | Pod 재시작 중 | `kubectl get pods -n robot-telemetry` 상태 확인 |

---

## §4 Grafana 대시보드 이슈 진단

### 증상: "Grafana Fleet 대시보드가 데이터를 안 보여준다"

#### Step 1: Grafana Data Source 확인

```bash
# Grafana UI 접속
kubectl port-forward -n monitoring svc/grafana 3000:80

# 웹 브라우저: http://localhost:3000
# admin / admin (기본 비번, 변경 권고)

# Configuration → Data Sources
# 확인:
# - Athena: Connected? (green 체크)
# - CloudWatch: Connected? (green 체크)
```

#### Step 2: Athena Data Source 쿼리 테스트

```
Grafana UI:
1. Configuration → Data Sources → Athena
2. "Test Data Source" 클릭
3. 응답: "Data source is working"?
   - 실패 시 에러 메시지 확인
   - "Database not found" → robot_telemetry_db 생성 확인
   - "AccessDenied" → IAM 권한 부족
```

#### Step 3: 대시보드 쿼리 확인

```bash
# Grafana 대시보드: robot_fleet
# 각 패널 클릭 → "Edit" → "Query" 탭

# 예시 쿼리:
# SELECT robot_id, avg_motor_temp, max_motor_temp, active_hours
# FROM gold_robot_daily_stats
# WHERE dt = '2026-04-27'
# ORDER BY max_motor_temp DESC
# LIMIT 100

# 실행 → "Run query" 클릭
# 응답: Rows (행 수)?
```

#### Step 4: Gold 테이블 직접 확인

```bash
# Athena 콘솔로 직접 쿼리
aws athena start-query-execution \
  --query-string "SELECT COUNT(*) FROM gold_robot_daily_stats WHERE dt='2026-04-27'" \
  --query-execution-context Database=robot_telemetry_db \
  --result-configuration OutputLocation=s3://bucket/project-athena-results/ \
  --work-group robot-telemetry-workgroup

# 몇 초 후 결과 확인
aws athena get-query-results --query-execution-id <query-id>
```

### 해결 책

| 증상 | 원인 | 해결 방법 |
|------|------|---------|
| Data Source 오류 | Athena 권한 부족 | Grafana IAM Role에 Athena `GetQueryResults`, `StartQueryExecution` 권한 추가 |
| 대시보드가 비어있음 | Gold 테이블에 데이터 없음 | Airflow DAG 실행 상태 확인 (§2 참조) |
| "Query timeout" | Athena 쿼리 시간 초과 | WHERE 절에 partition key (dt) 추가해서 스캔 범위 축소 |
| "Too many rows" | LIMIT 없는 쿼리 | 패널 쿼리에 LIMIT 100 추가 |

---

## 🎯 모니터링 대시보드 구성

### 핵심 메트릭 및 알람

#### 1️⃣ Kinesis 메트릭

```
CloudWatch Metrics:
├─ robot-telemetry-stream (Main KDS)
│  ├─ IncomingRecords: 정상값 10,000/sec (급락하면 Generator 이상)
│  ├─ IncomingBytes: 정상값 2,000,000 bytes/sec
│  ├─ GetRecords.IteratorAgeMilliseconds: 정상값 <5,000ms
│  │   (5초 이상 = Consumer 뒤처짐, Flink lag 증가)
│  └─ ReadProvisionedThroughputExceeded: 0 (초과 시 Shard 수 부족)
│
└─ robot-anomaly-alert-stream (Alert KDS)
   ├─ IncomingRecords: 변동적 (정상 시 100/sec, 이상 많으면 증가)
   └─ ReadProvisionedThroughputExceeded: 0
```

**CloudWatch Alarm 설정:**

```bash
# 1. Generator 데이터 흐름 끊김 감지
aws cloudwatch put-metric-alarm \
  --alarm-name robot-telemetry-ingestion-lag \
  --alarm-description "Kinesis lag > 5 min" \
  --metric-name GetRecords.IteratorAgeMilliseconds \
  --namespace AWS/Kinesis \
  --statistic Average \
  --period 300 \
  --threshold 300000 \
  --comparison-operator GreaterThanThreshold \
  --alarm-actions arn:aws:sns:eu-west-1:xxx:robot-anomaly-alerts

# 2. Firehose 실패율 모니터링
aws cloudwatch put-metric-alarm \
  --alarm-name robot-firehose-delivery-fail \
  --metric-name DeliveryToS3.Success \
  --namespace AWS/Firehose \
  --statistic Average \
  --period 300 \
  --threshold 95 \
  --comparison-operator LessThanThreshold \
  --alarm-actions arn:aws:sns:eu-west-1:xxx:robot-anomaly-alerts
```

#### 2️⃣ Flink 메트릭

```
CloudWatch Logs Insights 쿼리:
# Flink 처리 지연
fields @timestamp, @message, @duration
| filter @message like /processing_time/
| stats avg(@duration) as avg_latency

# Watermark lag (Late Data 발생 여부)
fields @timestamp, watermark_age
| stats max(watermark_age) as max_lag
```

#### 3️⃣ API & Bedrock 메트릭

```
CloudWatch Logs Insights:
# API 응답 시간
fields @timestamp, @duration
| filter @message like /POST \/api\/chat/
| stats avg(@duration) as avg_ms, pct(@duration, 95) as p95_ms

# Bedrock API 지연
fields @timestamp, bedrock_invoke_latency
| stats avg(bedrock_invoke_latency) as avg_bedrock_ms
```

#### 4️⃣ Airflow DAG 메트릭

```
Airflow UI → Admin → Log
필터: robot_daily_etl + execution_date + Task

확인:
- quality_check: 0분 (통과)
- bronze_to_silver: 5분 소요 (정상)
- silver_to_gold: 3분 소요 (정상)
- bedrock_report: 10분 소요 (정상)

전체 DAG 소요 시간: ~20분 (23:00~23:20)
```

---

## 🔧 일반적인 문제 & 해결책

### 문제 1: "메모리 부족" (Out Of Memory)

**징후:**
```
Pod eviction, OOMKilled 에러, API 응답 지연
```

**진단:**
```bash
# Pod 메모리 사용량 확인
kubectl top pods -n robot-telemetry

# API Pod 메모리: 512MB 요청, 1GB 제한
# Flink 상태 메모리 폭증? (Watermark 미설정)
# 캐시 크기 너무 큼? (Gold 데이터 10GB 이상)
```

**해결책:**
```
1. Flink: Watermark 설정 확인 (상태 저장소 크기 제한)
2. API: 캐시를 Redis로 외부화
3. Pod 리소스 요청/제한값 증가
   - requests.memory: 512Mi → 1Gi
   - limits.memory: 1Gi → 2Gi
```

### 문제 2: "Athena 쿼리 비용 폭증"

**원인:**
```
Partition Pruning 미적용 → 전체 S3 스캔
예: Bronze 테이블 전체 21.6GB 스캔 = $135/일
```

**진단:**
```bash
# Athena 쿼리 스캔 크기 확인
aws athena get-query-execution --query-execution-id <id>

# 응답:
# "DataScannedInBytes": 21600000000  (21.6GB = 너무 크다)

# 쿼리가 Partition Pruning을 사용했나?
# → WHERE 절에 year, month, day가 있나?
```

**해결책:**
```sql
-- ❌ 비효율 (전체 스캔)
SELECT * FROM bronze_robot_telemetry
WHERE robot_id = 'ROBOT-00042'

-- ✅ 효율 (파티션 프루닝)
SELECT * FROM bronze_robot_telemetry
WHERE year = 2026 AND month = 04 AND day = 27
AND robot_id = 'ROBOT-00042'
```

### 문제 3: "Late Data" 손실 (Flink 이상 탐지 누락)

**징후:**
```
신청 이후에 들어온 센서 데이터는 Alert 안 됨
예: 12:35:00 이상을 12:35:20에 탐지 → 버려짐
```

**원인:**
```
Watermark = event_time - 10초
→ 10초 이상 지연된 데이터는 이미 닫힌 Window에 버려짐
```

**해결책:**
```python
# Watermark 조정
WATERMARK FOR event_time AS event_time - INTERVAL '30' SECOND

# 트레이드오프:
# - 30초: 더 많은 Late Data 포함 (정확도 ↑)
# - 메모리: Window 종료 지연 (상태 저장 시간 ↑)
# - 처리 지연: +30초 (실시간성 ↓)

# 센서 데이터는 최신성 중요 → 10초 권장 유지
```

---

## 🛡️ 보안 체크리스트

### 정기 점검 (주 1회)

- [ ] Secrets Manager 권한 로그 확인
  ```bash
  aws secretsmanager describe-secret --secret-id robot-telemetry/slack-webhook-url
  ```
- [ ] IAM Role 권한이 최소 권한 원칙 준수?
  ```bash
  aws iam get-role-policy --role-name robot-generator-irsa --policy-name robot-kds-policy
  ```
- [ ] VPC Endpoint 접근 제한 설정?
  ```bash
  aws ec2 describe-vpc-endpoint-services --filter Name=service-name,Values=com.amazonaws.eu-west-1.kinesis-streams
  ```

### 정기 점검 (월 1회)

- [ ] CloudTrail 로그 검토 (API 호출 기록)
- [ ] Athena 쿼리 기록 (비정상 접근)
- [ ] SNS 구독 검증 (의도하지 않은 구독?)

---

## 📈 성능 최적화 팁

### 1️⃣ Kinesis Throughput 최적화

```python
# 현재: put_records (배치)
kinesis.put_records(
    StreamName='robot-telemetry-stream',
    Records=[{...}, {...}, ...] * 500  # 500건 배치
)
# 비용: 500건 × $0.014/week = 저가 ✓

# vs. put_record (개별)
for record in records:
    kinesis.put_record(...)  # 1건씩
# 비용: 500건 × 2배 (배치 이득 없음) ✗
```

### 2️⃣ Athena 쿼리 비용 절감

```sql
-- Before: 21.6GB 스캔 = $135
SELECT * FROM bronze_robot_telemetry

-- After: 28MB 스캔 = $0.17
SELECT * FROM bronze_robot_telemetry
WHERE year = 2026 AND month = 04 AND day = 27
LIMIT 1000000
```

**절감: 99.2% ✓**

### 3️⃣ Flink 상태 저장소 최적화

```python
# ❌ 상태 폭증 (Watermark 없음)
# Window: 5분, 레코드: 10,000/sec
# 상태: 5분 × 10,000 = 300,000 레코드 (메모리 폭증)

# ✅ 정상 (Watermark 설정)
WATERMARK FOR event_time AS event_time - INTERVAL '10' SECOND
# Window 종료: window_end + 10초 후
# 상태: 5분 + 10초 = 310초 (정상 크기)
```

### 4️⃣ API 캐시 최적화

```python
# 캐시 크기: 10,000 robots × 6 columns = ~10MB
# 메모리 사용: 30MB (파이썬 오버헤드 포함)

# 대량 쿼리 시나리오:
# - 단일 Pod: 메모리 안정적 (30MB)
# - 다중 Pod (HPA): 메모리 낭비 (30MB × N)
→ minReplicas = 1 유지 (캐시 공유 최대화)
```

---

## 📋 일일 체크리스트 (5분)

```
매일 아침 09:00에 확인:

□ Kinesis IncomingRecords > 0?
  aws cloudwatch get-metric-statistics \
    --metric-name IncomingRecords \
    --namespace AWS/Kinesis \
    --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 3600 \
    --statistics Sum

□ Airflow DAG robot_daily_etl 성공?
  kubectl exec -n airflow airflow-scheduler-0 -- \
    airflow dag-run list --dag-id robot_daily_etl | head -5

□ Bedrock Report 생성됨?
  aws s3 ls s3://bucket/reports/$(date -d 'yesterday' +%Y-%m-%d).txt

□ Slack Alert 채널에 메시지 있었나?
  (Slack UI에서 직접 확인)

□ Portal 응답 시간 확인
  curl -X POST http://api/api/chat \
    -d '{"question": "test"}' \
    -w "Time: %{time_total}s\n"

모두 통과? → Good! ✅
하나라도 실패? → 위 troubleshooting 참조
```

---

## 🚀 성장 시나리오별 확장 전략

### Scenario 1: 로봇 대수 10배 증가 (10K → 100K)

```
변경:
├─ KDS Shards: 10 → 100 (처리량 선형 증가)
├─ Firehose: 자동 조정 (처리량 증가)
├─ Generator Replicas: 1 → 10 (병렬 시뮬레이션)
├─ Athena: Partition Projection 필수 (스캔 비용 폭증)
└─ Flink DPU: 4 → 16 (상태 저장소 증가)

비용: +$5K/월
작업: ~2시간 (Terraform 수정 + 검증)
```

### Scenario 2: 실시간 분석 필요 (배치 → 스트림)

```
추가:
├─ Kinesis SQL (Flink 대체, 간편)
├─ DynamoDB (실시간 상태 저장)
├─ WebSocket (Portal → Real-time 업데이트)
└─ Apache Superset (라이브 대시보드)

비용: +$2K/월
작업: ~1주 (새로운 아키텍처)
```

### Scenario 3: 글로벌 확장 (EU → US + APAC)

```
변경:
├─ Cross-region replication (S3, DynamoDB)
├─ Route 53 (geo-routing)
├─ Lambda@Edge (CDN 캐시)
└─ DMS (데이터 동기화)

비용: +$10K/월 (리전당)
작업: ~1개월 (복잡한 아키텍처)
```

---

## 📞 Support & Escalation

### Level 1: 자체 진단 (위 가이드)
- 증상 파악 → flowchart 따라가기
- 해결 가능한 것: 10분 내 해결 ✓

### Level 2: AWS Support
- CloudFormation 스택 에러
- API Rate Limit 초과
- 서비스 가용성 문제

```bash
# Support Ticket 생성
aws support create-case \
  --subject "Kinesis throughput exceeded" \
  --communication-body "..." \
  --service-code "kinesis" \
  --severity-code "low"
```

### Level 3: 아키텍처 리뷰
- 비용 최적화 상담
- 성능 병목 분석
- 다중 리전 설계

→ AWS Solutions Architect 상담 (비용 있음)


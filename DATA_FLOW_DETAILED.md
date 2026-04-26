# 데이터 흐름 상세 분석 — 레코드 1개의 여행

> **목표**: "로봇이 생성한 센서 데이터 1개가 어떻게 Alert/Report가 되는가"를 추적할 수 있다

---

## 📍 시나리오: ROBOT-00042가 90°C 온도 감지

가상 로봇 ROBOT-00042가 2026-04-27 12:34:56 UTC에 motor_temp=90°C 센서 값을 생성했다.
이 데이터가 Slack Alert → Grafana → AI 리포트까지 어떻게 흐르는가?

---

## 🚀 Phase 1: Ingestion (00초~)

### Step 1-1: Generator가 데이터 생성

```python
# src/generator/app.py
timestamp = "2026-04-27T12:34:56Z"  # UTC 기준
record = {
    "robot_id": "ROBOT-00042",
    "pos_x": 15.3,
    "pos_y": 42.7,
    "battery_level": 78,
    "motor_temp": 90.0,          # ← 이상 온도!
    "current_load": 0.5,         # 부하 낮음
    "timestamp": timestamp
}

# boto3로 KDS에 전송
kinesis_client.put_records(
    StreamName="robot-telemetry-stream",
    Records=[{
        "Data": json.dumps(record),
        "PartitionKey": "ROBOT-00042"  # 같은 로봇은 같은 Shard로
    }]
)
```

### Step 1-2: Glue Schema Registry 검증 (선택사항)

```python
# Generator가 KDS 전송 전 스키마 검증
from glue_schema_registry_client import get_compatibility

schema = {
    "type": "record",
    "fields": [
        {"name": "robot_id", "type": "string"},
        {"name": "motor_temp", "type": "double"},
        ...
    ]
}
# 성공 → KDS 전송
# 실패 (필드 누락 등) → 예외 발생, 재시도
```

### Step 1-3: KDS에 저장 (1초 이내)

```
KDS Shard 구조:
- robot-telemetry-stream: 10개 Shard
- PartitionKey "ROBOT-00042" → Shard N (해시 기반)
  └─ Sequence: [12:34:56Z] ROBOT-00042 motor_temp=90.0
     DynamoDB Shard Iterator: shard-000012:12345678...

보존: 24시간
```

**실무 팁**: 같은 로봇 ID는 항상 같은 Shard로 라우팅된다.
→ 순서 보장 (ROBOT-00042의 센서 값들이 시간 순서대로 처리됨)

---

## ⚡ Phase 2: Streaming — Real-time Anomaly Detection (1초~10초)

### Step 2-1: Managed Flink가 KDS 소비

```python
# src/flink/app.py (PyFlink Table API)
env = StreamExecutionEnvironment.get_execution_environment()
t_env = StreamTableEnvironment.create(environment=env)

# Source: KDS to Table
t_env.execute_sql("""
    CREATE TABLE source_kds (
        robot_id STRING,
        pos_x DOUBLE,
        pos_y DOUBLE,
        battery_level INT,
        motor_temp DOUBLE,
        current_load DOUBLE,
        event_time BIGINT,              -- Unix 타임스탬프
        WATERMARK FOR event_time AS event_time - INTERVAL '10' SECOND
    ) WITH (
        'connector' = 'kinesis',
        'stream' = 'robot-telemetry-stream',
        'aws.region' = 'eu-west-1',
        'format' = 'json'
    )
""")

# ROBOT-00042 레코드가 Flink에 도착 (1~2초 지연)
# Watermark: 10초 허용 (Late Data 처리)
```

### Step 2-2: 5분 Tumbling Window로 통계 계산

```python
# ROBOT-00042 기준으로 지난 5분간의 온도 통계
# [12:30~12:35] Window에 ROBOT-00042 데이터 ~300건 포함
#   ├─ 평균: 75°C
#   ├─ 표준편차: 4.2°C
#   └─ 현재: 90°C

t_env.execute_sql("""
    CREATE TEMPORARY VIEW window_stats AS
    SELECT
        TUMBLE_START(event_time, INTERVAL '5' MINUTE) as window_start,
        robot_id,
        AVG(motor_temp) as avg_temp,
        STDDEV(motor_temp) as stddev_temp,
        MIN(current_load) as min_load,
        MAX(motor_temp) as max_temp,
        COUNT(*) as cnt
    FROM source_kds
    GROUP BY
        TUMBLE(event_time, INTERVAL '5' MINUTE),
        robot_id
""")
```

### Step 2-3: 이상 탐지 조건 평가

```python
# 조건 1: Z-Score 기반 (통계적 이상)
Z_SCORE_THRESHOLD = 3.0
STDDEV_GUARD = 0.5

t_env.execute_sql("""
    CREATE TEMPORARY VIEW anomaly_candidates AS
    SELECT
        robot_id,
        event_time,
        motor_temp,
        current_load,
        (motor_temp - avg_temp) / GREATEST(stddev_temp, {})
            as zscore,
        motor_temp / GREATEST(current_load, 1.0)
            as temp_load_ratio
    FROM source_kds
    LEFT JOIN window_stats
        ON source_kds.robot_id = window_stats.robot_id
        AND source_kds.event_time BETWEEN 
            window_stats.window_start 
            AND window_stats.window_start + INTERVAL '5' MINUTE
""".format(STDDEV_GUARD))

# ROBOT-00042의 경우:
# Z-Score = (90 - 75) / 4.2 = 3.57 > 3.0 ✓ (이상!)
```

```python
# 조건 2: 다변량 상관성 (부하 대비 과열)
TEMP_LOAD_RATIO_THRESHOLD = 1.8
MIN_TEMP = 85.0

t_env.execute_sql("""
    SELECT * FROM anomaly_candidates
    WHERE 
        (ABS(zscore) > {})  -- 조건 1
        OR 
        (motor_temp >= {} AND temp_load_ratio > {})  -- 조건 2
""".format(
    Z_SCORE_THRESHOLD,
    MIN_TEMP,
    TEMP_LOAD_RATIO_THRESHOLD
))

# ROBOT-00042: Z-Score 조건 (3.57) ✓ → 이상 감지!
```

### Step 2-4: 1분 Tumbling Window로 재집계

```python
# 알람 폭주 방지: 같은 로봇이 연속 이상 → 1분에 1건만 집계
t_env.execute_sql("""
    CREATE TEMPORARY VIEW alert_events AS
    SELECT
        TUMBLE_START(event_time, INTERVAL '1' MINUTE) as alert_time,
        robot_id,
        COUNT(*) as anomaly_count,
        AVG(motor_temp) as avg_alert_temp,
        MAX(motor_temp) as max_alert_temp
    FROM anomaly_candidates
    GROUP BY
        TUMBLE(event_time, INTERVAL '1' MINUTE),
        robot_id
""")

# 12:34:00~12:35:00 Window
# ROBOT-00042: anomaly_count=3, avg_alert_temp=89°C, max=90°C
```

### Step 2-5: 이중 Sink (Dual Sink)

```python
# Sink 1: Alert KDS (Lambda 트리거)
t_env.execute_sql("""
    CREATE TABLE sink_alert_kds (
        robot_id STRING,
        anomaly_count INT,
        max_alert_temp DOUBLE,
        alert_time BIGINT
    ) WITH (
        'connector' = 'kinesis',
        'stream' = 'robot-anomaly-alert-stream',
        'aws.region' = 'eu-west-1',
        'format' = 'json'
    )
""")

# Sink 2: S3 (이력 추적)
t_env.execute_sql("""
    CREATE TABLE sink_s3_alerts (
        robot_id STRING,
        anomaly_count INT,
        max_alert_temp DOUBLE,
        alert_time BIGINT
    ) WITH (
        'connector' = 'filesystem',
        'path' = 's3://bucket/alerts/year=2026/month=04/day=27/',
        'format' = 'json'
    )
""")

# Statement Set: 두 Sink를 동일 트랜잭션에서 실행
statement_set = t_env.create_statement_set()
statement_set.add_insert_into("sink_alert_kds", 
                               t_env.from_path("alert_events"))
statement_set.add_insert_into("sink_s3_alerts",
                               t_env.from_path("alert_events"))
statement_set.execute()

# Result:
# [Alert KDS] {robot_id: "ROBOT-00042", anomaly_count: 3, max_alert_temp: 90.0, alert_time: 1714225440}
# [S3] s3://bucket/alerts/year=2026/month=04/day=27/hour=12/.../ROBOT-00042_alert.json
```

**실무 팁**: Statement Set으로 두 Sink를 동시에 실행하면 Exactly-Once 보장
(한쪽만 실패 → 트랜잭션 롤백 → 둘 다 재시도)

---

## 🔔 Phase 3: Real-time Alert — Lambda + SNS + Slack

### Step 3-1: Lambda Event Source Mapping

```python
# terraform/modules/data_pipeline/lambda.tf
resource "aws_lambda_event_source_mapping" "alert_kds" {
  event_source_arn  = aws_kinesis_stream.alert.arn
  function_name     = aws_lambda_function.alert_handler.arn
  enabled           = true
  batch_size        = 100  # 100건마다 Lambda 호출
  starting_position = "LATEST"  # 최신부터 읽기
}

# Lambda가 Alert KDS를 폴링: 100ms마다 배치 확인
# Alert KDS에 새 레코드 → Lambda 자동 호출 (~1초 내)
```

### Step 3-2: Lambda 핸들러 실행

```python
# src/lambda/alert_handler.py
import boto3
import json
from datetime import datetime

ssm = boto3.client('ssm')
sns = boto3.client('sns')

def lambda_handler(event, context):
    # 1. Alert KDS 이벤트 파싱
    for record in event['Records']:
        payload = json.loads(
            base64.b64decode(record['kinesis']['data'])
        )
        
        robot_id = payload['robot_id']
        max_temp = payload['max_alert_temp']
        timestamp = datetime.fromtimestamp(
            payload['alert_time']
        ).isoformat()
        
        # 2. SSM Parameter Store에서 portal_url 런타임 조회
        try:
            response = ssm.get_parameter(
                Name='/robot-telemetry/portal-url'
            )
            portal_url = response['Parameter']['Value']
        except ssm.exceptions.ParameterNotFound:
            portal_url = "https://pending.setup"  # Fallback
        
        # 3. Slack 메시지 생성
        slack_message = f"""
⚠️ *이상 감지* 

🤖 로봇 ID: {robot_id}
🌡️  온도: {max_temp:.1f}°C
🕐 감지 시각: {timestamp}

🔗 <{portal_url}/?robot_id={robot_id}|포털에서 확인>
        """
        
        # 4. SNS로 발행
        sns.publish(
            TopicArn='arn:aws:sns:eu-west-1:xxx:robot-anomaly-alerts',
            Message=slack_message,
            Subject=f'[Alert] {robot_id} 고온 감지'
        )
        
        print(f"Alert published: {robot_id} → {max_temp}°C")

# Lambda 콜드스타트: ~500ms
# Alert 발행부터 Slack 수신까지: ~2초
```

### Step 3-3: SNS → Slack

```
SNS Topic: robot-anomaly-alerts
└─ Subscription: Slack Webhook
   └─ URL: https://hooks.slack.com/services/T00000000/B00000000/XXXX
   
메시지:
⚠️ 이상 감지
🤖 로봇 ID: ROBOT-00042
🌡️  온도: 90.0°C
🕐 감지 시각: 2026-04-27T12:34:56Z
🔗 포털에서 확인: https://k8s-xxx.elb.amazonaws.com/?robot_id=ROBOT-00042
```

**Timeline 정리:**
- 12:34:56Z: 센서 데이터 생성 (Generator)
- 12:34:57Z: KDS 저장 (Ingestion)
- 12:34:58Z: Flink 처리 (Streaming)
- 12:35:00Z: Lambda 호출 (Batch)
- 12:35:02Z: Slack 수신 (Real-time Alert)

**총 지연: 6초** ✓

---

## 📊 Phase 4: Batch Processing — Bronze → Silver → Gold

### 다음 날 자정 (2026-04-27 23:59:59 → 2026-04-28 00:00:00)

### Step 4-1: Firehose가 Bronze를 S3에 저장

```
Timeline 2026-04-27 00:00:00 ~ 23:59:59:
- Firehose가 KDS의 모든 레코드를 5분마다 배치로 S3에 저장
- Format Conversion: JSON → Parquet (Snappy 압축)
- Dynamic Partitioning:

S3 경로:
s3://bucket/bronze/
  year=2026/
    month=04/
      day=27/
        hour=00/
          <UUID>.parquet  # 00:00~00:05의 데이터
        hour=01/
          <UUID>.parquet  # 01:00~01:05의 데이터
        ...
        hour=12/
          <UUID>.parquet  # 12:30~12:35: ROBOT-00042 포함
          <UUID>.parquet  # 12:35~12:40
```

### Step 4-2: Airflow DAG 시작 (실행_date = 2026-04-27)

```python
# dags/robot_daily_etl.py
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.amazon.aws.operators.athena import AthenaOperator

dag = DAG(
    'robot_daily_etl',
    schedule_interval='0 0 * * *',  # 매일 자정
    catchup=False
)

with dag:
    # Task 1: Data Quality Check
    quality_check = PythonOperator(
        task_id='quality_check',
        python_callable=evaluate_quality,
        op_kwargs={'execution_date': '{{ ds }}'}  # ds = 2026-04-27
    )
    
    # Task 2: Bronze → Silver
    bronze_to_silver = AthenaOperator(
        task_id='bronze_to_silver',
        query="""
            INSERT OVERWRITE TABLE silver_robot_telemetry
            PARTITION (dt = '{{ ds }}')
            SELECT
                robot_id, pos_x, pos_y, battery_level,
                motor_temp, current_load, timestamp
            FROM bronze_robot_telemetry
            WHERE year = YEAR(CAST('{{ ds }}' AS DATE))
              AND month = MONTH(CAST('{{ ds }}' AS DATE))
              AND day = DAY(CAST('{{ ds }}' AS DATE))
              AND motor_temp < 500
              AND battery_level BETWEEN 0 AND 100
              AND robot_id IS NOT NULL
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY robot_id, timestamp ORDER BY robot_id
            ) = 1  -- 중복 제거
        """,
        database='robot_telemetry_db'
    )
    
    # Task 3: Silver → Gold
    silver_to_gold = AthenaOperator(
        task_id='silver_to_gold',
        query="""
            INSERT OVERWRITE TABLE gold_robot_daily_stats
            PARTITION (dt = '{{ ds }}')
            SELECT
                '{{ ds }}' as dt,
                robot_id,
                CAST(AVG(motor_temp) AS DECIMAL(5,2))
                    as avg_motor_temp,
                CAST(MAX(motor_temp) AS DECIMAL(5,2))
                    as max_motor_temp,
                CAST(100 - MIN(battery_level) AS DECIMAL(5,2))
                    as battery_drain,
                COUNT(DISTINCT HOUR(timestamp))
                    as active_hours
            FROM silver_robot_telemetry
            WHERE dt = '{{ ds }}'
            GROUP BY dt, robot_id
        """,
        database='robot_telemetry_db'
    )
    
    # Task 4: Bedrock Report
    bedrock_report = PythonOperator(
        task_id='bedrock_report',
        python_callable=generate_bedrock_report,
        op_kwargs={'execution_date': '{{ ds }}'}
    )
    
    # DAG 체인
    quality_check >> bronze_to_silver >> silver_to_gold >> bedrock_report
```

### Step 4-3: ROBOT-00042 데이터 변환

#### Bronze (원본)
```sql
SELECT * FROM bronze_robot_telemetry
WHERE day = 27 AND robot_id = 'ROBOT-00042'
ORDER BY timestamp

robot_id      | timestamp           | motor_temp | battery_level | ...
ROBOT-00042   | 2026-04-27 12:34:56 | 90.0       | 78            |
ROBOT-00042   | 2026-04-27 12:34:56 | 90.0       | 78            | (중복!)
ROBOT-00042   | 2026-04-27 12:35:12 | 88.5       | 77            |
ROBOT-00042   | 2026-04-27 12:35:28 | 87.2       | 76            |
... (240개 레코드)
```

#### Silver (정제)
```sql
SELECT * FROM silver_robot_telemetry
WHERE dt = '2026-04-27' AND robot_id = 'ROBOT-00042'

robot_id      | timestamp           | motor_temp | battery_level | dt
ROBOT-00042   | 2026-04-27 12:34:56 | 90.0       | 78            | 2026-04-27
ROBOT-00042   | 2026-04-27 12:35:12 | 88.5       | 77            | 2026-04-27
ROBOT-00042   | 2026-04-27 12:35:28 | 87.2       | 76            | 2026-04-27
... (240개, 중복 제거)
```

#### Gold (집계)
```sql
SELECT * FROM gold_robot_daily_stats
WHERE dt = '2026-04-27' AND robot_id = 'ROBOT-00042'

dt           | robot_id    | avg_motor_temp | max_motor_temp | battery_drain | active_hours
2026-04-27   | ROBOT-00042 | 78.5           | 90.0           | 22.0          | 22
```

**분석:**
- 일일 평균 온도 78.5°C: 정상
- 최고 온도 90.0°C: 오늘 우리가 감지한 이상
- 배터리 소모: 22% (정상 범위)
- 가동 시간: 22시간 (하루 종일 거의 운영)

---

## 📝 Phase 5: AI Insight & Serving

### Step 5-1: Bedrock Report 생성 (2026-04-28 00:30)

```python
# dags/robot_daily_etl.py의 bedrock_report Task
def _bedrock_report(execution_date):
    athena = boto3.client('athena', region_name='eu-west-1')
    bedrock = boto3.client('bedrock-runtime', region_name='eu-west-1')
    s3 = boto3.client('s3')
    
    # 1. Gold 테이블 조회 (어제 데이터)
    query = f"""
        SELECT dt, robot_id, avg_motor_temp, max_motor_temp, 
               battery_drain, active_hours
        FROM gold_robot_daily_stats
        WHERE dt = '{execution_date}'
        ORDER BY max_motor_temp DESC
        LIMIT 100
    """
    
    # Athena 쿼리 실행
    result = athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={'Database': 'robot_telemetry_db'},
        ResultConfiguration={
            'OutputLocation': 's3://bucket/project-athena-results/'
        }
    )
    
    # 2. 결과 대기 및 파싱
    query_id = result['QueryExecutionId']
    # ... polling ...
    data_summary = """
    [2026-04-27 로봇 상태 요약]
    - 전체 로봇: 10,000대
    - 이상 감지: 3대
    - 평균 온도: 75.2°C
    - 최고 온도: 92.3°C (ROBOT-00042, ROBOT-00087, ROBOT-00156)
    """
    
    # 3. Bedrock Claude 호출
    bedrock_payload = {
        "modelId": "anthropic.claude-3-haiku-20240307-v1:0",
        "contentType": "application/json",
        "accept": "application/json",
        "body": json.dumps({
            "system": "당신은 공장 로봇 정비팀의 기술 고문입니다.",
            "messages": [
                {
                    "role": "user",
                    "content": f"""
다음은 오늘 공장 로봇들의 상태 지표야:

{data_summary}

이를 분석해서 가장 점검이 시급한 로봇 3대와 그 이유를 
정비반장에게 보내는 형식으로 300자 이내로 요약해.
응답 시 로봇 ID를 [ROBOT-XXXXX] 형식으로 표기해.
                    """
                }
            ],
            "max_tokens": 512,
            "temperature": 0.7
        })
    }
    
    response = bedrock.invoke_model(**bedrock_payload)
    report_text = json.loads(response['body'].read())['content'][0]['text']
    
    # 4. S3에 저장
    s3.put_object(
        Bucket='bucket',
        Key=f'reports/{execution_date}.txt',
        Body=report_text,
        ContentType='text/plain'
    )
    
    print(f"Report saved: {execution_date}.txt")
    return report_text

# 생성된 리포트 예시:
"""
[점검 시급 로봇 현황]

1. [ROBOT-00042] — 최고온도 90.0°C 도달
   원인: 모터 과열 신호. 평소 78.5°C 대비 11°C 급상승.
   조치: 모터 베어링 상태 점검, 냉각 시스템 확인 필수.

2. [ROBOT-00087] — 배터리 급속 방전 중
   원인: 충전 회로 이상 의심. 일반 로봇 대비 30% 이상 높은 소모율.
   조치: 배터리 전압 측정, 충전 보드 교체 고려.

3. [ROBOT-00156] — 비정상 가동 시간 패턴
   원인: 초 단위 ON/OFF 반복 (전기 접점 불량 추정).
   조치: 메인 전원 커넥터 재납땜, 전자부품 교체.

(총 285자)
"""
```

### Step 5-2: API 캐시 갱신 (2026-04-28 01:00)

```python
# src/api/main.py
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

scheduler = BackgroundScheduler()

def refresh_cache():
    """매일 01:00 KST에 Gold 데이터 로드"""
    global _gold_cache, _cache_updated_at, _data_date, _cache_ready
    
    _cache_ready = False
    
    try:
        athena = boto3.client('athena', region_name='eu-west-1')
        
        # 어제 데이터 조회 (execution_date 기준)
        yesterday = (datetime.now(pytz.timezone('Asia/Seoul'))
                     - timedelta(days=1)).date()
        
        query = f"""
            SELECT dt, robot_id, avg_motor_temp, max_motor_temp,
                   battery_drain, active_hours
            FROM gold_robot_daily_stats
            WHERE dt = '{yesterday}'
        """
        
        result = athena.start_query_execution(
            QueryString=query,
            QueryExecutionContext={'Database': 'robot_telemetry_db'},
            ResultConfiguration={
                'OutputLocation': 's3://bucket/project-athena-results/'
            }
        )
        
        # 결과 대기
        query_id = result['QueryExecutionId']
        # ... polling (보통 10~30초) ...
        
        # DataFrame으로 변환
        _gold_cache = df  # 약 10,000행 × 6컬럼
        _data_date = str(yesterday)
        _cache_updated_at = datetime.now(pytz.UTC).isoformat()
        _cache_ready = True
        
        logger.info(f"Cache refreshed: {_data_date} at {_cache_updated_at}")
    
    except Exception as e:
        logger.error(f"Cache refresh failed: {e}")
        _cache_ready = False

# APScheduler 설정
scheduler.add_job(
    refresh_cache,
    'cron',
    hour=1,          # KST 01:00
    minute=0,
    timezone='Asia/Seoul'  # ← 타임존 명시 필수!
)

scheduler.start()

# API 시작 시에도 한 번 실행
refresh_cache()
```

### Step 5-3: 운영자가 Portal 접속 (2026-04-28 10:00)

```
사용자: https://k8s-xxx.elb.amazonaws.com/?robot_id=ROBOT-00042

1. FastAPI /api/status 호출
   Response: {
       "data_date": "2026-04-27",
       "cached_at": "2026-04-28T01:00:00Z"
   }
   → Portal 헤더: "2026-04-27 기준 데이터 · 01:00 갱신"

2. portal.html 로드
   → URLSearchParams에서 robot_id=ROBOT-00042 파싱
   → AI Chat 입력란에 자동 입력:
      "ROBOT-00042의 현재 상태를 분석해줘"
   → 자동 전송

3. /api/chat 호출
   POST /api/chat
   Body: { "question": "ROBOT-00042의 현재 상태를 분석해줘" }

4. Server-side 처리
   ├─ 캐시에서 ROBOT-00042 데이터 조회 (1ms)
   │  └─ avg_motor_temp: 78.5, max_motor_temp: 90.0, ...
   │
   ├─ Bedrock 호출 (300ms)
   │  └─ prompt = "데이터: ... 질문: ROBOT-00042의 현재 상태를 분석해줘"
   │
   └─ 응답 생성 (1초)
      "ROBOT-00042는 오늘 최고 90°C에 도달했습니다. 
       이는 5분 이동평균 대비 3-sigma 이상의 이상치입니다. 
       모터 상태를 점검해주세요. 자세한 내용은 [상태보기]에서 확인하세요."

5. Portal UI 렌더링
   ├─ Grafana iframe 로드 (Fleet Dashboard)
   │  └─ src="http://grafana-svc/d/robot_fleet/?robot=ROBOT-00042&kiosk=tv"
   │
   ├─ AI 응답 렌더링
   │  └─ [상태보기] 버튼 → DIV 클릭 시 Grafana src 변경
   │
   └─ 시각화 완료
```

---

## 🔁 전체 사이클 (하루 기준)

| 시간 | 주체 | 작업 | 지연 |
|------|------|------|------|
| 00:00~23:59 | Generator | 센서 데이터 생성 & KDS 전송 | 실시간 |
| 00:00~23:59 | Flink | 실시간 이상 탐지 & Alert 발행 | <3초 |
| 00:00~23:59 | Lambda | Alert → Slack 전송 | <2초 |
| 00:00~23:59 | Firehose | Bronze S3 저장 | 5분 배치 |
| 00:00 | Airflow | quality_check 시작 | - |
| 00:10 | Airflow | bronze_to_silver ETL | ~5분 |
| 00:15 | Airflow | silver_to_gold ETL | ~3분 |
| 00:20 | Airflow | bedrock_report 생성 | ~10분 |
| 01:00 | API | Cache refresh (Gold 데이터 로드) | 10~30초 |
| 10:00 | 운영자 | Portal 접속 & AI Chat | <1초 응답 |

**핵심 인사이트:**
1. 센서 데이터 → Slack Alert: 6초 (실시간성)
2. 센서 데이터 → Gold Table: 24시간 (배치 분석)
3. Gold Table → AI Report: 1시간 (자동 생성)
4. AI Report → 운영자 Dashboard: 즉시 (캐시 기반)

---

## 📌 ROBOT-00042 최종 상태

```
[2026-04-27 일일 보고]

센서 수집        Gold 테이블         AI 분석
─────────────────────────────────────────────
240건 레코드     avg: 78.5°C         "모터 과열 주의"
중복 제거됨      max: 90.0°C ← ★     "베어링 점검 권장"
이상치 필터      battery: -22%
                active: 22h
                
Slack Alert      Dashboard            Report
─────────────────────────────────────────────
⚠️ 90.0°C        Grafana 시각화       📄 reports/2026-04-27.txt
"포털에서 확인"  Fleet Status         (자동 생성, S3 저장)
12:35:02Z        Anomaly Timeline
                 Pipeline Health
```

---

## 실무 체크리스트

### 데이터 흐름 이해도 자가 진단

- [ ] Generator가 왜 `asyncio`를 사용하는가? (병렬성)
- [ ] KDS가 `PartitionKey`로 ROBOT-00042를 사용하는 이유? (순서 보장)
- [ ] Flink Watermark가 왜 필수인가? (Window 종료)
- [ ] Alert KDS가 별도로 필요한 이유? (Lambda 트리거, 격리)
- [ ] Bronze/Silver/Gold 간 데이터 손실이 발생하는가? (INSERT OVERWRITE)
- [ ] 캐시 갱신 시 Athena 비용이 발생하는가? (최소 1 스캔 = ~10MB = $0.005)
- [ ] ROBOT-00042가 정상인데 Alert가 발생할 수 있는가? (Z-Score 이슈)

### 트러블슈팅 시나리오

1. **"Slack Alert이 안 온다"**
   - [ ] Alert KDS에 레코드가 들어왔는가? (Flink logs)
   - [ ] Lambda가 호출됐는가? (CloudWatch Logs)
   - [ ] SNS 구독 설정이 맞는가?
   - [ ] Slack Webhook 유효한가?

2. **"Bedrock Report가 비어있다"**
   - [ ] Gold 테이블에 데이터가 있는가? (execution_date 확인)
   - [ ] Athena 쿼리가 성공했는가? (FAILED 상태 확인)
   - [ ] Bedrock 할당량이 남았는가? (RateLimit 에러)

3. **"Portal Chat 응답이 느리다"**
   - [ ] 캐시가 로드됐는가? (_cache_ready=True)
   - [ ] 캐시 크기가 너무 크면? (10,000 × 6 = 60,000행 = ~10MB)
   - [ ] Bedrock 콜드스타트인가? (첫 호출 +500ms)

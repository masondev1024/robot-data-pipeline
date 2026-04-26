# Step 1: flink-sql

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/research.md`
- `/terraform/modules/data_pipeline/kinesis.tf`

## 작업

`flink/anomaly_detection.sql`을 작성하라.

### Source Table (KDS → Flink)
```sql
CREATE TABLE robot_telemetry_source (
    robot_id      STRING,
    pos_x         DOUBLE,
    pos_y         DOUBLE,
    battery_level INT,
    current_load  INT,
    motor_temp    DOUBLE,
    `timestamp`   STRING,
    event_time AS TO_TIMESTAMP(`timestamp`, 'yyyy-MM-dd''T''HH:mm:ss''Z'''),
    WATERMARK FOR event_time AS event_time - INTERVAL '10' SECOND  -- Late Data 처리
) WITH (
    'connector'              = 'kinesis',
    'stream'                 = 'robot-telemetry-stream',
    'aws.region'             = 'ap-northeast-2',
    'scan.stream.initpos'    = 'LATEST',
    'format'                 = 'json'
);
```

### Sink ① — S3 이력 로깅
```sql
CREATE TABLE robot_alert_s3_sink (
    window_start   TIMESTAMP(3),
    window_end     TIMESTAMP(3),
    robot_id       STRING,
    avg_motor_temp DOUBLE,
    max_motor_temp DOUBLE,
    alert_count    BIGINT
) WITH (
    'connector' = 'filesystem',
    'path'      = 's3://de-ai-06-827913617635-ap-northeast-2-an/alerts/',
    'format'    = 'json'
);
```

### Sink ② — Alert KDS (Lambda 트리거용)
```sql
CREATE TABLE robot_alert_kinesis_sink (
    window_start   TIMESTAMP(3),
    window_end     TIMESTAMP(3),
    robot_id       STRING,
    avg_motor_temp DOUBLE,
    max_motor_temp DOUBLE,
    alert_count    BIGINT
) WITH (
    'connector'   = 'kinesis',
    'stream'      = 'robot-anomaly-alert-stream',
    'aws.region'  = 'ap-northeast-2',
    'format'      = 'json'
);
```

### 이상 탐지 쿼리 — 1분 Tumbling Window
```sql
-- S3 Sink
INSERT INTO robot_alert_s3_sink
SELECT
    TUMBLE_START(event_time, INTERVAL '1' MINUTE) AS window_start,
    TUMBLE_END(event_time, INTERVAL '1' MINUTE)   AS window_end,
    robot_id,
    AVG(motor_temp)  AS avg_motor_temp,
    MAX(motor_temp)  AS max_motor_temp,
    COUNT(*)         AS alert_count
FROM robot_telemetry_source
WHERE motor_temp > 90.0
GROUP BY robot_id, TUMBLE(event_time, INTERVAL '1' MINUTE);

-- KDS Sink (동일 쿼리, Sink만 다름)
INSERT INTO robot_alert_kinesis_sink ...
```

## Acceptance Criteria

```bash
ls flink/anomaly_detection.sql
grep -q "WATERMARK" flink/anomaly_detection.sql && echo "OK: watermark"
grep -q "TUMBLE_START" flink/anomaly_detection.sql && echo "OK: tumbling window"
grep -q "motor_temp > 90" flink/anomaly_detection.sql && echo "OK: threshold"
grep -q "robot-anomaly-alert-stream" flink/anomaly_detection.sql && echo "OK: alert KDS sink"
grep -q "robot_alert_s3_sink" flink/anomaly_detection.sql && echo "OK: S3 sink"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - WATERMARK가 있는가? (Late Data 처리 — CLAUDE.md 필수)
   - 이상 탐지 결과가 **S3 + KDS 양쪽 모두** Sink 되는가?
   - KDS Sink 스트림 이름이 `"robot-anomaly-alert-stream"`인가?
   - 임계값이 `motor_temp > 90.0`인가?
3. `phases/3-realtime/index.json` step 1 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "flink/anomaly_detection.sql: KDS Source, Dual Sink(S3 alerts/ + robot-anomaly-alert-stream), 1분 Tumbling Window, WATERMARK"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- SNS Sink를 직접 작성하지 마라. 이유: Flink에 SNS Native Connector가 없다. Flink → KDS → Lambda → SNS 순서
- S3 Sink만 작성하고 KDS Sink를 빠뜨리지 마라. 이유: Phase 4 Lambda 트리거가 Alert KDS를 읽어야 한다
- WATERMARK 선언을 생략하지 마라. 이유: CLAUDE.md에서 Late Data 처리를 위한 Watermark 필수로 명시

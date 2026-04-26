# Step 1: flink-app (PyFlink 이상 탐지 — Z-Score + 다변량)

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md` (ADR-009 이상 탐지 알고리즘, ADR-010 PyFlink 결정)
- `/docs/research.md` §4 (Z-Score, 다변량, Watermark, Threshold 외부화)
- `/terraform/modules/data_pipeline/flink.tf` (step 0 산출물 — property group 키 매핑 확인)
- `/terraform/modules/data_pipeline/kinesis.tf` (Source/Sink 스트림 이름)

## 작업

PyFlink Application을 작성하고 ZIP으로 패키징하라. 산출물은 다음 4개:

1. `flink/anomaly_detection.py` — 메인 진입점 (PyFlink Table API)
2. `flink/requirements.txt` — `apache-flink==1.18.1` (Managed Flink 1.18 일치)
3. `flink/lib/flink-sql-connector-kinesis-1.18.1.jar` — Kinesis connector JAR (다운로드 스크립트로 받음)
4. `flink/build.sh` — 위 항목들을 `flink/anomaly_detection.zip`으로 패키징하는 빌드 스크립트

### `flink/anomaly_detection.py` 명세

```python
from pyflink.table import EnvironmentSettings, TableEnvironment
import os, json

def get_property(prop_map: dict, key: str, default: str = None) -> str:
    """Managed Flink runtime properties.json에서 값 읽기."""
    # Application property group "robot-app-config"에서 읽음
    ...

def main():
    # 1) TableEnvironment 생성 (streaming mode)
    env_settings = EnvironmentSettings.in_streaming_mode()
    t_env = TableEnvironment.create(env_settings)

    # 2) Managed Flink가 주입한 property 읽기
    #    runtime properties.json 위치: /etc/flink/application_properties.json
    #    group_id: "robot-app-config"
    props = load_application_properties("robot-app-config")
    main_stream    = props["kinesis.main.stream"]
    alert_stream   = props["kinesis.alert.stream"]
    s3_alerts_path = props["s3.alerts.path"]
    region         = props["aws.region"]
    zscore_thr     = float(props["zscore.threshold"])
    sigma_floor    = float(props["zscore.sigma.floor"])
    load_thr       = float(props["load.ratio.threshold"])
    min_temp       = float(props["load.ratio.min.temp"])

    # 3) Source Table — KDS robot-telemetry-stream
    t_env.execute_sql(f"""
        CREATE TABLE robot_telemetry_source (
            robot_id      STRING,
            pos_x         DOUBLE,
            pos_y         DOUBLE,
            battery_level INT,
            current_load  INT,
            motor_temp    DOUBLE,
            `timestamp`   STRING,
            event_time AS TO_TIMESTAMP(`timestamp`, 'yyyy-MM-dd''T''HH:mm:ss''Z'''),
            WATERMARK FOR event_time AS event_time - INTERVAL '10' SECOND
        ) WITH (
            'connector'           = 'kinesis',
            'stream'              = '{main_stream}',
            'aws.region'          = '{region}',
            'scan.stream.initpos' = 'LATEST',
            'format'              = 'json'
        )
    """)

    # 4) Sink ① — S3 alerts/ (이력)
    t_env.execute_sql(f"""
        CREATE TABLE robot_alert_s3_sink (
            window_start   TIMESTAMP(3),
            window_end     TIMESTAMP(3),
            robot_id       STRING,
            avg_motor_temp DOUBLE,
            max_motor_temp DOUBLE,
            alert_count    BIGINT
        ) WITH (
            'connector' = 'filesystem',
            'path'      = '{s3_alerts_path}',
            'format'    = 'json'
        )
    """)

    # 5) Sink ② — Alert KDS (Lambda 트리거용)
    t_env.execute_sql(f"""
        CREATE TABLE robot_alert_kinesis_sink (
            window_start   TIMESTAMP(3),
            window_end     TIMESTAMP(3),
            robot_id       STRING,
            avg_motor_temp DOUBLE,
            max_motor_temp DOUBLE,
            alert_count    BIGINT
        ) WITH (
            'connector'  = 'kinesis',
            'stream'     = '{alert_stream}',
            'aws.region' = '{region}',
            'format'     = 'json'
        )
    """)

    # 6) 이상 탐지 — Z-Score (5분 OVER) + 다변량 OR
    #    OVER window로 robot_id별 5분 이동 mean/stddev 계산
    t_env.execute_sql(f"""
        CREATE TEMPORARY VIEW anomalies AS
        SELECT
            robot_id,
            event_time,
            motor_temp,
            current_load
        FROM (
            SELECT
                robot_id,
                event_time,
                motor_temp,
                current_load,
                AVG(motor_temp) OVER w5min AS mean_temp,
                STDDEV_POP(motor_temp) OVER w5min AS stddev_temp
            FROM robot_telemetry_source
            WINDOW w5min AS (
                PARTITION BY robot_id
                ORDER BY event_time
                RANGE BETWEEN INTERVAL '5' MINUTE PRECEDING AND CURRENT ROW
            )
        )
        WHERE
            -- Condition 1: Z-Score 3-sigma (sigma_floor 가드)
            ABS(motor_temp - mean_temp) / GREATEST(stddev_temp, {sigma_floor}) > {zscore_thr}
            -- OR Condition 2: 다변량 (current_load 가드)
            OR (motor_temp >= {min_temp} AND motor_temp / GREATEST(current_load, 1) > {load_thr})
    """)

    # 7) 1분 Tumbling Window 집계 (알람 폭주 방지)
    t_env.execute_sql("""
        CREATE TEMPORARY VIEW windowed AS
        SELECT
            TUMBLE_START(event_time, INTERVAL '1' MINUTE) AS window_start,
            TUMBLE_END(event_time, INTERVAL '1' MINUTE)   AS window_end,
            robot_id,
            AVG(motor_temp) AS avg_motor_temp,
            MAX(motor_temp) AS max_motor_temp,
            COUNT(*)        AS alert_count
        FROM anomalies
        GROUP BY robot_id, TUMBLE(event_time, INTERVAL '1' MINUTE)
    """)

    # 8) Statement Set — 두 Sink 동시 실행
    stmt_set = t_env.create_statement_set()
    stmt_set.add_insert_sql("INSERT INTO robot_alert_s3_sink       SELECT * FROM windowed")
    stmt_set.add_insert_sql("INSERT INTO robot_alert_kinesis_sink  SELECT * FROM windowed")
    stmt_set.execute()


# 순수 함수로 분리 — step 2 단위 테스트가 import 함
def compute_zscore(temp: float, mean: float, stddev: float, sigma_floor: float) -> float:
    """|temp - mean| / max(stddev, sigma_floor)"""
    ...

def compute_load_ratio(temp: float, current_load: int) -> float:
    """temp / max(current_load, 1)"""
    ...

def is_anomaly(
    temp: float, mean: float, stddev: float, current_load: int,
    zscore_thr: float, sigma_floor: float, load_thr: float, min_temp: float,
) -> bool:
    """두 조건 OR — 단위 테스트 가능한 순수 함수"""
    cond1 = compute_zscore(temp, mean, stddev, sigma_floor) > zscore_thr
    cond2 = temp >= min_temp and compute_load_ratio(temp, current_load) > load_thr
    return cond1 or cond2


if __name__ == "__main__":
    main()
```

### `flink/build.sh` 명세

- `flink/lib/flink-sql-connector-kinesis-1.18.1.jar`을 다운로드 (없을 때만, idempotent):
  - URL: `https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-connector-kinesis/1.18.1/flink-sql-connector-kinesis-1.18.1.jar`
  - `curl -fsSL -o flink/lib/flink-sql-connector-kinesis-1.18.1.jar <URL>` (필수: `set -euo pipefail`)
- `flink/anomaly_detection.zip`을 다음 구조로 생성:
  ```
  anomaly_detection.py
  requirements.txt
  lib/flink-sql-connector-kinesis-1.18.1.jar
  ```
- 빌드 후 ZIP 크기 출력으로 검증.

### `flink/requirements.txt`

```
apache-flink==1.18.1
```

## Acceptance Criteria

```bash
# 1) 파일 존재
ls flink/anomaly_detection.py flink/requirements.txt flink/build.sh

# 2) PyFlink 핵심 요소
grep -q "WATERMARK" flink/anomaly_detection.py && echo "OK: watermark"
grep -q "RANGE BETWEEN INTERVAL '5' MINUTE PRECEDING" flink/anomaly_detection.py && echo "OK: 5-min OVER window"
grep -q "GREATEST(stddev_temp" flink/anomaly_detection.py && echo "OK: sigma floor guard"
grep -q "GREATEST(current_load, 1)" flink/anomaly_detection.py && echo "OK: load div-by-zero guard"
grep -q "TUMBLE(event_time, INTERVAL '1' MINUTE)" flink/anomaly_detection.py && echo "OK: 1-min tumbling"
grep -q "create_statement_set\|STATEMENT SET" flink/anomaly_detection.py && echo "OK: dual sink in statement set"
grep -q "robot_alert_s3_sink" flink/anomaly_detection.py && echo "OK: S3 sink"
grep -q "robot_alert_kinesis_sink" flink/anomaly_detection.py && echo "OK: KDS sink"

# 3) Threshold 외부화 (코드에 hardcoded 숫자 금지)
! grep -E "> 3\.0|> 1\.8|>= 85\.0" flink/anomaly_detection.py && echo "OK: no hardcoded thresholds"
grep -q "zscore.threshold" flink/anomaly_detection.py && echo "OK: reads zscore.threshold"
grep -q "load.ratio.threshold" flink/anomaly_detection.py && echo "OK: reads load.ratio.threshold"

# 4) 순수 함수 (step 2 단위 테스트가 import)
python3 -c "
import sys; sys.path.insert(0, 'flink')
from anomaly_detection import compute_zscore, compute_load_ratio, is_anomaly
assert compute_zscore(95, 80, 5, 0.5) == 3.0
assert compute_load_ratio(90, 50) == 1.8
assert is_anomaly(95, 80, 5, 50, zscore_thr=3.0, sigma_floor=0.5, load_thr=1.8, min_temp=85.0) is True
assert is_anomaly(80, 80, 5, 50, zscore_thr=3.0, sigma_floor=0.5, load_thr=1.8, min_temp=85.0) is False
print('OK: pure functions correct')
"

# 5) 빌드 스크립트 동작
bash flink/build.sh
ls flink/anomaly_detection.zip flink/lib/flink-sql-connector-kinesis-1.18.1.jar
unzip -l flink/anomaly_detection.zip | grep -q "anomaly_detection.py" && echo "OK: zip contains main"
unzip -l flink/anomaly_detection.zip | grep -q "lib/flink-sql-connector-kinesis-1.18.1.jar" && echo "OK: zip contains connector"
```

## 검증 절차

1. 위 AC 커맨드를 모두 실행하여 통과 확인.
2. 아키텍처 체크리스트:
   - Watermark가 10초 INTERVAL로 선언됐는가?
   - Z-Score는 `RANGE BETWEEN INTERVAL '5' MINUTE PRECEDING AND CURRENT ROW` OVER window를 쓰는가? (TUMBLE/HOP 아님 — 모든 행에 대해 직전 5분 평균을 계산해야 정확)
   - σ floor (`GREATEST(stddev_temp, sigma_floor)`) 와 current_load floor (`GREATEST(current_load, 1)`) 가드가 둘 다 있는가?
   - Statement Set으로 S3 + KDS 두 Sink 동시 실행하는가? (`stmt_set.add_insert_sql` 2회)
   - 모든 threshold가 `load_application_properties("robot-app-config")` 에서 읽히는가?
3. `phases/3-realtime/index.json` step 1 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "anomaly_detection.py: PyFlink Z-Score(5min OVER)+다변량 OR, 1min Tumbling, Dual Sink (S3+Alert KDS), threshold 외부화, ZIP 빌드 OK"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- SNS Sink를 직접 작성하지 마라. 이유: Flink에 SNS Native Connector가 없다 (ADR-007). Flink → KDS → Lambda → SNS 순서.
- Z-Score / load_ratio / min_temp 등 숫자 threshold를 코드에 하드코딩하지 마라. 이유: 운영 튜닝 시 재배포 발생 (ADR-009 결정).
- WATERMARK 선언을 생략하지 마라. 이유: CLAUDE.md 필수 규칙 + Late Data 처리 + state 무한 누적 방지.
- `STDDEV_POP` 대신 `STDDEV_SAMP`를 쓰지 마라. 이유: 모집단 분산 기반 3-sigma rule이 본 알고리즘 가정.
- 단순 임계값(`motor_temp > 90.0`)으로 폴백하지 마라. 이유: ADR-009가 고도화 결정. 단순 임계는 false positive 폭증.
- `'aws.region' = 'ap-northeast-2'` 처럼 region을 hardcoding 하지 마라. 이유: 실제 인프라는 `eu-west-1`. region property로 주입.
- `event_time`을 BIGINT epoch로 다루지 마라. 이유: Source DDL이 `TO_TIMESTAMP(timestamp, 'yyyy-MM-dd''T''HH:mm:ss''Z''')`로 STRING ISO8601 → TIMESTAMP 변환을 명시.

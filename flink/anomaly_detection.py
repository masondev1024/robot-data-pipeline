import os
import json

# 표준 라이브러리만 사용 — PyFlink import는 main()에서만 수행
# AWS Managed Service for Apache Flink — Python runtime property loader 표준 패턴
# Managed Flink가 application 시작 시 /etc/flink/application_properties.json 에 자동 주입.
APP_PROPS_PATH_RUNTIME = "/etc/flink/application_properties.json"
APP_PROPS_PATH_LOCAL = "application_properties.json"  # 로컬 개발용 fallback


def load_application_properties(group_id: str) -> dict:
    """Managed Flink가 주입한 PropertyGroup을 dict로 반환. 누락 시 빈 dict.

    Args:
        group_id: step 0의 environment_properties.property_group.property_group_id
                  (예: "robot-app-config")
    """
    file_path = APP_PROPS_PATH_LOCAL if os.environ.get("IS_LOCAL") else APP_PROPS_PATH_RUNTIME
    try:
        with open(file_path, "r") as f:
            groups = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    for prop in groups:
        if prop.get("PropertyGroupId") == group_id:
            return prop.get("PropertyMapProperties", {})
    return {}


def compute_zscore(temp: float, mean: float, stddev: float, sigma_floor: float) -> float:
    """Z-Score 계산: |temp - mean| / max(stddev, sigma_floor)"""
    denom = max(stddev, sigma_floor)
    return abs(temp - mean) / denom if denom > 0 else 0.0


def compute_load_ratio(temp: float, current_load: int) -> float:
    """부하 대비 온도 비율: temp / max(current_load, 1)"""
    return temp / max(current_load, 1)


def is_anomaly(
    temp: float,
    mean: float,
    stddev: float,
    current_load: int,
    zscore_thr: float,
    sigma_floor: float,
    load_thr: float,
    min_temp: float,
) -> bool:
    """두 조건 OR — 단위 테스트 가능한 순수 함수

    Condition 1: Moving Z-Score > threshold
    Condition 2: temp >= min_temp AND load_ratio > load_thr
    """
    cond1 = compute_zscore(temp, mean, stddev, sigma_floor) > zscore_thr
    cond2 = temp >= min_temp and compute_load_ratio(temp, current_load) > load_thr
    return cond1 or cond2


def main():
    """Managed Flink Application — PyFlink Table API"""
    # PyFlink import (Managed Flink에서만 사용)
    from pyflink.table import EnvironmentSettings, TableEnvironment

    # 1) TableEnvironment 생성 (streaming mode)
    env_settings = EnvironmentSettings.in_streaming_mode()
    t_env = TableEnvironment.create(env_settings)

    # 2) Managed Flink가 주입한 property 읽기
    #    runtime properties.json 위치: /etc/flink/application_properties.json
    #    group_id: "robot-app-config"
    props = load_application_properties("robot-app-config")
    main_stream = props.get("kinesis.main.stream", "robot-telemetry-stream")
    alert_stream = props.get("kinesis.alert.stream", "robot-anomaly-alert-stream")
    s3_alerts_path = props.get("s3.alerts.path", "s3://de-ai-06-smartfactory-bucket/alerts/")
    region = props.get("aws.region", "eu-west-1")
    zscore_thr = float(props.get("zscore.threshold", "3.0"))
    sigma_floor = float(props.get("zscore.sigma.floor", "0.5"))
    load_thr = float(props.get("load.ratio.threshold", "1.8"))
    min_temp = float(props.get("load.ratio.min.temp", "85.0"))

    # 3) Source Table — KDS robot-telemetry-stream
    t_env.execute_sql(
        f"""
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
    """
    )

    # 4) Sink ① — S3 alerts/ (이력)
    t_env.execute_sql(
        f"""
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
    """
    )

    # 5) Sink ② — Alert KDS (Lambda 트리거용)
    t_env.execute_sql(
        f"""
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
    """
    )

    # 6) 이상 탐지 — Z-Score (5분 OVER) + 다변량 OR
    #    OVER window로 robot_id별 5분 이동 mean/stddev 계산
    t_env.execute_sql(
        f"""
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
    """
    )

    # 7) 1분 Tumbling Window 집계 (알람 폭주 방지)
    #    Watermark 동작: WATERMARK = event_time - 10s 이므로
    #    Window [T, T+1min) 은 watermark가 T+1min 도달 시 close.
    #    → event_time ∈ [T, T+1min) 이벤트는 "최신 이벤트 시각 + 10s" 이내 도착 시 윈도우 포함.
    #    → 그 이후 도착(very-late)은 drop. 본 use case에서는 의도된 동작이며
    #      Cond1(5min OVER)이 누적이므로 다음 윈도우에서 재포착 가능.
    t_env.execute_sql(
        """
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
    """
    )

    # 8) Statement Set — 두 Sink 동시 실행
    stmt_set = t_env.create_statement_set()
    stmt_set.add_insert_sql("INSERT INTO robot_alert_s3_sink SELECT * FROM windowed")
    stmt_set.add_insert_sql("INSERT INTO robot_alert_kinesis_sink SELECT * FROM windowed")
    stmt_set.execute()


if __name__ == "__main__":
    main()

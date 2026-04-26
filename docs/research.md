# Architecture & Context Memory

## 1. Architecture Overview (Lambda Architecture)
- **Data Source:** 스마트 팩토리 로봇 텔레메트리 — Kaggle **AI4I 2020 Predictive Maintenance Dataset** 기반 시뮬레이션
  - 데이터셋: https://www.kaggle.com/datasets/stephanmatzka/predictive-maintenance-dataset-ai4i-2020
  - 컬럼 매핑: `Process temperature [K]` → `motor_temp`, `Rotational speed [rpm]` → `current_load`, `Tool wear [min]` → `battery_drain_factor`
  - `Machine failure=1` 프로필 보유 로봇은 `motor_temp > 90°C` 스파이크 확률 70% (Flink 이상탐지 시나리오 검증용)
- **Speed Layer (실시간):** Kinesis Data Streams -> Managed Flink -> Alert (Anomaly Detection)
- **Batch Layer (대용량):** Kinesis Firehose -> S3 (Bronze) -> Athena/Glue -> S3 (Silver/Gold) -> Airflow 스케줄링
- **Serving Layer (인사이트):** Amazon Bedrock을 활용한 자연어(LLM) 정비 리포트 자동 생성

## 2. Data Contract (데이터 스키마 기준)
모든 파이프라인 단계에서 아래의 스키마 명세(Data Contract)를 엄격히 준수한다.

**[Robot Telemetry Payload]**
- `robot_id` (String): 로봇 고유 식별자 (Kinesis Partition Key)
- `pos_x`, `pos_y` (Float): 위치 좌표
- `battery_level` (Integer): 배터리 잔량 (0~100)
- `current_load` (Integer): 적재 중량
- `motor_temp` (Float): 모터 온도 (핵심 이상 탐지 지표)
- `timestamp` (String): ISO8601 포맷 (예: `2026-04-25T14:00:30Z`)

## 3. Engineering Best Practices Implemented
- **Schema Evolution 대응:** JSON 데이터를 Parquet으로 변환할 때 Glue Data Catalog를 활용하여 컬럼 추가에 유연하게 대응.
- **Cost Optimization:** Athena 쿼리 비용을 최소화하기 위해 S3 경로 파티셔닝을 일/시간 단위로 쪼개어 스캔 범위 제한.
- **Data Quality:** Airflow DAG 내에 `Great Expectations` 개념을 차용하여, Silver Layer 적재 전 Null 값이나 비정상 범위(예: 온도 500도) 데이터를 필터링하는 품질 검증 Task 포함.
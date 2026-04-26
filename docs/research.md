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

## 4. 실시간 이상 탐지 — 고도화 알고리즘 (Speed Layer)
단순 임계값(`motor_temp > 90°C`)은 알람 피로도와 false positive 문제로 운영 부적합. 본 프로젝트는 **두 조건의 OR 결합**으로 정밀도 + 재현율을 동시에 확보한다 (ADR-009 참조).

### 4.1 Condition 1 — Moving Z-Score (개별 로봇 베이스라인 기반)
- 최근 **5분 OVER window**, robot_id별 `motor_temp`의 이동 평균 μ, 이동 표준편차 σ 계산
- `|motor_temp - μ| / σ > 3.0` (3-sigma rule) 시 통계적 이상
- 의도: 로봇마다 정상 운영 온도가 다름(베어링 종류·라인 환경). 개별 로봇 기준선 대비 급격한 변화만 잡아 false positive 최소화
- σ가 매우 작은 초기 구간에서의 division-by-zero는 `GREATEST(σ, ε)` 가드로 처리 (`ε=0.5`)
- Flink Table API 표현:
  ```sql
  AVG(motor_temp) OVER (
      PARTITION BY robot_id
      ORDER BY event_time
      RANGE INTERVAL '5' MINUTE PRECEDING
  ) AS motor_temp_mean
  ```

### 4.2 Condition 2 — Multivariate Correlation (부하 대비 과열)
- `motor_temp >= 85.0` AND `(motor_temp / GREATEST(current_load, 1)) > 1.8` 시 이상
- 의도: 저부하인데 온도가 높으면 → sensor drift / 냉각 시스템 이상 / 베어링 마모 의심. 단변량 임계값(`temp > 90`)으로는 검출 불가능
- 분모 0 division 가드: `GREATEST(current_load, 1)`
- AI4I 2020 데이터셋의 `OSF (Overstrain Failure)`, `HDF (Heat Dissipation Failure)` 라벨이 정확히 이 다변량 패턴을 따름

### 4.3 Sink 전략 — Window 집계 후 분기 (1분 Tumbling Window)
- 두 조건 중 하나라도 True인 레코드만 남긴 뒤, **1분 Tumbling Window**로 robot_id별 집계 (avg_temp, max_temp, alert_count) → 알람 폭주 방지
- Dual Sink:
  - `S3 alerts/` — 이력 로깅 (filesystem connector + JSON)
  - `robot-anomaly-alert-stream` (KDS) — Lambda 트리거용 (kinesis connector + JSON)
- ADR-007에 따라 SNS Native Sink는 사용하지 않음 (Flink → KDS → Lambda → SNS → Slack)

### 4.4 Threshold 외부화
- `zscore.threshold = 3.0`, `load.ratio.threshold = 1.8`, `load.ratio.min.temp = 85.0` 모두 **Flink `environment_properties`의 `property_map`** 으로 외부 주입
- 운영 데이터로 튜닝 시 코드 변경 없이 Terraform variable 수정만으로 반영

### 4.5 Watermark 설정
- `event_time AS TO_TIMESTAMP(timestamp)`, `WATERMARK FOR event_time AS event_time - INTERVAL '10' SECOND`
- 10초까지 늦게 도착하는 데이터는 윈도우에 포함, 그 이상은 drop
- Watermark 없이 Event Time 기반 Window 사용 시 state 무한 누적 → CLAUDE.md 필수 규칙
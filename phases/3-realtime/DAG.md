# Phase DAG: 3-realtime

```mermaid
graph TD
  classDef completed fill:#4CAF50,stroke:#fff,color:#fff;
  classDef pending fill:#f9f9f9,stroke:#333;
  classDef error fill:#f44336,stroke:#fff,color:#fff;
  classDef blocked fill:#FF9800,stroke:#fff,color:#fff;
  S0["0. flink-terraform"]
  class S0 pending;
  S1["1. flink-app (PyFlink)"]
  class S1 pending;
  S2["2. flink-validation"]
  class S2 pending;
  S3["3. bedrock-report-tests"]
  class S3 pending;
  S0 --> S1
  S1 --> S2
```

## 병렬성

- `S0 → S1 → S2`는 의존성 체인 (S1은 S0의 property_map 참조, S2는 S1의 순수 함수 import)
- `S3`은 독립 (`depends_on: []`) — Phase 2 산출물(`dags/robot_daily_etl.py`)만 의존하므로 S0~S2와 병렬 실행 가능
- execute.py가 자동으로 S0과 S3을 동시 시작

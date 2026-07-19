# PRISM ↔ production interface

PRISM orchestration은 데이터 저장소와 predictor를 Protocol 뒤에 둬 demo와 production이 같은 분석 흐름을 사용하게 합니다.

| 환경 | DataSource | Predictor | LLM |
|---|---|---|---|
| Demo | DuckDB (`StorageDB`) | local 6-class XGBoost | deterministic cache replay |
| Live demo | DuckDB | local 6-class XGBoost | Amazon Bedrock |
| Production | Athena Gold/Silver | SageMaker endpoint | Amazon Bedrock |

## DataSource

`src/orchestration/datasource.py`가 daily stats와 realtime telemetry의 최소 계약을 정의합니다. `get_data_source()`는 `PRISM_MODE`에 따라 구현을 선택합니다. Athena 쿼리는 최근 유효 파티션 fallback을 사용하면서 inner/outer query 모두 window predicate를 유지해 full scan을 방지합니다.

CNC telemetry는 demo 스키마에만 존재합니다. production 구현이 `NotImplementedError`를 반환하는 것은 미완성 fallback이 아니라 도메인 경계를 드러내는 의도된 동작입니다.

## Predictor

`src/orchestration/predictor.py`가 local model과 SageMaker endpoint의 공통 계약을 정의합니다. production endpoint가 배포되지 않은 경우 인프라 예외를 그대로 노출하지 않고 명시적인 unavailable 결과를 반환합니다. SageMaker 응답은 SDK/serving 차이를 고려해 JSON 배열과 CSV를 모두 처리합니다.

## LLM/cache

PRISM의 Bedrock 호출은 `src/orchestration/llm_cache.py`를 통과합니다. offline 모드에서 cache miss를 가짜 응답으로 숨기지 않고 즉시 실패시켜 데모 결정성을 보존합니다.

## Serving

FastAPI `/api/recommendation`은 production data source와 predictor 결과를 orchestration output으로 연결합니다. Streamlit demo와 production portal은 UI가 다르지만 supervisor output schema를 공유합니다.

## 검증 가능한 계약

- datasource/predictor factory와 mode routing
- Athena partition query와 result parsing
- SageMaker unavailable/error and response parsing
- cache replay hit/miss behavior
- supervisor output schema
- FastAPI recommendation response

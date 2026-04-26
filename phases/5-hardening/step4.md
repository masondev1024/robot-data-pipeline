# Step 4: hardening-tests (SageMaker train + DLQ alarm 검증)

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/src/ml/train.py` (step 3 산출물 — Athena 조회 + SageMaker XGBoost 학습)
- `/src/ml/train_entry.py` (step 3 산출물 — XGBoost entry point)
- `/tests/ml/test_predict_endpoint.py` (step 3 갱신본 — 회귀 안전망)
- `/terraform/modules/data_pipeline/cloudwatch.tf` (Firehose DLQ alarm 위치 파악)
- `/tests/conftest.py` (sys.path 패턴)
- `/plan.md` Task 5.3 — **읽기만, 수정 금지**

## 작업

step 3까지 완성된 ML 코드와 phase 1의 DLQ alarm을 단위 테스트로 검증. **모든 AWS 호출은 Mock**.

### 산출물 2종

1. `tests/ml/test_train.py` — SageMaker XGBoost 학습 파이프라인 mock 검증
2. `tests/ml/test_train_entry.py` — XGBoost entry point 순수 함수 검증

(Optional 3종: DLQ alarm SNS publish 검증은 별도 step 또는 phase 1 회귀로 분리 — 본 step에서는 skip)

### `tests/ml/test_train.py` 케이스 (최소 5건)

| # | 케이스 | 검증 |
|---|---|---|
| 1 | `fetch_training_data` Athena 호출 | mock Athena `start_query_execution` → DB=`robot_telemetry_db`, OutputLocation 끝 `/project-athena-results/` |
| 2 | SELECT 컬럼 정합성 | QUERY 문자열에 4 feature 컬럼(`avg_motor_temp`, `max_motor_temp`, `battery_drain`, `active_hours`) + `CASE WHEN max_motor_temp > 90` 패턴 모두 존재 |
| 3 | stale 컬럼 부재 | `battery_drain_rate`, `operation_ratio`, `machine_failure` 어떤 것도 QUERY에 없음 (회귀 가드) |
| 4 | `run_training_job` SageMaker estimator 인자 | mock `XGBoost` 생성자 호출 시 `entry_point="train_entry.py"`, `framework_version="1.7-1"`, `instance_type="ml.m5.large"` |
| 5 | deploy 시 endpoint name | `endpoint_name="robot-failure-predictor"`, `instance_type="ml.t2.medium"` |

### `tests/ml/test_train_entry.py` 케이스 (최소 4건)

XGBoost entry point는 SageMaker 컨테이너 내부 실행이므로 mock SM 환경변수 + tmp directory 패턴:

```python
import os
import tempfile
import pandas as pd
import pytest
from unittest.mock import patch
```

| # | 케이스 | 검증 |
|---|---|---|
| 1 | `parse_args` SM 환경변수 | `SM_MODEL_DIR`, `SM_CHANNEL_TRAIN` 둘 다 환경변수에서 읽힘 |
| 2 | feature_cols 정합성 | `feature_cols == ["avg_motor_temp", "max_motor_temp", "battery_drain", "active_hours"]` |
| 3 | DataFrame 로드 후 X/y split | tmp csv 생성 후 entry main 실행 → X.shape, y 값 검증 |
| 4 | 모델 산출물 저장 경로 | `xgboost-model` 파일이 `args.model_dir` 안에 생성되는가 |

### Mock 패턴 — 케이스 4 예시

```python
def test_train_entry_produces_model(tmp_path):
    """tmp dir에 csv 데이터 생성 후 train_entry.main 호출 시 model 파일이 생성됨."""
    train_dir = tmp_path / "train"
    model_dir = tmp_path / "model"
    train_dir.mkdir(); model_dir.mkdir()

    csv_path = train_dir / "train.csv"
    pd.DataFrame({
        "avg_motor_temp": [70, 88, 92, 60],
        "max_motor_temp": [85, 95, 110, 70],
        "battery_drain":  [10, 20, 30, 5],
        "active_hours":   [8, 8, 12, 4],
        "label":          [0, 1, 1, 0],
    }).to_csv(csv_path, index=False)

    # SM 환경변수 모킹
    with patch.dict(os.environ, {
        "SM_MODEL_DIR":     str(model_dir),
        "SM_CHANNEL_TRAIN": str(train_dir),
    }):
        # entry script가 sys.argv 파싱하므로 monkey-patch
        with patch("sys.argv", ["train_entry.py", "--num-round", "3"]):
            import importlib, train_entry
            importlib.reload(train_entry)
            train_entry.main()

    assert (model_dir / "xgboost-model").exists()
```

(테스트 실행 환경에 `xgboost` 라이브러리가 없으면 mock으로 우회. 단, `pip install xgboost` 가능하다면 실제 학습이 통과되는지가 더 강한 보증)

## Acceptance Criteria

```bash
# 1) 파일 존재
ls tests/ml/test_train.py tests/ml/test_train_entry.py

# 2) 의존성 (xgboost는 운영 학습 시 SageMaker 컨테이너에 있으므로 로컬 설치 안 돼도 케이스 1-3은 통과해야 함)
python3 -c "import xgboost" 2>&1 | grep -q "ImportError" && echo "WARN: xgboost not installed locally — case 4 may skip"

# 3) 테스트 통과
pytest tests/ml/ -v 2>&1 | tail -15
# 위 결과: train + train_entry + 기존 predict_endpoint 합쳐서 11+ PASSED 또는 skipped

# 4) 회귀 — 전체 테스트
pytest tests/ -q 2>&1 | tail -3
# 65 → 76+ PASSED 예상 (신규 11+)
```

## 검증 절차

1. 위 AC 커맨드 모두 OK.
2. 아키텍처 체크리스트:
   - test_train.py가 `train.py`의 stale 컬럼(`battery_drain_rate` 등) 부재를 회귀 가드로 검증하는가?
   - test_train_entry.py가 SageMaker 표준 환경변수 패턴(`SM_MODEL_DIR`, `SM_CHANNEL_TRAIN`)을 검증하는가?
   - 모든 boto3.client 호출이 mock 처리됐는가?
   - 회귀 — tests/ml/ 외 다른 테스트(api, lambda, etl, flink, generator)는 영향받지 않았는가?
3. `phases/5-hardening/index.json` step 4 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "tests/ml/test_train.py(SageMaker 5) + test_train_entry.py(entry point 4) — 9+ PASSED, 회귀 76+"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

### 🚨 메타 파일 보호 (반드시 준수)

- **`/plan.md` 절대 수정/덮어쓰기/삭제 금지.** 본 step의 출력 산출물은 오직 `tests/ml/test_train.py`(신규), `tests/ml/test_train_entry.py`(신규), 그리고 `phases/5-hardening/index.json`(step 4 entry만) 3종이다.
- 프로젝트 루트의 `*.md` 어떤 것도 수정하지 마라.
- 다른 step 디렉토리나 docs를 수정하지 마라.
- `src/ml/train.py`, `src/ml/train_entry.py`를 수정하지 마라 — 본 step은 검증 전용. 결함 발견 시 step `blocked` 마킹.

### 구현 규칙

- 실 SageMaker / Athena를 호출하지 마라. 이유: 비용 + flaky + 모델 미배포. 모든 boto3 호출 mock.
- xgboost 라이브러리 의존성을 강제하지 마라 (강한 가정). 이유: CI 환경에 xgboost 미설치 가능. 케이스 4는 `pytest.importorskip("xgboost")` 또는 mock으로 우회 가능.
- DLQ CloudWatch alarm 통합 테스트는 본 step에 포함하지 마라. 이유: 운영 인프라 배포 후 별도 검증. 본 step은 코드 정합성 검증만.
- 테스트 안에서 실제 XGBoost 학습 시간을 길게 두지 마라. 이유: `--num-round 3` 정도면 충분 (실제 학습 결과 정확도 검증 아닌 코드 경로 검증).

# Step 3: ml-feature-alignment (Gold DDL ↔ ML 코드 정합성 정정)

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/sql/gold_ddl.sql` (실제 컬럼: `robot_id`, `avg_motor_temp`, `max_motor_temp`, `battery_start`, `battery_end`, `battery_drain`, `active_hours`, `dt`)
- `/dags/robot_daily_etl.py` (`_silver_to_gold` 쿼리에서 INSERT하는 컬럼 확인)
- `/src/ml/train.py` (보강 대상)
- `/src/api/main.py` (`/api/predict` 엔드포인트 + `PredictRequest` 스키마 — 보강 대상)
- `/tests/ml/test_predict_endpoint.py` (보강 대상)
- `/plan.md` Task 5.2 ML feature 컬럼 정합성 — **읽기만, 수정 금지**

## 작업

기존 ML 코드(train.py + main.py /api/predict + test)는 gold DDL에 없는 컬럼(`battery_drain_rate`, `operation_ratio`, `machine_failure`)을 참조 중. **gold DDL은 source of truth로 두고 ML 코드를 정정**.

### A) `src/ml/train.py` 보강 (덮어쓰기)

**SELECT 컬럼 정정 + 라벨 룰 기반 생성:**

```python
QUERY = """
SELECT
    robot_id,
    avg_motor_temp,
    max_motor_temp,
    battery_drain,
    active_hours,
    -- 룰 기반 라벨: max_motor_temp > 90°C 인 날을 failure 양성으로 마킹
    CASE WHEN max_motor_temp > 90.0 THEN 1 ELSE 0 END AS label
FROM gold_robot_daily_stats
WHERE dt >= date_format(current_date - interval '30' day, '%Y-%m-%d')
"""
```

**Feature 컬럼 4개:** `avg_motor_temp`, `max_motor_temp`, `battery_drain`, `active_hours`. 기존 `battery_drain_rate`, `operation_ratio` 참조는 모두 제거.

XGBoost 학습 / SageMaker estimator는 그대로 유지 (입력 형식만 변경). `entry_point="train_entry.py"` 호출은 step 3-B에서 구현하는 entry 파일로 연결.

### B) `src/ml/train_entry.py` 신규 작성

SageMaker XGBoost framework가 학습 컨테이너 내부에서 호출하는 entry point. 표준 SageMaker 패턴:

```python
"""SageMaker XGBoost entry point — container 내부에서 실행되어
S3 train channel에서 데이터 읽고 XGBoost 모델을 fit한 뒤 model.tar.gz 산출."""

import argparse
import os
import pickle
import pandas as pd
import xgboost as xgb


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--num-round",  type=int,   default=100)
    p.add_argument("--max-depth",  type=int,   default=5)
    p.add_argument("--eta",        type=float, default=0.1)
    p.add_argument("--objective",  type=str,   default="binary:logistic")
    # SageMaker 표준 환경변수
    p.add_argument("--model-dir",  type=str, default=os.environ["SM_MODEL_DIR"])
    p.add_argument("--train-dir",  type=str, default=os.environ["SM_CHANNEL_TRAIN"])
    return p.parse_args()


def main():
    args = parse_args()
    # train_dir 안의 모든 csv를 로드
    csv_files = [f for f in os.listdir(args.train_dir) if f.endswith(".csv")]
    df = pd.concat([pd.read_csv(os.path.join(args.train_dir, f)) for f in csv_files])

    # 컬럼 순서: feature 4개 + label
    feature_cols = ["avg_motor_temp", "max_motor_temp", "battery_drain", "active_hours"]
    X = df[feature_cols]
    y = df["label"]

    dtrain = xgb.DMatrix(X, label=y)
    params = {
        "objective": args.objective,
        "max_depth": args.max_depth,
        "eta":       args.eta,
    }
    booster = xgb.train(params, dtrain, num_boost_round=args.num_round)

    out_path = os.path.join(args.model_dir, "xgboost-model")
    booster.save_model(out_path)


if __name__ == "__main__":
    main()
```

### C) `src/api/main.py` `/api/predict` 정정

`PredictRequest` 스키마 + endpoint 호출 본문을 4 feature로 정정:

```python
class PredictRequest(BaseModel):
    robot_id:        str
    avg_motor_temp:  float
    max_motor_temp:  float
    battery_drain:   int    # int — gold DDL 타입 일치
    active_hours:    int

@app.post("/api/predict")
@limiter.limit("20/minute")
async def predict_failure(request: Request, body: PredictRequest):
    features = f"{body.avg_motor_temp},{body.max_motor_temp},{body.battery_drain},{body.active_hours}"
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=ENDPOINT_NAME,
        ContentType="text/csv",
        Body=features,
    )
    failure_prob = float(response["Body"].read().decode())
    return {
        "robot_id": body.robot_id,
        "failure_probability": round(failure_prob, 4),
        "risk_level": "high" if failure_prob > 0.7 else "medium" if failure_prob > 0.4 else "low",
    }
```

**기존 `battery_drain_rate`, `operation_ratio` 필드는 삭제**. 다른 엔드포인트(예: `/api/chat`, `/api/status`)는 변경하지 마라.

### D) `tests/ml/test_predict_endpoint.py` 정정

기존 테스트가 옛 schema(battery_drain_rate 등)를 사용하고 있다면 새 schema로 교체. mock SageMaker invoke_endpoint 응답 패턴은 유지.

```python
# 요청 body 정정 예
body = {
    "robot_id":       "ROBOT-00001",
    "avg_motor_temp": 88.5,
    "max_motor_temp": 95.0,
    "battery_drain":  30,
    "active_hours":   8,
}
# 호출
response = client.post("/api/predict", json=body)
assert response.status_code == 200
data = response.json()
assert "failure_probability" in data
assert data["risk_level"] in ("high", "medium", "low")
```

## Acceptance Criteria

```bash
# 1) train.py 컬럼 정정
grep -q "avg_motor_temp" src/ml/train.py && echo "OK: avg_motor_temp"
grep -q "battery_drain[^_]" src/ml/train.py && echo "OK: battery_drain (not _rate)"
grep -q "active_hours" src/ml/train.py && echo "OK: active_hours"
grep -q "CASE WHEN max_motor_temp" src/ml/train.py && echo "OK: rule-based label"
! grep -q "battery_drain_rate\|operation_ratio" src/ml/train.py && echo "OK: stale columns removed"
python3 -m py_compile src/ml/train.py && echo "OK: train.py syntax"

# 2) train_entry.py 신규
ls src/ml/train_entry.py
grep -q "SM_MODEL_DIR\|SM_CHANNEL_TRAIN" src/ml/train_entry.py && echo "OK: sagemaker env vars"
grep -q "xgb.train\|xgb.DMatrix" src/ml/train_entry.py && echo "OK: xgboost calls"
python3 -c "import ast; ast.parse(open('src/ml/train_entry.py').read()); print('OK: train_entry.py parses')"

# 3) main.py /api/predict 정정
grep -q "battery_drain:" src/api/main.py && echo "OK: predict body battery_drain"
grep -q "active_hours:" src/api/main.py && echo "OK: predict body active_hours"
! grep -q "battery_drain_rate\|operation_ratio" src/api/main.py && echo "OK: stale fields removed"
python3 -m py_compile src/api/main.py && echo "OK: main.py syntax"

# 4) test 회귀
pytest tests/ml/ -v 2>&1 | tail -10
```

## 검증 절차

1. 위 AC 모두 OK + tests/ml/ 회귀 테스트 PASSED.
2. 아키텍처 체크리스트:
   - SELECT 컬럼이 모두 gold_ddl.sql 실제 컬럼인가?
   - 라벨 생성 룰이 명확한가? (`max_motor_temp > 90 → 1`)
   - PredictRequest 스키마 4 필드와 train_entry.py feature_cols 4개가 일치하는가?
   - `/api/predict` 응답 형식(`failure_probability`, `risk_level`)이 변경되지 않았는가?
3. `phases/5-hardening/index.json` step 3 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "train.py SELECT 컬럼 정정(gold DDL 일치) + 룰 라벨(max_motor_temp>90) + train_entry.py 신규 + /api/predict 4-feature schema 정정 + test 회귀"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

### 🚨 메타 파일 보호 (반드시 준수)

- **`/plan.md` 절대 수정/덮어쓰기/삭제 금지.** 본 step의 출력 산출물은 오직 `src/ml/train.py`(보강), `src/ml/train_entry.py`(신규), `src/api/main.py`(/api/predict 부분만 정정), `tests/ml/test_predict_endpoint.py`(테스트 schema 갱신), 그리고 `phases/5-hardening/index.json`(step 3 entry만) 5종이다.
- 프로젝트 루트의 `*.md` 어떤 것도 수정하지 마라.
- 다른 step 디렉토리나 docs를 수정하지 마라.
- `sql/gold_ddl.sql` / `silver_ddl.sql`을 수정하지 마라. 이유: 본 step의 결정은 "gold DDL은 source of truth, ML이 맞춘다". DDL을 손대면 phase 2 batch DAG와 회귀 발생.
- `dags/robot_daily_etl.py`를 수정하지 마라. 이유: phase 2에서 확정된 ETL 로직.

### 구현 규칙

- 라벨 룰을 `motor_temp > 90` 단일 조건으로 두지 마라. 이유: gold는 일별 집계이므로 `max_motor_temp > 90` 사용. avg는 일평균이라 90 도달이 거의 없음(단일 스파이크 보존을 위해 max 사용).
- 다른 라벨 룰(예: K-Means cluster, 업스트림 ML 라벨)을 임의 도입하지 마라. 이유: 본 결정은 단순 룰 기반 (사용자 합의). 향후 더 정교한 라벨링은 별도 PR.
- `/api/predict` 응답 schema(`failure_probability`, `risk_level`)를 변경하지 마라. 이유: 기존 클라이언트(portal.html, 향후 grafana action 등)와 호환.
- `train.py` 안의 `entry_point="train_entry.py"`, `source_dir="src/ml/"`, `framework_version="1.7-1"`을 변경하지 마라. 이유: 이미 SageMaker XGBoost 표준 패턴.
- 학습 데이터를 30일 외로 확장하지 마라. 이유: Athena 스캔 비용 통제 + 라벨이 룰 기반이라 더 많은 데이터가 정확도에 큰 영향 없음.

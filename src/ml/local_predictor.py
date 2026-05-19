"""LocalXGBoost6Class — in-process XGBoost 6-class 예지보전 모델.

본선 시연용 (PRISM Phase 3, 마커 1):
  - SageMaker / AWS 의존 없음 — 순수 로컬 in-process
  - 6-class: NONE(0) / TWF(1) / HDF(2) / PWF(3) / OSF(4) / RNF(5)
  - seed=2026 고정 → 결정성 보장
  - assets/xgb_6class.pkl 사전 학습 후 commit, 시연 시 load 만
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

# real xgboost (not the sagemaker wrapper)
import xgboost as xgb

# ── 상수 ─────────────────────────────────────────────────────────────────────

LABEL_MAP: dict[str, int] = {
    "NONE": 0,
    "TWF": 1,
    "HDF": 2,
    "PWF": 3,
    "OSF": 4,
    "RNF": 5,
}
LABEL_NAMES: list[str] = ["NONE", "TWF", "HDF", "PWF", "OSF", "RNF"]
NUM_CLASSES: int = len(LABEL_MAP)

# causal_dag feature 순서와 정합
FEATURE_COLS: list[str] = [
    "tool_age",
    "spindle_rpm",
    "coolant_temp",
    "vibration_xyz",
    "thermal_drift",
    "dimension_dev",
]

_DEFAULT_PKL = Path(__file__).parent.parent.parent / "assets" / "xgb_6class.pkl"


# ── LocalXGBoost6Class ────────────────────────────────────────────────────────

class LocalXGBoost6Class:
    """XGBoost multi:softprob 6-class 로컬 예지보전 모델.

    사용 예::

        model = LocalXGBoost6Class()
        model.fit(df, target_col="failure_type")
        model.save("assets/xgb_6class.pkl")

        loaded = LocalXGBoost6Class.load("assets/xgb_6class.pkl")
        probs = loaded.predict_proba(sample_dict)
        # {"NONE": 0.12, "TWF": 0.18, "HDF": 0.62, ...}
    """

    def __init__(self, seed: int = 2026) -> None:
        self.seed = seed
        self._model: xgb.XGBClassifier | None = None

    # ── 학습 ─────────────────────────────────────────────────────────────────

    def fit(self, df: pd.DataFrame, target_col: str = "failure_type") -> "LocalXGBoost6Class":
        """XGBoost multi:softprob 학습.

        Args:
            df: feature 컬럼 + target_col 을 포함한 DataFrame
            target_col: 6-class 정수 라벨 컬럼명 (0~5)

        Returns:
            self (chain 가능)
        """
        X = df[FEATURE_COLS].values.astype(np.float32)
        y = df[target_col].values.astype(np.int32)

        self._model = xgb.XGBClassifier(
            objective="multi:softprob",
            num_class=NUM_CLASSES,
            n_estimators=100,
            max_depth=4,
            eval_metric="mlogloss",
            random_state=self.seed,
            seed=self.seed,
            verbosity=0,
            use_label_encoder=False,
        )
        self._model.fit(X, y)
        return self

    # ── 추론 ─────────────────────────────────────────────────────────────────

    def predict_proba(
        self,
        sample: dict[str, float] | pd.Series | pd.DataFrame,
    ) -> dict[str, float]:
        """6-class softmax 확률 반환.

        Args:
            sample: feature dict / Series / single-row DataFrame

        Returns:
            {"NONE": p0, "TWF": p1, "HDF": p2, "PWF": p3, "OSF": p4, "RNF": p5}
            합 = 1.0 (softmax 보장)
        """
        if self._model is None:
            raise RuntimeError("모델이 학습되지 않았습니다. fit() 또는 load() 먼저 호출하세요.")

        if isinstance(sample, dict):
            X = np.array([[sample[f] for f in FEATURE_COLS]], dtype=np.float32)
        elif isinstance(sample, pd.Series):
            X = sample[FEATURE_COLS].values.reshape(1, -1).astype(np.float32)
        elif isinstance(sample, pd.DataFrame):
            X = sample[FEATURE_COLS].values[:1].astype(np.float32)
        else:
            raise TypeError(f"sample 타입 미지원: {type(sample)}")

        proba = self._model.predict_proba(X)[0]  # shape (6,)
        return {name: float(p) for name, p in zip(LABEL_NAMES, proba)}

    def predict_proba_timed(
        self,
        sample: dict[str, float] | pd.Series | pd.DataFrame,
    ) -> tuple[dict[str, float], float]:
        """predict_proba + 실행 시간(ms) 반환.

        Returns:
            (probs_dict, latency_ms)
        """
        t0 = time.perf_counter()
        probs = self.predict_proba(sample)
        latency_ms = (time.perf_counter() - t0) * 1000
        return probs, latency_ms

    # ── 저장 / 로드 ──────────────────────────────────────────────────────────

    def save(self, path: str | Path = _DEFAULT_PKL) -> None:
        """joblib 직렬화."""
        if self._model is None:
            raise RuntimeError("학습된 모델이 없습니다.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: str | Path = _DEFAULT_PKL) -> "LocalXGBoost6Class":
        """joblib 역직렬화."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"pkl 파일 없음: {path}")
        return joblib.load(path)


# ── 합성 학습 데이터 생성 ──────────────────────────────────────────────────────

def synthesize_training_data(n: int = 5_000, seed: int = 2026) -> pd.DataFrame:
    """6-class 라벨 합성 데이터 생성 (causal_dag feature 공간과 정합).

    라벨 분포 (AI4I 2020 근사):
        NONE  50%  (2500 rows)
        HDF   15%  ( 750 rows)
        TWF   12%  ( 600 rows)
        PWF   10%  ( 500 rows)
        OSF    8%  ( 400 rows)
        RNF    5%  ( 250 rows)

    feature causal structure (causal_dag.py 정합):
        tool_age      ~ N(0,1)
        spindle_rpm   ~ N(0,1)
        coolant_temp  ~ N(0,1)
        vibration_xyz = 0.4*tool_age + 0.6*spindle_rpm + noise
        thermal_drift = 0.7*coolant_temp + noise
        dimension_dev = 0.5*vibration_xyz + 0.5*thermal_drift + noise
    """
    rng = np.random.default_rng(seed)

    # 클래스 비율 (AI4I 2020 근사). n 가변 → 비율 기반 row 수 산정.
    ratios = {
        "NONE": 0.50,
        "HDF":  0.15,
        "TWF":  0.12,
        "PWF":  0.10,
        "OSF":  0.08,
        "RNF":  0.05,
    }
    counts = {label: max(1, int(n * r)) for label, r in ratios.items()}
    # 반올림 손실분은 NONE 으로 보정 (합 == n)
    counts["NONE"] += n - sum(counts.values())

    rows: list[dict] = []

    for label_name, cnt in counts.items():
        label_int = LABEL_MAP[label_name]

        # 클래스별 feature 분포 (anomaly 클래스는 extreme 쪽으로 편향)
        if label_name == "NONE":
            tool_age    = rng.normal(0.0, 1.0, cnt)
            spindle_rpm = rng.normal(0.0, 1.0, cnt)
            coolant_temp = rng.normal(0.0, 1.0, cnt)
        elif label_name == "HDF":   # 방열 결함 — coolant 고온
            tool_age    = rng.normal(0.0, 1.0, cnt)
            spindle_rpm = rng.normal(0.3, 1.0, cnt)
            coolant_temp = rng.normal(1.8, 0.8, cnt)   # 고온 편향
        elif label_name == "TWF":   # 공구 마모 — tool_age 높음
            tool_age    = rng.normal(2.0, 0.7, cnt)    # 마모 편향
            spindle_rpm = rng.normal(0.5, 1.0, cnt)
            coolant_temp = rng.normal(0.5, 1.0, cnt)
        elif label_name == "PWF":   # 전력 결함 — rpm 급등
            tool_age    = rng.normal(0.5, 1.0, cnt)
            spindle_rpm = rng.normal(2.0, 0.8, cnt)    # 고rpm 편향
            coolant_temp = rng.normal(0.8, 1.0, cnt)
        elif label_name == "OSF":   # 과부하 — rpm + 공구 복합
            tool_age    = rng.normal(1.5, 0.8, cnt)
            spindle_rpm = rng.normal(1.5, 0.8, cnt)
            coolant_temp = rng.normal(1.0, 0.9, cnt)
        else:                        # RNF — 전 영역 분산
            tool_age    = rng.normal(0.0, 1.5, cnt)
            spindle_rpm = rng.normal(0.0, 1.5, cnt)
            coolant_temp = rng.normal(0.0, 1.5, cnt)

        vibration_xyz = 0.4 * tool_age + 0.6 * spindle_rpm + rng.normal(0, 0.3, cnt)
        thermal_drift = 0.7 * coolant_temp + rng.normal(0, 0.3, cnt)
        dimension_dev = 0.5 * vibration_xyz + 0.5 * thermal_drift + rng.normal(0, 0.2, cnt)

        for i in range(cnt):
            rows.append({
                "tool_age":     float(tool_age[i]),
                "spindle_rpm":  float(spindle_rpm[i]),
                "coolant_temp": float(coolant_temp[i]),
                "vibration_xyz": float(vibration_xyz[i]),
                "thermal_drift": float(thermal_drift[i]),
                "dimension_dev": float(dimension_dev[i]),
                "failure_type": label_int,
            })

    df = pd.DataFrame(rows)
    # shuffle
    df = df.sample(frac=1, random_state=seed).reset_index(drop=True)
    return df


# ── 본선 시연 fault scenario (마커 1 결정론적 입력) ──────────────────────────────

DEMO_FAULT_SCENARIO: dict[str, float] = {
    # ROBOT-00018: motor_temp 92°C 상승, tool_age 누적, coolant 고온
    "tool_age":     2.1,    # 높은 마모 누적
    "spindle_rpm":  0.8,    # 약간 상승
    "coolant_temp": 1.9,    # 고온 (HDF 트리거)
    "vibration_xyz": 1.2,   # vibration 상승
    "thermal_drift": 1.4,   # thermal 상승
    "dimension_dev": 1.1,   # 치수 편차 상승
}

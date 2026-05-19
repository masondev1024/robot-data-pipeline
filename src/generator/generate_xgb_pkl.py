"""assets/xgb_6class.pkl 사전 학습 스크립트.

본선 시연 전 1회 실행 → pkl commit. 시연 시에는 load 만.

Usage:
    python src/generator/generate_xgb_pkl.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# project root 를 sys.path 에 추가
_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from src.ml.local_predictor import (
    LocalXGBoost6Class,
    DEMO_FAULT_SCENARIO,
    synthesize_training_data,
)

_PKL_PATH = _ROOT / "assets" / "xgb_6class.pkl"


def main() -> None:
    print("[generate_xgb_pkl] 합성 데이터 생성 (n=5000, seed=2026) ...")
    df = synthesize_training_data(n=5_000, seed=2026)
    print(f"  DataFrame shape: {df.shape}")
    print(f"  라벨 분포:\n{df['failure_type'].value_counts().sort_index()}")

    print("[generate_xgb_pkl] 학습 시작 ...")
    model = LocalXGBoost6Class(seed=2026)
    model.fit(df, target_col="failure_type")

    print("[generate_xgb_pkl] 추론 smoke test ...")
    probs = model.predict_proba(DEMO_FAULT_SCENARIO)
    top_class = max(probs, key=probs.get)
    print(f"  DEMO_FAULT_SCENARIO 예측: top={top_class}")
    for cls, p in probs.items():
        bar = "█" * int(p * 30)
        print(f"  {cls:4s}: {p:.3f}  {bar}")

    print(f"[generate_xgb_pkl] 저장 → {_PKL_PATH}")
    model.save(_PKL_PATH)
    print("[generate_xgb_pkl] 완료.")


if __name__ == "__main__":
    main()

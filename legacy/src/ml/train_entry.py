"""SageMaker XGBoost entry point — container 내부에서 실행되어
S3 train channel에서 데이터 읽고 XGBoost 모델을 fit한 뒤 model.tar.gz 산출.

Task 8.2: Multi-class (6 classes) — train.py 가 sample_weight 칼럼을 라벨 다음에
주입하므로 컬럼 순서는 [label, sample_weight, feat...] 이다.
"""

import argparse
import os
import pandas as pd
import xgboost as xgb


COLUMN_NAMES = [
    "label",
    "sample_weight",
    "avg_motor_temp",
    "max_motor_temp",
    "battery_drain",
    "active_hours",
    "max_temp_load_ratio",
]
FEATURE_COLS = COLUMN_NAMES[2:]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--num_round",  type=int,   default=100)
    p.add_argument("--max_depth",  type=int,   default=5)
    p.add_argument("--eta",        type=float, default=0.1)
    p.add_argument("--objective",  type=str,   default="multi:softprob")
    p.add_argument("--num_class",  type=int,   default=6)
    p.add_argument("--eval_metric", type=str,  default="mlogloss")
    # SageMaker 표준 환경변수
    p.add_argument("--model_dir",  type=str, default=os.environ.get("SM_MODEL_DIR", "/opt/ml/model"))
    p.add_argument("--train_dir",  type=str, default=os.environ.get("SM_CHANNEL_TRAIN", "/opt/ml/input/data/train"))
    return p.parse_args()


def main():
    args = parse_args()
    csv_files = [f for f in os.listdir(args.train_dir) if f.endswith(".csv")]
    df = pd.concat([
        pd.read_csv(os.path.join(args.train_dir, f), header=None, names=COLUMN_NAMES)
        for f in csv_files
    ])

    X = df[FEATURE_COLS]
    y = df["label"]
    w = df["sample_weight"]

    dtrain = xgb.DMatrix(X, label=y, weight=w)
    params = {
        "objective": args.objective,
        "num_class": args.num_class,
        "eval_metric": args.eval_metric,
        "max_depth": args.max_depth,
        "eta":       args.eta,
    }
    booster = xgb.train(params, dtrain, num_boost_round=args.num_round)

    out_path = os.path.join(args.model_dir, "xgboost-model")
    booster.save_model(out_path)


def model_fn(model_dir):
    """SageMaker inference hook — load saved booster."""
    booster = xgb.Booster()
    booster.load_model(os.path.join(model_dir, "xgboost-model"))
    return booster


def predict_fn(input_data, model):
    """SageMaker inference hook — multi:softprob 응답은 (N, num_class) 배열."""
    return model.predict(input_data)


if __name__ == "__main__":
    main()

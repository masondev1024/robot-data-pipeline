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
    p.add_argument("--model-dir",  type=str, default=os.environ.get("SM_MODEL_DIR", "/opt/ml/model"))
    p.add_argument("--train-dir",  type=str, default=os.environ.get("SM_CHANNEL_TRAIN", "/opt/ml/input/data/train"))
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

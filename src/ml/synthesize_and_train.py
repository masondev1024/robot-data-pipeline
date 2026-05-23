"""Phase 8 multi-class 합성 학습 데이터 생성 + train.py run_training_job/deploy 재사용.

Gold 의 dominant_failure_type 가 1450 rows 전부 NULL 인 상황(ETL 미반영)에서
demo-day 시연용으로 6 클래스 분포 데이터를 합성해 multi:softprob 모델을 학습/배포한다.
실제 Gold 자연 분포가 아니라는 점은 발표 시 명시 필수 (plan.md demo-day-2 entry).
"""
import os
import random
import uuid

from src.common.aws import get_client
from src.ml.train import (
    MODEL_PREFIX,
    S3_BUCKET,
    LABEL_MAP,
    _cleanup_existing_endpoint,
    run_training_job,
)

random.seed(42)

# 클래스별 합성 분포 — AI4I 2020 + generator OVERHEATED/STUCK 패턴 모방.
# 각 feature 의 (low, high) 균등분포 범위.
CLASS_PROFILES = {
    "NONE": {
        "count": 600,
        "avg_motor_temp": (65, 80),
        "max_motor_temp": (75, 88),
        "battery_drain": (15, 50),
        "active_hours": (6, 14),
        "max_temp_load_ratio": (0.5, 2.2),
    },
    "HDF": {  # 방열 결함 — 고온 + 높은 ratio
        "count": 100,
        "avg_motor_temp": (85, 95),
        "max_motor_temp": (95, 115),
        "battery_drain": (40, 70),
        "active_hours": (10, 18),
        "max_temp_load_ratio": (2.5, 4.0),
    },
    "PWF": {  # 전력 결함 — 배터리 급강하
        "count": 80,
        "avg_motor_temp": (75, 88),
        "max_motor_temp": (85, 100),
        "battery_drain": (65, 95),
        "active_hours": (8, 16),
        "max_temp_load_ratio": (1.8, 3.0),
    },
    "OSF": {  # 과부하 — ratio 매우 높음
        "count": 80,
        "avg_motor_temp": (80, 92),
        "max_motor_temp": (90, 105),
        "battery_drain": (50, 75),
        "active_hours": (10, 20),
        "max_temp_load_ratio": (3.0, 5.0),
    },
    "TWF": {  # 공구 마모 — active_hours 높음
        "count": 70,
        "avg_motor_temp": (78, 90),
        "max_motor_temp": (88, 100),
        "battery_drain": (45, 70),
        "active_hours": (18, 28),
        "max_temp_load_ratio": (2.0, 3.2),
    },
    "RNF": {  # 랜덤 결함 — 전 영역 분산
        "count": 70,
        "avg_motor_temp": (70, 95),
        "max_motor_temp": (80, 110),
        "battery_drain": (25, 80),
        "active_hours": (8, 22),
        "max_temp_load_ratio": (1.0, 4.5),
    },
}

MINORITY_WEIGHT = 50.0


def synthesize_csv() -> str:
    rows = []
    for ftype, profile in CLASS_PROFILES.items():
        label = LABEL_MAP[ftype]
        weight = 1.0 if ftype == "NONE" else MINORITY_WEIGHT
        for _ in range(profile["count"]):
            rows.append((
                label,
                weight,
                round(random.uniform(*profile["avg_motor_temp"]), 2),
                round(random.uniform(*profile["max_motor_temp"]), 2),
                int(random.uniform(*profile["battery_drain"])),
                int(random.uniform(*profile["active_hours"])),
                round(random.uniform(*profile["max_temp_load_ratio"]), 3),
            ))
    random.shuffle(rows)
    return "\n".join(",".join(str(c) for c in r) for r in rows) + "\n"


def main():
    role_arn = os.environ["SAGEMAKER_ROLE_ARN"]
    csv_body = synthesize_csv()

    train_id = uuid.uuid4().hex[:16]
    train_key = f"{MODEL_PREFIX}/train/synthetic-{train_id}.csv"
    s3 = get_client("s3")
    s3.put_object(Bucket=S3_BUCKET, Key=train_key, Body=csv_body.encode("utf-8"))
    train_uri = f"s3://{S3_BUCKET}/{train_key}"
    print(f"[synthesize] uploaded {len(csv_body)} bytes → {train_uri}")

    estimator = run_training_job(train_uri, role_arn)
    _cleanup_existing_endpoint("robot-failure-predictor")
    estimator.deploy(
        initial_instance_count=1,
        instance_type="ml.t2.medium",
        endpoint_name="robot-failure-predictor",
    )
    print("[deploy] robot-failure-predictor InService")


if __name__ == "__main__":
    main()

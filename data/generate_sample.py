"""
AI4I 2020 Predictive Maintenance 포맷과 동일한 합성 샘플 CSV를 생성한다.
리포지토리에 포함되어 로컬 개발 및 CI 테스트에 사용된다.

실행:
    python3 data/generate_sample.py
출력:
    data/seed_data_sample.csv (200행)
"""

import csv
import random
from pathlib import Path

random.seed(42)

ROWS = 200
OUTPUT = Path(__file__).parent / "seed_data_sample.csv"

HEADERS = [
    "UDI", "Product ID", "Type",
    "Air temperature [K]", "Process temperature [K]",
    "Rotational speed [rpm]", "Torque [Nm]", "Tool wear [min]",
    "Machine failure", "TWF", "HDF", "PWF", "OSF", "RNF",
]


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def gauss(mu, sigma, lo=None, hi=None):
    v = random.gauss(mu, sigma)
    if lo is not None or hi is not None:
        v = clamp(v, lo if lo is not None else -1e9, hi if hi is not None else 1e9)
    return v


rows = []
failure_count = 0

for i in range(1, ROWS + 1):
    product_type = random.choice(["L", "L", "M", "M", "H"])
    air_k        = round(gauss(300, 2, 295, 305), 1)
    proc_k       = round(air_k + gauss(10, 0.5, 9, 11), 1)
    rpm          = round(gauss(1500, 200, 1168, 2886), 1)
    torque       = round(gauss(40, 10, 3, 77), 1)
    wear         = round(random.uniform(0, 250), 1)

    # 5% 고장 확률
    failure = 1 if (random.random() < 0.05) else 0
    failure_count += failure
    twf = failure if failure and random.random() < 0.4 else 0
    hdf = failure if failure and not twf and random.random() < 0.5 else 0
    pwf = failure if failure and not twf and not hdf else 0
    osf = 0
    rnf = 0

    rows.append([
        i, f"M{i:05d}", product_type,
        air_k, proc_k, rpm, torque, wear,
        failure, twf, hdf, pwf, osf, rnf,
    ])

with open(OUTPUT, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(HEADERS)
    writer.writerows(rows)

print(f"생성 완료: {OUTPUT}")
print(f"  총 {ROWS}행 / 고장 프로필: {failure_count}행 ({failure_count/ROWS*100:.1f}%)")
print(f"  헤더: {HEADERS}")

# Step 4: generator-app

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/research.md`
- `/terraform/modules/data_pipeline/kinesis.tf`

## 작업

두 가지를 작성하라: **① Seed CSV 샘플 파일**, **② Generator 앱**

---

### ① `data/seed_data_sample.csv` (200행 합성 데이터)

AI4I 2020 Predictive Maintenance Dataset 포맷과 동일한 헤더를 가진 합성 CSV를 생성하라.
이 파일은 리포지토리에 커밋되어 로컬 테스트에 사용된다.

```
UDI,Product ID,Type,Air temperature [K],Process temperature [K],Rotational speed [rpm],Torque [Nm],Tool wear [min],Machine failure,TWF,HDF,PWF,OSF,RNF
```

행 생성 규칙:
- `UDI`: 1~200
- `Product ID`: `M{UDI:05d}` (예: M00001)
- `Type`: L/M/H 중 하나 (각 1/3 비율)
- `Air temperature [K]`: 295~305 K (정규분포)
- `Process temperature [K]`: 305~315 K (Air temp + 9~11 K)
- `Rotational speed [rpm]`: 1,200~2,800 (정규분포, μ=1,500)
- `Torque [Nm]`: 3~77 (정규분포, μ=40)
- `Tool wear [min]`: 0~250 (균등분포)
- `Machine failure`: 0이 95%, 1이 5% (TWF/HDF/PWF/OSF/RNF 중 하나도 1)

Python 스크립트(`data/generate_sample.py`)로 생성 후 CSV로 저장하라:
```python
# data/generate_sample.py — 실행하면 seed_data_sample.csv 생성
import csv, random, math

random.seed(42)
rows = []
for i in range(1, 201):
    air_k  = random.gauss(300, 2)
    proc_k = air_k + random.uniform(9, 11)
    rpm    = max(1168, min(2886, random.gauss(1500, 200)))
    torque = max(3, min(77, random.gauss(40, 10)))
    wear   = random.uniform(0, 250)
    failure = 1 if random.random() < 0.05 else 0
    rows.append([i, f"M{i:05d}", random.choice(["L","M","H"]),
                 round(air_k,1), round(proc_k,1), round(rpm,1),
                 round(torque,1), round(wear,1), failure,
                 failure, 0, 0, 0, 0])

with open("data/seed_data_sample.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["UDI","Product ID","Type","Air temperature [K]",
                "Process temperature [K]","Rotational speed [rpm]",
                "Torque [Nm]","Tool wear [min]","Machine failure",
                "TWF","HDF","PWF","OSF","RNF"])
    w.writerows(rows)
print("생성 완료: data/seed_data_sample.csv")
```

`data/generate_sample.py`를 실행하여 CSV를 생성한 뒤 리포지토리에 커밋하라.

---

### ② `src/generator/app.py`

**asyncio 기반 10,000대 동시 시뮬레이션 + put_records 배치 전송**

#### 모듈 구조

```python
# src/generator/app.py

import asyncio, csv, json, os, random, math
from datetime import datetime, timezone
from pathlib import Path
import boto3

# ── 1. Seed CSV 로딩 ──────────────────────────────────────────

def load_profiles(csv_path: str, robot_count: int) -> list[dict]:
    """
    AI4I 2020 CSV를 읽어 robot_count개 로봇 프로필을 반환한다.
    CSV 행 수 < robot_count이면 행을 순환(cycle)한다.

    컬럼 매핑:
      Process temperature [K] → motor_temp_base  (K-273.15, clamp 60~100°C)
      Rotational speed [rpm]  → load_base         (1168~2886 → 0~100 정규화)
      Tool wear [min]         → drain_factor       (0~250 → 0.1~3.0)
      Machine failure         → is_faulty          (True면 스파이크 확률 70%)
    """
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))

    profiles = []
    for i in range(robot_count):
        r = rows[i % len(rows)]
        proc_k  = float(r["Process temperature [K]"])
        rpm     = float(r["Rotational speed [rpm]"])
        wear    = float(r["Tool wear [min]"])
        failure = int(r["Machine failure"])

        motor_base  = min(100.0, max(60.0, proc_k - 273.15 + 30))
        load_base   = int(min(100, max(0, (rpm - 1168) / (2886 - 1168) * 100)))
        drain       = min(3.0, max(0.1, wear / 100))

        # 공장 그리드 좌표 (균등 배치)
        grid_x = 37.4 + (i % 100) * 0.003
        grid_y = 126.8 + (i // 100) * 0.004

        profiles.append({
            "robot_id":        f"ROBOT-{i+1:05d}",
            "pos_x":           round(grid_x, 6),
            "pos_y":           round(grid_y, 6),
            "motor_temp_base": motor_base,
            "load_base":       load_base,
            "drain_factor":    drain,
            "is_faulty":       bool(failure),
            "battery":         random.randint(50, 100),
        })
    return profiles


# ── 2. 로봇 시뮬레이터 (1 coroutine = 1 로봇) ──────────────────

async def simulate_robot(profile: dict, queue: asyncio.Queue) -> None:
    """초당 1건 센서 레코드를 생성하여 queue에 넣는다. 무한 루프."""
    battery = profile["battery"]
    drift   = 0.0  # 점진적 온도 드리프트

    while True:
        # motor_temp: 베이스 ± 가우시안 노이즈 + 드리프트
        noise = random.gauss(0, 2)
        spike = 0.0
        if profile["is_faulty"] and random.random() < 0.05:
            spike = random.uniform(91, 99) - profile["motor_temp_base"]
        drift = drift * 0.99 + random.gauss(0, 0.1)  # 천천히 변화
        motor_temp = round(
            min(110.0, max(55.0,
                profile["motor_temp_base"] + noise + drift + spike)), 2)

        # battery: drain_factor 기반 감소, 0 도달 시 재충전
        battery -= profile["drain_factor"] * random.uniform(0.01, 0.05)
        if battery <= 0:
            battery = round(random.uniform(80, 100), 1)

        # current_load: RPM 베이스 ± 노이즈
        load = int(min(100, max(0,
            profile["load_base"] + random.gauss(0, 5))))

        record = {
            "robot_id":     profile["robot_id"],
            "pos_x":        profile["pos_x"] + random.uniform(-0.0001, 0.0001),
            "pos_y":        profile["pos_y"] + random.uniform(-0.0001, 0.0001),
            "battery_level":int(max(0, min(100, battery))),
            "current_load": load,
            "motor_temp":   motor_temp,
            "timestamp":    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        await queue.put(record)
        await asyncio.sleep(1.0)


# ── 3. 배치 전송 (put_records 500건) ───────────────────────────

async def batch_sender(queue: asyncio.Queue,
                        stream_name: str,
                        kinesis_client) -> None:
    """
    queue에서 최대 500건씩 꺼내 put_records 호출.
    50ms 간격 = 초당 최대 20회 배치 → 10,000 rec/sec 처리 가능.
    """
    loop = asyncio.get_event_loop()
    while True:
        batch = []
        while len(batch) < 500:
            try:
                record = queue.get_nowait()
                batch.append({
                    "Data":         json.dumps(record).encode(),
                    "PartitionKey": record["robot_id"],
                })
            except asyncio.QueueEmpty:
                break

        if batch:
            await loop.run_in_executor(
                None,
                lambda b=batch: kinesis_client.put_records(
                    StreamName=stream_name, Records=b),
            )

        await asyncio.sleep(0.05)


# ── 4. 진입점 ───────────────────────────────────────────────────

async def main() -> None:
    robot_count = int(os.environ.get("ROBOT_COUNT", "10000"))
    stream_name = os.environ["KINESIS_STREAM_NAME"]
    csv_path    = os.environ.get("SEED_CSV_PATH", "data/seed_data_sample.csv")

    print(f"Loading profiles from {csv_path} for {robot_count} robots...")
    profiles = load_profiles(csv_path, robot_count)

    kinesis = boto3.client("kinesis", region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-2"))
    queue   = asyncio.Queue(maxsize=robot_count * 2)

    tasks = [asyncio.create_task(simulate_robot(p, queue)) for p in profiles]
    tasks += [asyncio.create_task(batch_sender(queue, stream_name, kinesis))]

    print(f"Started {len(profiles)} robot simulators. Streaming to {stream_name}...")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
```

### `src/generator/requirements.txt`
```
boto3
```

## Acceptance Criteria

```bash
# 1. CSV 생성 스크립트 실행
python3 data/generate_sample.py
test -f data/seed_data_sample.csv && echo "OK: seed CSV exists"
python3 -c "
import csv
rows = list(csv.DictReader(open('data/seed_data_sample.csv')))
assert len(rows) == 200, f'Expected 200 rows, got {len(rows)}'
assert 'Process temperature [K]' in rows[0], 'Missing column'
assert 'Machine failure' in rows[0], 'Missing column'
print(f'OK: {len(rows)} rows, columns: {list(rows[0].keys())}')
"

# 2. Generator 구문 검사
python3 -m py_compile src/generator/app.py

# 3. 핵심 함수 존재 확인
python3 -c "
import ast
tree = ast.parse(open('src/generator/app.py').read())
fn = [n.name for n in ast.walk(tree)
      if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))]
for name in ['load_profiles', 'simulate_robot', 'batch_sender', 'main']:
    assert name in fn, f'{name} missing'
print('OK: all functions found:', fn)
"

# 4. DDAREUNGI_API_KEY 참조가 없는지 확인
grep -rn "ddareungi\|따릉이\|DDAREUNGI" src/generator/app.py && echo "FAIL: 따릉이 참조 발견" || echo "OK: no 따릉이 reference"
```

## 검증 절차

1. 위 AC 커맨드를 모두 실행한다.
2. 아키텍처 체크리스트:
   - `seed_data_sample.csv` 파일이 200행, AI4I 2020 포맷인가?
   - `load_profiles()`이 CSV를 읽고 프로필을 생성하는가?
   - `Machine failure=1` 프로필의 로봇에 스파이크 로직이 있는가?
   - `simulate_robot()`이 `asyncio` 코루틴인가?
   - `batch_sender()`가 `put_records` 500건 배치를 사용하는가?
   - `SEED_CSV_PATH`, `ROBOT_COUNT`, `KINESIS_STREAM_NAME` 환경변수에서 읽는가?
   - 코드에 AWS 자격증명 하드코딩이 없는가?
3. `phases/1-ingestion/index.json` step 4 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "data/seed_data_sample.csv(AI4I 포맷 200행) + src/generator/app.py(asyncio 10,000로봇, put_records 배치, failure 프로필 스파이크 로직)"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- 따릉이 API를 호출하는 코드를 작성하지 마라. 이유: CSV Seed 방식으로 교체됨
- `put_record()`(단건)를 루프로 호출하지 마라. 이유: 반드시 `put_records` 배치(최대 500건)
- `threading`으로 구현하지 마라. 이유: 10,000 스레드는 메모리 한계. `asyncio` 코루틴 사용
- `seed_data_sample.csv`를 실제 Kaggle 전체 데이터(10,000행 이상)로 커밋하지 마라. 이유: 리포지토리 크기 증가. 전체 데이터는 `data/seed_data.csv`에 로컬 배치

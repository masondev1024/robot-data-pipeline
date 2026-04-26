# Step 7: generator-tests

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/src/generator/app.py`
- `/data/seed_data_sample.csv`

## 작업

`tests/generator/` 디렉토리를 생성하고 pytest 단위 테스트를 작성하라.

---

### `tests/generator/__init__.py`
빈 파일.

### `tests/generator/test_generator.py`

```python
"""
Generator 단위 테스트.
실제 Kinesis/AWS 호출 없이 로직만 검증한다.
"""
import csv
import sys
import os
import pytest

# src/generator를 import 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src/generator'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from app import load_profiles


# ── 픽스처 ──────────────────────────────────────────────────────

SEED_CSV = os.path.join(os.path.dirname(__file__), '../../data/seed_data_sample.csv')


# ── 1. load_profiles 테스트 ──────────────────────────────────────

class TestLoadProfiles:
    def test_returns_correct_count(self):
        """ROBOT_COUNT개 프로필을 반환한다."""
        profiles = load_profiles(SEED_CSV, 100)
        assert len(profiles) == 100

    def test_cycles_when_count_exceeds_csv(self):
        """CSV 행 수(200)보다 robot_count가 크면 순환한다."""
        profiles = load_profiles(SEED_CSV, 300)
        assert len(profiles) == 300
        # 순환 확인: 프로필 0과 프로필 200는 같은 robot_id가 아닌 다른 ID
        assert profiles[0]["robot_id"] == "ROBOT-00001"
        assert profiles[200]["robot_id"] == "ROBOT-00201"

    def test_profile_schema(self):
        """각 프로필이 필수 필드를 모두 갖는다."""
        profiles = load_profiles(SEED_CSV, 1)
        p = profiles[0]
        required = {"robot_id", "pos_x", "pos_y", "motor_temp_base",
                    "load_base", "drain_factor", "is_faulty", "battery"}
        assert required.issubset(p.keys()), f"Missing fields: {required - p.keys()}"

    def test_robot_id_format(self):
        """robot_id가 ROBOT-XXXXX 형식(5자리 패딩)이다."""
        profiles = load_profiles(SEED_CSV, 10)
        for p in profiles:
            assert p["robot_id"].startswith("ROBOT-"), f"Bad id: {p['robot_id']}"
            suffix = p["robot_id"][6:]
            assert len(suffix) == 5 and suffix.isdigit(), f"Bad suffix: {suffix}"

    def test_motor_temp_base_range(self):
        """motor_temp_base가 60~100°C 범위내이다."""
        profiles = load_profiles(SEED_CSV, 200)
        for p in profiles:
            assert 60.0 <= p["motor_temp_base"] <= 100.0, \
                f"motor_temp_base out of range: {p['motor_temp_base']}"

    def test_load_base_range(self):
        """load_base가 0~100 범위내이다."""
        profiles = load_profiles(SEED_CSV, 200)
        for p in profiles:
            assert 0 <= p["load_base"] <= 100, \
                f"load_base out of range: {p['load_base']}"

    def test_faulty_robots_exist(self):
        """is_faulty=True인 로봇이 1대 이상 있다 (5% 비율)."""
        profiles = load_profiles(SEED_CSV, 200)
        faulty = [p for p in profiles if p["is_faulty"]]
        assert len(faulty) > 0, "No faulty robots found in 200 profiles"


# ── 2. 데이터 스키마 검증 ─────────────────────────────────────────

class TestSeedCSVSchema:
    def test_csv_has_required_columns(self):
        """seed_data_sample.csv에 AI4I 2020 필수 컬럼이 존재한다."""
        with open(SEED_CSV, newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames

        required_columns = [
            "Process temperature [K]",
            "Rotational speed [rpm]",
            "Tool wear [min]",
            "Machine failure",
        ]
        for col in required_columns:
            assert col in headers, f"Missing column: {col}"

    def test_csv_has_200_rows(self):
        """seed_data_sample.csv가 200행이다."""
        with open(SEED_CSV, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 200, f"Expected 200 rows, got {len(rows)}"


# ── 3. 함수 존재 확인 ────────────────────────────────────────────

class TestFunctionSignatures:
    def test_required_functions_exist(self):
        """app.py에 필수 함수 4개가 모두 존재한다."""
        import ast
        app_path = os.path.join(os.path.dirname(__file__), '../../src/generator/app.py')
        with open(app_path) as f:
            tree = ast.parse(f.read())

        fn_names = {n.name for n in ast.walk(tree)
                    if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))}

        for name in ["load_profiles", "simulate_robot", "batch_sender", "main"]:
            assert name in fn_names, f"Function '{name}' not found in app.py"

    def test_no_ddareungi_reference(self):
        """app.py에 따릉이 관련 코드가 없다."""
        app_path = os.path.join(os.path.dirname(__file__), '../../src/generator/app.py')
        content = open(app_path).read().lower()
        for keyword in ["ddareungi", "따릉이", "bike_api", "openapi.seoul"]:
            assert keyword not in content, f"Found forbidden reference: {keyword}"
```

### `tests/conftest.py` (루트 레벨, 없으면 생성)

```python
# pytest configuration — 특별한 설정 없음
```

---

## Acceptance Criteria

```bash
# 의존성 확인
python3 -m py_compile src/generator/app.py

# 테스트 실행
python3 -m pytest tests/generator/ -v --tb=short

# 통과 기준: 9개 테스트 모두 PASSED
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - 실제 Kinesis/AWS API를 호출하지 않는가? (순수 로컬 단위 테스트)
   - `load_profiles()` 결과 스키마 검증이 있는가?
   - CSV 컬럼 존재 확인이 있는가?
   - ROBOT_COUNT 순환 로직 테스트가 있는가?
3. `phases/1-ingestion/index.json` step 7 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "tests/generator/test_generator.py: 9개 테스트(load_profiles 7개+CSV스키마 2개) pytest 통과"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- 실제 AWS API를 호출하는 통합 테스트를 이 step에 포함하지 마라. 이유: CI 환경에 AWS 자격증명이 없다
- `moto` 없이 boto3를 직접 mocking하지 마라. 이유: load_profiles는 로컬 로직만 테스트하면 충분하다

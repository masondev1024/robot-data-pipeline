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
        """id_range 만큼 프로필을 반환한다."""
        profiles = load_profiles(SEED_CSV, (0, 100))
        assert len(profiles) == 100

    def test_cycles_when_count_exceeds_csv(self):
        """CSV 행 수(200)보다 id_range 가 크면 순환한다."""
        profiles = load_profiles(SEED_CSV, (0, 300))
        assert len(profiles) == 300
        # 순환 확인: 프로필 0과 프로필 200는 같은 robot_id가 아닌 다른 ID
        assert profiles[0]["robot_id"] == "ROBOT-00001"
        assert profiles[200]["robot_id"] == "ROBOT-00201"

    def test_id_range_offset_slicing(self):
        """StatefulSet ordinal 기반 슬라이싱: (300, 400) → ROBOT-00301~ROBOT-00400."""
        profiles = load_profiles(SEED_CSV, (300, 400))
        assert len(profiles) == 100
        assert profiles[0]["robot_id"] == "ROBOT-00301"
        assert profiles[-1]["robot_id"] == "ROBOT-00400"

    def test_profile_schema(self):
        """각 프로필이 필수 필드를 모두 갖는다."""
        profiles = load_profiles(SEED_CSV, (0, 1))
        p = profiles[0]
        required = {"robot_id", "pos_x", "pos_y", "motor_temp_base",
                    "load_base", "drain_factor", "is_faulty", "battery"}
        assert required.issubset(p.keys()), f"Missing fields: {required - p.keys()}"

    def test_robot_id_format(self):
        """robot_id가 ROBOT-XXXXX 형식(5자리 패딩)이다."""
        profiles = load_profiles(SEED_CSV, (0, 10))
        for p in profiles:
            assert p["robot_id"].startswith("ROBOT-"), f"Bad id: {p['robot_id']}"
            suffix = p["robot_id"][6:]
            assert len(suffix) == 5 and suffix.isdigit(), f"Bad suffix: {suffix}"

    def test_motor_temp_base_range(self):
        """motor_temp_base가 60~100°C 범위내이다."""
        profiles = load_profiles(SEED_CSV, (0, 200))
        for p in profiles:
            assert 60.0 <= p["motor_temp_base"] <= 100.0, \
                f"motor_temp_base out of range: {p['motor_temp_base']}"

    def test_load_base_range(self):
        """load_base가 0~100 범위내이다."""
        profiles = load_profiles(SEED_CSV, (0, 200))
        for p in profiles:
            assert 0 <= p["load_base"] <= 100, \
                f"load_base out of range: {p['load_base']}"

    def test_faulty_robots_exist(self):
        """is_faulty=True인 로봇이 1대 이상 있다 (5% 비율)."""
        profiles = load_profiles(SEED_CSV, (0, 200))
        faulty = [p for p in profiles if p["is_faulty"]]
        assert len(faulty) > 0, "No faulty robots found in 200 profiles"


class TestResolveRobotIdRange:
    def test_pod_zero_first_slice(self, monkeypatch):
        """generator-0 → (0, 100) for total=1000, replicas=10."""
        from app import _resolve_robot_id_range
        monkeypatch.setenv("POD_NAME", "robot-telemetry-generator-0")
        monkeypatch.setenv("TOTAL_ROBOTS", "1000")
        monkeypatch.setenv("POD_TOTAL_REPLICAS", "10")
        assert _resolve_robot_id_range() == (0, 100)

    def test_pod_three_third_slice(self, monkeypatch):
        """generator-3 → (300, 400)."""
        from app import _resolve_robot_id_range
        monkeypatch.setenv("POD_NAME", "robot-telemetry-generator-3")
        monkeypatch.setenv("TOTAL_ROBOTS", "1000")
        monkeypatch.setenv("POD_TOTAL_REPLICAS", "10")
        assert _resolve_robot_id_range() == (300, 400)

    def test_last_pod_clipped_to_total(self, monkeypatch):
        """generator-9 with total=1000 replicas=10 → (900, 1000) — 끝점 clip."""
        from app import _resolve_robot_id_range
        monkeypatch.setenv("POD_NAME", "robot-telemetry-generator-9")
        monkeypatch.setenv("TOTAL_ROBOTS", "1000")
        monkeypatch.setenv("POD_TOTAL_REPLICAS", "10")
        assert _resolve_robot_id_range() == (900, 1000)

    def test_uneven_split_ceil(self, monkeypatch):
        """1000 / 7 = 142.86 → ceil(143) per pod, 마지막 pod 은 142 담당."""
        from app import _resolve_robot_id_range
        monkeypatch.setenv("TOTAL_ROBOTS", "1000")
        monkeypatch.setenv("POD_TOTAL_REPLICAS", "7")
        # pod-0: (0, 143), pod-6: (858, 1000)
        monkeypatch.setenv("POD_NAME", "generator-0")
        assert _resolve_robot_id_range() == (0, 143)
        monkeypatch.setenv("POD_NAME", "generator-6")
        assert _resolve_robot_id_range() == (858, 1000)


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

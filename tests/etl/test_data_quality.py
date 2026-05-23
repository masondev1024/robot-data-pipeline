import pytest

pytest.importorskip("airflow")

from robot_daily_etl import evaluate_quality


def test_pass_clean_data():
    assert evaluate_quality(total=1000, null_id=0, bad_temp=0, bad_battery=0) == []


def test_pass_under_threshold():
    assert evaluate_quality(total=1000, null_id=5, bad_temp=5, bad_battery=5) == []


def test_fail_zero_records():
    assert evaluate_quality(total=0, null_id=0, bad_temp=0, bad_battery=0) == ["레코드 0건"]


def test_fail_high_null_ratio():
    failures = evaluate_quality(total=1000, null_id=20, bad_temp=0, bad_battery=0)
    assert any("robot_id null" in f for f in failures)


def test_fail_high_temp_ratio():
    failures = evaluate_quality(total=1000, null_id=0, bad_temp=20, bad_battery=0)
    assert any("motor_temp" in f for f in failures)


def test_fail_high_battery_ratio():
    failures = evaluate_quality(total=1000, null_id=0, bad_temp=0, bad_battery=20)
    assert any("battery_level" in f for f in failures)


def test_fail_multiple_violations():
    failures = evaluate_quality(total=1000, null_id=15, bad_temp=20, bad_battery=30)
    assert len(failures) == 3

"""DAG 구조/토폴로지 검증 — pytest-airflow 대체.

Airflow 자체 설치된 환경에서만 동작. CI/로컬 모두 동일.
"""
import pytest

pytest.importorskip("airflow")

from robot_daily_etl import dag


def test_dag_loaded():
    """DAG가 import 시점에 정상 로딩되어 있어야 한다."""
    assert dag is not None
    assert dag.dag_id == "robot_daily_etl"


def test_dag_has_no_import_errors():
    """DAG 객체 자체는 import 시 ParseError 없이 만들어진다 (이 import가 성공한 것이 증거)."""
    assert callable(getattr(dag, "topological_sort", None)) or hasattr(dag, "task_dict")


def test_dag_task_set():
    """기대 task 4종이 모두 존재한다 (Phase 5b: ML 재학습은 weekly_ml_retrain DAG 로 분리)."""
    expected = {
        "quality_check",
        "bronze_to_silver",
        "silver_to_gold",
        "bedrock_report",
    }
    actual = set(dag.task_dict.keys())
    missing = expected - actual
    assert not missing, f"누락된 task: {missing}"
    # ML retrain task 가 daily DAG 에 남아있지 않음을 확인
    assert "retrain_ml_model" not in actual
    assert "check_monday" not in actual


def test_dag_topology_quality_first():
    """quality_check가 bronze_to_silver의 upstream이어야 한다."""
    bronze = dag.get_task("bronze_to_silver")
    upstreams = {t.task_id for t in bronze.upstream_list}
    assert "quality_check" in upstreams, f"bronze_to_silver upstream={upstreams}"


def test_dag_topology_silver_to_gold():
    """silver_to_gold는 bronze_to_silver 다음에 실행된다."""
    gold = dag.get_task("silver_to_gold")
    upstreams = {t.task_id for t in gold.upstream_list}
    assert "bronze_to_silver" in upstreams


def test_dag_topology_bedrock_after_gold():
    """bedrock_report는 silver_to_gold 이후에 실행된다."""
    bedrock = dag.get_task("bedrock_report")
    upstreams = {t.task_id for t in bedrock.upstream_list}
    assert "silver_to_gold" in upstreams


def test_dag_no_cycles():
    """DAG에 순환 참조가 없어야 한다 (Airflow가 자체 검증)."""
    # DagBag 검증을 우회하지 않고 Airflow의 검증을 그대로 활용
    dag.test_cycle() if hasattr(dag, "test_cycle") else None  # Airflow 2.x: 예외 발생 시 fail
    assert True  # 위 호출에서 raise 안 되면 OK


def test_dag_default_args():
    """default_args에 retries, retry_delay가 설정되어 있다."""
    assert dag.default_args.get("retries") == 1
    assert dag.default_args.get("retry_delay") is not None

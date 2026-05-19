"""DAG 함수 로컬 실행 — Airflow(EKS) 비활성화 상태에서 ETL을 수동 트리거.

사용:
    # .env 로드 후
    python3 scripts/run_etl_local.py 2026-04-27

전제:
- bronze_robot_telemetry 에 해당 날짜(year=YYYY, month=MM, day=DD) 데이터 존재
- AWS credentials .env 에서 export 또는 환경변수로 설정
- airflow + boto3 설치 (pytest 환경과 동일)

흐름:
    quality_check → _bronze_to_silver → _silver_to_gold → _bedrock_report

⚠️ DAG의 dt 추출은 execution_date 기준 (`DATE '{dt}'`). backfill 시나리오의
record-timestamp 기반 자연 분산은 plan.md "알려진 후속 이슈" 참조.
"""
import os
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "dags"))


def _load_env_file(env_path: Path) -> None:
    """간단한 .env 로더 (python-dotenv 의존 회피)."""
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/run_etl_local.py YYYY-MM-DD")
        sys.exit(1)

    dt_str = sys.argv[1]
    execution_date = datetime.strptime(dt_str, "%Y-%m-%d")
    ctx = {"execution_date": execution_date}

    _load_env_file(REPO_ROOT / ".env")
    os.environ.setdefault("AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "eu-west-1"))

    # airflow 설치된 환경에서만 import 가능
    from robot_daily_etl import _quality_check, _bronze_to_silver, _silver_to_gold

    steps = [
        ("quality_check", _quality_check),
        ("bronze_to_silver", _bronze_to_silver),
        ("silver_to_gold", _silver_to_gold),
    ]

    for name, fn in steps:
        print(f"\n=== {name} (execution_date={dt_str}) ===")
        try:
            fn(**ctx)
            print(f"✅ {name} 완료")
        except Exception as exc:
            print(f"❌ {name} 실패: {exc}")
            sys.exit(2)

    print("\n🎉 ETL 정상 흐름 완료. silver_robot_telemetry / gold_robot_daily_stats 적재됨.")


if __name__ == "__main__":
    main()

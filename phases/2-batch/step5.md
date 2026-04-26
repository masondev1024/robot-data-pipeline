# Step 5: data-quality-gate

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md`
- `/dags/robot_daily_etl.py` (step 4 정정 후 상태)
- `/sql/bronze_ddl.sql` (Bronze 파티션: year/month/day/hour)

## 배경 — Task 2.0

plan.md Task 2.0이 요구하는 "데이터 품질 게이트"는 다음과 같다:

- `requirements.txt`에 `great-expectations` 추가
- `dags/robot_daily_etl.py`에 Bronze→Silver 진입 전 `PythonOperator` Task 삽입:
  - 검사 항목: `robot_id` null 비율 < 1%, `motor_temp` 범위 0~500, `battery_level` 범위 0~100, 레코드 수 > 0.
  - 검사 실패 시 `AirflowException` 발생 → DAG 중단 + SNS(`robot-anomaly-alerts`)로 "데이터 품질 실패" Slack 알림.
- `tests/etl/test_data_quality.py` 작성 — Mock DataFrame으로 품질 검사 로직 단위 테스트.

## 작업

### 1. `requirements.txt` 신규 작성 — 프로젝트 루트

Airflow DAG가 사용하는 Python 라이브러리. 다음 3개 라인:

```
great-expectations>=0.18,<1.0
pandas>=2.0
boto3>=1.28
```

이미 다른 곳(예: `src/api/requirements.txt`)에 있는 의존성과 별개로, **프로젝트 루트의 `requirements.txt`** 가 Airflow Helm 차트 또는 로컬 Airflow가 참조하는 위치다.

### 2. `dags/robot_daily_etl.py` — Quality Check Task 삽입

기존 Task 흐름:

```
bronze_to_silver >> silver_to_gold >> bedrock_report >> check_monday >> retrain_model
```

새로운 흐름:

```
quality_check >> bronze_to_silver >> silver_to_gold >> bedrock_report >> check_monday >> retrain_model
```

신규 Python callable `_quality_check`:

```python
def _quality_check(**ctx):
    """
    Bronze 데이터 품질 검사. 기준 위반 시 AirflowException + SNS 알림.

    검사 항목 (Athena 단일 쿼리로 집계):
      - 레코드 수 > 0
      - robot_id null 비율 < 1%
      - motor_temp 범위 0~500 위반 비율 < 1%
      - battery_level 범위 0~100 위반 비율 < 1%
    """
    from airflow.exceptions import AirflowException

    execution_date = ctx["execution_date"]
    year, month, day = execution_date.year, execution_date.month, execution_date.day

    query = f"""
SELECT
    COUNT(*)                                                                          AS total_count,
    SUM(CASE WHEN robot_id IS NULL THEN 1 ELSE 0 END)                                  AS null_robot_id,
    SUM(CASE WHEN motor_temp NOT BETWEEN 0 AND 500 THEN 1 ELSE 0 END)                  AS bad_temp,
    SUM(CASE WHEN battery_level NOT BETWEEN 0 AND 100 THEN 1 ELSE 0 END)               AS bad_battery
FROM bronze_robot_telemetry
WHERE year = {year} AND month = {month} AND day = {day}
"""
    execution_id = _run_athena_query(query)

    athena = boto3.client("athena", region_name="eu-west-1")
    rows = athena.get_query_results(QueryExecutionId=execution_id)["ResultSet"]["Rows"]
    # 첫 행은 헤더, 두 번째 행이 값
    values = [cell.get("VarCharValue", "0") for cell in rows[1]["Data"]]
    total, null_id, bad_temp, bad_battery = (int(v) for v in values)

    if total == 0:
        _publish_dq_failure(f"레코드 0건 (year={year}, month={month}, day={day})")
        raise AirflowException("Data quality check failed: 레코드 0건")

    null_ratio    = null_id    / total
    bad_temp_ratio = bad_temp   / total
    bad_batt_ratio = bad_battery / total

    failures = []
    if null_ratio    >= 0.01: failures.append(f"robot_id null 비율 {null_ratio:.2%}")
    if bad_temp_ratio >= 0.01: failures.append(f"motor_temp 이상치 비율 {bad_temp_ratio:.2%}")
    if bad_batt_ratio >= 0.01: failures.append(f"battery_level 이상치 비율 {bad_batt_ratio:.2%}")

    if failures:
        msg = "; ".join(failures)
        _publish_dq_failure(msg)
        raise AirflowException(f"Data quality check failed: {msg}")
```

신규 보조 함수 `_publish_dq_failure`:

```python
def _publish_dq_failure(detail: str):
    """SNS robot-anomaly-alerts 토픽으로 DQ 실패 알림 발송."""
    import os
    sns = boto3.client("sns", region_name="eu-west-1")
    topic_arn = os.environ.get(
        "DQ_SNS_TOPIC_ARN",
        f"arn:aws:sns:eu-west-1:{os.environ.get('AWS_ACCOUNT_ID', '')}:robot-telemetry-anomaly-alerts",
    )
    sns.publish(
        TopicArn=topic_arn,
        Subject="[Robot ETL] 데이터 품질 검사 실패",
        Message=f"Bronze 단계 품질 게이트 실패: {detail}",
    )
```

신규 Operator 등록 + dependency:

```python
quality_check = PythonOperator(
    task_id="quality_check",
    python_callable=_quality_check,
    dag=dag,
)

quality_check >> bronze_to_silver >> silver_to_gold >> bedrock_report >> check_monday >> retrain_model
```

(기존 마지막 줄의 chain을 위 chain으로 교체. 두 개의 chain 줄이 동시에 존재하면 안 됨.)

### 3. `tests/etl/__init__.py` + `tests/etl/test_data_quality.py` 작성

`_quality_check`는 Athena 호출이 결합되어 있어 그대로 단위 테스트하기 어렵다. 따라서 **순수 검증 로직을 별도 함수로 추출**한 뒤 테스트한다.

`dags/robot_daily_etl.py`에 다음 순수 함수 추가 (`_quality_check`보다 위에 배치):

```python
def evaluate_quality(total: int, null_id: int, bad_temp: int, bad_battery: int) -> list[str]:
    """
    품질 게이트 평가 순수 함수. 실패 사유 리스트를 반환한다 (빈 리스트 = 통과).

    임계값:
      - 레코드 수 > 0
      - robot_id null 비율 < 1%
      - motor_temp 이상치(0~500 외) 비율 < 1%
      - battery_level 이상치(0~100 외) 비율 < 1%
    """
    if total == 0:
        return ["레코드 0건"]

    failures = []
    if null_id    / total >= 0.01: failures.append(f"robot_id null 비율 {null_id/total:.2%}")
    if bad_temp   / total >= 0.01: failures.append(f"motor_temp 이상치 비율 {bad_temp/total:.2%}")
    if bad_battery / total >= 0.01: failures.append(f"battery_level 이상치 비율 {bad_battery/total:.2%}")
    return failures
```

`_quality_check` 내부의 임계 판정은 `evaluate_quality(total, null_id, bad_temp, bad_battery)` 호출로 단순화한다.

`tests/etl/test_data_quality.py`:

```python
from dags.robot_daily_etl import evaluate_quality


def test_pass_clean_data():
    # 1000건 모두 정상
    assert evaluate_quality(total=1000, null_id=0, bad_temp=0, bad_battery=0) == []


def test_pass_under_threshold():
    # 1% 미만 위반 → 통과
    assert evaluate_quality(total=1000, null_id=5, bad_temp=5, bad_battery=5) == []


def test_fail_zero_records():
    failures = evaluate_quality(total=0, null_id=0, bad_temp=0, bad_battery=0)
    assert failures == ["레코드 0건"]


def test_fail_high_null_ratio():
    # 2% null
    failures = evaluate_quality(total=1000, null_id=20, bad_temp=0, bad_battery=0)
    assert any("robot_id null" in f for f in failures)


def test_fail_multiple_violations():
    failures = evaluate_quality(total=1000, null_id=15, bad_temp=20, bad_battery=30)
    assert len(failures) == 3
```

`tests/etl/__init__.py` 는 빈 파일.

`tests/conftest.py`에 `dags/` 가 sys.path에 있는지 확인. 없다면 추가:

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "dags"))
```

(이미 적용돼 있다면 건드리지 마라.)

## Acceptance Criteria

```bash
# 1. requirements.txt 검증
test -f requirements.txt && echo "OK: requirements.txt"
grep -q "great-expectations" requirements.txt && echo "OK: great-expectations in requirements"

# 2. DAG 구조 검증
grep -q "def _quality_check" dags/robot_daily_etl.py && echo "OK: quality_check callable"
grep -q "def evaluate_quality" dags/robot_daily_etl.py && echo "OK: pure evaluator"
grep -q "quality_check >> bronze_to_silver" dags/robot_daily_etl.py && echo "OK: dependency wiring"
grep -q "AirflowException" dags/robot_daily_etl.py && echo "OK: airflow exception"

# 3. 테스트 실행
test -f tests/etl/test_data_quality.py && echo "OK: test file"
python3 -m pytest tests/etl/test_data_quality.py -q && echo "OK: pytest passed"

# 4. Python 문법
python3 -c "import ast; ast.parse(open('dags/robot_daily_etl.py').read())" && echo "OK: python syntax"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - 멱등성: `quality_check`는 Athena READ-only 쿼리만 수행 → 멱등성 ✅
   - SNS 알림 토픽이 plan.md 확정값(`robot-telemetry-anomaly-alerts`)을 참조하는가?
   - DAG는 `quality_check → bronze_to_silver` 순으로 dependency 설정되어, 품질 게이트가 실패하면 downstream task가 실행되지 않는가?
3. `phases/2-batch/index.json` step 5 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "Task 2.0 데이터 품질 게이트 구현(quality_check + evaluate_quality 순수 함수 + pytest)"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- `great-expectations` SDK의 무거운 Suite/Checkpoint 추상을 도입하지 마라. 이유: 본 step의 핵심은 **DAG 게이트 + 알림** 이며, GE 라이브러리 자체는 임계 평가 로직의 표현 도구일 뿐이다. `great_expectations` 패키지는 dependency로 추가하되 코드는 SQL 집계 + 순수 함수로 단순화하여 학습/유지보수 비용을 낮춘다.
- `_quality_check`에서 SQL 결과를 파싱할 때 `pandas` DataFrame으로 변환하지 마라. 이유: Airflow worker pod에 메모리 부담을 줄이기 위해 4개 정수만 추출한다.
- 임계값(1%)을 코드에 흩뿌리지 마라. 이유: 단일 진실의 출처(`evaluate_quality` 함수 내부 1% 리터럴)에서 관리한다. 추후 환경변수화는 별도 step의 일이다.
- `_publish_dq_failure`에서 Slack Webhook을 직접 호출하지 마라. 이유: SNS → Lambda → Slack 경로(`robot-anomaly-alert-stream` 흐름과 별개로 직접 SNS publish)가 plan.md Task 4.1 아키텍처와 일치한다.

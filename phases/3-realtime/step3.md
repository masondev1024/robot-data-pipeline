# Step 3: bedrock-report-tests

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/PRD.md` (핵심 기능 #6 LLM 배치 리포트)
- `/sql/gold_ddl.sql` (실제 컬럼: `robot_id`, `avg_motor_temp`, `max_motor_temp`, `battery_start`, `battery_end`, `battery_drain`, `active_hours`)
- `/dags/robot_daily_etl.py` (`_bedrock_report` 함수 — 167-223줄)
- `/tests/etl/test_data_quality.py` (테스트 패턴 참조)
- `/tests/conftest.py` (sys.path 패턴)

## 작업

`tests/etl/test_bedrock_report.py`를 작성하라. **이미 구현된 `_bedrock_report` 함수**의 동작을 Mock으로 검증한다 (코드 수정 없음).

### 검증 항목
1. **Athena 호출 검증**:
   - `start_query_execution`이 `WorkGroup="robot-telemetry-workgroup"`, `Database="robot_telemetry_db"`, `OutputLocation` 끝이 `/project-athena-results/`로 호출되는가?
   - SQL에 `gold_robot_daily_stats`, `dt = DATE '<ds>'`, `LIMIT 20`이 포함되는가?

2. **Bedrock 호출 검증**:
   - `bedrock-runtime` 클라이언트가 `region_name="eu-west-1"`로 생성되는가?
   - `invoke_model`이 `modelId="anthropic.claude-3-haiku-20240307-v1:0"`, `contentType="application/json"`, `accept="application/json"`로 호출되는가?
   - body JSON에 `anthropic_version="bedrock-2023-05-31"`, `max_tokens=512`, `messages[0].role="user"` 가 포함되는가?
   - prompt 안에 Athena 결과의 robot_id가 포함되는가? ("점검이 시급한 로봇 3대" 문구 + 300자 이내 명령 포함 검증)

3. **S3 저장 검증**:
   - `put_object`가 `Bucket="de-ai-06-827913617635-ap-northeast-2-an"`, `Key="reports/<ds>.txt"`, `Body=<Bedrock 응답 텍스트>.encode("utf-8")`로 호출되는가?

4. **DAG 체인 검증**:
   - `bedrock_report` task가 DAG에 존재하는가?
   - upstream에 `silver_to_gold`가 있는가?
   - downstream에 `check_monday`가 있는가?
   - 전체 토폴로지: `quality_check >> bronze_to_silver >> silver_to_gold >> bedrock_report >> check_monday >> retrain_ml_model`

### 파일 구조

```python
# tests/etl/test_bedrock_report.py
import json
from unittest.mock import patch, MagicMock

import pytest

from dags.robot_daily_etl import _bedrock_report, dag


@pytest.fixture
def mock_athena_response():
    """get_query_results paginator가 반환할 가짜 페이지."""
    return {
        "ResultSet": {
            "Rows": [
                {"Data": [{"VarCharValue": "robot_id"},
                         {"VarCharValue": "avg_motor_temp"},
                         {"VarCharValue": "max_motor_temp"},
                         {"VarCharValue": "battery_drain"},
                         {"VarCharValue": "active_hours"}]},
                {"Data": [{"VarCharValue": "ROBOT-00001"},
                         {"VarCharValue": "92.5"},
                         {"VarCharValue": "98.0"},
                         {"VarCharValue": "30"},
                         {"VarCharValue": "8"}]},
                # ... 추가 robot 2~3건
            ]
        }
    }


class TestBedrockReportAthena:
    """Athena 호출 파라미터 검증"""
    @patch("dags.robot_daily_etl.boto3.client")
    def test_athena_workgroup_and_database(self, mock_boto, mock_athena_response):
        ...

class TestBedrockReportInvoke:
    """Bedrock invoke_model 호출 검증"""
    @patch("dags.robot_daily_etl.boto3.client")
    def test_model_id_and_max_tokens(self, mock_boto, mock_athena_response):
        ...

    @patch("dags.robot_daily_etl.boto3.client")
    def test_prompt_contains_data_summary(self, mock_boto, mock_athena_response):
        ...

class TestBedrockReportS3:
    """S3 put_object 호출 검증"""
    @patch("dags.robot_daily_etl.boto3.client")
    def test_s3_key_and_body(self, mock_boto, mock_athena_response):
        ...

class TestDagChain:
    """DAG 토폴로지 검증"""
    def test_bedrock_report_task_exists(self):
        assert "bedrock_report" in dag.task_ids

    def test_upstream_silver_to_gold(self):
        t = dag.get_task("bedrock_report")
        assert any(u.task_id == "silver_to_gold" for u in t.upstream_list)

    def test_full_topology(self):
        ids = [t.task_id for t in dag.topological_sort()]
        # 순서 검증
        ...
```

### Mock 설정 핵심
- `boto3.client`는 `side_effect`로 service별 다른 mock 반환:
  - `"athena"` → `start_query_execution` + `get_query_execution` + `get_paginator("get_query_results")`
  - `"bedrock-runtime"` → `invoke_model` 응답: `{"body": MagicMock(read=lambda: json.dumps({"content": [{"text": "정비 우선순위 리포트 본문"}]}).encode("utf-8"))}`
  - `"s3"` → `put_object` 호출 인자 capture
- `execution_date`는 `pendulum.datetime(2026, 4, 25)` 또는 동등한 datetime 객체로 주입 → `ds = "2026-04-25"`

## Acceptance Criteria

```bash
# 단위 테스트 통과
pytest tests/etl/test_bedrock_report.py -v

# 클래스별 최소 케이스 카운트 — Athena 1+ Invoke 2+ S3 1+ DAG 3 = 7건 이상
pytest tests/etl/test_bedrock_report.py -v 2>&1 | grep -c "PASSED"
# 위 결과가 7 이상이어야 함

# 기존 테스트 회귀 검증 (Phase 2의 7건 + 본 step 7+)
pytest tests/etl/ -v
```

## 검증 절차

1. 위 AC 커맨드를 모두 실행, 7건 이상 PASSED 확인 + `tests/etl/` 전체 회귀 통과.
2. 아키텍처 체크리스트:
   - region이 `eu-west-1`로 검증되는가?
   - WorkGroup이 `robot-telemetry-workgroup`로 검증되는가?
   - Bedrock model이 `anthropic.claude-3-haiku-20240307-v1:0`로 검증되는가?
   - DAG 토폴로지가 `quality_check >> bronze_to_silver >> silver_to_gold >> bedrock_report >> check_monday >> retrain_ml_model`인가?
   - prompt에 Athena 결과 robot_id가 포함되는지 검증되는가?
3. `phases/3-realtime/index.json` step 3 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "tests/etl/test_bedrock_report.py: Athena+Bedrock+S3 mock 7케이스+DAG 토폴로지 검증 PASSED"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- `dags/robot_daily_etl.py`를 수정하지 마라. 이유: Phase 2에서 Source of Truth로 확정된 코드. 본 step은 **검증 전용**. 발견된 버그는 별도 issue로 보고하고 step에 `blocked_reason` 기록.
- Bedrock 실 API를 호출하지 마라. 이유: CI 비용 + flaky. 반드시 `unittest.mock.patch("dags.robot_daily_etl.boto3.client")`로 mock.
- `task_id="generate_bedrock_report"` 로 검증하지 마라. 이유: 실제 task_id는 `bedrock_report` (DAG 코드 확인). 이전 step2.md 초안의 AC는 깨진 상태였으므로 재사용 금지.
- 5분 이내 완료되지 않으면 mock 설정 문제이지 함수 자체 문제가 아니다. 이유: Bedrock/Athena가 mock된 상태에서는 즉시 반환됨. 시간 초과 시 mock 누수 의심.

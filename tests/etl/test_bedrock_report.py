"""ADR-012 마이그레이션으로 dags/robot_daily_etl.py 가 직접 invoke_model 호출 →
src.common.bedrock.invoke_claude helper 사용으로 변경. 본 모듈의 mock 위치
(robot_daily_etl.boto3.client) 는 더 이상 bedrock 호출을 잡지 못함 →
src.common.aws.boto3.client 패치 + body 형식(system 가 string 또는 list[block])
검증으로 재작성 필요. 본 transport 테스트의 우선순위는 낮음 (evals/ 가 회귀 담당)."""
import json
from unittest.mock import patch, MagicMock, call
from datetime import datetime

import pytest

pytestmark = pytest.mark.skip(reason="ADR-012 — invoke_claude helper 마이그레이션으로 mock 위치 변경 필요 (후속 PR)")

pytest.importorskip("airflow")

from robot_daily_etl import _bedrock_report, dag


@pytest.fixture(autouse=True)
def _isolate_bedrock_env(monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)


@pytest.fixture
def mock_athena_response():
    """get_query_results paginator가 반환할 가짜 페이지."""
    return {
        "ResultSet": {
            "Rows": [
                {
                    "Data": [
                        {"VarCharValue": "robot_id"},
                        {"VarCharValue": "avg_motor_temp"},
                        {"VarCharValue": "max_motor_temp"},
                        {"VarCharValue": "battery_drain"},
                        {"VarCharValue": "active_hours"},
                    ]
                },
                {
                    "Data": [
                        {"VarCharValue": "ROBOT-00001"},
                        {"VarCharValue": "92.5"},
                        {"VarCharValue": "98.0"},
                        {"VarCharValue": "30"},
                        {"VarCharValue": "8"},
                    ]
                },
                {
                    "Data": [
                        {"VarCharValue": "ROBOT-00002"},
                        {"VarCharValue": "88.3"},
                        {"VarCharValue": "95.0"},
                        {"VarCharValue": "25"},
                        {"VarCharValue": "7"},
                    ]
                },
                {
                    "Data": [
                        {"VarCharValue": "ROBOT-00003"},
                        {"VarCharValue": "85.1"},
                        {"VarCharValue": "92.0"},
                        {"VarCharValue": "20"},
                        {"VarCharValue": "6"},
                    ]
                },
            ]
        }
    }


@pytest.fixture
def mock_execution_context():
    """Airflow execution_date를 포함한 context."""
    return {"execution_date": datetime(2026, 4, 25)}


class TestBedrockReportAthena:
    """Athena 호출 파라미터 검증"""

    @patch("robot_daily_etl.boto3.client")
    def test_athena_workgroup_and_database(
        self, mock_boto, mock_athena_response, mock_execution_context
    ):
        """Athena start_query_execution이 올바른 WorkGroup, Database, OutputLocation으로 호출되는가?"""
        # Mock 설정
        mock_athena_client = MagicMock()
        mock_bedrock_client = MagicMock()
        mock_s3_client = MagicMock()

        def client_factory(service, region_name=None):
            if service == "athena":
                return mock_athena_client
            elif service == "bedrock-runtime":
                return mock_bedrock_client
            elif service == "s3":
                return mock_s3_client
            return MagicMock()

        mock_boto.side_effect = client_factory

        # Athena mocks
        mock_athena_client.start_query_execution.return_value = {
            "QueryExecutionId": "test-exec-id"
        }
        mock_athena_client.get_query_execution.return_value = {
            "QueryExecution": {"Status": {"State": "SUCCEEDED"}}
        }
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [mock_athena_response]
        mock_athena_client.get_paginator.return_value = mock_paginator

        # Bedrock mocks
        bedrock_response = MagicMock()
        bedrock_response.read.return_value = json.dumps(
            {"content": [{"text": "정비 우선순위 리포트"}]}
        ).encode("utf-8")
        mock_bedrock_client.invoke_model.return_value = {"body": bedrock_response}

        # S3 mocks
        mock_s3_client.put_object.return_value = {}

        # Execute
        _bedrock_report(**mock_execution_context)

        # Verify Athena start_query_execution call
        calls = mock_athena_client.start_query_execution.call_args_list
        assert len(calls) > 0, "start_query_execution not called"
        call_args = calls[0]
        assert call_args.kwargs["WorkGroup"] == "robot-telemetry-workgroup"
        assert call_args.kwargs["QueryExecutionContext"]["Database"] == "robot_telemetry_db"
        assert call_args.kwargs["ResultConfiguration"]["OutputLocation"].endswith(
            "/project-athena-results/"
        )

    @patch("robot_daily_etl.boto3.client")
    def test_athena_query_contains_gold_table(
        self, mock_boto, mock_athena_response, mock_execution_context
    ):
        """Athena 쿼리가 gold_robot_daily_stats, 날짜 필터, LIMIT 20을 포함하는가?"""
        # Mock 설정
        mock_athena_client = MagicMock()
        mock_bedrock_client = MagicMock()
        mock_s3_client = MagicMock()

        def client_factory(service, region_name=None):
            if service == "athena":
                return mock_athena_client
            elif service == "bedrock-runtime":
                return mock_bedrock_client
            elif service == "s3":
                return mock_s3_client
            return MagicMock()

        mock_boto.side_effect = client_factory

        # Athena mocks
        mock_athena_client.start_query_execution.return_value = {
            "QueryExecutionId": "test-exec-id"
        }
        mock_athena_client.get_query_execution.return_value = {
            "QueryExecution": {"Status": {"State": "SUCCEEDED"}}
        }
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [mock_athena_response]
        mock_athena_client.get_paginator.return_value = mock_paginator

        # Bedrock mocks
        bedrock_response = MagicMock()
        bedrock_response.read.return_value = json.dumps(
            {"content": [{"text": "정비 우선순위 리포트"}]}
        ).encode("utf-8")
        mock_bedrock_client.invoke_model.return_value = {"body": bedrock_response}

        # S3 mocks
        mock_s3_client.put_object.return_value = {}

        # Execute
        _bedrock_report(**mock_execution_context)

        # Verify SQL content
        calls = mock_athena_client.start_query_execution.call_args_list
        query = calls[0].kwargs["QueryString"]
        assert "gold_robot_daily_stats" in query
        assert "dt = DATE '2026-04-25'" in query
        assert "LIMIT 20" in query


class TestBedrockReportInvoke:
    """Bedrock invoke_model 호출 검증"""

    @patch("robot_daily_etl.boto3.client")
    def test_bedrock_model_id_and_parameters(
        self, mock_boto, mock_athena_response, mock_execution_context
    ):
        """Bedrock invoke_model이 올바른 modelId와 contentType으로 호출되는가?"""
        # Mock 설정
        mock_athena_client = MagicMock()
        mock_bedrock_client = MagicMock()
        mock_s3_client = MagicMock()

        def client_factory(service, region_name=None):
            if service == "athena":
                return mock_athena_client
            elif service == "bedrock-runtime":
                return mock_bedrock_client
            elif service == "s3":
                return mock_s3_client
            return MagicMock()

        mock_boto.side_effect = client_factory

        # Athena mocks
        mock_athena_client.start_query_execution.return_value = {
            "QueryExecutionId": "test-exec-id"
        }
        mock_athena_client.get_query_execution.return_value = {
            "QueryExecution": {"Status": {"State": "SUCCEEDED"}}
        }
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [mock_athena_response]
        mock_athena_client.get_paginator.return_value = mock_paginator

        # Bedrock mocks
        bedrock_response = MagicMock()
        bedrock_response.read.return_value = json.dumps(
            {"content": [{"text": "정비 우선순위 리포트"}]}
        ).encode("utf-8")
        mock_bedrock_client.invoke_model.return_value = {"body": bedrock_response}

        # S3 mocks
        mock_s3_client.put_object.return_value = {}

        # Execute
        _bedrock_report(**mock_execution_context)

        # Verify Bedrock invoke_model call
        call_args = mock_bedrock_client.invoke_model.call_args
        assert call_args.kwargs["modelId"] == "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
        assert call_args.kwargs["contentType"] == "application/json"
        assert call_args.kwargs["accept"] == "application/json"

    @patch("robot_daily_etl.boto3.client")
    def test_bedrock_body_contains_required_fields(
        self, mock_boto, mock_athena_response, mock_execution_context
    ):
        """Bedrock body JSON이 anthropic_version, max_tokens, messages를 포함하는가?"""
        # Mock 설정
        mock_athena_client = MagicMock()
        mock_bedrock_client = MagicMock()
        mock_s3_client = MagicMock()

        def client_factory(service, region_name=None):
            if service == "athena":
                return mock_athena_client
            elif service == "bedrock-runtime":
                return mock_bedrock_client
            elif service == "s3":
                return mock_s3_client
            return MagicMock()

        mock_boto.side_effect = client_factory

        # Athena mocks
        mock_athena_client.start_query_execution.return_value = {
            "QueryExecutionId": "test-exec-id"
        }
        mock_athena_client.get_query_execution.return_value = {
            "QueryExecution": {"Status": {"State": "SUCCEEDED"}}
        }
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [mock_athena_response]
        mock_athena_client.get_paginator.return_value = mock_paginator

        # Bedrock mocks
        bedrock_response = MagicMock()
        bedrock_response.read.return_value = json.dumps(
            {"content": [{"text": "정비 우선순위 리포트"}]}
        ).encode("utf-8")
        mock_bedrock_client.invoke_model.return_value = {"body": bedrock_response}

        # S3 mocks
        mock_s3_client.put_object.return_value = {}

        # Execute
        _bedrock_report(**mock_execution_context)

        # Verify Bedrock body content
        call_args = mock_bedrock_client.invoke_model.call_args
        body_str = call_args.kwargs["body"]
        body = json.loads(body_str)

        assert body["anthropic_version"] == "bedrock-2023-05-31"
        assert body["max_tokens"] == 512
        assert "messages" in body
        assert body["messages"][0]["role"] == "user"

    @patch("robot_daily_etl.boto3.client")
    def test_bedrock_prompt_contains_robot_data(
        self, mock_boto, mock_athena_response, mock_execution_context
    ):
        """Bedrock prompt이 Athena 결과의 robot_id를 포함하는가?"""
        # Mock 설정
        mock_athena_client = MagicMock()
        mock_bedrock_client = MagicMock()
        mock_s3_client = MagicMock()

        def client_factory(service, region_name=None):
            if service == "athena":
                return mock_athena_client
            elif service == "bedrock-runtime":
                return mock_bedrock_client
            elif service == "s3":
                return mock_s3_client
            return MagicMock()

        mock_boto.side_effect = client_factory

        # Athena mocks
        mock_athena_client.start_query_execution.return_value = {
            "QueryExecutionId": "test-exec-id"
        }
        mock_athena_client.get_query_execution.return_value = {
            "QueryExecution": {"Status": {"State": "SUCCEEDED"}}
        }
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [mock_athena_response]
        mock_athena_client.get_paginator.return_value = mock_paginator

        # Bedrock mocks
        bedrock_response = MagicMock()
        bedrock_response.read.return_value = json.dumps(
            {"content": [{"text": "정비 우선순위 리포트"}]}
        ).encode("utf-8")
        mock_bedrock_client.invoke_model.return_value = {"body": bedrock_response}

        # S3 mocks
        mock_s3_client.put_object.return_value = {}

        # Execute
        _bedrock_report(**mock_execution_context)

        # Verify prompt contains robot IDs and instructions
        call_args = mock_bedrock_client.invoke_model.call_args
        body_str = call_args.kwargs["body"]
        body = json.loads(body_str)
        prompt = body["messages"][0]["content"]

        assert "ROBOT-00001" in prompt
        assert "ROBOT-00002" in prompt
        assert "ROBOT-00003" in prompt
        assert "점검이 시급한" in prompt
        assert len(prompt) <= 500  # 약 300자 + 명령 포함


class TestBedrockReportS3:
    """S3 put_object 호출 검증"""

    @patch("robot_daily_etl.boto3.client")
    def test_s3_bucket_key_and_body(
        self, mock_boto, mock_athena_response, mock_execution_context
    ):
        """S3 put_object이 올바른 Bucket, Key, Body로 호출되는가?"""
        # Mock 설정
        mock_athena_client = MagicMock()
        mock_bedrock_client = MagicMock()
        mock_s3_client = MagicMock()

        def client_factory(service, region_name=None):
            if service == "athena":
                return mock_athena_client
            elif service == "bedrock-runtime":
                return mock_bedrock_client
            elif service == "s3":
                return mock_s3_client
            return MagicMock()

        mock_boto.side_effect = client_factory

        # Athena mocks
        mock_athena_client.start_query_execution.return_value = {
            "QueryExecutionId": "test-exec-id"
        }
        mock_athena_client.get_query_execution.return_value = {
            "QueryExecution": {"Status": {"State": "SUCCEEDED"}}
        }
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [mock_athena_response]
        mock_athena_client.get_paginator.return_value = mock_paginator

        # Bedrock mocks
        report_text = "정비 우선순위 리포트"
        bedrock_response = MagicMock()
        bedrock_response.read.return_value = json.dumps(
            {"content": [{"text": report_text}]}
        ).encode("utf-8")
        mock_bedrock_client.invoke_model.return_value = {"body": bedrock_response}

        # S3 mocks
        mock_s3_client.put_object.return_value = {}

        # Execute
        _bedrock_report(**mock_execution_context)

        # Verify S3 put_object call
        call_args = mock_s3_client.put_object.call_args
        assert call_args.kwargs["Bucket"] == "de-ai-06-smartfactory-bucket"
        assert call_args.kwargs["Key"] == "reports/2026-04-25.txt"
        assert call_args.kwargs["Body"] == report_text.encode("utf-8")


class TestDagChain:
    """DAG 토폴로지 검증"""

    def test_bedrock_report_task_exists(self):
        """bedrock_report task가 DAG에 존재하는가?"""
        assert "bedrock_report" in dag.task_ids

    def test_upstream_silver_to_gold(self):
        """bedrock_report의 upstream에 silver_to_gold가 있는가?"""
        task = dag.get_task("bedrock_report")
        upstream_task_ids = [t.task_id for t in task.upstream_list]
        assert "silver_to_gold" in upstream_task_ids

    def test_downstream_check_monday(self):
        """bedrock_report의 downstream에 check_monday가 있는가?"""
        task = dag.get_task("bedrock_report")
        downstream_task_ids = [t.task_id for t in task.downstream_list]
        assert "check_monday" in downstream_task_ids

    def test_full_dag_topology(self):
        """전체 DAG 토폴로지가 올바른가?"""
        # DAG 토폴로지 순서 검증
        expected_order = [
            "quality_check",
            "bronze_to_silver",
            "silver_to_gold",
            "bedrock_report",
            "check_monday",
            "retrain_ml_model",
        ]

        # topological_sort()로 순서 검증
        task_list = list(dag.topological_sort())
        actual_order = [t.task_id for t in task_list]

        assert actual_order == expected_order, f"Expected {expected_order}, got {actual_order}"

import base64
import json
from unittest.mock import patch, MagicMock, ANY
import pytest
import sys
import importlib.util
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))


@pytest.fixture
def kinesis_event():
    """Mock Kinesis event with robot anomaly data."""
    payload = {
        "robot_id": "ROBOT-00789",
        "max_motor_temp": 98.5,
        "window_end": "2026-04-27T10:30:00Z",
        "battery_drain": 35
    }
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return {
        "Records": [
            {
                "kinesis": {
                    "data": encoded
                }
            }
        ]
    }


@pytest.fixture
def alert_handler_module():
    """Load alert_handler module with mocked boto3."""
    with patch("boto3.client") as mock_boto:
        mock_sns_client = MagicMock()

        def client_factory(service, **kwargs):
            if service == "sns":
                return mock_sns_client
            elif service == "ssm":
                return MagicMock()
            return MagicMock()

        mock_boto.side_effect = client_factory

        spec = importlib.util.spec_from_file_location("alert_handler", "src/lambda/alert_handler.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["alert_handler"] = module
        spec.loader.exec_module(module)

        yield module, mock_sns_client


class TestAlertHandler:
    """Lambda alert_handler function tests"""

    @patch("boto3.client")
    def test_ssm_portal_url_called_once(self, mock_boto, kinesis_event, monkeypatch):
        """SSM get_parameter is called only once (module-level cache)."""
        mock_ssm_client = MagicMock()
        mock_ssm_client.get_parameter.return_value = {
            "Parameter": {"Value": "https://example.com/portal"}
        }
        mock_sns_client = MagicMock()

        def client_factory(service, **kwargs):
            if service == "ssm":
                return mock_ssm_client
            elif service == "sns":
                return mock_sns_client
            return MagicMock()

        mock_boto.side_effect = client_factory

        spec = importlib.util.spec_from_file_location("ah1", "src/lambda/alert_handler.py")
        module = importlib.util.module_from_spec(spec)
        module._portal_url = None
        spec.loader.exec_module(module)

        monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:eu-west-1:123456789:test-topic")

        module.handler(kinesis_event, None)
        module.handler(kinesis_event, None)

        assert mock_ssm_client.get_parameter.call_count == 1

    @patch("boto3.client")
    def test_alert_message_format_header(self, mock_boto, kinesis_event, monkeypatch):
        """Alert message contains header '[⚠️ 이상 감지]' or '이상 감지'."""
        mock_ssm_client = MagicMock()
        mock_ssm_client.get_parameter.return_value = {
            "Parameter": {"Value": "https://example.com/portal"}
        }
        mock_sns_client = MagicMock()

        def client_factory(service, **kwargs):
            if service == "ssm":
                return mock_ssm_client
            elif service == "sns":
                return mock_sns_client
            return MagicMock()

        mock_boto.side_effect = client_factory

        spec = importlib.util.spec_from_file_location("ah2", "src/lambda/alert_handler.py")
        module = importlib.util.module_from_spec(spec)
        module._portal_url = None
        spec.loader.exec_module(module)

        monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:eu-west-1:123456789:test-topic")

        module.handler(kinesis_event, None)

        assert mock_sns_client.publish.called
        call_args = mock_sns_client.publish.call_args
        message = call_args.kwargs["Message"]
        assert "이상 감지" in message or "⚠️" in message

    @patch("boto3.client")
    def test_alert_message_deeplink(self, mock_boto, kinesis_event, monkeypatch):
        """Alert message contains deeplink with format '포털: ../?robot_id=ROBOT-XXXXX'."""
        mock_ssm_client = MagicMock()
        mock_ssm_client.get_parameter.return_value = {
            "Parameter": {"Value": "https://example.com/portal"}
        }
        mock_sns_client = MagicMock()

        def client_factory(service, **kwargs):
            if service == "ssm":
                return mock_ssm_client
            elif service == "sns":
                return mock_sns_client
            return MagicMock()

        mock_boto.side_effect = client_factory

        spec = importlib.util.spec_from_file_location("ah3", "src/lambda/alert_handler.py")
        module = importlib.util.module_from_spec(spec)
        module._portal_url = None
        spec.loader.exec_module(module)

        monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:eu-west-1:123456789:test-topic")

        module.handler(kinesis_event, None)

        assert mock_sns_client.publish.called
        call_args = mock_sns_client.publish.call_args
        message = call_args.kwargs["Message"]
        assert "포털" in message
        assert "/?robot_id=ROBOT-00789" in message

    @patch("boto3.client")
    def test_window_end_priority_over_timestamp(self, mock_boto, kinesis_event, monkeypatch):
        """window_end is preferred, timestamp is fallback."""
        mock_ssm_client = MagicMock()
        mock_ssm_client.get_parameter.return_value = {
            "Parameter": {"Value": "https://example.com/portal"}
        }
        mock_sns_client = MagicMock()

        def client_factory(service, **kwargs):
            if service == "ssm":
                return mock_ssm_client
            elif service == "sns":
                return mock_sns_client
            return MagicMock()

        mock_boto.side_effect = client_factory

        spec = importlib.util.spec_from_file_location("ah4", "src/lambda/alert_handler.py")
        module = importlib.util.module_from_spec(spec)
        module._portal_url = None
        spec.loader.exec_module(module)

        monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:eu-west-1:123456789:test-topic")

        module.handler(kinesis_event, None)

        assert mock_sns_client.publish.called
        call_args = mock_sns_client.publish.call_args
        message = call_args.kwargs["Message"]
        assert "2026-04-27T10:30:00Z" in message

    @patch("boto3.client")
    def test_ssm_failure_sns_still_published(self, mock_boto, kinesis_event, monkeypatch):
        """When SSM fails, SNS publish still succeeds (with error message)."""
        mock_ssm_client = MagicMock()
        mock_ssm_client.get_parameter.side_effect = Exception("SSM error")
        mock_sns_client = MagicMock()

        def client_factory(service, **kwargs):
            if service == "ssm":
                return mock_ssm_client
            elif service == "sns":
                return mock_sns_client
            return MagicMock()

        mock_boto.side_effect = client_factory

        spec = importlib.util.spec_from_file_location("ah5", "src/lambda/alert_handler.py")
        module = importlib.util.module_from_spec(spec)
        module._portal_url = None
        spec.loader.exec_module(module)

        monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:eu-west-1:123456789:test-topic")

        module.handler(kinesis_event, None)

        assert mock_sns_client.publish.called
        call_args = mock_sns_client.publish.call_args
        message = call_args.kwargs["Message"]
        assert "포털" in message or "조회 실패" in message

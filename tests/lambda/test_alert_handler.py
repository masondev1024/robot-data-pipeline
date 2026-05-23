import base64
import json
from unittest.mock import patch, MagicMock
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


def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, "src/lambda/alert_handler.py")
    module = importlib.util.module_from_spec(spec)
    module._portal_url = None
    spec.loader.exec_module(module)
    return module


def _make_ssm_mock(value="https://example.com/portal", fail=False):
    mock_ssm = MagicMock()
    if fail:
        mock_ssm.get_parameter.side_effect = Exception("SSM error")
    else:
        mock_ssm.get_parameter.return_value = {"Parameter": {"Value": value}}
    return mock_ssm


def _make_urlopen_mock():
    """Returns a context-manager mock that mimics urllib.request.urlopen."""
    response = MagicMock()
    response.status = 200
    cm = MagicMock()
    cm.__enter__.return_value = response
    cm.__exit__.return_value = False
    urlopen_mock = MagicMock(return_value=cm)
    return urlopen_mock


class TestAlertHandler:
    """Lambda alert_handler function tests"""

    @patch("urllib.request.urlopen")
    @patch("boto3.client")
    def test_ssm_portal_url_called_once(self, mock_boto, mock_urlopen, kinesis_event, monkeypatch):
        """SSM get_parameter is called only once (module-level cache)."""
        mock_ssm = _make_ssm_mock()
        mock_boto.return_value = mock_ssm
        urlopen_mock = _make_urlopen_mock()
        mock_urlopen.side_effect = urlopen_mock

        module = _load_module("ah1")

        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")

        module.handler(kinesis_event, None)
        module.handler(kinesis_event, None)

        assert mock_ssm.get_parameter.call_count == 1

    @patch("urllib.request.urlopen")
    @patch("boto3.client")
    def test_alert_message_format_header(self, mock_boto, mock_urlopen, kinesis_event, monkeypatch):
        """Slack POST body contains header '[⚠️ 이상 감지]' or '이상 감지'."""
        mock_boto.return_value = _make_ssm_mock()
        urlopen_mock = _make_urlopen_mock()
        mock_urlopen.side_effect = urlopen_mock

        module = _load_module("ah2")

        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")

        module.handler(kinesis_event, None)

        assert mock_urlopen.called
        req = mock_urlopen.call_args.args[0]
        body = json.loads(req.data.decode("utf-8"))
        assert "이상 감지" in body["text"] or "⚠️" in body["text"]

    @patch("urllib.request.urlopen")
    @patch("boto3.client")
    def test_alert_message_deeplink(self, mock_boto, mock_urlopen, kinesis_event, monkeypatch):
        """Slack POST body contains deeplink with format '포털: ../?robot_id=ROBOT-XXXXX'."""
        mock_boto.return_value = _make_ssm_mock()
        urlopen_mock = _make_urlopen_mock()
        mock_urlopen.side_effect = urlopen_mock

        module = _load_module("ah3")

        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")

        module.handler(kinesis_event, None)

        assert mock_urlopen.called
        req = mock_urlopen.call_args.args[0]
        body = json.loads(req.data.decode("utf-8"))
        assert "포털" in body["text"]
        assert "/?robot_id=ROBOT-00789" in body["text"]

    @patch("urllib.request.urlopen")
    @patch("boto3.client")
    def test_window_end_priority_over_timestamp(self, mock_boto, mock_urlopen, kinesis_event, monkeypatch):
        """window_end is preferred, timestamp is fallback."""
        mock_boto.return_value = _make_ssm_mock()
        urlopen_mock = _make_urlopen_mock()
        mock_urlopen.side_effect = urlopen_mock

        module = _load_module("ah4")

        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")

        module.handler(kinesis_event, None)

        assert mock_urlopen.called
        req = mock_urlopen.call_args.args[0]
        body = json.loads(req.data.decode("utf-8"))
        assert "2026-04-27T10:30:00Z" in body["text"]

    @patch("urllib.request.urlopen")
    @patch("boto3.client")
    def test_ssm_failure_slack_still_posted(self, mock_boto, mock_urlopen, kinesis_event, monkeypatch):
        """When SSM fails, Slack POST still succeeds (with error message)."""
        mock_boto.return_value = _make_ssm_mock(fail=True)
        urlopen_mock = _make_urlopen_mock()
        mock_urlopen.side_effect = urlopen_mock

        module = _load_module("ah5")

        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")

        module.handler(kinesis_event, None)

        assert mock_urlopen.called
        req = mock_urlopen.call_args.args[0]
        body = json.loads(req.data.decode("utf-8"))
        assert "포털" in body["text"] or "조회 실패" in body["text"]

    @patch("urllib.request.urlopen")
    @patch("boto3.client")
    def test_cloudwatch_alarm_event_routed(self, mock_boto, mock_urlopen, monkeypatch):
        """CloudWatch Alarm 직접 invoke event 가 분기를 타고 Slack 으로 알림 발송."""
        urlopen_mock = _make_urlopen_mock()
        mock_urlopen.side_effect = urlopen_mock

        module = _load_module("ah6")

        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")

        alarm_event = {
            "AlarmName": "robot-telemetry-firehose-delivery-errors",
            "AlarmDescription": "Firehose delivery to S3 success rate < 95%",
            "NewStateValue": "ALARM",
            "OldStateValue": "OK",
            "NewStateReason": "Threshold Crossed: 2 datapoints were less than the threshold (95.0).",
            "Region": "EU (Ireland)",
            "AlarmArn": "arn:aws:cloudwatch:eu-west-1:827913617635:alarm:robot-telemetry-firehose-delivery-errors",
        }

        result = module.handler(alarm_event, None)

        # SSM 은 호출되지 않아야 함 (CloudWatch alarm 분기는 portal_url 불필요)
        assert mock_boto.call_count == 0
        assert mock_urlopen.called
        req = mock_urlopen.call_args.args[0]
        body = json.loads(req.data.decode("utf-8"))
        assert "[CloudWatch]" in body["text"]
        assert "ALARM" in body["text"]
        assert "robot-telemetry-firehose-delivery-errors" in body["text"]
        assert result["alarm"] == "robot-telemetry-firehose-delivery-errors"
        assert result["newState"] == "ALARM"

    @patch("urllib.request.urlopen")
    @patch("boto3.client")
    def test_cloudwatch_alarm_lambda_direct_invoke_schema(self, mock_boto, mock_urlopen, monkeypatch):
        """Lambda direct invoke (alarm_actions=Lambda ARN) 시 AWS 가 사용하는 nested
        camelCase schema(`alarmData.alarmName`, `alarmData.state.value`) 를 정확히 파싱.
        """
        urlopen_mock = _make_urlopen_mock()
        mock_urlopen.side_effect = urlopen_mock

        module = _load_module("ah7")

        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")

        # Lambda direct invoke schema (실 운영에서 받는 실제 payload 형식)
        alarm_event = {
            "source": "aws.cloudwatch",
            "alarmArn": "arn:aws:cloudwatch:eu-west-1:827913617635:alarm:robot-telemetry-firehose-delivery-errors",
            "accountId": "827913617635",
            "time": "2026-05-01T10:30:39Z",
            "region": "eu-west-1",
            "alarmData": {
                "alarmName": "robot-telemetry-firehose-delivery-errors",
                "state": {
                    "value": "ALARM",
                    "reason": "manual e2e test",
                    "timestamp": "2026-05-01T10:30:39Z",
                },
                "previousState": {"value": "OK"},
                "configuration": {"description": "Firehose delivery success < 95%"},
            },
        }

        result = module.handler(alarm_event, None)

        assert mock_boto.call_count == 0  # SSM 미호출
        assert mock_urlopen.called
        body = json.loads(mock_urlopen.call_args.args[0].data.decode("utf-8"))
        assert "[CloudWatch]" in body["text"]
        assert "ALARM" in body["text"]
        assert "robot-telemetry-firehose-delivery-errors" in body["text"]
        assert "eu-west-1" in body["text"]
        assert result["alarm"] == "robot-telemetry-firehose-delivery-errors"
        assert result["newState"] == "ALARM"

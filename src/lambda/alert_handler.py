import base64
import json
import os
import urllib.request
import boto3

_portal_url: str | None = None


def _get_portal_url() -> str:
    """Get portal URL from SSM Parameter Store (cached at cold start)."""
    global _portal_url
    if _portal_url is None:
        try:
            ssm = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "eu-west-1"))
            _portal_url = ssm.get_parameter(Name="/robot-telemetry/portal-url")["Parameter"]["Value"]
        except Exception as e:
            print(f"SSM get_parameter failed: {str(e)}")
            _portal_url = ""
    return _portal_url


def _post_to_slack(webhook_url: str, text: str) -> None:
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"Slack POST failed: status={resp.status}")


def _handle_cloudwatch_alarm(event: dict, webhook_url: str) -> dict:
    """CloudWatch Alarm 직접 invoke 분기. alarm 발화/회복 시 Slack 알림.

    두 가지 alarm event schema 모두 지원:
    - Lambda direct invoke (alarm_actions = Lambda ARN): `alarmData.alarmName`,
      `alarmData.state.value`, `alarmData.state.reason` (중첩, camelCase).
    - SNS-published alarm: `AlarmName`, `NewStateValue`, `NewStateReason` (top-level, PascalCase).
    """
    alarm_data = event.get("alarmData") or {}
    state_data = alarm_data.get("state") or {}

    alarm_name = alarm_data.get("alarmName") or event.get("AlarmName", "UNKNOWN")
    new_state = state_data.get("value") or event.get("NewStateValue", "?")
    reason = state_data.get("reason") or event.get("NewStateReason", "")
    region = event.get("region") or event.get("Region", "?")

    icon = "🚨" if new_state == "ALARM" else ("✅" if new_state == "OK" else "ℹ️")
    message = (
        f"{icon} [CloudWatch] {alarm_name} → {new_state}\n"
        f"리전: {region}\n"
        f"사유: {reason[:300]}"
    )
    # 운영 가시성: CloudWatch Logs 에서 grep 가능하도록 alarm 처리 진입점 명시.
    print(f"[cloudwatch_alarm] name={alarm_name} state={new_state} region={region}")
    _post_to_slack(webhook_url, message)
    print(f"[cloudwatch_alarm] slack_post_success name={alarm_name} state={new_state}")
    return {"statusCode": 200, "alarm": alarm_name, "newState": new_state}


def handler(event, context):
    """이벤트 source 분기 후 처리:
    - Kinesis Records: Flink 이상 탐지 알람 (batchItemFailures 보고).
    - CloudWatch Alarm: Firehose DLQ 등 인프라 알람 직접 invoke.
    """
    webhook_url = os.environ["SLACK_WEBHOOK_URL"]

    # CloudWatch Alarm event 식별: direct invoke(`alarmData`) 또는 SNS-published(`AlarmName`).
    if isinstance(event, dict) and ("alarmData" in event or "AlarmName" in event):
        return _handle_cloudwatch_alarm(event, webhook_url)

    # 기본 Kinesis Records 경로
    portal_url = _get_portal_url()
    failures: list[dict] = []
    for record in event["Records"]:
        try:
            payload = json.loads(base64.b64decode(record["kinesis"]["data"]))

            robot_id = payload.get("robot_id", "UNKNOWN")
            motor_temp = payload.get("max_motor_temp") or payload.get("motor_temp", "?")
            timestamp = payload.get("window_end") or payload.get("timestamp", "?")

            header = f"[⚠️ 이상 감지] robot_id: {robot_id} | motor_temp: {motor_temp}°C | 감지: {timestamp}"
            if portal_url:
                footer = f"🔗 포털: {portal_url}/?robot_id={robot_id}"
            else:
                footer = "🔗 포털 URL 조회 실패"
            message = f"{header}\n{footer}"

            _post_to_slack(webhook_url, message)
        except Exception as e:
            seq = record.get("kinesis", {}).get("sequenceNumber", "")
            print(f"Error processing record seq={seq}: {str(e)}")
            failures.append({"itemIdentifier": seq})

    return {"batchItemFailures": failures}

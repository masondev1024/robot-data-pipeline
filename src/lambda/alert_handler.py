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


def handler(event, context):
    webhook_url = os.environ["SLACK_WEBHOOK_URL"]
    portal_url = _get_portal_url()

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
            print(f"Error processing record: {str(e)}")

    return {
        "statusCode": 200,
        "body": json.dumps("Alerts processed successfully")
    }

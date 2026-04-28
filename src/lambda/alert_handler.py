import base64
import json
import boto3
import os

sns = boto3.client("sns")

# Module-level cache for portal_url (cold start optimization)
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

def handler(event, context):
    sns_topic_arn = os.environ["SNS_TOPIC_ARN"]
    portal_url = _get_portal_url()

    for record in event["Records"]:
        try:
            # Decode Kinesis payload
            payload = json.loads(base64.b64decode(record["kinesis"]["data"]))

            # Extract alert fields
            robot_id = payload.get("robot_id", "UNKNOWN")
            motor_temp = payload.get("max_motor_temp") or payload.get("motor_temp", "?")
            timestamp = payload.get("window_end") or payload.get("timestamp", "?")

            # Format alert message with deeplink
            header = f"[⚠️ 이상 감지] robot_id: {robot_id} | motor_temp: {motor_temp}°C | 감지: {timestamp}"
            if portal_url:
                footer = f"🔗 포털: {portal_url}/?robot_id={robot_id}"
            else:
                footer = "🔗 포털 URL 조회 실패"
            message = f"{header}\n{footer}"

            # Publish to SNS
            sns.publish(
                TopicArn=sns_topic_arn,
                Subject="로봇 이상 감지 알림",
                Message=message
            )
        except Exception as e:
            print(f"Error processing record: {str(e)}")
            # Continue processing other records instead of raising

    return {
        "statusCode": 200,
        "body": json.dumps("Alerts processed successfully")
    }

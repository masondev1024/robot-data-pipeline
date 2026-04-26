import base64
import json
import os

import boto3


def handler(event, context):
    sns = boto3.client("sns")
    for record in event["Records"]:
        payload = json.loads(base64.b64decode(record["kinesis"]["data"]))
        msg = (
            f"[⚠️ 이상 감지] "
            f"robot_id: {payload['robot_id']} | "
            f"motor_temp: {payload.get('max_motor_temp', '?')}°C | "
            f"감지 시각: {payload.get('window_end', '?')}"
        )
        sns.publish(TopicArn=os.environ["SNS_TOPIC_ARN"], Message=msg)

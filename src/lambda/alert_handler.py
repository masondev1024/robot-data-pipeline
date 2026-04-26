import base64
import json
import boto3
import os

sns = boto3.client("sns")

def handler(event, context):
    sns_topic_arn = os.environ["SNS_TOPIC_ARN"]
    
    for record in event["Records"]:
        try:
            # Decode Kinesis payload
            payload = json.loads(base64.b64decode(record["kinesis"]["data"]))
            
            # Extract alert fields
            robot_id = payload.get("robot_id", "UNKNOWN")
            motor_temp = payload.get("max_motor_temp", "?")
            window_end = payload.get("window_end", "?")
            
            # Format alert message
            message = (
                f"[⚠️ 이상 감지]\n"
                f"로봇 ID: {robot_id}\n"
                f"모터 온도: {motor_temp}°C\n"
                f"감지 시각: {window_end}"
            )
            
            # Publish to SNS
            sns.publish(
                TopicArn=sns_topic_arn,
                Subject="로봇 이상 감지 알림",
                Message=message
            )
        except Exception as e:
            print(f"Error processing record: {str(e)}")
            raise
    
    return {
        "statusCode": 200,
        "body": json.dumps("Alerts processed successfully")
    }

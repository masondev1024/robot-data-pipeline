# Step 0: lambda-alert

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md` (ADR-007: SNS → Slack)
- `/terraform/modules/data_pipeline/kinesis.tf`
- `/terraform/modules/data_pipeline/iam.tf`

## 작업

두 Terraform 파일과 Lambda 핸들러 코드를 작성하라.

### `terraform/modules/data_pipeline/sns.tf`
```hcl
resource "aws_sns_topic" "alerts" {
  name = "robot-anomaly-alerts"
}

resource "aws_sns_topic_subscription" "slack" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "https"
  endpoint  = var.slack_webhook_url  # .env에서 주입
}

# variables.tf에 추가
variable "slack_webhook_url" { sensitive = true }
```

### `terraform/modules/data_pipeline/lambda.tf`
```hcl
# Lambda 패키지: src/lambda/alert_handler.py를 zip으로 압축
data "archive_file" "alert_handler" {
  type        = "zip"
  source_file = "${path.root}/../src/lambda/alert_handler.py"
  output_path = "${path.root}/lambda_alert.zip"
}

resource "aws_lambda_function" "alert" {
  function_name    = "robot-anomaly-alert-lambda"
  runtime          = "python3.11"
  handler          = "alert_handler.handler"
  filename         = data.archive_file.alert_handler.output_path
  source_code_hash = data.archive_file.alert_handler.output_base64sha256
  role             = aws_iam_role.lambda_alert.arn
  environment {
    variables = { SNS_TOPIC_ARN = aws_sns_topic.alerts.arn }
  }
}

resource "aws_lambda_event_source_mapping" "alert_kds" {
  event_source_arn  = aws_kinesis_stream.alert.arn
  function_name     = aws_lambda_function.alert.arn
  starting_position = "LATEST"
  batch_size        = 10
}

resource "aws_iam_role" "lambda_alert" {
  name               = "robot-anomaly-alert-lambda-role"
  assume_role_policy = # lambda.amazonaws.com 신뢰
}

resource "aws_iam_role_policy" "lambda_alert" {
  # kinesis:GetRecords, GetShardIterator, DescribeStream, ListStreams
  # sns:Publish
  # logs:CreateLogGroup, CreateLogStream, PutLogEvents
}
```

### `src/lambda/alert_handler.py`
```python
import base64, json, boto3, os

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
```

## Acceptance Criteria

```bash
terraform fmt -check -recursive terraform/modules/
python3 -m py_compile src/lambda/alert_handler.py
grep -q "robot-anomaly-alerts" terraform/modules/data_pipeline/sns.tf && echo "OK: SNS topic"
grep -q "robot-anomaly-alert-lambda" terraform/modules/data_pipeline/lambda.tf && echo "OK: Lambda"
grep -q "robot-anomaly-alert-stream" terraform/modules/data_pipeline/lambda.tf && echo "OK: KDS trigger"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - SNS Topic 이름이 `"robot-anomaly-alerts"`인가?
   - Lambda 이름이 `"robot-anomaly-alert-lambda"`인가?
   - Event Source Mapping이 `robot-anomaly-alert-stream`을 참조하는가?
   - Lambda IAM에 Kinesis Read + SNS Publish + CloudWatch Logs 권한이 있는가?
   - Slack Webhook URL이 `var.slack_webhook_url`로 관리되는가? (하드코딩 금지)
3. `phases/4-serving/index.json` step 0 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "sns.tf(robot-anomaly-alerts) + lambda.tf(robot-anomaly-alert-lambda, KDS 트리거) + alert_handler.py 작성"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

### 🚨 메타 파일 보호 (반드시 준수)

- **`/plan.md`(프로젝트 루트의 master plan)을 절대 수정/덮어쓰기/삭제하지 마라.** 이유: plan.md는 Phase 0~5 전체 진행 상황을 기록하는 master 문서이며, step worker의 계획 메모장이 아니다. 본 step의 출력 산출물은 오직 `terraform/modules/data_pipeline/sns.tf`, `terraform/modules/data_pipeline/lambda.tf`, `src/lambda/alert_handler.py`, 그리고 `phases/4-serving/index.json`(step 0 entry만) 4종이다.
- 프로젝트 루트의 `*.md`(plan.md, README.md, CLAUDE.md 등) 어떤 것도 수정하지 마라.
- 다른 step 디렉토리(`phases/0-setup/`, `phases/3-realtime/` 등)나 docs(`/docs/*.md`)를 수정하지 마라.

### 구현 규칙

- Slack Webhook URL을 코드나 Terraform 파일에 하드코딩하지 마라. 이유: `var.slack_webhook_url` sensitive 변수로만 관리
- Lambda에 SNS Sink를 직접 만들지 말고 SNS `Publish`만 호출하라. 이유: SNS가 Slack 구독을 처리한다
- `robot-anomaly-alert-stream` 대신 메인 스트림을 트리거로 연결하지 마라. 이유: Alert 전용 스트림을 사용해야 메인 데이터 처리에 영향 없음

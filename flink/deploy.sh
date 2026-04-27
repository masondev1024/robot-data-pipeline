#!/bin/bash
set -euo pipefail

# AWS Managed Service for Apache Flink Deployment Script
# Prerequisites: terraform state, AWS CLI, IAM permissions for Flink + S3 operations

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SCRIPT_DIR"

# Configuration
APP_NAME="robot-anomaly-detection"
RUNTIME="FLINK_1_18"
SERVICE_EXEC_ROLE_ARN=""  # Will be fetched from Terraform
S3_BUCKET=""  # Will be fetched from Terraform
S3_KEY="flink-code/anomaly_detection.zip"
KINESIS_INPUT_STREAM="robot-telemetry-stream"
KINESIS_OUTPUT_STREAM="robot-anomaly-alert-stream"
AWS_REGION="${AWS_REGION:-eu-west-1}"

echo "=== AWS Managed Service for Apache Flink Deployment ==="
echo "Application: $APP_NAME"
echo "Runtime: $RUNTIME"
echo "Region: $AWS_REGION"
echo ""

# 1) Fetch Terraform outputs
echo "[*] Fetching Terraform outputs..."
cd "$REPO_ROOT/terraform"
if ! TERRAFORM_OUTPUT=$(terraform output -json 2>/dev/null); then
    echo "[WARN] terraform output failed. Ensure terraform apply succeeded."
    echo "[*] Attempting fallback: querying IAM role and S3 bucket directly..."
else
    SERVICE_EXEC_ROLE_ARN=$(echo "$TERRAFORM_OUTPUT" | jq -r '.flink_service_execution_role_arn.value // empty')
    S3_BUCKET=$(echo "$TERRAFORM_OUTPUT" | jq -r '.datalake_bucket_name.value // empty')
fi

if [ -z "$SERVICE_EXEC_ROLE_ARN" ] || [ -z "$S3_BUCKET" ]; then
    echo "[WARN] Could not fetch all Terraform outputs."
    echo "[*] Attempting to fetch from AWS resources..."

    if [ -z "$S3_BUCKET" ]; then
        S3_BUCKET=$(aws s3 ls --region "$AWS_REGION" 2>/dev/null | grep "robot-telemetry" | awk '{print $3}' | head -1)
        echo "  Found S3 bucket: $S3_BUCKET"
    fi

    if [ -z "$SERVICE_EXEC_ROLE_ARN" ]; then
        SERVICE_EXEC_ROLE_ARN=$(aws iam list-roles --region "$AWS_REGION" 2>/dev/null | jq -r '.Roles[] | select(.RoleName | contains("flink-service")) | .Arn' | head -1)
        echo "  Found IAM role: $SERVICE_EXEC_ROLE_ARN"
    fi
fi

if [ -z "$SERVICE_EXEC_ROLE_ARN" ] || [ -z "$S3_BUCKET" ]; then
    echo "[ERROR] Could not determine Service Execution Role ARN or S3 bucket."
    echo "  Please ensure terraform apply has completed successfully."
    exit 1
fi

echo "[OK] Service Execution Role: $SERVICE_EXEC_ROLE_ARN"
echo "[OK] S3 Bucket: $S3_BUCKET"
echo ""

# 2) Build Flink application ZIP
echo "[*] Building Flink application..."
cd "$SCRIPT_DIR"
if ! bash build.sh; then
    echo "[ERROR] build.sh failed."
    exit 1
fi
echo "[OK] Flink application built successfully."
echo ""

# 3) Upload to S3
echo "[*] Uploading anomaly_detection.zip to S3..."
if aws s3 cp anomaly_detection.zip "s3://$S3_BUCKET/$S3_KEY" \
    --region "$AWS_REGION" \
    --no-progress; then
    echo "[OK] Uploaded: s3://$S3_BUCKET/$S3_KEY"
else
    echo "[ERROR] Failed to upload to S3."
    exit 1
fi
echo ""

# 4) Check if Managed Flink application exists
echo "[*] Checking if Managed Flink application exists..."
APP_DETAILS=$(aws kinesisanalyticsv2 describe-application \
    --application-name "$APP_NAME" \
    --region "$AWS_REGION" 2>/dev/null || echo "")

if [ -z "$APP_DETAILS" ]; then
    echo "[*] Application not found. Creating..."

    # Create Managed Flink application
    aws kinesisanalyticsv2 create-application \
        --application-name "$APP_NAME" \
        --runtime-environment "$RUNTIME" \
        --region "$AWS_REGION" \
        --service-execution-role-arn "$SERVICE_EXEC_ROLE_ARN" \
        --application-configuration '{
            "ApplicationCodeConfiguration": {
                "CodeContent": {
                    "S3ContentLocation": {
                        "BucketARN": "arn:aws:s3:::'$S3_BUCKET'",
                        "FileKey": "'$S3_KEY'",
                        "ObjectVersion": ""
                    }
                },
                "CodeContentType": "ZIPFILE"
            },
            "EnvironmentProperties": {
                "PropertyGroups": [
                    {
                        "PropertyGroupId": "robot-app-config",
                        "PropertyMapProperties": {
                            "KINESIS_INPUT_STREAM": "'$KINESIS_INPUT_STREAM'",
                            "KINESIS_OUTPUT_STREAM": "'$KINESIS_OUTPUT_STREAM'",
                            "AWS_REGION": "'$AWS_REGION'",
                            "ZSCORE_THRESHOLD": "3.0",
                            "SIGMA_FLOOR": "5.0",
                            "LOAD_THRESHOLD": "80",
                            "MIN_TEMP": "25"
                        }
                    }
                ]
            },
            "FlinkApplicationConfiguration": {
                "CheckpointConfiguration": {
                    "ConfigurationType": "CUSTOM",
                    "CheckpointingEnabled": true,
                    "CheckpointInterval": 60000,
                    "MinPauseBetweenCheckpoints": 5000
                },
                "MonitoringConfiguration": {
                    "ConfigurationType": "CUSTOM",
                    "MetricsLevel": "APPLICATION",
                    "LogLevel": "INFO"
                },
                "ParallelismConfiguration": {
                    "ConfigurationType": "CUSTOM",
                    "Parallelism": 4,
                    "ParallelismPerKPU": 1,
                    "AutoScalingEnabled": true
                }
            },
            "ApplicationSnapshotConfiguration": {
                "SnapshotsEnabled": true
            }
        }' > /dev/null

    echo "[OK] Application created: $APP_NAME"
    sleep 10  # Wait for application to be ready
else
    echo "[*] Application exists. Updating code..."

    # Update application code
    APP_VERSION=$(echo "$APP_DETAILS" | jq -r '.ApplicationDetail.ApplicationVersionId')

    aws kinesisanalyticsv2 update-application \
        --application-name "$APP_NAME" \
        --current-application-version-id "$APP_VERSION" \
        --region "$AWS_REGION" \
        --application-configuration '{
            "ApplicationCodeConfigurationUpdate": {
                "CodeContentUpdate": {
                    "S3ContentLocationUpdate": {
                        "BucketARNUpdate": "arn:aws:s3:::'$S3_BUCKET'",
                        "FileKeyUpdate": "'$S3_KEY'",
                        "ObjectVersionUpdate": ""
                    }
                }
            }
        }' > /dev/null

    echo "[OK] Application code updated."
fi
echo ""

# 5) Start the application
echo "[*] Starting Managed Flink application..."
APP_STATUS=$(aws kinesisanalyticsv2 describe-application \
    --application-name "$APP_NAME" \
    --region "$AWS_REGION" \
    | jq -r '.ApplicationDetail.ApplicationStatus')

if [ "$APP_STATUS" = "RUNNING" ]; then
    echo "[OK] Application is already running."
elif [ "$APP_STATUS" = "STOPPED" ] || [ "$APP_STATUS" = "CREATED" ]; then
    aws kinesisanalyticsv2 start-application \
        --application-name "$APP_NAME" \
        --region "$AWS_REGION" > /dev/null
    echo "[OK] Application started."
else
    echo "[WARN] Application status: $APP_STATUS. Manual intervention may be required."
fi
echo ""

# 6) Monitor application startup
echo "[*] Monitoring application startup (max 2 minutes)..."
for i in {1..12}; do
    sleep 10
    CURRENT_STATUS=$(aws kinesisanalyticsv2 describe-application \
        --application-name "$APP_NAME" \
        --region "$AWS_REGION" \
        | jq -r '.ApplicationDetail.ApplicationStatus')

    echo "  Attempt $i: Status = $CURRENT_STATUS"

    if [ "$CURRENT_STATUS" = "RUNNING" ]; then
        echo "[OK] Application is running!"
        break
    fi
done

echo ""
echo "=== Deployment Complete ==="
echo "Application: $APP_NAME"
echo "Status: $CURRENT_STATUS"
echo "Input Stream: $KINESIS_INPUT_STREAM"
echo "Output Stream: $KINESIS_OUTPUT_STREAM"
echo ""
echo "Next steps:"
echo "1. Verify application logs: aws logs tail /aws/kinesisanalytics/$APP_NAME --follow"
echo "2. Check metrics: AWS Console → Kinesis Analytics → Applications → $APP_NAME"
echo "3. Monitor anomaly stream: aws kinesis get-records --shard-id ... --stream-name $KINESIS_OUTPUT_STREAM"

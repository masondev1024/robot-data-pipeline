# ⚠️ DATA-ONLY DEPLOY: EKS IRSA outputs는 비활성화 시점에 제거됨.
# 복구 시 grafana_irsa_role_arn, airflow_irsa_role_arn을 다시 추가해야 addons.tf에서 참조 가능.

output "datalake_bucket" {
  description = "Data Lake S3 Bucket name (Bronze/Silver/Gold)"
  value       = aws_s3_bucket.datalake.bucket
}

output "datalake_bucket_name" {
  description = "Data Lake S3 Bucket name (for Flink deploy.sh)"
  value       = aws_s3_bucket.datalake.id
}

output "datalake_bucket_arn" {
  description = "Data Lake S3 Bucket ARN"
  value       = aws_s3_bucket.datalake.arn
}

output "flink_service_execution_role_arn" {
  description = "Flink Service Execution IAM Role ARN"
  value       = aws_iam_role.flink.arn
}

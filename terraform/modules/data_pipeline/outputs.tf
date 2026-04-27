output "grafana_irsa_role_arn" {
  description = "Grafana ServiceAccount IRSA Role ARN (Athena + CloudWatch Data Source 접근용)"
  value       = aws_iam_role.grafana_irsa.arn
}

output "airflow_irsa_role_arn" {
  description = "Airflow Worker ServiceAccount IRSA Role ARN (Athena + S3 + SNS + Bedrock)"
  value       = aws_iam_role.airflow_irsa.arn
}

output "datalake_bucket" {
  description = "Data Lake S3 Bucket name (Bronze/Silver/Gold)"
  value       = aws_s3_bucket.datalake.bucket
}

output "datalake_bucket_arn" {
  description = "Data Lake S3 Bucket ARN"
  value       = aws_s3_bucket.datalake.arn
}

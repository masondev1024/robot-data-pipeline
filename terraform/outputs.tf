# Data Pipeline Outputs (Flink Deploy용)
output "datalake_bucket_name" {
  description = "Data Lake S3 Bucket name for Flink deployment"
  value       = module.data_pipeline.datalake_bucket_name
}

output "flink_service_execution_role_arn" {
  description = "Flink Service Execution IAM Role ARN"
  value       = module.data_pipeline.flink_service_execution_role_arn
}

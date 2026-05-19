output "datalake_bucket_name" {
  description = "Data Lake S3 Bucket name"
  value       = module.data_pipeline.datalake_bucket_name
}

# ── IRSA Role ARNs (EKS 부팅 후 K8s SA annotate에 사용) ──

output "generator_irsa_role_arn" {
  description = "Generator Pod IRSA Role ARN"
  value       = module.data_pipeline.generator_irsa_role_arn
}

output "api_irsa_role_arn" {
  description = "AI Query API Pod IRSA Role ARN"
  value       = module.data_pipeline.api_irsa_role_arn
}

output "airflow_irsa_role_arn" {
  description = "Airflow Worker IRSA Role ARN"
  value       = module.data_pipeline.airflow_irsa_role_arn
}

output "grafana_irsa_role_arn" {
  description = "Grafana IRSA Role ARN"
  value       = module.data_pipeline.grafana_irsa_role_arn
}

output "alb_controller_irsa_role_arn" {
  description = "AWS Load Balancer Controller IRSA Role ARN"
  value       = module.data_pipeline.alb_controller_irsa_role_arn
}

output "aws_region" {
  description = "AWS region containing the deployed resources"
  value       = var.aws_region
}

output "eks_cluster_name" {
  description = "EKS cluster name used by deployment tooling"
  value       = aws_eks_cluster.main.name
}

output "datalake_bucket_name" {
  description = "Data Lake S3 Bucket name"
  value       = module.data_pipeline.datalake_bucket_name
}

output "generator_ecr_repository_url" {
  description = "Generator container ECR repository URL"
  value       = aws_ecr_repository.generator.repository_url
}

output "api_ecr_repository_url" {
  description = "API container ECR repository URL"
  value       = aws_ecr_repository.api.repository_url
}

output "airflow_ecr_repository_url" {
  description = "Airflow container ECR repository URL"
  value       = aws_ecr_repository.airflow.repository_url
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

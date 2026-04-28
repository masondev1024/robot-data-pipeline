output "datalake_bucket" {
  description = "Data Lake S3 Bucket name (Bronze/Silver/Gold)"
  value       = aws_s3_bucket.datalake.bucket
}

output "datalake_bucket_name" {
  description = "Data Lake S3 Bucket name"
  value       = aws_s3_bucket.datalake.id
}

output "datalake_bucket_arn" {
  description = "Data Lake S3 Bucket ARN"
  value       = aws_s3_bucket.datalake.arn
}

# ── IRSA Role ARNs (EKS 부팅 후 K8s ServiceAccount annotate에 사용) ──

output "generator_irsa_role_arn" {
  description = "Generator Pod IRSA Role ARN — kubectl annotate sa generator-sa eks.amazonaws.com/role-arn=..."
  value       = aws_iam_role.generator_irsa.arn
}

output "api_irsa_role_arn" {
  description = "AI Query API Pod IRSA Role ARN"
  value       = aws_iam_role.api_irsa.arn
}

output "airflow_irsa_role_arn" {
  description = "Airflow Worker IRSA Role ARN — Helm install 시 serviceAccount.annotations에 주입"
  value       = aws_iam_role.airflow_irsa.arn
}

output "grafana_irsa_role_arn" {
  description = "Grafana IRSA Role ARN — Helm install 시 serviceAccount.annotations에 주입"
  value       = aws_iam_role.grafana_irsa.arn
}

output "alb_controller_irsa_role_arn" {
  description = "AWS Load Balancer Controller IRSA Role ARN — Helm install 시 serviceAccount.annotations에 주입"
  value       = aws_iam_role.alb_controller.arn
}

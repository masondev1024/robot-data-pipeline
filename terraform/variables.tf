variable "aws_region" {
  default = "eu-west-1"
}

variable "project_name" {
  default = "robot-telemetry"
}

variable "s3_bucket_name" {
  description = "Data Lake S3 bucket name (Bronze/Silver/Gold layers)"
  type        = string
  default     = "de-ai-06-smartfactory-bucket"
}

variable "eks_cluster_name" {
  default = "robot-telemetry-cluster"
}

variable "vpc_cidr" {
  default = "10.0.0.0/16"
}

variable "node_instance_type" {
  default = "t3.large"
}

variable "environment" {
  default = "dev"
}

variable "github_owner" {
  default = "masondev1024"
}

variable "github_repo" {
  default = "robot-data-pipeline"
}

variable "github_branch" {
  default = "main"
}

# NOTE: slack_webhook_url 변수는 제거됨.
# Lambda는 modules/data_pipeline/lambda.tf 의 aws_secretsmanager_secret_version
# data source 로 /robot-telemetry/slack-webhook-url 에서 직접 읽는다 (single source of truth).
# 사고 회귀 방지: TF_VAR 미export 시 default 'CHANGEME' apply silent failure 차단.

variable "grafana_admin_password" {
  description = "Grafana admin password (managed by AWS Secrets Manager)"
  type        = string
  sensitive   = true
  default     = "changeme123"
}

variable "kds_main_shard_count" {
  description = "Telemetry KDS shard count. 1000 robots × 1.0s tick = 1000 records/s 부하 기준 default 2 (한도 2000 RPS 의 50% 사용, read GetRecords 한도 10/s 도 KDF+Flink 합계와 정합). 부하 증감 시 조정."
  type        = number
  default     = 2
}

variable "kds_alert_shard_count" {
  description = "Anomaly alert KDS shard count. 학습/비용 절감 기본 1. 운영 시 2 권장."
  type        = number
  default     = 1
}

variable "eks_cluster_version" {
  description = "EKS K8s version. 1.33 standard support 만료 ~2026-07. 만료 임박 시 1.34/1.35 등 새 standard 로 끌어올려서 Extended Support fee ($0.50/h, 월 $360) 회귀 차단."
  type        = string
  default     = "1.33"
}

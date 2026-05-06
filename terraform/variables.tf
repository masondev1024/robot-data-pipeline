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
  description = "Telemetry KDS shard count. 학습 환경 100 robots × 2s tick = 50 rec/s, 10 KB/s 부하 → 1 shard (1000 RPS, 1 MB/s 한도) 의 ~5% 사용으로 충분. 2 shard 운영 시 Firehose buffer flush 가 shard 간 staggered → 5분 sliding window distinct robot count 가 jitter (2026-05-04 사고). 부하 증가 시 (>500 rec/s) 만 2+ 로 복귀."
  type        = number
  default     = 1
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

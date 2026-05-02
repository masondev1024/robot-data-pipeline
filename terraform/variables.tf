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

variable "slack_webhook_url" {
  description = "Slack Incoming Webhook URL. 값은 TF_VAR_slack_webhook_url 환경변수 또는 -var 로 주입 (.env 가 source of truth). default 'CHANGEME' 는 미주입 시 fallback — git 에 실 URL 커밋 방지용 의도적 안전장치."
  type        = string
  sensitive   = true
  default     = "https://hooks.slack.com/services/CHANGEME"
}

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

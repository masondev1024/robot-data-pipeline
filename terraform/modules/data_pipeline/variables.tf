variable "project_name" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "datalake_bucket_name" {
  description = "Data Lake S3 bucket name passed from root"
  type        = string
}

variable "eks_oidc_provider_arn" {
  description = "EKS OIDC provider ARN (root에서 aws_iam_openid_connect_provider.eks.arn 전달)"
  type        = string
}

variable "eks_oidc_issuer_url" {
  description = "EKS OIDC issuer URL (root에서 aws_iam_openid_connect_provider.eks.url 전달)"
  type        = string
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "slack_webhook_url" {
  description = "Slack Webhook URL for alert notifications (injected from .env)"
  type        = string
  sensitive   = true
}

variable "grafana_admin_password" {
  description = "Grafana admin password (Helm 수동 설치 후 사용. 현재 모듈 내 미참조)"
  type        = string
  sensitive   = true
}

variable "kds_main_shard_count" {
  description = "Telemetry KDS shard count. 운영 기본 10, 발표 시연 시 -var=kds_main_shard_count=1"
  type        = number
  default     = 10
}

variable "kds_alert_shard_count" {
  description = "Anomaly alert KDS shard count. 운영 기본 2, 시연 시 1로 축소"
  type        = number
  default     = 2
}

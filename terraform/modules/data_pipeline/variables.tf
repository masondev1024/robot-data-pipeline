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

# NOTE: grafana_admin_password 변수 제거 (2026-05-19 D-3 보안 H1).
# 모듈 내 미참조 + root fallback 'changeme123' silent apply 위험 (CLAUDE.md §C).
# Grafana admin 은 K8s secret `grafana-admin` 에서 직접 read.

variable "kds_main_shard_count" {
  description = "Telemetry KDS shard count. Root default is 4 for the production-like 1000-robot baseline; override only after measuring throughput and throttling."
  type        = number
  default     = 1
}

variable "kds_alert_shard_count" {
  description = "Anomaly alert KDS shard count. Root default is 1 because alert volume is sparse; increase only after measuring throttling."
  type        = number
  default     = 1
}

variable "firehose_buffering_size_mb" {
  description = "Main telemetry Firehose buffer size in MB"
  type        = number
  default     = 128
}

variable "firehose_buffering_interval_seconds" {
  description = "Main telemetry Firehose buffering interval in seconds"
  type        = number
  default     = 300
}

variable "alert_firehose_buffering_size_mb" {
  description = "Alert archive Firehose buffer size in MB"
  type        = number
  default     = 128
}

variable "alert_firehose_buffering_interval_seconds" {
  description = "Alert archive Firehose buffering interval in seconds"
  type        = number
  default     = 300
}

variable "athena_bytes_scanned_cutoff_per_query" {
  description = "Athena per-query bytes scanned cutoff in bytes"
  type        = number
  default     = 10737418240
}

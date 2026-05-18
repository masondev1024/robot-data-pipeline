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
  description = "Telemetry KDS shard count. root variables.tf 가 100 robots × 2s tick 학습 부하 기준 default 1 를 전달 (1 shard 한도 1000 RPS 의 ~5% 사용). 2+ 시 Firehose flush stagger 회귀 위험."
  type        = number
  default     = 1
}

variable "kds_alert_shard_count" {
  description = "Anomaly alert KDS shard count. 운영 기본 2, 시연 시 1로 축소"
  type        = number
  default     = 1
}

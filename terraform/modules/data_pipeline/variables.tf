variable "project_name" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "eks_oidc_provider_arn" {
  type = string
}

variable "eks_oidc_issuer_url" {
  type = string
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "s3_bucket_name" {
  description = "사전 생성된 S3 버킷명 (Terraform으로 생성하지 않음)"
  type        = string
  default     = "de-ai-06-827913617635-ap-northeast-2-an"
}

variable "slack_webhook_url" {
  description = "Slack Webhook URL for alert notifications (injected from .env)"
  type        = string
  sensitive   = true
}

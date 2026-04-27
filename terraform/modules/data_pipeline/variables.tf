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

variable "slack_webhook_url" {
  description = "Slack Webhook URL for alert notifications (injected from .env)"
  type        = string
  sensitive   = true
}

variable "aws_region" {
  default = "eu-west-1"
}

variable "project_name" {
  default = "robot-telemetry"
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
  default = "robot-telemetry-platform"
}

variable "github_branch" {
  default = "main"
}

variable "slack_webhook_url" {
  description = "Slack Incoming Webhook URL (managed by AWS Secrets Manager)"
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
  description = "Telemetry KDS shard count. 운영 기본 10. 시연/비용 절감 시 1로 축소."
  type        = number
  default     = 10
}

variable "kds_alert_shard_count" {
  description = "Anomaly alert KDS shard count. 운영 기본 2. 시연 시 1로 축소."
  type        = number
  default     = 2
}

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
  description = "Telemetry KDS shard count. 1000 robots × 1Hz peak = 1000 rec/s 송신. 4 shard = 4000 rec/s 한계 → peak 25% 사용. 한 shard 분포 편향 30~60% 시도 한 shard 300~600 rec/s, 안전 마진 40%+. 2 shard 도 가능하나 Firehose flush stagger (2026-05-04 사고) 안전 마진 위해 4. apply 후 OpenShardCount=4 명시 검증 필수 (CLAUDE.md 가드레일, 2026-05-05 사고)."
  type        = number
  default     = 4
}

variable "kds_alert_shard_count" {
  description = "Anomaly alert KDS shard count. 1000 robots 환경에서도 분당 ~15 episode → 0.25 rec/s. 1 shard (1000 rec/s 한계) 충분."
  type        = number
  default     = 1
}

variable "generator_replicas" {
  description = "Generator StatefulSet replicas. 1단계 HPA 잠금이라 10 고정. POD_TOTAL_REPLICAS env 와 동기화 필요 — Downward API reconciler 구현 후 동적 변경."
  type        = number
  default     = 10
}

variable "generator_total_robots" {
  description = "총 robot 수. 각 pod 이 ceil(total / replicas) 만큼 담당 (StatefulSet ordinal 슬라이싱)."
  type        = number
  default     = 1000
}

variable "eks_cluster_version" {
  description = "EKS K8s version. 1.33 standard support 만료 ~2026-07. 만료 임박 시 1.34/1.35 등 새 standard 로 끌어올려서 Extended Support fee ($0.50/h, 월 $360) 회귀 차단."
  type        = string
  default     = "1.33"
}

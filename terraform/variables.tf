variable "aws_region" {
  description = "AWS region for the complete data platform. SSO directory region and service region are configured independently."
  type        = string
  default     = "ap-northeast-2"
}

variable "project_name" {
  default = "robot-telemetry"
}

variable "s3_bucket_name" {
  description = "Data Lake S3 bucket name (Bronze/Silver/Gold layers)"
  type        = string

  validation {
    condition = (
      length(var.s3_bucket_name) >= 3 &&
      length(var.s3_bucket_name) <= 63 &&
      can(regex("^[a-z0-9][a-z0-9.-]*[a-z0-9]$", var.s3_bucket_name)) &&
      !strcontains(var.s3_bucket_name, "..") &&
      !can(regex("^[0-9]{1,3}(\\.[0-9]{1,3}){3}$", var.s3_bucket_name)) &&
      !startswith(var.s3_bucket_name, "xn--") &&
      !startswith(var.s3_bucket_name, "sthree-") &&
      !startswith(var.s3_bucket_name, "amzn-s3-demo-") &&
      !endswith(var.s3_bucket_name, "-s3alias") &&
      !endswith(var.s3_bucket_name, "--ol-s3") &&
      !endswith(var.s3_bucket_name, ".mrap") &&
      !endswith(var.s3_bucket_name, "--x-s3") &&
      !endswith(var.s3_bucket_name, "--table-s3")
    )
    error_message = "s3_bucket_name must be a globally unique, AWS-compatible S3 bucket name: 3-63 lowercase letters, numbers, periods, or hyphens; begin and end with a letter or number; and not be an IP address or use an AWS-reserved prefix/suffix."
  }
}

variable "eks_cluster_name" {
  default = "robot-telemetry-cluster"
}

variable "vpc_cidr" {
  default = "10.0.0.0/16"
}

variable "node_instance_type" {
  description = "Managed node group instance type. Keep t3.large as the baseline until CPU/memory p95 supports a smaller class."
  type        = string
  default     = "t3.large"
}

variable "node_group_min_size" {
  description = "Minimum managed node group capacity. One Spot node keeps the dev data plane schedulable."
  type        = number
  default     = 1

  validation {
    condition     = var.node_group_min_size >= 0
    error_message = "node_group_min_size must be non-negative."
  }
}

variable "node_group_desired_size" {
  description = "Initial managed node group capacity. Keep this low for the cost-controlled baseline; Karpenter adds burst capacity."
  type        = number
  default     = 1

  validation {
    condition     = var.node_group_desired_size >= 0
    error_message = "node_group_desired_size must be non-negative."
  }
}

variable "node_group_max_size" {
  description = "Maximum managed node group capacity before Karpenter burst capacity is used."
  type        = number
  default     = 10

  validation {
    condition     = var.node_group_max_size >= 0
    error_message = "node_group_max_size must be non-negative."
  }
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

variable "manage_github_oidc_provider" {
  description = "Create and own the GitHub Actions OIDC provider only when the AWS account does not already have the shared provider. Keep false for accounts with an existing provider so teardown cannot remove it."
  type        = bool
  default     = false
}

# NOTE: slack_webhook_url 변수는 제거됨.
# Lambda는 modules/data_pipeline/lambda.tf 의 aws_secretsmanager_secret_version
# data source 로 /robot-telemetry/slack-webhook-url 에서 직접 읽는다 (single source of truth).
# 사고 회귀 방지: TF_VAR 미export 시 default 'CHANGEME' apply silent failure 차단.

# NOTE: grafana_admin_password 변수는 제거됨 (2026-05-19 D-3 보안 점검 H1 fix).
# Grafana admin 은 K8s secret `grafana-admin` (k8s/monitoring/grafana-deployment.yaml:40,45)
# 에서 직접 read 하며, terraform 모듈은 변수만 정의했을 뿐 미참조였다.
# 사고 회귀 방지: CLAUDE.md §C — fallback default 'changeme123' silent apply 금지.
# Secrets Manager data source 패턴 (slack_webhook 참조) 으로 향후 통합 시 추가.

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

variable "kds_iterator_age_threshold_milliseconds" {
  description = "Kinesis consumer lag SLO threshold. 120 seconds is the default streaming freshness budget."
  type        = number
  default     = 120000

  validation {
    condition     = var.kds_iterator_age_threshold_milliseconds > 0
    error_message = "kds_iterator_age_threshold_milliseconds must be greater than zero."
  }
}

variable "firehose_data_freshness_threshold_seconds" {
  description = "Firehose S3 delivery freshness SLO threshold."
  type        = number
  default     = 600

  validation {
    condition     = var.firehose_data_freshness_threshold_seconds > 0
    error_message = "firehose_data_freshness_threshold_seconds must be greater than zero."
  }
}

variable "lambda_reserved_concurrency" {
  description = "Optional alert Lambda reserved concurrency. Null preserves the account unreserved pool during short-lived validation."
  type        = number
  default     = null
  nullable    = true

  validation {
    condition     = var.lambda_reserved_concurrency == null || var.lambda_reserved_concurrency >= 0
    error_message = "lambda_reserved_concurrency must be null or a non-negative number."
  }
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
  description = "Pinned EKS Kubernetes version. 1.35 is a currently standard-supported, region-verified baseline; upgrade deliberately after addon/chart compatibility checks."
  type        = string
  default     = "1.35"
}

variable "firehose_buffering_size_mb" {
  description = "Main telemetry Firehose buffer size in MB. Larger buffers reduce S3 PUT frequency but increase delivery latency."
  type        = number
  default     = 128

  validation {
    condition     = var.firehose_buffering_size_mb >= 1 && var.firehose_buffering_size_mb <= 128
    error_message = "firehose_buffering_size_mb must be between 1 and 128 MB."
  }
}

variable "firehose_buffering_interval_seconds" {
  description = "Main telemetry Firehose buffering interval. 300 seconds is the cost/freshness baseline."
  type        = number
  default     = 300

  validation {
    condition     = var.firehose_buffering_interval_seconds >= 60 && var.firehose_buffering_interval_seconds <= 900
    error_message = "firehose_buffering_interval_seconds must be between 60 and 900 seconds."
  }
}

variable "alert_firehose_buffering_size_mb" {
  description = "Alert archive Firehose buffer size in MB. Keep at or below the main stream unless alert volume is measured."
  type        = number
  default     = 128

  validation {
    condition     = var.alert_firehose_buffering_size_mb >= 1 && var.alert_firehose_buffering_size_mb <= 128
    error_message = "alert_firehose_buffering_size_mb must be between 1 and 128 MB."
  }
}

variable "alert_firehose_buffering_interval_seconds" {
  description = "Alert archive Firehose buffering interval."
  type        = number
  default     = 300

  validation {
    condition     = var.alert_firehose_buffering_interval_seconds >= 60 && var.alert_firehose_buffering_interval_seconds <= 900
    error_message = "alert_firehose_buffering_interval_seconds must be between 60 and 900 seconds."
  }
}

variable "athena_bytes_scanned_cutoff_per_query" {
  description = "Athena per-query bytes scanned cutoff in bytes. 10 GiB preserves the current daily ETL baseline while preventing unbounded scans; lower for dev after measuring workload."
  type        = number
  default     = 10737418240

  validation {
    condition     = var.athena_bytes_scanned_cutoff_per_query >= 1048576
    error_message = "athena_bytes_scanned_cutoff_per_query must be at least 1 MiB."
  }
}

variable "allow_full_stack_apply" {
  description = "Explicit cost approval gate for the complete EKS/EC2/NAT/ALB/RDS/SageMaker stack."
  type        = bool
  default     = false
}

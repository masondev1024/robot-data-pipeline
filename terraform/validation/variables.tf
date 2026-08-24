variable "aws_region" {
  description = "AWS region for the short-lived pipeline validation stack."
  type        = string
  default     = "eu-west-1"
}

variable "project_name" {
  description = "Unique prefix for validation resources."
  type        = string
  default     = "robot-telemetry-validation"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,39}$", var.project_name))
    error_message = "project_name must be 3-40 characters of lowercase letters, numbers, or hyphens and start with a letter."
  }
}

variable "s3_bucket_name" {
  description = "Globally unique S3 bucket for short-lived Parquet evidence."
  type        = string

  validation {
    condition = (
      length(var.s3_bucket_name) >= 3 &&
      length(var.s3_bucket_name) <= 63 &&
      can(regex("^[a-z0-9][a-z0-9.-]*[a-z0-9]$", var.s3_bucket_name)) &&
      !strcontains(var.s3_bucket_name, "..") &&
      !can(regex("^[0-9]{1,3}(\\.[0-9]{1,3}){3}$", var.s3_bucket_name))
    )
    error_message = "s3_bucket_name must be a globally unique AWS-compatible S3 bucket name."
  }
}

variable "kds_main_shard_count" {
  description = "Two shards provide 50% headroom for a 1,000-record/s validation burst."
  type        = number
  default     = 2

  validation {
    condition     = var.kds_main_shard_count >= 1 && var.kds_main_shard_count <= 10
    error_message = "kds_main_shard_count must be between 1 and 10."
  }
}

variable "kds_retention_period_hours" {
  description = "Minimum Kinesis retention; short-lived validation does not need extended replay history."
  type        = number
  default     = 24

  validation {
    condition     = var.kds_retention_period_hours >= 24 && var.kds_retention_period_hours <= 168
    error_message = "kds_retention_period_hours must be between 24 and 168."
  }
}

variable "firehose_buffering_size_mb" {
  description = "Minimum buffer required for Firehose record format conversion; production buffering is configured separately."
  type        = number
  default     = 64

  validation {
    condition     = var.firehose_buffering_size_mb >= 1 && var.firehose_buffering_size_mb <= 128
    error_message = "firehose_buffering_size_mb must be between 1 and 128; use at least 64 when Parquet conversion is enabled."
  }
}

variable "firehose_buffering_interval_seconds" {
  description = "Flush interval for short-lived freshness verification."
  type        = number
  default     = 60

  validation {
    condition     = var.firehose_buffering_interval_seconds >= 60 && var.firehose_buffering_interval_seconds <= 900
    error_message = "firehose_buffering_interval_seconds must be between 60 and 900."
  }
}

variable "firehose_freshness_threshold_seconds" {
  description = "Validation freshness budget aligned with the one-minute buffer."
  type        = number
  default     = 120

  validation {
    condition     = var.firehose_freshness_threshold_seconds > 0
    error_message = "firehose_freshness_threshold_seconds must be greater than zero."
  }
}

variable "enable_parquet_conversion" {
  description = "Keep Parquet conversion enabled for the integrated lakehouse validation."
  type        = bool
  default     = true
}

variable "validation_object_expiration_days" {
  description = "Automatic expiration for test evidence; destroy still removes the bucket immediately."
  type        = number
  default     = 1

  validation {
    condition     = var.validation_object_expiration_days >= 1 && var.validation_object_expiration_days <= 7
    error_message = "validation_object_expiration_days must be between 1 and 7."
  }
}

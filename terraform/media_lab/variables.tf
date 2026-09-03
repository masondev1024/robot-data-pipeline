variable "project_name" {
  type        = string
  description = "Short-lived media lab resource prefix."
  default     = "robot-media-lab"

  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.project_name))
    error_message = "project_name must contain only lowercase letters, digits, and hyphens."
  }
}

variable "run_id" {
  type        = string
  description = "Unique run identifier used in globally unique S3 and CloudFront names."
  default     = "20260824"

  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.run_id))
    error_message = "run_id must contain only lowercase letters, digits, and hyphens."
  }
}

variable "aws_profile" {
  type        = string
  description = "AWS CLI profile used only for this disposable lab."
  default     = "develope-test"
}

variable "primary_region" {
  type        = string
  description = "Primary HLS origin region."
  default     = "eu-west-1"
}

variable "secondary_region" {
  type        = string
  description = "Secondary HLS origin region."
  default     = "us-east-1"
}

variable "hls_prefix" {
  type        = string
  description = "Object prefix uploaded by the HLS asset script."
  default     = "media"

  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.hls_prefix))
    error_message = "hls_prefix must contain only lowercase letters, digits, and hyphens."
  }
}

locals {
  name = "${var.project_name}-${var.run_id}"

  common_tags = {
    Project       = var.project_name
    RunId         = var.run_id
    ManagedBy     = "terraform"
    Lifecycle     = "short-lived-media-lab"
    CostOwner     = "robot-data-pipeline"
    TeardownAfter = "verification"
  }
}

variable "aws_region" {
  description = "AWS service region for the short-lived migration lab."
  type        = string
  default     = "ap-northeast-2"
}

variable "project_name" {
  description = "Lowercase resource prefix."
  type        = string
  default     = "robot-glue-rds-lab"
}

variable "db_username" {
  description = "Non-root lab database user."
  type        = string
  default     = "labadmin"
}

variable "rds_instance_class" {
  description = "Smallest practical MySQL instance for the short-lived lab."
  type        = string
  default     = "db.t4g.micro"
}

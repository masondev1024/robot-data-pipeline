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
  default = "10.0.32.0/16"
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

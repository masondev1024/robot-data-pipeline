terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = var.primary_region
  profile = var.aws_profile

  default_tags {
    tags = local.common_tags
  }
}

provider "aws" {
  alias   = "primary"
  region  = var.primary_region
  profile = var.aws_profile

  default_tags {
    tags = local.common_tags
  }
}

provider "aws" {
  alias   = "secondary"
  region  = var.secondary_region
  profile = var.aws_profile

  default_tags {
    tags = local.common_tags
  }
}

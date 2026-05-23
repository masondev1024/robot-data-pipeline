# S3 Data Lake Bucket
# force_destroy: terraform destroy 가 BucketNotEmpty 로 막혀 EKS·VPC 까지 청산 못 하는
# 사고 회피 (2026-05-23 — versioning 28개 object 잔여로 3차 시도 필요). 운영 데이터는
# Bronze→Glacier IR 라이프사이클로 archived 되어 본 bucket 자체 삭제 risk 는 낮음.
resource "aws_s3_bucket" "datalake" {
  bucket        = var.datalake_bucket_name
  force_destroy = true

  tags = {
    Name = "robot-telemetry-datalake"
  }
}

# S3 Lifecycle Policy
resource "aws_s3_bucket_lifecycle_configuration" "datalake" {
  bucket = aws_s3_bucket.datalake.id

  rule {
    id     = "bronze-to-glacier"
    status = "Enabled"

    filter {
      prefix = "bronze/"
    }

    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }
  }

  rule {
    id     = "silver-to-glacier"
    status = "Enabled"

    filter {
      prefix = "silver/"
    }

    transition {
      days          = 365
      storage_class = "GLACIER_IR"
    }
  }

  rule {
    id     = "dlq-expiration"
    status = "Enabled"

    filter {
      prefix = "bronze-dlq/"
    }

    expiration {
      days = 30
    }
  }
}

# Enable versioning for data protection
resource "aws_s3_bucket_versioning" "datalake" {
  bucket = aws_s3_bucket.datalake.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Block public access
resource "aws_s3_bucket_public_access_block" "datalake" {
  bucket = aws_s3_bucket.datalake.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

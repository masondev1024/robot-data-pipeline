# S3 Data Lake Bucket
resource "aws_s3_bucket" "datalake" {
  bucket = "de-ai-06-smartfactory-bucket"

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

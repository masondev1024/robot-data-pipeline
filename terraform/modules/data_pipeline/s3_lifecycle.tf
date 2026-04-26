data "aws_s3_bucket" "main" {
  bucket = var.s3_bucket_name
}

resource "aws_s3_bucket_lifecycle_configuration" "data_lake" {
  bucket = data.aws_s3_bucket.main.id

  rule {
    id     = "bronze-glacier"
    status = "Enabled"
    filter { prefix = "bronze/" }
    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }
  }

  rule {
    id     = "silver-glacier"
    status = "Enabled"
    filter { prefix = "silver/" }
    transition {
      days          = 365
      storage_class = "GLACIER_IR"
    }
  }

  rule {
    id     = "dlq-expire"
    status = "Enabled"
    filter { prefix = "bronze-dlq/" }
    expiration { days = 30 }
  }
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "primary" {
  provider      = aws.primary
  bucket        = "${local.name}-primary"
  force_destroy = true
}

resource "aws_s3_bucket" "secondary" {
  provider      = aws.secondary
  bucket        = "${local.name}-secondary"
  force_destroy = true
}

resource "aws_s3_bucket_ownership_controls" "primary" {
  provider = aws.primary
  bucket   = aws_s3_bucket.primary.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_ownership_controls" "secondary" {
  provider = aws.secondary
  bucket   = aws_s3_bucket.secondary.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "primary" {
  provider = aws.primary
  bucket   = aws_s3_bucket.primary.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "secondary" {
  provider = aws.secondary
  bucket   = aws_s3_bucket.secondary.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_cors_configuration" "primary" {
  provider = aws.primary
  bucket   = aws_s3_bucket.primary.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD", "OPTIONS"]
    allowed_origins = ["*"]
    expose_headers  = ["ETag", "Content-Length"]
    max_age_seconds = 300
  }
}

resource "aws_s3_bucket_cors_configuration" "secondary" {
  provider = aws.secondary
  bucket   = aws_s3_bucket.secondary.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD", "OPTIONS"]
    allowed_origins = ["*"]
    expose_headers  = ["ETag", "Content-Length"]
    max_age_seconds = 300
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "primary" {
  provider = aws.primary
  bucket   = aws_s3_bucket.primary.id

  rule {
    id     = "expire-short-lived-media"
    status = "Enabled"

    filter {}

    expiration {
      days = 1
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "secondary" {
  provider = aws.secondary
  bucket   = aws_s3_bucket.secondary.id

  rule {
    id     = "expire-short-lived-media"
    status = "Enabled"

    filter {}

    expiration {
      days = 1
    }
  }
}

resource "aws_cloudfront_origin_access_control" "media" {
  name                              = "${local.name}-oac"
  description                       = "Short-lived HLS media lab origin access control"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_cache_policy" "playlist" {
  name        = "${local.name}-playlist-cache"
  comment     = "Short TTL for HLS playlists"
  default_ttl = 2
  max_ttl     = 5
  min_ttl     = 0

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config {
      cookie_behavior = "none"
    }

    headers_config {
      header_behavior = "none"
    }

    query_strings_config {
      query_string_behavior = "none"
    }

    enable_accept_encoding_brotli = true
    enable_accept_encoding_gzip   = true
  }
}

resource "aws_cloudfront_cache_policy" "segment" {
  name        = "${local.name}-segment-cache"
  comment     = "Longer TTL for immutable HLS segments"
  default_ttl = 300
  max_ttl     = 86400
  min_ttl     = 0

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config {
      cookie_behavior = "none"
    }

    headers_config {
      header_behavior = "none"
    }

    query_strings_config {
      query_string_behavior = "none"
    }

    enable_accept_encoding_brotli = true
    enable_accept_encoding_gzip   = true
  }
}

resource "aws_cloudfront_response_headers_policy" "hls_cors" {
  name    = "${local.name}-hls-cors"
  comment = "CORS headers for browser HLS clients"

  cors_config {
    access_control_allow_credentials = false

    access_control_allow_headers {
      items = ["*"]
    }

    access_control_allow_methods {
      items = ["GET", "HEAD", "OPTIONS"]
    }

    access_control_allow_origins {
      items = ["*"]
    }

    origin_override = true
  }
}

resource "aws_cloudfront_distribution" "primary" {
  enabled             = true
  comment             = "${local.name} primary HLS distribution"
  default_root_object = "${var.hls_prefix}/index.m3u8"
  price_class         = "PriceClass_100"

  origin {
    domain_name              = aws_s3_bucket.primary.bucket_regional_domain_name
    origin_id                = "${local.name}-primary-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.media.id
  }

  default_cache_behavior {
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    target_origin_id           = "${local.name}-primary-s3"
    viewer_protocol_policy     = "redirect-to-https"
    cache_policy_id            = aws_cloudfront_cache_policy.segment.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.hls_cors.id
    compress                   = true
  }

  ordered_cache_behavior {
    path_pattern               = "${var.hls_prefix}/*.m3u8"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    target_origin_id           = "${local.name}-primary-s3"
    viewer_protocol_policy     = "redirect-to-https"
    cache_policy_id            = aws_cloudfront_cache_policy.playlist.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.hls_cors.id
    compress                   = true
  }

  ordered_cache_behavior {
    path_pattern               = "${var.hls_prefix}/*.ts"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    target_origin_id           = "${local.name}-primary-s3"
    viewer_protocol_policy     = "redirect-to-https"
    cache_policy_id            = aws_cloudfront_cache_policy.segment.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.hls_cors.id
    compress                   = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

resource "aws_cloudfront_distribution" "secondary" {
  enabled             = true
  comment             = "${local.name} secondary HLS distribution"
  default_root_object = "${var.hls_prefix}/index.m3u8"
  price_class         = "PriceClass_100"

  origin {
    domain_name              = aws_s3_bucket.secondary.bucket_regional_domain_name
    origin_id                = "${local.name}-secondary-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.media.id
  }

  default_cache_behavior {
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    target_origin_id           = "${local.name}-secondary-s3"
    viewer_protocol_policy     = "redirect-to-https"
    cache_policy_id            = aws_cloudfront_cache_policy.segment.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.hls_cors.id
    compress                   = true
  }

  ordered_cache_behavior {
    path_pattern               = "${var.hls_prefix}/*.m3u8"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    target_origin_id           = "${local.name}-secondary-s3"
    viewer_protocol_policy     = "redirect-to-https"
    cache_policy_id            = aws_cloudfront_cache_policy.playlist.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.hls_cors.id
    compress                   = true
  }

  ordered_cache_behavior {
    path_pattern               = "${var.hls_prefix}/*.ts"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    target_origin_id           = "${local.name}-secondary-s3"
    viewer_protocol_policy     = "redirect-to-https"
    cache_policy_id            = aws_cloudfront_cache_policy.segment.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.hls_cors.id
    compress                   = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

data "aws_iam_policy_document" "primary_bucket" {
  statement {
    sid    = "AllowCloudFrontReadOnly"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.primary.arn}/*"]

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.primary.arn]
    }
  }
}

data "aws_iam_policy_document" "secondary_bucket" {
  statement {
    sid    = "AllowCloudFrontReadOnly"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.secondary.arn}/*"]

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.secondary.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "primary" {
  provider = aws.primary
  bucket   = aws_s3_bucket.primary.id
  policy   = data.aws_iam_policy_document.primary_bucket.json
}

resource "aws_s3_bucket_policy" "secondary" {
  provider = aws.secondary
  bucket   = aws_s3_bucket.secondary.id
  policy   = data.aws_iam_policy_document.secondary_bucket.json
}

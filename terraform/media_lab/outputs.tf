output "primary_bucket" {
  value       = aws_s3_bucket.primary.bucket
  description = "Private S3 bucket for the primary HLS origin."
}

output "secondary_bucket" {
  value       = aws_s3_bucket.secondary.bucket
  description = "Private S3 bucket for the secondary HLS origin."
}

output "primary_cloudfront_domain" {
  value       = aws_cloudfront_distribution.primary.domain_name
  description = "Primary CloudFront distribution domain."
}

output "secondary_cloudfront_domain" {
  value       = aws_cloudfront_distribution.secondary.domain_name
  description = "Secondary CloudFront distribution domain."
}

output "primary_cloudfront_id" {
  value       = aws_cloudfront_distribution.primary.id
  description = "Primary CloudFront distribution ID for invalidation/teardown evidence."
}

output "secondary_cloudfront_id" {
  value       = aws_cloudfront_distribution.secondary.id
  description = "Secondary CloudFront distribution ID for invalidation/teardown evidence."
}

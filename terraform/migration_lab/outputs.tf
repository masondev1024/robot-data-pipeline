output "aws_region" {
  value = var.aws_region
}

output "bucket_name" {
  value = aws_s3_bucket.lab.bucket
}

output "rds_endpoint" {
  value = aws_db_instance.lab.address
}

output "rds_secret_arn" {
  value = aws_secretsmanager_secret.rds.arn
}

output "bootstrap_job_name" {
  value = aws_glue_job.bootstrap.name
}

output "extract_job_name" {
  value = aws_glue_job.extract.name
}

output "promote_job_name" {
  value = aws_glue_job.promote.name
}

output "verify_job_name" {
  value = aws_glue_job.verify.name
}

output "aws_region" {
  value = var.aws_region
}

output "stream_name" {
  value = aws_kinesis_stream.main.name
}

output "firehose_name" {
  value = aws_kinesis_firehose_delivery_stream.main.name
}

output "datalake_bucket_name" {
  value = aws_s3_bucket.datalake.bucket
}

output "validation_profile" {
  value = {
    eks                         = false
    nat_gateway                 = false
    ec2                         = false
    ecr                         = false
    main_shards                 = var.kds_main_shard_count
    firehose_buffer_mb          = var.firehose_buffering_size_mb
    firehose_buffer_seconds     = var.firehose_buffering_interval_seconds
    parquet_conversion_enabled  = var.enable_parquet_conversion
    freshness_threshold_seconds = var.firehose_freshness_threshold_seconds
  }
}

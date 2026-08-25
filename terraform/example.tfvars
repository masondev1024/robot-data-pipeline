# Copy this file to terraform.tfvars and replace the example identifiers with
# values that are unique to your AWS account and environment.

aws_region       = "ap-northeast-2"
project_name     = "acme-robot-telemetry"
environment      = "dev"
eks_cluster_name = "acme-robot-telemetry-dev"

# S3 bucket names are globally unique. Include your AWS account ID or another
# organization-specific identifier before applying.
s3_bucket_name = "acme-robot-telemetry-dev-123456789012"

vpc_cidr                = "10.0.0.0/16"
node_instance_type      = "t3.large"
eks_cluster_version     = "1.35"
node_group_min_size     = 1
node_group_desired_size = 1
node_group_max_size     = 10

github_owner  = "acme-engineering"
github_repo   = "robot-data-pipeline"
github_branch = "main"

kds_main_shard_count   = 4
kds_alert_shard_count  = 1
generator_replicas     = 10
generator_total_robots = 1000

# Cost/freshness knobs. Keep the production-like baseline until measured;
# reduce only after validating freshness and delivery-error SLOs.
firehose_buffering_size_mb                = 128
firehose_buffering_interval_seconds       = 300
alert_firehose_buffering_size_mb          = 128
alert_firehose_buffering_interval_seconds = 300
athena_bytes_scanned_cutoff_per_query     = 10737418240

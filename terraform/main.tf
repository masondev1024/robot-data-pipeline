module "data_pipeline" {
  source = "./modules/data_pipeline"

  project_name          = var.project_name
  aws_region            = var.aws_region
  environment           = var.environment
  datalake_bucket_name  = var.s3_bucket_name
  kds_main_shard_count  = var.kds_main_shard_count
  kds_alert_shard_count = var.kds_alert_shard_count

  kds_iterator_age_threshold_milliseconds   = var.kds_iterator_age_threshold_milliseconds
  firehose_data_freshness_threshold_seconds = var.firehose_data_freshness_threshold_seconds

  # EKS OIDC — 루트 eks_and_iam.tf 의 OIDC provider 참조
  eks_oidc_provider_arn = aws_iam_openid_connect_provider.eks.arn
  eks_oidc_issuer_url   = aws_iam_openid_connect_provider.eks.url

  depends_on = [aws_iam_openid_connect_provider.eks]
}

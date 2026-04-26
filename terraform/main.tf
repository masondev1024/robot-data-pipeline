module "data_pipeline" {
  source = "./modules/data_pipeline"

  project_name          = var.project_name
  aws_region            = var.aws_region
  eks_oidc_provider_arn = aws_iam_openid_connect_provider.eks.arn
  eks_oidc_issuer_url   = aws_iam_openid_connect_provider.eks.url
  environment           = var.environment
  s3_bucket_name        = "de-ai-06-827913617635-ap-northeast-2-an"
}

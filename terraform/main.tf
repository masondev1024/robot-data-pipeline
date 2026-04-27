module "data_pipeline" {
  source = "./modules/data_pipeline"

  project_name            = var.project_name
  aws_region              = var.aws_region
  eks_oidc_provider_arn   = aws_iam_openid_connect_provider.eks.arn
  eks_oidc_issuer_url     = aws_iam_openid_connect_provider.eks.url
  environment             = var.environment
  slack_webhook_url       = var.slack_webhook_url
  grafana_admin_password  = var.grafana_admin_password
}

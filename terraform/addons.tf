resource "helm_release" "adot_operator" {
  name             = "adot-operator"
  repository       = "https://aws.github.io/eks-charts"
  chart            = "aws-otel-operator"
  namespace        = "monitoring"
  create_namespace = false
  version          = "0.3.0"

  set {
    name  = "manager.env.AWS_REGION"
    value = var.aws_region
  }
}

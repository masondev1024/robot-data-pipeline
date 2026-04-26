# AWS Load Balancer Controller
resource "aws_iam_role" "alb_controller" {
  name = "${var.project_name}-alb-controller-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRoleWithWebIdentity"
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.eks.arn
      }
      Condition = {
        StringEquals = {
          "${replace(aws_iam_openid_connect_provider.eks.url, "https://", "")}:sub" : "system:serviceaccount:kube-system:aws-load-balancer-controller"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "alb_controller" {
  name = "${var.project_name}-alb-controller-policy"
  role = aws_iam_role.alb_controller.id

  policy = file("${path.module}/policies/alb_controller_policy.json") # I'll need to create this or find it
}

resource "helm_release" "alb_controller" {
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  namespace  = "kube-system"

  set {
    name  = "clusterName"
    value = var.eks_cluster_name
  }

  set {
    name  = "serviceAccount.create"
    value = "true"
  }

  set {
    name  = "serviceAccount.name"
    value = "aws-load-balancer-controller"
  }

  set {
    name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
    value = aws_iam_role.alb_controller.arn
  }

  depends_on = [aws_eks_node_group.main]
}

# External Secrets Operator
resource "helm_release" "external_secrets" {
  name             = "external-secrets"
  repository       = "https://charts.external-secrets.io"
  chart            = "external-secrets"
  namespace        = "kube-system"
  create_namespace = false

  depends_on = [aws_eks_node_group.main]
}

# Airflow
resource "helm_release" "airflow" {
  name             = "airflow"
  repository       = "https://airflow.apache.org"
  chart            = "airflow"
  namespace        = "airflow"
  create_namespace = true

  set {
    name  = "executor"
    value = "KubernetesExecutor"
  }

  depends_on = [aws_eks_node_group.main]
}

# Grafana
resource "helm_release" "grafana" {
  name             = "grafana"
  repository       = "https://grafana.github.io/helm-charts"
  chart            = "grafana"
  namespace        = "monitoring"
  create_namespace = true

  set {
    name  = "adminPassword"
    value = var.grafana_admin_password
  }

  set {
    name  = "service.type"
    value = "ClusterIP"
  }

  set {
    name  = "persistence.enabled"
    value = "true"
  }

  set {
    name  = "grafana\\.ini.security.allow_embedding"
    value = "true"
  }

  set {
    name  = "grafana\\.ini.auth\\.anonymous.enabled"
    value = "true"
  }

  set {
    name  = "grafana\\.ini.auth\\.anonymous.org_role"
    value = "Viewer"
  }

  depends_on = [aws_eks_node_group.main]
}

# ADOT Operator (OpenTelemetry)
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

  depends_on = [aws_eks_node_group.main]
}

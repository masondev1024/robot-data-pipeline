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
  timeout    = 600

  values = [jsonencode({
    clusterName = var.eks_cluster_name
    serviceAccount = {
      create = true
      name   = "aws-load-balancer-controller"
      annotations = {
        "eks.amazonaws.com/role-arn" = aws_iam_role.alb_controller.arn
      }
    }
  })]

  depends_on = [aws_eks_node_group.main]
}

# External Secrets Operator
resource "helm_release" "external_secrets" {
  name             = "external-secrets"
  repository       = "https://charts.external-secrets.io"
  chart            = "external-secrets"
  namespace        = "kube-system"
  create_namespace = false
  timeout          = 600

  depends_on = [aws_eks_node_group.main]
}

# Airflow
resource "helm_release" "airflow" {
  name             = "airflow"
  repository       = "https://airflow.apache.org"
  chart            = "airflow"
  namespace        = "airflow"
  create_namespace = true
  timeout          = 900

  values = [jsonencode({
    executor = "KubernetesExecutor"
    # Worker IRSA — DAG 안에서 Athena/S3/SNS/Bedrock 호출 권한 (KubernetesExecutor의 Worker Pod에 적용)
    workers = {
      serviceAccount = {
        create = true
        name   = "airflow-worker"
        annotations = {
          "eks.amazonaws.com/role-arn" = module.data_pipeline.airflow_irsa_role_arn
        }
      }
    }
  })]

  depends_on = [aws_eks_node_group.main, module.data_pipeline]
}

# Grafana
resource "helm_release" "grafana" {
  name             = "grafana"
  repository       = "https://grafana.github.io/helm-charts"
  chart            = "grafana"
  namespace        = "monitoring"
  create_namespace = true
  timeout          = 600

  values = [jsonencode({
    adminPassword = var.grafana_admin_password
    service = {
      type = "ClusterIP"
    }
    persistence = {
      enabled = true
    }
    "grafana.ini" = {
      security = {
        allow_embedding = true
      }
      auth = {
        anonymous = {
          enabled  = true
          org_role = "Viewer"
        }
      }
    }

    # Plugins (Athena, X-Ray; CloudWatch는 built-in)
    plugins = [
      "grafana-athena-datasource",
      "grafana-x-ray-datasource",
    ]

    # ServiceAccount IRSA — Athena + CloudWatch 접근 권한
    serviceAccount = {
      create = true
      name   = "grafana"
      annotations = {
        "eks.amazonaws.com/role-arn" = module.data_pipeline.grafana_irsa_role_arn
      }
    }

    # Data Sources 자동 프로비저닝
    datasources = {
      "datasources.yaml" = {
        apiVersion = 1
        datasources = [
          {
            name      = "CloudWatch"
            type      = "cloudwatch"
            uid       = "cloudwatch"
            access    = "proxy"
            isDefault = false
            jsonData = {
              authType      = "default"
              defaultRegion = var.aws_region
            }
          },
          {
            name      = "Athena"
            type      = "grafana-athena-datasource"
            uid       = "athena"
            access    = "proxy"
            isDefault = true
            jsonData = {
              authType      = "default"
              defaultRegion = var.aws_region
              catalog       = "AwsDataCatalog"
              database      = "robot_telemetry_db"
              workgroup     = "robot-telemetry-workgroup"
              outputLocation = "s3://${module.data_pipeline.datalake_bucket}/project-athena-results/"
            }
          },
          {
            name   = "X-Ray"
            type   = "grafana-x-ray-datasource"
            uid    = "xray"
            access = "proxy"
            jsonData = {
              authType      = "default"
              defaultRegion = var.aws_region
            }
          },
        ]
      }
    }
  })]

  depends_on = [aws_eks_node_group.main, module.data_pipeline]
}

# ADOT Operator (OpenTelemetry) — TODO: chart not found in AWS repository
# Commented out for initial deployment. Enable after verifying correct chart name/repository.
# resource "helm_release" "adot_operator" {
#   name             = "adot-operator"
#   repository       = "https://aws.github.io/eks-charts"
#   chart            = "aws-otel-operator"
#   namespace        = "monitoring"
#   create_namespace = false
#
#   values = [jsonencode({
#     manager = {
#       env = {
#         AWS_REGION = var.aws_region
#       }
#     }
#   })]
#
#   depends_on = [aws_eks_node_group.main]
# }

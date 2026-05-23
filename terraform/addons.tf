# ── ADOT Operator EKS Add-on (Task 5.1 line 390) ──────────────────────
# AWS Distro for OpenTelemetry — Generator/API pod 의 OTEL annotation 기반
# auto-instrumentation 활성화. EKS Add-on 으로 AWS 가 lifecycle 관리.
#
# 사전 의존: cert-manager (ADOT Operator webhook TLS). EKS Add-on 자체는
# cert-manager 를 자동 설치하지 않음. terraform apply 전 1회 helm install:
#   helm repo add jetstack https://charts.jetstack.io
#   helm install cert-manager jetstack/cert-manager \
#     -n cert-manager --create-namespace --set crds.enabled=true
#
# Add-on apply 후 Collector + Instrumentation CR 은 별도 yaml apply 필요:
#   kubectl apply -f k8s/monitoring/adot/
#
# 의존: aws_iam_openid_connect_provider.eks (eks_and_iam.tf), Generator/API
# deployment 의 instrumentation.opentelemetry.io/inject-python: "true" annotation
# (이미 적용됨, k8s/{generator,api}/deployment.yaml).

data "aws_iam_policy_document" "adot_collector_assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.eks.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${trimprefix(aws_iam_openid_connect_provider.eks.url, "https://")}:sub"
      # ADOT Collector SA 이름은 Collector CR 의 spec.serviceAccount 값과 일치.
      # k8s/monitoring/adot/collector.yaml 에서 동일 이름으로 정의.
      values = ["system:serviceaccount:opentelemetry-operator-system:adot-collector-sa"]
    }

    condition {
      test     = "StringEquals"
      variable = "${trimprefix(aws_iam_openid_connect_provider.eks.url, "https://")}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "adot_collector" {
  name               = "${var.project_name}-adot-collector-irsa"
  assume_role_policy = data.aws_iam_policy_document.adot_collector_assume_role.json

  tags = {
    Name = "${var.project_name}-adot-collector-irsa"
  }
}

# X-Ray PutTraceSegments + PutTelemetryRecords + CloudWatch metrics put.
resource "aws_iam_role_policy_attachment" "adot_xray" {
  role       = aws_iam_role.adot_collector.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_iam_role_policy_attachment" "adot_cloudwatch" {
  role       = aws_iam_role.adot_collector.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

# ADOT EKS Add-on 자체. cert-manager 가 사전 설치되어 있어야 install success.
resource "aws_eks_addon" "adot" {
  cluster_name             = aws_eks_cluster.main.name
  addon_name               = "adot"
  service_account_role_arn = aws_iam_role.adot_collector.arn

  # 노드그룹 떠있어야 operator pod 스케줄됨
  depends_on = [aws_eks_node_group.main]

  tags = {
    Name = "${var.project_name}-adot-addon"
  }
}

output "adot_collector_irsa_role_arn" {
  description = "ADOT Collector IRSA Role ARN (Collector CR serviceAccount annotation 에 부착)"
  value       = aws_iam_role.adot_collector.arn
}

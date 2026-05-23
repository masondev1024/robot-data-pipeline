# ── EBS CSI Driver Addon ────────────────────────────────────────────
# Airflow 등 stateful workload의 PVC를 위해 필요. 모든 PVC 요청을 EBS volume으로
# 자동 프로비저닝하는 EKS 표준 addon.
#
# 의존: aws_iam_openid_connect_provider.eks (eks_and_iam.tf)

data "aws_iam_policy_document" "ebs_csi_assume_role" {
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
      values   = ["system:serviceaccount:kube-system:ebs-csi-controller-sa"]
    }

    condition {
      test     = "StringEquals"
      variable = "${trimprefix(aws_iam_openid_connect_provider.eks.url, "https://")}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ebs_csi" {
  name               = "${var.project_name}-ebs-csi-irsa"
  assume_role_policy = data.aws_iam_policy_document.ebs_csi_assume_role.json

  tags = {
    Name = "${var.project_name}-ebs-csi-irsa"
  }
}

resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

resource "aws_eks_addon" "ebs_csi" {
  cluster_name             = aws_eks_cluster.main.name
  addon_name               = "aws-ebs-csi-driver"
  service_account_role_arn = aws_iam_role.ebs_csi.arn

  # 노드그룹 떠있어야 driver pod 스케줄됨
  depends_on = [aws_eks_node_group.main]
}

output "ebs_csi_irsa_role_arn" {
  description = "EBS CSI Driver IRSA Role ARN"
  value       = aws_iam_role.ebs_csi.arn
}

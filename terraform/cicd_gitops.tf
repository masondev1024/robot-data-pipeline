# ECR Repositories
resource "aws_ecr_repository" "generator" {
  name                 = "${var.project_name}-generator"
  image_tag_mutability = "MUTABLE"
  # 단기 검증 스택은 destroy 시 테스트 이미지를 함께 제거해 잔여 과금을 막는다.
  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "api" {
  name                 = "${var.project_name}-api"
  image_tag_mutability = "MUTABLE"
  # 단기 검증 스택은 destroy 시 테스트 이미지를 함께 제거해 잔여 과금을 막는다.
  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Custom Airflow image — _PIP_ADDITIONAL_REQUIREMENTS 매 콜드스타트 install 을 image baked-in
# 으로 옮겨 webserver/scheduler 콜드스타트 ~94s → ~30s 단축. Dockerfile: docker/airflow/.
resource "aws_ecr_repository" "airflow" {
  name                 = "${var.project_name}-airflow"
  image_tag_mutability = "MUTABLE"
  # 단기 검증 스택은 destroy 시 테스트 이미지를 함께 제거해 잔여 과금을 막는다.
  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

# GitHub Actions OIDC Role
#
# GitHub's OIDC provider is account-scoped and is shared by repositories. It is
# bootstrapped once outside this workload stack; treating it as a data source
# prevents a second short-lived validation stack from trying to create the same
# provider and failing with EntityAlreadyExists.
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_role" "github_actions" {
  name = "${var.project_name}-github-actions-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRoleWithWebIdentity"
      Effect = "Allow"
      Principal = {
        Federated = data.aws_iam_openid_connect_provider.github.arn
      }
      Condition = {
        StringLike = {
          "token.actions.githubusercontent.com:sub" : "repo:${var.github_owner}/${var.github_repo}:*"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github_actions" {
  name = "${var.project_name}-github-actions-policy"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action   = ["ecr:*", "eks:DescribeCluster", "sts:GetCallerIdentity"]
        Effect   = "Allow"
        Resource = "*"
      },
      {
        Action   = ["s3:*"]
        Effect   = "Allow"
        Resource = ["arn:aws:s3:::*"]
      },
      {
        Action   = ["ssm:PutParameter", "ssm:GetParameter"]
        Effect   = "Allow"
        Resource = "arn:aws:ssm:${var.aws_region}:*:parameter/robot-telemetry/*"
      },
      # phase8-e2e-verify 워크플로우의 Bronze 파티션 검증용. workgroup 한정.
      {
        Action = [
          "athena:StartQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:StopQueryExecution",
          "athena:GetWorkGroup",
        ]
        Effect   = "Allow"
        Resource = "arn:aws:athena:${var.aws_region}:*:workgroup/robot-telemetry-workgroup"
      },
      # Athena 가 Glue 카탈로그 메타데이터 읽기 권한 필요. 읽기만 허용.
      {
        Action = [
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:GetTable",
          "glue:GetTables",
          "glue:GetPartition",
          "glue:GetPartitions",
        ]
        Effect = "Allow"
        Resource = [
          "arn:aws:glue:${var.aws_region}:*:catalog",
          "arn:aws:glue:${var.aws_region}:*:database/robot_telemetry_db",
          "arn:aws:glue:${var.aws_region}:*:table/robot_telemetry_db/*",
        ]
      }
    ]
  })
}

# kubectl apply / rollout restart 가 EKS API 인증을 통과하려면 access entry 필수.
resource "aws_eks_access_entry" "github_actions" {
  cluster_name  = aws_eks_cluster.main.name
  principal_arn = aws_iam_role.github_actions.arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "github_actions_admin" {
  cluster_name  = aws_eks_cluster.main.name
  principal_arn = aws_iam_role.github_actions.arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }
}

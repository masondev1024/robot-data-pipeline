#!/usr/bin/env bash
# Karpenter IAM 리소스 일회성 생성 스크립트.
# 사유: terraform state에 OIDC provider/데이터 파이프라인 등이 없어 terraform apply 위험.
# AWS CLI로 직접 생성 → 추후 terraform import로 정식 IaC 통합.
#
# 생성 리소스:
#   1) Karpenter Node IAM Role (+ 4 managed policy attach)
#   2) Instance Profile (Node Role attach)
#   3) Karpenter Controller IRSA Role (OIDC federated trust)
#   4) Controller Inline Policy (EC2/IAM/EKS 권한)
#
# Idempotent: 이미 존재하면 skip.

set -euo pipefail

# ---------- 환경변수 (override 가능) ----------
PROJECT="${PROJECT:-robot-telemetry}"
CLUSTER="${CLUSTER:-robot-telemetry-cluster}"
REGION="${REGION:-${AWS_REGION:-ap-northeast-2}}"
ACCOUNT_ID="${ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
OIDC_ID="${OIDC_ID:-}"
if [[ -n "$OIDC_ID" ]]; then
  OIDC_ISSUER="oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}"
else
  OIDC_URL="$(aws eks describe-cluster \
    --name "$CLUSTER" \
    --region "$REGION" \
    --query 'cluster.identity.oidc.issuer' \
    --output text)"
  if [[ -z "$OIDC_URL" || "$OIDC_URL" == "None" ]]; then
    echo "unable to resolve the OIDC issuer for EKS cluster ${CLUSTER}" >&2
    exit 1
  fi
  OIDC_ISSUER="${OIDC_URL#https://}"
fi

NODE_ROLE="${PROJECT}-karpenter-node-role"
CONTROLLER_ROLE="${PROJECT}-karpenter-controller-role"
INSTANCE_PROFILE="${PROJECT}-karpenter-instance-profile"

echo "▶ Account: ${ACCOUNT_ID}, Region: ${REGION}, Cluster: ${CLUSTER}"
echo "▶ OIDC Issuer: ${OIDC_ISSUER}"
echo

# ---------- 1. Karpenter Node Role ----------
echo "[1/4] Node Role 생성 (${NODE_ROLE})"
cat > /tmp/karp-node-trust.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "ec2.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
EOF

if aws iam get-role --role-name "$NODE_ROLE" >/dev/null 2>&1; then
  echo "  → 이미 존재, skip"
else
  aws iam create-role \
    --role-name "$NODE_ROLE" \
    --assume-role-policy-document file:///tmp/karp-node-trust.json \
    --tags "Key=Project,Value=${PROJECT}" "Key=ManagedBy,Value=karpenter" >/dev/null
  echo "  → created"
fi

for POLICY in \
  arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy \
  arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy \
  arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly \
  arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore; do
  aws iam attach-role-policy --role-name "$NODE_ROLE" --policy-arn "$POLICY"
  echo "  → attach $(basename "$POLICY")"
done
echo

# ---------- 2. Instance Profile ----------
echo "[2/4] Instance Profile 생성 (${INSTANCE_PROFILE})"
if aws iam get-instance-profile --instance-profile-name "$INSTANCE_PROFILE" >/dev/null 2>&1; then
  echo "  → 이미 존재, skip"
else
  aws iam create-instance-profile --instance-profile-name "$INSTANCE_PROFILE" >/dev/null
  echo "  → created"
fi

# Role-to-InstanceProfile attach (idempotent)
ATTACHED_ROLE=$(aws iam get-instance-profile \
  --instance-profile-name "$INSTANCE_PROFILE" \
  --query "InstanceProfile.Roles[0].RoleName" --output text 2>/dev/null || echo "None")
if [[ "$ATTACHED_ROLE" == "$NODE_ROLE" ]]; then
  echo "  → role 이미 연결됨"
else
  aws iam add-role-to-instance-profile \
    --instance-profile-name "$INSTANCE_PROFILE" \
    --role-name "$NODE_ROLE"
  echo "  → role attached"
fi
echo

# ---------- 3. Controller IRSA Role ----------
echo "[3/4] Controller IRSA Role 생성 (${CONTROLLER_ROLE})"
cat > /tmp/karp-ctrl-trust.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/${OIDC_ISSUER}"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "${OIDC_ISSUER}:sub": "system:serviceaccount:karpenter:karpenter",
        "${OIDC_ISSUER}:aud": "sts.amazonaws.com"
      }
    }
  }]
}
EOF

if aws iam get-role --role-name "$CONTROLLER_ROLE" >/dev/null 2>&1; then
  echo "  → 이미 존재, trust 갱신"
  aws iam update-assume-role-policy \
    --role-name "$CONTROLLER_ROLE" \
    --policy-document file:///tmp/karp-ctrl-trust.json
else
  aws iam create-role \
    --role-name "$CONTROLLER_ROLE" \
    --assume-role-policy-document file:///tmp/karp-ctrl-trust.json \
    --tags "Key=Project,Value=${PROJECT}" "Key=ManagedBy,Value=karpenter" >/dev/null
  echo "  → created"
fi
echo

# ---------- 4. Controller Inline Policy ----------
echo "[4/4] Controller Inline Policy 등록"
cat > /tmp/karp-ctrl-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowEC2AndDescribe",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ec2:DescribeImages",
        "ec2:RunInstances",
        "ec2:DescribeSubnets",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeLaunchTemplates",
        "ec2:DescribeInstances",
        "ec2:DescribeInstanceTypes",
        "ec2:DescribeInstanceTypeOfferings",
        "ec2:DescribeAvailabilityZones",
        "ec2:DeleteLaunchTemplate",
        "ec2:CreateLaunchTemplate",
        "ec2:CreateFleet",
        "ec2:CreateTags",
        "ec2:TerminateInstances",
        "ec2:DescribeSpotPriceHistory",
        "pricing:GetProducts"
      ],
      "Resource": "*"
    },
    {
      "Sid": "AllowPassNodeRole",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::${ACCOUNT_ID}:role/${NODE_ROLE}"
    },
    {
      "Sid": "AllowDescribeCluster",
      "Effect": "Allow",
      "Action": "eks:DescribeCluster",
      "Resource": "arn:aws:eks:${REGION}:${ACCOUNT_ID}:cluster/${CLUSTER}"
    },
    {
      "Sid": "AllowInstanceProfileMgmt",
      "Effect": "Allow",
      "Action": [
        "iam:CreateInstanceProfile",
        "iam:DeleteInstanceProfile",
        "iam:GetInstanceProfile",
        "iam:RemoveRoleFromInstanceProfile",
        "iam:AddRoleToInstanceProfile",
        "iam:TagInstanceProfile"
      ],
      "Resource": "arn:aws:iam::${ACCOUNT_ID}:instance-profile/*"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name "$CONTROLLER_ROLE" \
  --policy-name "${PROJECT}-karpenter-controller-policy" \
  --policy-document file:///tmp/karp-ctrl-policy.json
echo "  → inline policy 등록 완료"
echo

# ---------- 결과 출력 ----------
echo "════════════════════════════════════════"
echo "✅ Karpenter IAM 리소스 생성 완료"
echo "════════════════════════════════════════"
echo "  Node Role ARN       : arn:aws:iam::${ACCOUNT_ID}:role/${NODE_ROLE}"
echo "  Controller Role ARN : arn:aws:iam::${ACCOUNT_ID}:role/${CONTROLLER_ROLE}"
echo "  Instance Profile    : ${INSTANCE_PROFILE}"
echo
echo "다음 단계: EKS access entry 등록 (Step 3)"

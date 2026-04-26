# Step 1: network

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md`
- `/terraform/providers.tf`
- `/terraform/variables.tf`

## 작업

`terraform/network.tf`를 작성하라.

### VPC 3계층 서브넷 구조
- **VPC**: CIDR은 `var.vpc_cidr` (`10.0.32.0/16`). DNS hostname/support 활성화
- **Public 서브넷** (2개, AZ: ap-northeast-2a / ap-northeast-2c): NAT Gateway, ALB 배치용
- **Private 서브넷** (2개, AZ: ap-northeast-2a / ap-northeast-2c): EKS Worker Node 배치용
- **Intra 서브넷** (2개, AZ: ap-northeast-2a / ap-northeast-2c): EKS Control Plane ENI용
- **Internet Gateway**: Public 서브넷용
- **NAT Gateway** (1개, EIP 포함): Private 서브넷 아웃바운드용
- **Route Tables**: Public / Private / Intra 각각 분리

### EKS 전용 태그
```hcl
# Public 서브넷
"kubernetes.io/role/elb" = "1"
# Private 서브넷
"kubernetes.io/role/internal-elb" = "1"
# 모든 서브넷
"kubernetes.io/cluster/${var.eks_cluster_name}" = "shared"
```

### VPC Endpoints (비용·보안 최적화)
EKS Pod 트래픽이 NAT Gateway를 우회하여 AWS 내부 네트워크로 처리되도록 아래 2개를 반드시 추가한다:

**① S3 Gateway Endpoint** (무료):
```hcl
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id, aws_route_table.intra.id]
}
```

**② Kinesis Streams Interface Endpoint** (PrivateLink):
```hcl
resource "aws_vpc_endpoint" "kinesis" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.kinesis-streams"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [private 서브넷 ID 목록]
  security_group_ids  = [aws_security_group.vpc_endpoint.id]
  private_dns_enabled = true
}
```
- Kinesis Endpoint용 Security Group 생성: inbound HTTPS(443) from VPC CIDR

## Acceptance Criteria

```bash
terraform fmt -check -recursive terraform/
grep -q "vpc_endpoint" terraform/network.tf && echo "OK: VPC endpoints found"
grep -q "kinesis-streams" terraform/network.tf && echo "OK: Kinesis endpoint found"
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - Public / Private / Intra 서브넷 각 2개(2 AZ)?
   - EKS 태그가 서브넷에 있는가?
   - S3 Gateway Endpoint가 있는가?
   - Kinesis Interface Endpoint가 있는가?
3. `phases/0-setup/index.json` step 1 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "network.tf: VPC 10.0.32.0/16, 3계층 서브넷 2AZ, NAT GW, S3/Kinesis VPC Endpoint"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- VPC Endpoint 2개(S3, Kinesis)를 생략하지 마라. 이유: 10,000 rec/sec 트래픽이 NAT Gateway를 타면 데이터 전송 비용이 급증한다
- Bastion Host, RDS 리소스를 추가하지 마라. 이유: 이번 프로젝트 범위 외
- CIDR을 `var.vpc_cidr` 없이 하드코딩하지 마라

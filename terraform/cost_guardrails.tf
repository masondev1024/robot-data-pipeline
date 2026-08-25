resource "terraform_data" "full_stack_apply_guardrail" {
  input = var.allow_full_stack_apply

  lifecycle {
    precondition {
      condition     = var.allow_full_stack_apply
      error_message = "전체 EKS/EC2/NAT/ALB/RDS/SageMaker 스택은 비용 승인 후 -var='allow_full_stack_apply=true'를 명시해야 합니다. 스트리밍 검증은 terraform/validation을 사용하세요."
    }
  }
}

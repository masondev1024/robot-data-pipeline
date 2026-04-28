# ⚠️ DATA-ONLY DEPLOY: EKS/SNS/X-Ray 비활성화. 모든 변수는 모듈 default 더미값 사용.
# EKS/SNS/XRay 권한 받으면 .disabled 파일 복원 + module 입력 다시 주입.

module "data_pipeline" {
  source = "./modules/data_pipeline"

  project_name          = var.project_name
  aws_region            = var.aws_region
  environment           = var.environment
  kds_main_shard_count  = var.kds_main_shard_count
  kds_alert_shard_count = var.kds_alert_shard_count
}

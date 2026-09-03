# 실환경 증적 안내

이 폴더의 JSON은 2026-09-03 서울 리전에서 실행한 Glue·RDS 검증 결과를
민감정보 없이 고정한 파일이다.

- `2026-09-03-migration-success.json`: 정상 4건의 검증·staging·승격·replay 결과
- `2026-09-03-migration-reject.json`: 계약 위반 1건의 reject·감사·target 격리 결과

실행 ID와 시각은 AWS Glue 실행 기록과 대조할 수 있다. RDS endpoint, Secret ARN,
비밀번호, access key는 의도적으로 기록하지 않았다. 실험 스택은 증적 저장 후
Terraform destroy로 폐기됐기 때문에 이 JSON만으로 현재 AWS 서비스가 실행 중이라고
해석하면 안 된다.

이 증적이 말할 수 있는 범위는 작은 샘플의 데이터 계약 검증, 실패 격리, 멱등 승격,
건수 대조다. 대규모 처리량, Multi-AZ failover, 장기 SLO, 전체 exactly-once는
별도 검증이 필요하다.

# 단기 스트리밍 검증 스택

이 디렉터리는 전체 EKS·ML 플랫폼을 운영하기 위한 Terraform이 아니라, Kinesis → Firehose → S3 Parquet 경로와 스트리밍 SLO를 짧게 검증하기 위한 비용 최소화 프로필입니다.

## 비용과 범위

다음 리소스는 생성하지 않습니다.

- EKS control plane과 worker node
- EC2, NAT Gateway, Elastic IP, ALB
- ECR repository
- RDS, SageMaker endpoint, Airflow, Grafana, Slack/Lambda 알림

생성하는 핵심 리소스는 Kinesis 2 shards, Firehose 1개, S3 1개, Glue catalog/table, CloudWatch guardrail뿐입니다. Parquet 변환을 유지할 때 Firehose API가 허용하는 최소 버퍼가 `64MB`이므로 기본값은 `64MB/60초`입니다. 기존 전체 스택의 `128MB/300초`보다 freshness 결과를 빠르게 확인하면서도 Parquet 데이터 계약 검증을 보존합니다.

## 실행

```bash
cd terraform/validation
export AWS_PROFILE=develope-test
export AWS_REGION=eu-west-1
terraform init -backend=false

terraform apply -auto-approve \
  -var="aws_region=$AWS_REGION" \
  -var='project_name=robot-telemetry-validation-YYYYMMDD' \
  -var='s3_bucket_name=robot-telemetry-validation-ACCOUNT-YYYYMMDD'
```

계정 ID와 날짜를 포함해 S3 bucket 이름을 전역적으로 유일하게 지정합니다. 실제 검증이 끝나면 같은 디렉터리에서 즉시 삭제합니다.

```bash
terraform destroy -auto-approve \
  -var="aws_region=$AWS_REGION" \
  -var='project_name=robot-telemetry-validation-YYYYMMDD' \
  -var='s3_bucket_name=robot-telemetry-validation-ACCOUNT-YYYYMMDD'
```

## 데이터 전송과 SLO 확인

로컬 generator를 사용해 100Hz에서 시작하고, 정상일 때만 1,000Hz로 올립니다.
generator와 verifier는 저장소 루트에서 실행해야 하므로, validation 디렉터리에서 루트로 이동한 뒤 Terraform output을 조회합니다.

```bash
cd ../..
STREAM_NAME="$(terraform -chdir=terraform/validation output -raw stream_name)"
AWS_PROFILE=develope-test AWS_REGION=eu-west-1 \
  KINESIS_STREAM_NAME="$STREAM_NAME" \
  ROBOT_COUNT=100 TICK_INTERVAL_SECONDS=1 \
  python -m src.generator.app
```

검증 도중 프로세스를 종료하고 다음 read-only verifier를 실행합니다.

```bash
AWS_PROFILE=develope-test AWS_REGION=eu-west-1 \
  python scripts/verify_pipeline_slo.py \
  --stream-name "$STREAM_NAME" \
  --firehose-name "$(terraform -chdir=terraform/validation output -raw firehose_name)" \
  --firehose-freshness-threshold-seconds 120
```

`NO_DATA`를 정상으로 허용하는 `--allow-no-data`는 실제 producer가 꺼진 상태를 검사할 때만 사용합니다. 일반 부하 검증에서는 데이터가 없으면 실패로 처리합니다.

## 의도적인 trade-off

- EKS를 없앴으므로 Kubernetes workload, HPA, ALB, Canary는 검증하지 않습니다. 해당 항목은 별도의 명시적 EKS 비용 프로필에서 검증합니다.
- Kinesis main stream은 2 shards로 두어 1,000 records/s에서 shard당 약 50% 사용률을 목표로 합니다. 큰 레코드나 partition-key skew가 있으면 4 shards 표준 프로필로 전환합니다.
- Firehose `64MB/60초`는 Parquet 변환을 켠 상태에서 사용할 수 있는 최소 크기입니다. 낮은 검증 처리량에서는 크기보다 60초 interval이 flush를 결정하므로 기존 `128MB/300초` 대비 freshness feedback을 최대 약 4분 줄입니다. 검증이 끝난 뒤 테스트 객체는 lifecycle로 1일 후 만료됩니다.
- Parquet 변환을 켠 채 `5MB`로 낮추면 AWS API가 거부하므로 plan 단계 precondition으로 차단합니다. raw JSON만 의도적으로 검증할 때만 Parquet 변환을 끄고 더 작은 버퍼를 선택할 수 있습니다.
- CloudWatch alarm action은 비활성화했습니다. 실제 Slack 알림은 유효한 Webhook Secret과 별도 알림 프로필을 준비한 뒤 검증합니다.

## 전체 스택 실행 안전 게이트

저장소 루트 `terraform/`은 EKS·EC2·NAT·ALB·RDS·SageMaker를 포함하는 비교용 전체 플랫폼입니다. 실수로 전체 스택을 실행해 비용이 발생하지 않도록 기본값은 차단되어 있습니다. 비용 승인과 종료 담당자가 정해진 경우에만 다음 명시적 변수를 추가합니다.

```bash
terraform -chdir=terraform plan \
  -var='allow_full_stack_apply=true' \
  -var='project_name=robot-telemetry-full-YYYYMMDD'
```

스트리밍 수집·Firehose·Parquet·SLO만 검증할 때는 위 전체 스택이 아니라 이 디렉터리의 validation 프로필을 사용합니다. 적용 직후부터 destroy 담당자와 종료 시각을 기록하고, 실험 종료 후 `terraform destroy`와 AWS 잔여 리소스 확인을 한 묶음으로 수행합니다.

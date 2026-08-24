# AWS cost estimate for portfolio validation

기준일: 2026-08-24, region `eu-west-1`, USD, 세금·VAT·Free Tier/크레딧 제외.

이 문서는 청구서가 아니라 Terraform 기본값과 AWS 공개 가격을 이용한 사전 예측이다. 실제 금액은 Spot 가격, ALB LCU, NAT 처리량, 로그량, S3 Parquet 압축률, 계정의 Free Tier 사용량에 따라 달라진다.

## 이번 작업의 비용 기준

### 1. 코드/CI/로컬 검증

AWS 리소스를 생성하지 않으면 AWS 추가 비용은 `$0`이다. GitHub Actions, Terraform `validate`, Docker build, k6 script validation, SLO unit test는 AWS 사용료를 만들지 않는다.

### 2. 실제 AWS short-lived validation (이번 범위)

기본 비용식은 다음과 같다.

```text
총액 = 시간기반 리소스
     + 데이터량 기반 Kinesis/Firehose/S3/Athena 비용
     + 로그/메트릭/ALB LCU/NAT 처리량
```

이번 작업은 서비스를 운영하지 않는다. 구현이 끝난 뒤 한 번의 검증 세션에서 리소스를 생성하고, smoke/load/failure drill과 증거 수집을 마친 즉시 destroy한다. 아래 금액은 24시간 상시 운전 예측이 아니라 이 세션의 예산을 산정하기 위해 시간당 비용을 환산한 것이다.

### robot-data-pipeline의 시간당 비용 기준

| 항목 | Terraform 기본값/가정 | 월 환산 참고값 |
|---|---|---:|
| EKS control plane | standard support | 약 `$73` |
| EKS worker | t3.large Spot 1대, 최근 관측 Spot 약 `$0.0417/h` | 약 `$30` |
| NAT Gateway + EIP | 1개 | `$32.85 + $3.65` + `$0.045/GB` |
| ALB | 1개, 기본 시간비 | 약 `$16.43` + LCU + public IPv4 2개 약 `$7.30` |
| Kinesis shards | main 4 + alert 1, `$0.015/shard-hour` | 약 `$54.75` |
| CloudWatch alarms/dashboards | 표준 metric, Free Tier 초과분만 | 대체로 수 달러 이하 |
| S3/Glue/Athena/Lambda/ECR/Secrets | 사용량 기반 | 보통 수 달러~수십 달러 |

위 리소스의 고정/저변동 비용은 월 환산 약 `$218`이며, 실제 실험에서는 사용 시간만큼 비례 청구된다. 여기에 Kinesis PUT payload, Firehose ingest/Parquet conversion, S3 저장량이 더해진다.

## 가장 중요한 데이터량 비용

기본 generator를 `1,000 robots × 1 record/sec`로 가정하고 JSON 레코드가 5KB 미만이면:

- Kinesis provisioned shard: 약 `$54.75/월`
- Kinesis PUT payload: 약 `$36.29/월` (`2.592B records × 1 × $0.014/M`)
- Firehose ingestion: Firehose 5KB billing increment 때문에 약 `12,359.6 GB/월 × $0.029 = $358.43`
- Firehose JSON→Parquet conversion: 약 `12,359.6 GB/월 × $0.018 = $222.47`
- Firehose 합계: 약 `$580.90/월`

이 수치는 상시 운영비가 아니라 데이터량 비용이 시간에 비례한다는 것을 설명하기 위한 계산 근거다. 이번 작업에서는 이 workload를 24×7로 유지하지 않는다.

100Hz로 낮추면 고정비는 거의 같지만 데이터량 기반 비용은 대략 1/10로 줄어든다. 따라서 검증은 100Hz에서 시작해 지표가 정상인 경우에만 1,000Hz로 올린다.

## 1차 GitOps 트래픽 프로젝트 구성

현재 Terraform 정의에는 다음 고정비가 있다.

- EKS standard control plane: 약 `$73/월`
- t3.medium on-demand 2대: 약 `$66.58/월`
- bastion t3.micro 1대: 약 `$8.32/월`
- RDS MySQL db.t3.micro primary + replica: 인스턴스 약 `$26.28/월` + 20GB급 storage/backup
- NAT Gateway 2개 + EIP 2개: 약 `$73/월` + 처리량
- Secrets Manager interface endpoint 2 AZ: 약 `$14.60/월`
- ALB와 public IPv4: 약 `$23.73/월` + LCU

시간당 환산하면 약 `$0.40~$0.45/h` 수준이다. 4시간 검증의 고정비는 대략 `$2` 전후이며, raffle 부하 요청량·로그·RDS storage·ALB LCU를 포함한 안전 예산은 **`$3~$10`**으로 잡는다. 이 프로젝트는 부하테스트만 할 때도 RDS primary/replica, NAT 2개, bastion이 생성되므로 검증 직후 반드시 destroy한다.

## 단기 검증 예산 — 이번 작업의 실제 기준

| 실행 | 권장 입력 | 예상 AWS 추가비용 |
|---|---|---:|
| 2시간 smoke | 100 robots로 health/readiness와 KDS/Firehose 연결 확인 | 약 `$2~$5` |
| 4시간 통합 검증 | 100Hz → 1,000Hz 단계 부하, SLO, failure drill, 증거 수집 후 destroy | robot 약 `$4~$10`, GitOps 약 `$3~$10` |
| 8시간 상한 | 재시도/장애 복구가 길어지는 경우의 상한 | 두 프로젝트 합계 약 `$15~$30` |

권장 사전 승인 예산은 **두 프로젝트 합계 `$25`**다. 실제 요청량과 Spot scale-out이 예상보다 커져도 `$50`을 넘기지 않도록 Billing alarm과 destroy 체크를 먼저 준비한다.

범위에는 리소스 생성/삭제 중 실제 사용 시간, Spot 변동, ALB LCU, NAT data processing, CloudWatch logs, EBS, S3, data transfer의 불확실성을 포함한 안전 마진이 들어 있다.

## 비용 가드레일

1. `dev/demo`는 EKS 1 cluster, Spot 1 node, NAT 1개를 생성하고 100Hz에서 먼저 검증한다.
2. 1,000Hz 검증은 5분 → 15분 → 1시간 단계로 올리며 각 단계에서 iterator age, Firehose freshness, throttle을 확인한다.
3. `k6`/generator를 종료한 뒤 Kinesis/Firehose/ALB metric이 멈췄는지 확인하고 Terraform destroy를 실행한다. 이번 범위에서 리소스를 다음 날까지 남겨두지 않는다.
4. `aws ce get-cost-and-usage` 또는 Cost Explorer에서 `eu-west-1`와 `robot-telemetry`/`data-engineer` 태그를 확인한다.
5. Billing alarm을 설정하고, Terraform state·S3 bucket·ECR images·Secrets Manager secret·Elastic IP·NAT Gateway·ALB가 남지 않았는지 destroy 후 점검한다.
6. EKS `1.33`은 2026-07-29 standard support가 종료되었으므로 기본값을 `1.34`로 올렸다. extended support 회귀를 막아 검증 세션에서도 불필요한 control-plane surcharge가 생기지 않게 한다.

## 공식 가격 참고

- [Amazon EKS pricing](https://aws.amazon.com/eks/pricing/)
- [Amazon Kinesis Data Streams pricing](https://aws.amazon.com/kinesis/data-streams/pricing/)
- [Amazon Data Firehose pricing](https://aws.amazon.com/firehose/pricing/)
- [Amazon VPC/NAT Gateway pricing](https://aws.amazon.com/vpc/pricing/)
- [Elastic Load Balancing pricing](https://aws.amazon.com/elasticloadbalancing/pricing/)
- [Amazon S3 pricing](https://aws.amazon.com/s3/pricing/)
- [Amazon Athena pricing](https://aws.amazon.com/athena/pricing/)
- [Amazon CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)

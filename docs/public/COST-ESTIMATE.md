# AWS cost estimate for portfolio validation

기준일: 2026-08-24, region `eu-west-1`, USD, 세금·VAT·Free Tier/크레딧 제외.

이 문서는 청구서가 아니라 Terraform 기본값과 AWS 공개 가격을 이용한 사전 예측이다. 실제 금액은 Spot 가격, ALB LCU, NAT 처리량, 로그량, S3 Parquet 압축률, 계정의 Free Tier 사용량에 따라 달라진다.

## 비용 최적화 적용 결과

2026-08-24에 전체 Terraform 구성을 실제 plan으로 점검한 결과, 기존 전체 스택은 **104개 리소스 생성 대상**이었다. 이 구성은 EKS, worker, NAT Gateway, ECR, Glue, Kinesis, Firehose, Lambda, observability 등을 모두 포함하므로 스트리밍 SLO만 확인하는 실험에는 과하다.

이를 위해 `terraform/validation`에 **pipeline-only 단기 검증 프로필**을 추가했다. 같은 조건의 plan은 **14개 리소스**로 줄었고, 다음 리소스는 만들지 않는다.

- EKS control plane와 worker EC2
- NAT Gateway, Elastic IP, ALB
- ECR repository, RDS, SageMaker endpoint
- Slack Webhook Secret, Lambda alert handler, SNS alert action

### 선택한 최적화와 영향

| 최적화 | 기존 전체 스택 | 단기 검증 프로필 | 비용/속도 영향 |
|---|---|---|---|
| 실행 범위 | 104개 리소스 | 14개 리소스 | plan 리소스 수 약 86.5% 감소 |
| compute/network | EKS + Spot t3.large + NAT | 없음 | EKS·EC2·NAT 시간비용 100% 제거 |
| Kinesis | main 4 + alert 1 shard | main 2 shard | provisioned shard 고정비 60% 감소 |
| Firehose buffer | 128MB/300초 | 64MB/60초 | Parquet 변환을 유지하면서 freshness 피드백 최대 4분 단축 |
| Parquet | 변환 활성 | 변환 유지 | 검증 품질은 보존, Firehose 데이터 변환 비용은 유지 |
| 알림 | Lambda/Slack 의존 | CloudWatch alarm action 비활성 | Secret 누락·알림 잔여 리소스 제거 |
| 테스트 데이터 | 장기 보관 가능 | S3 lifecycle 1일 + destroy | 잔여 저장비용 최소화 |

Firehose buffer의 크기는 Parquet 변환을 켜면 64MB 아래로 낮출 수 없다. 따라서 이번에는 크기를 무리하게 5MB로 내리지 않고 interval을 300초에서 60초로 줄였다. 낮은 검증 처리량에서는 크기보다 interval이 flush를 결정하므로 약 1분 단위로 freshness와 Parquet 적재를 확인할 수 있다. 이 설정은 장기 운영 기본값이 아니라 검증 전용이다. 이 제약은 [Firehose record format conversion 공식 문서](https://docs.aws.amazon.com/firehose/latest/dev/enable-record-format-conversion.html)에 따른다.

실제 중단 사례에서 EKS 생성은 약 4분 50초, NAT Gateway 생성은 약 1분 59초가 걸렸다. 단기 프로필에서는 이 두 대기 구간이 제거된다. 이번 비용 검증에서는 Firehose Parquet 제약을 수정한 뒤 부분 state에서 나머지 3개 리소스 apply가 7.9초, 14개 리소스 destroy가 41.6초였다. 빈 계정에서의 전체 corrected apply 시간을 별도로 재측정하지 않았으므로 8~15분 절감은 EKS/NAT 관측값을 근거로 한 보수적 추정으로 남긴다.

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

### 기존 전체 robot-data-pipeline 스택 — 비교용 기준

| 항목 | Terraform 기본값/가정 | 월 환산 참고값 |
|---|---|---:|
| EKS control plane | standard support | 약 `$73` |
| EKS worker | t3.large Spot 1대, 최근 관측 Spot 약 `$0.0417/h` | 약 `$30` |
| NAT Gateway + EIP | 1개 | `$32.85 + $3.65` + `$0.045/GB` |
| ALB | 1개, 기본 시간비 | 약 `$16.43` + LCU + public IPv4 2개 약 `$7.30` |
| Kinesis shards | main 4 + alert 1, `$0.015/shard-hour` | 약 `$54.75` |
| CloudWatch alarms/dashboards | 표준 metric, Free Tier 초과분만 | 대체로 수 달러 이하 |
| S3/Glue/Athena/Lambda/ECR/Secrets | 사용량 기반 | 보통 수 달러~수십 달러 |

위 리소스의 고정/저변동 비용은 월 환산 약 `$218`이며, 실제 실험에서는 사용 시간만큼 비례 청구된다. 이 수치는 비교용 기준이며 이번 기본 검증 프로필에서는 EKS·worker·NAT를 생성하지 않는다. 여기에 Kinesis PUT payload, Firehose ingest/Parquet conversion, S3 저장량이 더해진다.

## 가장 중요한 데이터량 비용

기본 generator를 `1,000 robots × 1 record/sec`로 가정하고 JSON 레코드가 5KB 미만이면:

- Kinesis provisioned shard: 약 `$54.75/월`
- Kinesis PUT payload: 약 `$36.29/월` (`2.592B records × 1 × $0.014/M`)
- Firehose ingestion: Firehose 5KB billing increment 때문에 약 `12,359.6 GB/월 × $0.029 = $358.43`
- Firehose JSON→Parquet conversion: 약 `12,359.6 GB/월 × $0.018 = $222.47`
- Firehose 합계: 약 `$580.90/월`

이 수치는 상시 운영비가 아니라 데이터량 비용이 시간에 비례한다는 것을 설명하기 위한 계산 근거다. 이번 작업에서는 이 workload를 24×7로 유지하지 않는다.

100Hz로 낮추면 고정비는 거의 같지만 데이터량 기반 비용은 대략 1/10로 줄어든다. 따라서 검증은 100Hz에서 시작해 지표가 정상인 경우에만 1,000Hz로 올린다.

### 2026-08-24 실제 단기 실행 증거

| 항목 | 관측값 |
|---|---:|
| 프로필 | Kinesis 2 shards + Firehose 64MB/60초 + S3/Glue/CloudWatch |
| 전송량 | 7,200 records / 약 72초 / 100Hz |
| generator 실패 | 0건 |
| S3 산출물 | Parquet 2개, 총 154,074 bytes |
| Kinesis iterator age | 0ms |
| Kinesis write throttle | 0 |
| 검증 후 destroy | 14개 리소스 / 41.6초 |
| Cost Explorer 조회 | `Estimated=true`, 현재 `UnblendedCost=0 USD` |

Firehose CloudWatch 지표는 같은 시점 query에서 `NO_DATA`였기 때문에 freshness와 successful put metric은 PASS로 기록하지 않았다. S3 객체 생성은 별도의 직접 증거이며, AWS 청구 데이터는 지연될 수 있다. 오늘의 hard cap은 `$30`이고, 추가 AWS apply/load는 중단했다.

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

## 단기 검증 예산 — 최적화 프로필 기준

| 실행 | 권장 입력 | 예상 AWS 추가비용 |
|---|---|---:|
| 2시간 Smoke | pipeline-only 100Hz로 Kinesis/Firehose/S3 연결 확인 | 약 `$0.5~$2` |
| 4시간 단계 검증 | 100Hz → 1,000Hz 단계 부하, SLO, Parquet 증거 수집 후 destroy | robot 약 `$1~$3` |
| 4시간 1,000Hz 연속 | 데이터량 비용이 지배하는 상한 시나리오 | robot 약 `$4~$6` |
| 두 프로젝트 합계 | robot 최적화 프로필 + GitOps 4시간 short-lived 검증 | 약 `$4~$13` |
| 기존 방식 비교 | 두 전체 스택을 그대로 켜는 경우 | 약 `$15~$30` |

권장 사전 승인 예산은 최적화 프로필 기준 **두 프로젝트 합계 `$15`**다. 보수적인 전체 실험 상한은 `$25`, 프로세스상 hard ceiling은 `$50`으로 두되, Billing alarm은 자동 중지가 아니므로 단계별로 producer를 멈추고 destroy한다.

범위에는 리소스 생성/삭제 중 실제 사용 시간, Spot 변동, ALB LCU, NAT data processing, CloudWatch logs, EBS, S3, data transfer의 불확실성을 포함한 안전 마진이 들어 있다.

## 비용 가드레일

1. 스트리밍 SLO만 검증할 때는 `terraform/validation` pipeline-only 프로필을 사용한다. EKS 1 cluster, Spot node, NAT는 만들지 않는다.
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
## 2026-08-24 전체 EKS profile 실제 실행 메모

스트리밍 SLO만 확인하는 경우에는 앞의 14-resource validation profile이 여전히 권장된다. 다만 이번에는 플랫폼 동작을 확인하기 위해 `robot-telemetry-full-20260824` 전체 profile을 짧게 실행했다.

| 자원 | 실제 선택 | 비용 통제 이유 |
|---|---|---|
| EKS | 1.34, 1 cluster | 최신 지원 버전과 단일 control plane |
| Worker | t3.medium Spot 1대 | generator/API/Grafana를 한 노드에 배치해 시간비용 최소화 |
| Kinesis main | 2 shards | 약 100 records/s 검증에 충분한 최소 provisioned capacity |
| Firehose | Parquet 변환, 단기 버퍼 | Bronze 데이터 계약을 유지하면서 직접 S3 증거 확보 |
| PostgreSQL | 1 StatefulSet, 1 PVC | API smoke와 serving registry만 검증; HA DB는 제외 |
| Secrets | 임시 basic-auth/webhook secret | teardown 때 이름을 확인해 삭제 |

실측 workload는 약 100 records/s 구간에서 41,000 records, Kinesis throttle 0, Firehose freshness 약 306초, Bronze Parquet 객체 생성까지 확인했다. Managed Flink application은 계정에 없어 Flink compute 비용과 alert sink 실행 비용은 발생하지 않았다. 이 세션의 최종 비용은 teardown 후 Cost Explorer가 반영하는 `Estimated` 값을 별도로 확인하며, CloudWatch 비용 데이터 지연 때문에 즉시 확정 청구액으로 표현하지 않는다.

전체 profile은 validation profile보다 EKS control plane·Spot worker·NAT·EBS·CloudWatch observability 고정비가 추가된다. 따라서 다음 작업에서도 generator를 실제로 구동하는 구간만 켜고, S3/Firehose 증거가 확보되면 generator를 먼저 멈춘 뒤 Terraform destroy를 실행한다. 24시간 운영을 가정하지 않은 short-lived 실험 비용으로만 산정한다.

### 2026-08-24 teardown 실제 결과

Raffle 전체 profile은 Terraform 기준 72개 리소스를 `0 added, 0 changed, 72 destroyed`로 정리했다. Robot 전체 profile은 106개 destroy 계획을 실행했고, 이미지가 남은 ECR repository만 별도 강제 삭제한 뒤 최종 Terraform state를 0개 리소스로 확인했다. ECR repository에는 앞으로 `force_delete = true`를 적용해 이미지가 있는 단기 검증 스택도 한 번의 destroy로 닫히도록 했다.

최종 AWS read-only 감사에서 EKS, RDS, ALB, Kinesis, Firehose, ECR, Secrets Manager, S3, 전용 VPC/NAT/EIP가 모두 absent였다. StatefulSet이 남긴 1GiB 고아 EBS volume 1개는 attachment와 테스트 cluster tag를 확인한 뒤 삭제했고 EC2 control plane 재조회에서 absent를 확인했다. Tagging API는 삭제 ARN을 잠시 캐시했으므로 비용 잔여 판정은 직접 서비스 조회를 기준으로 했다. 이 결과는 리소스가 계속 실행 중이라는 가정의 비용을 제거하지만, 당일 Cost Explorer 반영 전이므로 최종 청구액과 동일하다고 보지 않는다.

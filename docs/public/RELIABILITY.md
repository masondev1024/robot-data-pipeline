# Reliability engineering notes

이 프로젝트의 운영 규칙은 장애를 회고하는 데서 끝내지 않고 다음 배포에서 재발하지 않게 만드는 것을 목표로 합니다.

| 실패 모드 | 원인 | 플랫폼 가드레일 |
|---|---|---|
| KDS 재생성 뒤 S3 적재 중단 | 기존 Firehose가 새 stream에 자동 연결되지 않음 | stream 수명주기와 Firehose 재생성을 한 절차로 결합 |
| alert stream은 정상인데 Slack 무알림 | Lambda event source mapping이 disabled 상태로 고착 | 복구 후 mapping 상태를 명시적으로 검증·활성화 |
| Firehose delivery alarm 오판 | `DeliveryToS3.Success`를 0~1 비율로 해석 | 성공 S3 put 명령 수는 `Minimum < 1`, 적재 지연은 `DeliveryToS3.DataFreshness` 초 단위로 분리 |
| KDS 소비자 backlog 증가 | producer throttle만 보고 downstream lag를 놓침 | `GetRecords.IteratorAgeMilliseconds`를 최대값 기준으로 별도 경보 |
| 셧다운 뒤 비용 잔존 | HPA, Grafana, Ingress/ALB가 workload/node를 유지 | workload → HPA/Ingress → ALB → node 순서와 0 상태 확인 |
| 강제 node 종료 뒤 PVC pending | stale VolumeAttachment 잔존 | 존재하지 않는 node의 attachment를 식별하는 복구 절차 |
| 인증 추가 뒤 pod CrashLoop | kubelet probe가 인증 경로에서 401 | auth, probe, test fixture, secret fallback을 한 변경 단위로 검증 |
| Athena endpoint 빈 응답 | 전날 파티션을 고정했으나 셧다운으로 미생성 | 최근 N일 내 `MAX(dt)` fallback과 partition pruning 병행 |

## 검증 층

- Unit/contract: schema, datasource/predictor, cache replay, API, generator, ETL
- Determinism: `PYTHONHASHSEED=2026`, 고정 random/NumPy seed, cache miss 즉시 실패
- IaC: Terraform format/validate/plan 기반 검사
- Deployment: ECR freshness, workload/Ingress, Athena 적재, API response schema
- AI quality: golden QA와 judge threshold를 별도 workflow로 측정

## Streaming SLO guardrails

- Kinesis consumer iterator age: 기본 120초 이하
- Firehose S3 delivery freshness: 기본 600초 이하
- Firehose successful S3 puts: 활성 전달 기간에 최소 1건
- `scripts/verify_pipeline_slo.py`는 CloudWatch `GetMetricData`만 호출하는 read-only 검증기입니다.

`DeliveryToS3.Success`는 0~1 비율이 아니라 성공한 S3 put 명령 수입니다. 지연 자체는 `DeliveryToS3.DataFreshness`로 측정해야 합니다. 자세한 metric 정의는 [Amazon Data Firehose CloudWatch metrics](https://docs.aws.amazon.com/firehose/latest/dev/monitoring-with-cloudwatch-metrics.html)와 [Amazon Kinesis Data Streams monitoring](https://docs.aws.amazon.com/streams/latest/dev/monitoring-with-cloudwatch.html)을 기준으로 합니다.

## 증거의 한계

로컬 테스트 통과는 AWS control plane, IAM, 네트워크, 실제 Kinesis/Firehose 전달을 증명하지 않습니다. 따라서 저장소는 offline 검증과 AWS E2E를 별도 workflow와 별도 상태로 취급합니다.

## 비용 프로필별 신뢰성 검증 경계

스트리밍 SLO 검증은 `terraform/validation`의 pipeline-only 프로필을 우선 사용한다. 이 프로필은 Kinesis main stream 2 shards, Firehose 64MB/60초 buffer, S3 Parquet, CloudWatch guardrail만 생성한다. Parquet 변환을 켜면 Firehose 버퍼를 64MB 아래로 설정할 수 없으므로 plan 단계 precondition으로 잘못된 조합을 차단한다. EKS, NAT, EC2, ALB, RDS, Lambda/Slack 알림은 의도적으로 제외한다.

## 지원용 신뢰성 증거 요약

비용 상한을 지키기 위해 2026-08-24에는 pipeline-only 프로필만 실제로 실행했다. 100Hz에서 약 72초 동안 7,200건을 Kinesis에 전송했고 `failed=0`, `schema_dropped=0`이었다. Firehose가 S3에 `.parquet` 객체 2개(72,227 bytes, 81,847 bytes)를 생성한 것을 확인했으며, Kinesis iterator age는 0ms, write throttle은 0이었다. CloudWatch Firehose metric query는 관측 지연으로 해당 시점에 `NO_DATA`를 반환했으므로 Firehose SLO `PASS`로 과장하지 않는다.

같은 실행의 계정 비용 조회는 `Estimated=true`, `UnblendedCost=0 USD`로 반환됐다. AWS Cost Explorer 최종 청구는 지연될 수 있으므로 이 값은 확정 청구서가 아니라 현재까지의 read-only 조회 결과다. 인프라는 검증 후 41.6초에 14개 리소스가 모두 destroy됐고 Kinesis, Firehose, S3, Terraform state 잔여가 없음을 확인했다.

따라서 이 프로필에서 `PASS`가 나와도 Kubernetes rollout, HPA, RDS failover, Canary rollback, Slack 전달의 성공을 의미하지 않는다. 해당 항목은 비용 승인 후 별도 애플리케이션 프로필에서 실행하고, 결과를 서로 다른 증거로 보관한다.

2026-08-24 전체 스택 apply 중 계정 공용 GitHub OIDC Provider가 이미 존재해 `EntityAlreadyExists`가 발생했다. 이후 workload Terraform은 OIDC Provider를 생성하지 않고 data source로 읽도록 변경했다. 계정 공용 리소스는 bootstrap state가 소유하고 workload state가 중복 생성하지 않는 것이 재현 가능한 운영 경계다.
## 2026-08-24 전체 파이프라인 short-lived AWS 증거

비용 승인 후 전체 EKS profile도 별도로 짧게 실행해 generator → Kinesis → Firehose → S3 Bronze 경로를 확인했다. 이 결과는 앞의 pipeline-only evidence와 섞지 않는다.

| SLI | 관측값 | 판정/한계 |
|---|---:|---|
| Kinesis incoming | 41,000 records, 약 100 records/s, 8,490,148 bytes | 단기 generator 구간 |
| Kinesis write throttle | 0 | PASS |
| Kinesis latest iterator age | 0ms | 직접 iterator 확인, CloudWatch query와 구분 |
| Firehose freshness | 306~312초, threshold 600초 | PASS |
| Firehose successful puts | 1/2 metric query | metric 의미를 put 명령 수로 해석 |
| Bronze output | Parquet 2개 이상, 각 약 0.34~0.39MB | S3 직접 list 확인 |
| Athena Bronze | 29,391 rows, 100 robots, 08:16:08Z~08:21:01Z | buffer flush 전 조회는 일부 구간만 포함 |

현재 계정의 Managed Flink application 목록은 비어 있어 anomaly alert KDS 발화 결과는 검증하지 않았다. `scripts/flink_integration_test.py`는 Notebook이 RUNNING이고 alert sink가 연결된 후에만 실행한다. 따라서 이번 AWS 증거는 수집·저장·freshness/lag 경계까지이며, Flink detector의 실제 발화·Lambda/Slack 전달을 성공했다고 말하지 않는다.

## 2026-08-24 teardown 감사

전체 EKS profile은 검증 직후 Terraform destroy를 실행했다. Robot stack은 최초 destroy에서 이미지가 남은 ECR repository 때문에 repository 삭제가 거절됐고, 해당 테스트 repository를 강제 삭제한 뒤 refresh plan/apply로 state를 0개 리소스로 수렴시켰다. 이후 재발 방지를 위해 `aws_ecr_repository` 세 곳에 `force_delete = true`를 선언했다.

최종 read-only 감사에서 다음 항목은 모두 조회되지 않았다.

- EKS cluster, RDS `data-pipeline-primary`, ALB
- Robot Kinesis main/alert stream, Firehose delivery stream
- 테스트 ECR repository, 임시 Secrets Manager secret
- 프로젝트 S3 bucket, Terraform state bucket, 전용 VPC/NAT Gateway/EIP
- Raffle Terraform state와 Robot Terraform state: 각각 0개 resource

추가로 PVC가 남긴 1GiB 고아 EBS volume을 발견했다. 해당 volume은 `available`, attachment 없음, 테스트 cluster tag가 일치하는 것을 확인한 뒤 명시적으로 삭제했고 EC2 `describe-volumes` 재조회에서 `NotFound`가 반환됐다. Resource Groups Tagging API는 잠시 삭제된 ARN을 캐시해 반환했으므로, teardown 판정은 실제 서비스 control plane 조회를 우선한다. Kubernetes Stateful workload를 단기 실행할 때는 cluster 삭제만으로 PVC/EBS가 항상 제거된다고 가정하지 않는다.

따라서 현재 남아 있는 실행 리소스를 전제로 비용을 추정하지 않는다. Cost Explorer의 당일 값은 청구 지연으로 최종 청구액과 다를 수 있으므로 다음 실행에서도 `Estimated` 표기와 teardown 감사 결과를 함께 기록한다.

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

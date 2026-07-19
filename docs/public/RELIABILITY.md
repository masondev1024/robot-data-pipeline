# Reliability engineering notes

이 프로젝트의 운영 규칙은 장애를 회고하는 데서 끝내지 않고 다음 배포에서 재발하지 않게 만드는 것을 목표로 합니다.

| 실패 모드 | 원인 | 플랫폼 가드레일 |
|---|---|---|
| KDS 재생성 뒤 S3 적재 중단 | 기존 Firehose가 새 stream에 자동 연결되지 않음 | stream 수명주기와 Firehose 재생성을 한 절차로 결합 |
| alert stream은 정상인데 Slack 무알림 | Lambda event source mapping이 disabled 상태로 고착 | 복구 후 mapping 상태를 명시적으로 검증·활성화 |
| CloudWatch alarm 상시 ALARM | 0~1 ratio metric에 percent 단위 threshold 사용 | metric 단위별 threshold contract 검증 |
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

## 증거의 한계

로컬 테스트 통과는 AWS control plane, IAM, 네트워크, 실제 Kinesis/Firehose 전달을 증명하지 않습니다. 따라서 저장소는 offline 검증과 AWS E2E를 별도 workflow와 별도 상태로 취급합니다.

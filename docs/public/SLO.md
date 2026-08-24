# Streaming and batch SLO contract

이 문서는 운영 환경에서 “파이프라인이 살아 있다”를 단순 pod 상태가 아니라 데이터 지연·적재·품질로 판단하기 위한 계약입니다.

## Streaming SLO

| SLI | 기본 목표 | 측정값 | 장애 의미 |
|---|---:|---|---|
| Kinesis consumer lag | `<= 120s` | `AWS/Kinesis:GetRecords.IteratorAgeMilliseconds` | Flink/Firehose 소비자가 producer를 따라가지 못함 |
| Firehose S3 freshness | `<= 600s` | `AWS/Firehose:DeliveryToS3.DataFreshness` (seconds) | S3 Bronze 적재가 retry/buffering으로 지연됨 |
| Firehose delivery | active period에 `>= 1` | `AWS/Firehose:DeliveryToS3.Success` (successful S3 put command count) | 성공한 S3 put이 없는 전달 구간 |
| Kinesis producer throttle | `0` | `AWS/Kinesis:WriteProvisionedThroughputExceeded` | shard capacity 또는 partition-key skew 초과 |

`DeliveryToS3.Success`는 0~1 비율이 아니다. 성공한 S3 put 명령의 개수이므로 성공률처럼 평균을 내거나 `0.95`를 threshold로 사용하면 잘못된 경보가 된다. 신선도는 별도의 초 단위 `DeliveryToS3.DataFreshness`로 판단한다.

## Batch SLO

- Gold daily partition freshness: KST 02:00 이전 생성 목표(현재 측정 자동화 전).
- Batch task success: Airflow DAG의 task state와 데이터 계약 검증을 함께 확인한다.
- `cache_refresh`는 현재 upstream API 실패를 기록하고 task를 성공 처리할 수 있으므로, batch freshness SLO의 최종 성공 신호로 사용하지 않는다. 다음 단계에서 task별 `start/end/row_count/max_event_time` metric과 데이터 품질 결과를 함께 발행한다.

## Error budget and verification

`scripts/verify_pipeline_slo.py`는 CloudWatch `GetMetricData`만 호출한다.

```bash
AWS_PROFILE=develope-test AWS_REGION=eu-west-1 \
  python scripts/verify_pipeline_slo.py \
  --stream-name robot-telemetry-stream \
  --firehose-name robot-telemetry-firehose
```

- `PASS`: 모든 metric이 최근 lookback window에 존재하고 threshold를 지킨다.
- `FAIL`: 하나 이상의 SLO가 threshold를 초과했다.
- `NO_DATA`: metric이 없거나 timestamp/value 쌍이 불완전하다. 기본적으로 실패로 종료하여 “데이터가 없으니 정상”이라는 오판을 막는다.
- `--allow-no-data`는 의도적으로 producer를 꺼 둔 비용 절감 환경에서만 사용한다.

## 증거 경계

오프라인 단위 테스트는 CloudWatch 권한, metric publication, Firehose delivery, Kinesis consumer 동작을 증명하지 않는다. 실제 SLO 판정은 AWS 환경을 짧게 띄운 뒤 verifier JSON과 CloudWatch alarm history를 함께 보관해야 한다.

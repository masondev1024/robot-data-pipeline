# Flink 이상치 탐지 계약과 검증 계획

## 결론

운영 Flink 탐지기는 AWS Managed Flink Studio Notebook을 원본으로 둡니다. 저장소에는
PyFlink 배포 패키지를 다시 두지 않고, Notebook과 로컬 검증기가 같은 입력·임계값·출력
계약을 사용하는지 검사하는 코드만 둡니다.

이번에 로컬 Git 이력에서 이전 구현(`62edb9a`, `flink/anomaly_detection.py`)을
확인했습니다. 이 구현은 다음 구조를 사용했습니다.

- `robot_id`별 5분 event-time 이동 통계
- Z-Score `σ > 3`과 온도/부하 비율 조건의 OR 결합
- 1분 tumbling window로 alert 폭주 억제
- alert KDS와 S3 이력 sink를 함께 기록
- 늦은 이벤트를 처리하기 위한 watermark

이 파일은 해당 구조를 현재 Notebook 계약으로 정리한 문서입니다. 실제 실행 원본이
저장소에 있는 것처럼 표현하지 않습니다.

## 현재 계약

| 항목 | 기준값 | 비고 |
|---|---:|---|
| Z-Score | `> 3.0` | `sigma_floor=0.5`로 분산 0에 대한 0 나눗셈 방지 |
| 다변량 온도 | `motor_temp >= 92.0°C` | 2026-04-29 Notebook 튜닝 후 기준 |
| 다변량 비율 | `motor_temp / max(current_load, 1) > 2.5` | 비율 비교는 strict greater-than |
| 결합 | `Z-Score OR 다변량` | 둘 중 하나라도 만족하면 후보 |
| 통계 범위 | 5분 이동 범위 | `robot_id`별 event-time 기준 |
| 출력 집계 | 1분 tumbling | 같은 로봇·윈도우의 후보를 묶음 |
| 입력 | main KDS telemetry | `robot_id`, `motor_temp`, `current_load`, `timestamp` 필수 |
| 출력 | alert KDS + S3 | Lambda와 Athena/Grafana downstream의 입력 |

기존 문서와 이력에는 이전 기준(`85°C`, `1.8`, watermark 10초)도 남아 있습니다. 이는
초기 구현과 후속 Notebook 튜닝이 완전히 동기화되지 않았던 흔적입니다. 따라서 live
검증 전에 Notebook paragraph의 실제 임계값과 watermark를 확인하고, 이 문서와
`src/streaming/anomaly_contract.py`를 함께 갱신해야 합니다. 현재 저장소의 smoke
검증기와 Grafana는 튜닝 후 기준인 `92°C/2.5`를 사용합니다.

## 저장소에 추가한 검증 경계

`src/streaming/anomaly_contract.py`는 배포용 Flink 코드가 아니라 다음을 위한 순수
계약 모듈입니다.

- 정상값·경계값·Z-Score-only·다변량-only 케이스의 결정론적 단위 테스트
- `scripts/smoke_distribution.py`의 이상치 발화율 계산
- `scripts/flink_integration_test.py`의 live black-box 시나리오 기준 공유

live 검증기는 정상 marker, 다변량 이상 marker, 정상 history 뒤의 Z-Score-only marker를
main KDS에 주입합니다. alert KDS에서 두 이상 marker가 모두 나오고 정상 marker가
나오지 않아야 PASS입니다. 1분 window와 watermark 지연을 고려해 기본 polling 시간은
120초입니다.

```bash
AWS_PROFILE=develope-test AWS_REGION=eu-west-1 \
KINESIS_STREAM_NAME=<main-stream> \
KINESIS_ALERT_STREAM_NAME=<alert-stream> \
python3 scripts/flink_integration_test.py --poll-sec 120
```

## 검증 증거의 경계

현재 계정/리전에서 Managed Flink application이 조회되지 않으면 이 검증기는 KDS
주입까지만 수행할 수 있고, alert 발화 PASS를 주장할 수 없습니다. 이 경우 기록할
상태는 다음과 같습니다.

1. main KDS `IncomingRecords`와 producer throttle 확인
2. Notebook/application 실행 상태와 sink 설정 확인
3. alert KDS marker polling
4. S3 alert 객체 및 Athena 결과 확인
5. 결과가 없으면 “탐지 실패”가 아니라 “Flink 실행 원본 부재/미실행”으로 분류

Kinesis `Records Sent: 0` 같은 단일 UI 값은 sink 성공의 증거로 사용하지 않습니다.
CloudWatch Kinesis 지표, alert KDS 실제 레코드, S3 객체를 함께 확인합니다.

## 후속 성능 최적화 이슈

기능 정합성을 먼저 고정한 뒤 다음 순서로 최적화합니다.

1. 5분 `OVER` 계산의 state 크기와 checkpoint 시간을 baseline 측정
2. 현재 row를 통계에 포함하는 방식이 민감도에 미치는 영향 비교
3. event-time skew와 late event 비율을 측정해 watermark를 조정
4. 1분 alert 중복률·robot별 alert cardinality를 측정해 dedup 정책 검토
5. KDS shard 수, Firehose buffer, S3 파일 크기를 함께 조정
6. 정확도(precision/recall), 탐지 지연, CPU/state bytes를 최적화 전후 수치로 기록

최적화 후에는 임계값을 임의로 바꾸지 않고, 같은 marker replay dataset으로 탐지율과
false-positive가 유지되는지 먼저 검증합니다.

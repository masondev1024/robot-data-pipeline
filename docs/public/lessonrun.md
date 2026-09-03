# Lesson run: 데이터 엔지니어링 실습을 내 것으로 만드는 순서

이 문서는 “코드를 만들었다”에서 끝내지 않고, 내가 직접 다시 실행하고 면접에서
설계 이유를 설명할 수 있게 만드는 학습 기록이다. 정답을 외우기보다 각 단계에서
어떤 실패를 막으려고 했는지 말할 수 있어야 한다.

## 1. 먼저 머릿속에 그릴 흐름

```text
S3 Bronze Parquet
  → Glue Spark에서 스키마·범위·시간 검증
  → 정상 행만 RDS staging
  → 트랜잭션으로 target 승격
  → 감사 건수·상태로 source와 target 대조

잘못된 행
  → S3 reject + 감사 장부
  → 원천 수정 후 새 attempt_id로 재처리
```

이 흐름의 핵심은 데이터가 어디에서 실패했는지를 알 수 있다는 점이다. 최종
테이블에 숫자가 보인다는 사실만으로는 원천 누락, 중복, 부분 성공을 알 수 없다.

## 2. 직접 재현할 순서

### 2-1. 로컬 계약 테스트

```bash
cd /Users/mason/Documents/Codex/2026-08-24/https-github-com-masondev1024-develope-project/work/robot-data-pipeline
python3 -m pytest -q tests/migration
python3 scripts/create_migration_fixture.py --output /tmp/robot-migration/sample.parquet
```

여기서 확인할 것:

- 배터리·부하 범위와 모터 온도 범위가 왜 계약에 들어가는가?
- 같은 업무 컬럼이면 왜 같은 `event_id`가 나와야 하는가?
- 중복을 애플리케이션 코드가 아니라 DB PK도 막아야 하는 이유는 무엇인가?

### 2-2. AWS에서 정상 배치 실행

```bash
export AWS_PROFILE=develope-test
export AWS_REGION=ap-northeast-2
terraform -chdir=terraform/migration_lab output
```

실제 값은 출력과 Secret에서 확인하고, 비밀번호는 터미널 기록이나 문서에
복사하지 않는다. 실행 순서는 `S3 업로드 → bootstrap → extract → promote →
verify`로 지킨다. 각 단계가 성공했다고 다음 단계를 맹목적으로 시작하지 말고
감사 상태와 실행 로그를 확인한다.

### 2-3. 같은 batch 재실행

정상 batch의 `promote`를 같은 `batch_id`, `attempt_id`로 다시 실행한다. 기대
결과는 target 총 건수와 고유 event_id가 늘지 않는 것이다. 이것이 멱등성의
작은 실험 증거다. 다만 Glue·DB·파일 시스템 전체가 exactly-once가 된 것은
아니며, 시스템 경계에서는 at-least-once를 전제로 설계했다.

### 2-4. 잘못된 데이터 실행

`battery_level=120`처럼 계약을 어기는 행을 넣는다. 기대 결과는 다음과 같다.

| 확인 지점 | 기대 결과 |
| --- | --- |
| Glue 상태 | `FAILED` 또는 정책상 `REJECTED` |
| S3 reject | 행과 `INVALID_BATTERY_LEVEL` 사유 존재 |
| RDS staging | 0건 |
| RDS target | 잘못된 행 0건 |
| 감사 테이블 | source 2, accepted 1, rejected 1, merged 0 |

실제 이번 실행도 이 값과 일치했다. 정상 target 4건이 그대로 남았다는 점까지
확인해야 실패 격리가 증명된다.

### 2-5. 비용을 남기고 폐기

실험 시작·종료 시각, Glue 작업 시간, RDS 크기, Endpoint 개수, 검증 결과를
기록한 뒤 Terraform으로 자원을 폐기한다. 비용을 아끼는 것은 작은 인스턴스를
고르는 것만이 아니라 “검증이 끝난 즉시 삭제할 수 있는 구조”를 만드는 것이다.

## 3. 이번 실습에서 얻은 운영 감각

### 데이터 계약은 코드보다 먼저 보는 운영 경계다

컬럼·범위·시간·허용 코드가 명확해야 실패를 자동으로 분류할 수 있다. 계약이
없으면 null, 늦은 데이터, 중복을 정상 데이터로 착각한다. 다음 단계에서는 계약
버전과 스키마 호환 규칙을 감사 장부에 추가한다.

### 실패한 작업도 산출물이다

SG 오류, Secret 연결 누락, Spark 타입 오류를 고치면서 실패 실행 ID와 원인을
남겼다. 이런 기록은 다음 사람의 복구 시간을 줄이고, 장애가 데이터·네트워크·
인증 중 어디에 속했는지 빠르게 구분하게 해준다.

### 재처리는 정상 운영 시나리오다

파일 재생성, Glue 재시도, DB 승격 재실행을 예외가 아니라 기본 흐름으로 본다.
`batch_id`, `attempt_id`, `event_id`를 분리하면 “같은 데이터의 다른 시도”와
“새 데이터”를 구분할 수 있다.

### 관측성은 성공률 하나로 부족하다

최소한 source, accepted, rejected, duplicate, staged, merged, target distinct
count를 맞춰야 한다. 여기에 Glue 실행시간, RDS CPU·연결 수, 처리량, freshness,
lag를 붙여야 용량과 SLO를 말할 수 있다.

## 4. 현재 증명한 것과 아직 증명하지 않은 것

### 증명한 것

- 서울 리전에서 private RDS와 Glue JDBC 연결이 실제로 통신했다.
- 정상 4건이 4건으로 적재·승격됐다.
- 같은 batch 재실행 후 target이 4건으로 유지됐다.
- 잘못된 배치 2건 중 1건이 reject되고 0건이 target에 들어갔다.
- 로봇 이관, 날씨 품질 렌더러, Kafka Parquet sink의 자동화 테스트가 통과했다.

### 아직 증명하지 않은 것

- 1천 대 이상 로봇의 처리량과 비용
- Multi-AZ RDS failover와 백업 복구 시간
- Iceberg snapshot 기반 스트리밍 exactly-once
- 실제 운영 데이터의 장기 freshness·lag SLO

이 경계를 명확히 말하는 것이 오히려 신뢰도를 높인다. 구현하지 않은 범위를
운영 성과처럼 표현하지 않고, 다음 실험 계획으로 연결한다.

## 5. 이력서와 면접에서의 설명 구조

다음 네 문장 순서로 설명하면 기술 나열보다 판단이 잘 드러난다.

1. 문제: S3에 쌓인 로봇 텔레메트리를 RDS 서비스 조회 계층으로 옮길 때 중복과
   잘못된 값이 섞일 수 있었다.
2. 판단: Glue에서 계약을 검증하고, 오류는 reject·감사로 격리하며, target은
   결정적 event_id와 트랜잭션 승격으로 멱등성을 보장했다.
3. 결과: 정상 4건은 4건 승격, 재실행 후 고유 event_id 4건 유지, 잘못된 2건은
   1건 거부·0건 승격으로 확인했다.
4. 운영 관점: 실험 환경에는 NAT·EKS·Bastion을 넣지 않아 비용을 낮췄고, 실제
   대규모 처리량·Multi-AZ는 별도 프로필로 남겼다.

## 6. 다음 학습 과제

1. 같은 계약에 늦게 도착한 파일과 중복 파일을 추가하고 backfill 범위를 정한다.
2. Glue 작업에 단계별 건수와 실행 시간을 CloudWatch 지표로 보낸다.
3. RDS Multi-AZ 프로필을 별도로 만들어 장애 전환 시간과 애플리케이션 재시도
   동작을 측정한다.
4. Kafka Parquet sink를 Iceberg 테이블로 바꾸고 snapshot, schema evolution,
   compaction, consumer lag를 검증한다.
5. 각 결과를 “기대값·실제값·판정·다음 조치” 표로 계속 남긴다.

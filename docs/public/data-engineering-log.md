# 데이터 엔지니어링 작업 기록

이 문서는 구현 목록만 적는 문서가 아니다. 어떤 장애가 있었는지, 왜 그 설계를
골랐는지, 실제로 어디까지 확인했는지를 나중에 다시 설명할 수 있도록 남기는
작업 기록이다. 실제 실행 결과와 아직 하지 않은 검증은 구분해서 쓴다.

## 작업 범위

| 영역 | 이번에 남긴 결과 | 증명 수준 |
| --- | --- | --- |
| 래플 부하·관측성 | 기존 k6, Prometheus, Grafana, API·DB·HPA·ALB 지표와 용량 문서 | 기존 AWS 실험 증적 |
| 배포 안정성 | Argo Rollouts 분석·자동 되돌리기, 잘못된 배포·Pod·DB 장애 훈련 문서 | 기존 저장소 구현·문서 |
| 로봇 데이터 이관 | S3 Parquet → Glue Spark → private RDS MySQL, reject·감사·재처리 | AWS 서울 리전 실환경 실행 |
| 날씨 데이터 제품 | 예보 품질 Gold export 보고서와 행정동-격자 품질 조인 도구 | 로컬 테스트 실행 |
| Kafka 분석 저장소 | canonical event → 중복 방지 장부 → 날짜별 Parquet | 로컬 테스트 실행 |
| 미디어 실험 | HLS·CloudFront·Cloudflare 경계와 비용·운영 문서 | 기존 미디어 Lab 구현·문서 |

래플과 미디어 Lab은 이번 문서에서 다시 배포하지 않았다. 이미 남아 있는 실행
증적과 코드를 참조하고, 이번 실환경 비용 검증은 로봇 데이터 이관에 집중했다.

## 2026-09-03 작업 흐름

1. AWS SSO로 계정에 로그인하고 기본 작업 리전을 `ap-northeast-2`로 고정했다.
   SSO 로그인 리전과 실제 서비스 리전은 별개이므로, 프로필의 SSO 리전은
   `ap-northeast-2`에 있는 IAM Identity Center 설정을 따르고 Glue·RDS·S3도
   서울 리전으로 명시했다.
2. Terraform으로 짧은 실험용 VPC와 private RDS, Glue 연결·작업, S3 경로,
   Secrets Manager를 만들었다. EKS, NAT Gateway, ALB, Bastion, RDS 읽기
   복제본은 만들지 않았다.
3. 정상 Parquet 4건을 Bronze 경로에 넣고 스키마 설치 → 계약 검증 → staging
   적재 → 트랜잭션 승격 → 건수 검증 순서로 실행했다.
4. 같은 batch를 다시 승격해도 target 총 건수와 고유 `event_id`가 4건으로
   유지되는지 확인했다.
5. `battery_level=120`인 잘못된 행을 포함한 2건을 넣고, 배치가 거부 상태가
   되며 reject Parquet와 감사 상태가 남고 RDS target에는 들어가지 않는지
   확인했다.
6. 실행 ID와 건수 결과를 비밀값 없이 `docs/public/evidence/`에 복사한 뒤
   Terraform destroy로 클라우드 자원을 폐기했다.

## 설계 판단과 근거

### D-001. 사설 RDS + 필요한 VPC Endpoint만 사용

실제 요구사항은 Glue가 S3의 데이터를 읽어 같은 VPC의 private RDS로 쓰는
경로를 확인하는 것이었다. 따라서 인터넷으로 나가는 NAT Gateway와 운영용
Bastion을 추가하지 않고, S3 Gateway Endpoint와 Glue가 필요한 AWS API용
Endpoint만 선택했다. 이 선택은 실험 비용과 외부 노출 면을 줄인다.

대신 단일 AZ RDS이므로 Multi-AZ 장애복구를 증명하는 구성은 아니다. 고가용성이
필요한 운영 프로필에서는 Multi-AZ, 백업, 복구 시점 목표, 장애 전환 시간을
별도 실험으로 측정해야 한다.

### D-002. 작은 RDS와 Glue 작업자, 동시 실행 1개

샘플 4건의 데이터 품질과 이관 경계를 확인하는 데 큰 DB나 여러 작업자가
필요하지 않았다. RDS는 `db.t4g.micro`, 20 GiB gp3, 백업 보존 0일,
Glue는 G.1X 2개·최대 10분·동시 실행 1개로 고정했다. 동시 실행을 막은 것은
비용뿐 아니라 같은 batch가 서로 덮어쓰는 실험 오염을 방지하기 위해서다.

이 설정으로 대규모 처리량을 주장하지 않는다. 실제 용량을 말하려면 행 수와
파일 수를 키워 Glue 시간, RDS CPU·연결 수, 실패율을 함께 측정해야 한다.

### D-003. 데이터 계약 위반은 배치 전체를 닫힌 상태로 처리

유효한 행만 먼저 RDS에 넣고 나중에 실패시키면 부분 성공을 놓치기 쉽다.
그래서 계약 위반이 하나라도 있으면 유효 행을 staging에 남기지 않고 reject
경로와 감사 테이블만 남기는 fail-closed 정책을 사용했다. 이후 원천 데이터를
고치거나 계약 버전을 올려 새 `attempt_id`로 재처리한다.

### D-004. 결정적인 event_id + DB 제약 + 트랜잭션 승격

Glue 재실행과 DB 재시도는 현실적인 at-least-once 상황이다. 업무 컬럼을
정규화해 SHA-256 `event_id`를 만들고 target PK와 `(robot_id, event_time)`
고유 키를 두었다. 승격은 `ON DUPLICATE KEY UPDATE`와 트랜잭션으로 처리했다.
따라서 재실행 중복을 줄일 수 있지만 Kafka offset, Glue, DB를 하나로 묶은
exactly-once라고 말하지 않는다.

### D-005. 민감정보는 작업 인자와 증적에서 제외

RDS 접속 비밀번호는 Glue 인자에 직접 넣지 않고 Secrets Manager에서 읽었다.
실행 결과 JSON에도 endpoint, 비밀번호, secret 값은 넣지 않았다. 운영 환경에서는
KMS 키·IAM 최소 권한·비밀값 회전·CloudTrail 접근 기록을 추가한다.

### D-006. 날씨 품질 결과에 `NO_METRICS`를 허용

품질 지표가 없는 장소를 0점으로 채우면 품질이 낮은 것과 데이터가 없는 것을
구분할 수 없다. 그래서 공간 조인 결과에 `NO_METRICS`와 근거 상태를 남긴다.
이는 데이터 품질에서 결측과 실제 0을 구분하는 기본 원칙이다.

### D-007. Kafka sink는 Iceberg 전환 전 경계를 명시

현재 sink는 DuckDB로 중복 장부와 날짜별 Parquet를 검증하는 작은 실습이다.
Kafka offset commit과 파일 commit은 하나의 트랜잭션이 아니므로 at-least-once다.
운영 전환 시에는 Spark Structured Streaming + Iceberg snapshot, 스키마 호환성,
consumer lag·freshness·backfill 정책을 추가해야 한다. 구현하지 않은 것을
구현했다고 쓰지 않는 것이 이력서 신뢰도에 더 중요하다.

## 실제 AWS 검증 수치

| 배치 | 원천 | 정상 | 거부 | staging | 승격 | 최종 target | 상태 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `robot-demo-20260903` | 4 | 4 | 0 | 4 | 4 | 4 | `PROMOTED` |
| `robot-invalid-20260903` | 2 | 1 | 1 | 0 | 0 | 기존 4 유지 | `REJECTED` |

정상 배치는 10:08:31~10:35:48 KST 사이에 schema, extract, promote, replay,
verify를 실행했다. 주요 단계의 실행 시간은 bootstrap 약 90초, extract 약
140초, promote 약 57초였다. 거부 행은 `battery_level=120`으로 식별됐고
`INVALID_BATTERY_LEVEL` 사유의 Parquet reject 파일이 남았다. 10:47 KST에
Terraform destroy가 38개 리소스를 삭제했고, 전용 VPC·RDS·NAT·Endpoint·Glue·
Secret·S3를 다시 조회했을 때 남은 리소스가 없었다.

같은 날 Cost Explorer를 조회한 결과는 `Estimated=true`,
`UnblendedCost=0 USD`, 서비스별 그룹 없음이었다. 비용 데이터는 늦게 반영될
수 있으므로 이 값을 최종 청구액이라고 쓰지 않고, “실험 직후 조회 결과”로만
남긴다.

최종 검증 원본은 다음 파일이다.

- `evidence/2026-09-03-migration-success.json`
- `evidence/2026-09-03-migration-reject.json`

## 실패를 통해 확인한 것

- Glue JDBC 연결은 URL만 있다고 끝나지 않는다. 연결에 Secret ID를 연결해야
  작업이 private RDS 인증정보를 가져올 수 있다.
- Glue VPC 작업자 보안 그룹은 작업자끼리 통신할 수 있도록 자기 자신에 대한
  전체 인바운드 규칙이 필요했다. 인터넷 전체를 허용하지 않고 자기 SG로
  제한했다.
- SQL 주석 안의 세미콜론을 단순히 `split(';')`하면 주석 일부가 SQL로 실행될
  수 있다. full-line 주석을 제거한 뒤 문장을 나누도록 수정했다.
- Spark가 `None`만 가진 감사 행의 타입을 추론하지 못했다. 감사 스키마를
  명시적으로 지정해 실패 경로도 안정적으로 기록했다.
- Glue 작업은 동시 실행 1개로 제한했기 때문에 작업 중 즉시 재실행하면
  `ConcurrentRunsExceededException`이 발생한다. 다음 실행은 상태를 조회하고
  앞선 작업이 끝난 뒤 시작해야 한다.

상세 원인과 재발 방지는 `troubleshooting.md`에 따로 정리했다. 직접 다시
실습할 순서는 `lessonrun.md`에 정리했다.

## 이력서·면접에서 말할 수 있는 핵심

> S3 Bronze Parquet를 AWS Glue Spark로 검증해 private RDS staging에 적재하고,
> 계약 위반 데이터는 reject와 감사 장부로 격리했습니다. 동일 batch를 재실행해도
> 결정적인 event_id와 DB 제약으로 target 중복이 생기지 않는 것을 확인했고,
> 정상 4건은 4건으로 승격되며 잘못된 배치 2건은 1건 거부·0건 승격으로 끝나는
> 수치를 남겼습니다. 비용을 낮추기 위해 실험 환경에서는 NAT·EKS·Bastion을
> 제외하고 필요한 Endpoint와 작은 RDS/Glue 작업자만 사용했습니다.

이 문장을 사용할 때는 “대규모 처리량을 검증했다”, “완전한 exactly-once다”,
“Multi-AZ 장애복구를 했다”라고 확대하지 않는다. 이번 증적이 뒷받침하는 것은
작은 데이터셋의 계약 검증·격리·멱등 재처리·감사 경계다.

## 다음에 확장할 작업

1. 1천·1만·10만 행으로 부하 크기를 올리고 처리량과 비용을 함께 기록한다.
2. RDS CPU, 메모리, 연결 수, Glue DPU 시간을 CloudWatch 지표로 수집한다.
3. Multi-AZ RDS failover, 백업 복구, private subnet 접속 장애를 별도 비용
   프로필로 실행한다.
4. S3 원천 계약을 Glue Data Quality 또는 dbt 검사와 연결하고 스키마 버전을
   감사 장부에 추가한다.
5. Kafka sink를 Iceberg snapshot과 consumer lag·freshness 알림까지 확장한다.

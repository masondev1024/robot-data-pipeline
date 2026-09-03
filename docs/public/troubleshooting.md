# 트러블슈팅 기록

문제 해결은 “에러를 없앴다”보다 증상, 확인한 사실, 원인, 수정, 재발 방지를
남기는 것이 목적이다. 아래 사례는 2026-09-03 서울 리전 Glue 실험에서 실제로
발생한 기록이다.

## 1. Glue JDBC 연결에 Secret ID가 빠짐

### 증상

Glue 작업 연결을 만들었지만 RDS 접속 작업이 시작되지 않거나 연결 설정
검증에서 실패했다.

### 확인한 사실

Glue Connection의 타입은 JDBC였지만 접속 속성에 JDBC URL만 있고 Secrets
Manager 연결 식별자가 없었다.

### 원인

Glue의 JDBC 연결은 URL과 인증정보를 함께 알아야 한다. 이번 설계는 비밀번호를
작업 인자로 노출하지 않고 Secrets Manager를 사용했는데, 연결 리소스에 그
Secret을 명시하지 않은 상태였다.

### 조치

Terraform의 연결 속성을 `JDBC_CONNECTION_URL`과 `SECRET_ID` 조합으로 수정하고,
작업 역할에 Secret 읽기 권한을 부여한 뒤 bootstrap 작업을 재실행했다.

### 재발 방지

연결 리소스 검토 때 URL, Secret 연결, private subnet, SG를 한 묶음으로 확인한다.
비밀번호를 Terraform 출력·Glue 인자·로그에 넣지 않는다.

## 2. Glue VPC 보안 그룹의 자기 자신 허용 누락

### 증상

bootstrap 실행 직후 다음 오류로 중단됐다.

```text
At least one security group must open all ingress ports.
To limit traffic, the source security group in your inbound rule can be restricted to the same security group
```

실패 실행: `jr_d5a1efff2e6d159bc79f7185b285175c3b2ea1dbdf97c37d7706e45f6116f1e1`

### 원인

Glue가 VPC 안에 만드는 작업자 ENI끼리 통신할 수 있도록 SG 자기 자신에 대한
전체 포트 인바운드 규칙이 필요했다. 처음에는 RDS 3306만 허용했다.

### 조치

Glue 전용 SG에 source를 같은 SG로 제한한 self-ingress 전체 프로토콜 규칙을
추가했다. `0.0.0.0/0`은 열지 않았다. 이후 bootstrap이 약 90초 만에 성공했다.

### 재발 방지

Glue VPC 작업을 만들 때 RDS SG의 3306 허용과 Glue SG의 self-ingress를 별도로
검토한다. SG 변경 후 인터넷 노출 여부를 먼저 확인한다.

## 3. SQL 주석의 세미콜론이 문장 분리를 깨뜨림

### 증상

SG 문제를 수정한 뒤 schema bootstrap이 다음과 비슷한 SQL 문법 오류로 실패했다.

```text
You have an error in your SQL syntax near 'target is idempotent by event_id'
```

실패 실행: `jr_7d7f97e75c8e45f052f702e14b91e99585c0b0d7e71e304977b9fb4d14c5bdca`

### 원인

스키마 설명 주석에 `attempt; target ...`처럼 세미콜론이 들어 있었고, 코드가
주석을 제거하기 전에 단순히 `split(';')`했다. 주석 일부가 JDBC SQL로 전달됐다.

### 조치

full-line `--` 주석을 먼저 제거한 뒤 SQL 문장을 분리하도록 bootstrap 작업을
수정했다. 성공 실행은 `jr_de135f38f0f4e844c4f7a2760df8a7e1ab7b7943dbffa7a817f9c6ef9ede0f66`다.

### 재발 방지

운영에서는 검증된 SQL 실행기나 migration 도구를 사용하고, 최소한 주석·문자열
안의 구분자를 고려한 파서를 사용한다. schema bootstrap은 빈 DB에서만 실행하고
재실행 가능성을 별도로 검증한다.

## 4. Spark 감사 행의 타입 추론 실패

### 증상

정상 데이터가 RDS에 기록된 뒤에도 extract 작업이 다음 오류로 실패했다.

```text
PySparkValueError: [CANNOT_DETERMINE_TYPE] Some of types cannot be determined after inferring.
```

실패 실행: `jr_6707c15169993c2dad97bee5e4390efdd0736466e2464e57a8a3b1f946f2df06`

### 원인

감사 행의 오류 메시지가 정상 경로에서는 `None`이어서 Spark가 해당 컬럼의
타입을 추론할 수 없었다. 데이터 적재 자체와 감사 기록 성공을 한 단계로
생각한 것이 문제였다.

### 조치

감사 DataFrame에 `StructType`을 명시하고 nullable 문자열 컬럼을 선언했다.
같은 입력을 `attempt-02`로 다시 실행해 extract가 성공했고, 이후 promote와
replay도 성공했다.

### 재발 방지

운영 감사·reject 스키마는 샘플 데이터로 추론하지 않고 계약으로 고정한다.
정상·실패·빈 배치 각각을 테스트한다.

## 5. Terraform 출력 명령을 잘못된 디렉터리에서 실행

### 증상

`terraform output`이 비어 있거나 출력값을 찾지 못했다.

### 원인

Terraform 구성은 `terraform/migration_lab` 아래에 있는데 저장소 루트에서
명령을 실행했다. 다른 작업 디렉터리의 상태를 조회한 셈이다.

### 조치

모든 운영 명령을 다음처럼 상태 디렉터리를 명시했다.

```bash
terraform -chdir=terraform/migration_lab output -raw bucket_name
terraform -chdir=terraform/migration_lab destroy -auto-approve
```

### 재발 방지

실행 문서에서 `-chdir`를 사용하고, destroy 전에는 `terraform state list`와
리전·계정·프로젝트 태그를 확인한다.

## 6. 동시 실행 제한 때문에 재실행이 거부됨

### 증상

promote가 끝나기 전에 같은 작업을 바로 다시 시작하자
`ConcurrentRunsExceededException`이 발생했다.

### 원인

비용과 실험 오염을 막기 위해 Glue 작업의 `max_concurrent_runs=1`을 선택했다.
따라서 앞선 실행이 `RUNNING`인 동안 두 번째 실행은 정상적으로 거부된다.

### 조치

임의로 중복 실행하지 않고 `get-job-run`으로 종료 상태를 확인한 다음 replay를
시작했다. replay 실행 `jr_8de7749dadb9ee254940150d0e6fea8c6ac9e7ce168913e428edacb4949ed090`은
성공했고 target 건수도 변하지 않았다.

### 재발 방지

재시도는 상태 조건을 기다리는 방식으로 자동화한다. 운영에서는 batch lock,
지수 백오프, 실행자별 `attempt_id`를 사용하고, 동시성을 올릴 때 RDS 쓰기
경합과 비용을 먼저 측정한다.

## 7. 검증 작업의 인자 이름 불일치

### 증상

거부 배치 건수 검증을 시작했지만 Glue가 56초 후 다음 오류로 중단됐다.

```text
GlueArgumentError: the following arguments are required: --OUTPUT_PATH
```

실패 실행: `jr_afd2fbf9f40afd7bb189afa418495c0afe282bde3ba909b0fe3063c582ea0645`

### 원인

스크립트가 요구하는 인자는 `--OUTPUT_PATH`인데 실행 명령에서 임의로
`--OUTPUT_S3`를 전달했다. 데이터 문제나 네트워크 문제가 아니라 실행 계약
불일치였다.

### 조치

스크립트의 `getResolvedOptions` 선언을 기준으로 `--OUTPUT_PATH`로 재실행했다.
최종 검증 `jr_299d6bfda55a3fd6a1a549059388cb0c6acad7651fa2472d0ab9747cc296986d`가
성공했고 감사 건수는 source 2, accepted 1, rejected 1, merged 0이었다.

### 재발 방지

작업별 필수 인자를 README와 Terraform 기본 인자에 함께 정의하고, 실행 전에
`getResolvedOptions`와 명령의 키를 비교하는 작은 계약 테스트를 둔다.

## 장애를 분류하는 순서

1. 계정·리전·프로필이 맞는지 `aws sts get-caller-identity`로 확인한다.
2. Glue 작업 상태와 오류 시간을 확인하고, CloudWatch 로그에서 첫 원인을 찾는다.
3. 네트워크(SG·subnet·Endpoint), 인증(Secret·IAM), 데이터 계약, DB 제약 순서로
   경계를 좁힌다.
4. 수정 뒤에는 정상 경로뿐 아니라 실패 입력과 재실행을 다시 돌린다.
5. 결과 건수와 감사 상태를 저장하고, 마지막에 자원을 폐기한다.

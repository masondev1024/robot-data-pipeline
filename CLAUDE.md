# AI Developer Harness Rules & Constraints

## 1. Global Directives (Feedforward Controls)
- **[CRITICAL] No Blind Coding:** 사용자의 명시적인 승인(`/plan.md` 내 상태가 `[APPROVED]`로 변경됨) 전에는 절대 프로덕션 코드(`.py`, `.tf`, `.sql`)를 작성하거나 수정하지 마라.
- **Plan First:** 모든 작업은 `/plan.md`에 목적과 수정 경로를 선언하고 인간의 리뷰(Human-in-the-loop)를 대기한다.
- **Git Revert Override (Auto-Healing):** 오류 발생 시 Worker가 최대 2회 자가 교정을 시도한다. 2회 후에도 실패하면 execute.py가 자동으로 `git reset --hard HEAD`를 실행하여 부분 변경을 정리한 뒤 종료한다. 단, 아키텍처 원칙 위반·보안 취약점이 발견된 경우 즉시 리셋한다.

## 2. Modern Data Engineering Standards
이 프로젝트는 단순한 파이프라인이 아닌, 엔터프라이즈 수준의 확장성과 멱등성을 보장해야 한다. 다음 원칙을 반드시 준수하라.

- **Infrastructure as Code (Terraform):** - 하드코딩 금지. 모든 환경 변수는 `variables.tf`로 분리한다.
  - 모듈화(`modules/`)를 통해 재사용성을 극대화한다.
- **Streaming Pipeline (Kinesis & Flink):**
  - Kinesis Data Streams (KDS) 구성 시 Shard Iterator와 데이터 보존 기간(Retention Period)을 명시적으로 설정한다.
  - Flink 집계 시 Late Data(지연 데이터) 처리를 위한 Watermark(워터마크) 로직을 반드시 포함한다.
- **Data Lakehouse (Firehose & S3):**
  - KDF에서 S3로 적재 시 **반드시 Parquet 포맷으로 변환(Format Conversion)**한다.
  - `year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/` 형태의 **Dynamic Partitioning(동적 파티셔닝)**을 적용한다.
- **Batch Orchestration (Airflow):**
  - 모든 DAG와 Task는 재실행 시에도 결과가 동일한 **멱등성(Idempotency)**을 보장하도록 작성한다.
  - Task 간 데이터 전달은 XCom 사용을 지양하고, 외부 스토리지(S3) 경로를 매개변수로 전달한다.
- **Serverless Analytics (Athena):**
  - 파티션된 S3 데이터를 읽을 때, 비용 최적화를 위해 **Partition Projection(파티션 프로젝션)**을 테이블 DDL에 적용한다.


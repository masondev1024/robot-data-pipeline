# Step 1: airflow-setup

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/PRD.md`
- `/sql/bronze_ddl.sql`

## 작업

Airflow를 로컬에서 빠르게 실행할 수 있는 `docker-compose.yaml`을 프로젝트 루트에 작성하라.

### `docker-compose.yaml`
- 서비스: `airflow-webserver`, `airflow-scheduler`, `postgres`(메타DB), `airflow-init`(초기화)
- 이미지: `apache/airflow:2.9.0` (또는 최신 2.x)
- DAG 디렉토리: `./dags:/opt/airflow/dags` 볼륨 마운트
- 환경변수:
  - `AIRFLOW__CORE__EXECUTOR=LocalExecutor`
  - `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:airflow@postgres/airflow`
  - `AIRFLOW_CONN_AWS_DEFAULT=aws://...` 또는 별도 Connection 설정 안내 주석
  - AWS 자격증명: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION=ap-northeast-2` — `.env` 파일에서 `env_file: .env`로 로드
- `airflow-init` 서비스: DB 초기화 + 기본 Admin 계정 생성

### `requirements.txt` (Airflow 추가 패키지)
- `apache-airflow-providers-amazon` (Athena Operator, S3 Hook 포함)
- `boto3`

### 실행 방법 주석
`docker-compose.yaml` 상단에 아래 주석을 포함하라:
```yaml
# 시작: docker compose up -d
# 종료: docker compose down
# Airflow UI: http://localhost:8080 (admin/admin)
# DAG 폴더: ./dags/ 에 .py 파일을 추가하면 자동 감지
```

## Acceptance Criteria

```bash
docker compose config --quiet
# docker-compose.yaml 구문 오류 없음
```

## 검증 절차

1. 위 AC 커맨드를 실행한다. (`docker`가 없으면 "blocked" 처리)
2. 아키텍처 체크리스트를 확인한다:
   - `./dags` 볼륨 마운트가 있는가?
   - AWS 자격증명이 `env_file: .env`로만 로드되는가? (하드코딩 금지)
   - `apache-airflow-providers-amazon`이 포함되어 있는가?
3. 결과에 따라 `phases/2-batch/index.json`의 step 1을 업데이트한다:
   - 성공 → `"status": "completed"`, `"summary": "docker-compose.yaml 생성: Airflow LocalExecutor, PostgreSQL, dags/ 마운트, AWS Provider 포함"`
   - Docker 미설치 → `"status": "blocked"`, `"blocked_reason": "docker 명령어를 찾을 수 없음. Docker Desktop을 설치한 뒤 재실행하세요."`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

- `AIRFLOW__CORE__EXECUTOR=KubernetesExecutor`를 사용하지 마라. 이유: 로컬 Docker Compose 환경에서는 LocalExecutor가 적합하다
- AWS 자격증명을 `docker-compose.yaml`에 직접 값으로 넣지 마라. 이유: `.env` 파일로 분리해야 한다

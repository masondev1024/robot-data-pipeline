# Robot Data Pipeline + PRISM — Codex Operating Manual

매 세션 자동 로드되는 **불변 규칙·사고 가드레일·라우팅만** 둔다. 이 파일은 항상 200줄 미만으로 유지하며 새 규칙 추가 전 중복을 압축한다. 변동 작업은 `docs/plan/active.md`, 리소스 ID는 `docs/plan/naming.md`, 운영 체크는 `docs/plan/ops-checklist.md`가 원본이다.

현재 스코프: legacy 대규모 데이터 파이프라인을 production source of truth로 유지하고 PRISM AI 인과추론 레이어를 결합한다.

## 1. 영구 가드레일

### Streaming: KDS / Firehose / Flink
- KDS 삭제 시 Firehose도 삭제한다. 재생성된 KDS에 기존 Firehose는 자동 reconnect되지 않는다 (`7a1ec08`).
- KDS 재생성 후 Lambda event source mapping의 Disabled 항목을 찾아 재활성화한다 (`비용절감플랜/up.sh` step 4, 2026-05-02).
- Flink anomaly detection 코드는 git에 두지 않는다. Studio Notebook 콘솔이 single source of truth다 (ADR-010 REVISED 2).
- Flink `Records Sent: 0`만으로 sink 실패를 판정하지 않는다. CloudWatch `IncomingRecords`와 Lambda log로 검증한다.
- 다중 shard + Firehose buffer의 Athena sliding window는 `buffer interval + shard 수×1분` 이상으로 잡는다 (`f70aa38`).

### Alert / Lambda / Secret
- Slack webhook 등 민감값을 하드코딩하거나 `TF_VAR_*`로 전달하지 않는다. Terraform이 Secrets Manager/SSM을 직접 읽어 바인딩한다 (`7bcaa6d`, `5b044ca`).
- 단일 Slack 채널은 Lambda가 직접 POST한다. SNS HTTPS 구독 우회는 금지한다 (`6bfd47d`, ADR-007a).
- CloudWatch ratio 메트릭 임계값은 0.0~1.0 소수로 쓴다. `95`가 아니라 `0.95`다 (`cc5d241`).

### Terraform / IaC
- Terraform 관리 리소스를 AWS CLI로 바꿨다면 다음 apply 전 `terraform plan`/`import`로 drift를 동기화한다 (`d4459a2`).
- 빈 변수의 `CHANGEME`류 fallback을 apply하지 않는다. 민감값 fallback 자체를 만들지 않는다 (`5b044ca`).
- `aws_s3_bucket`과 `aws_athena_workgroup`은 `force_destroy = true`를 명시한다. 청산 실패 시 version/history를 명시적으로 비운다 (2026-05-23).
- `aws_eks_cluster`는 `lifecycle { ignore_changes = [bootstrap_self_managed_addons] }`를 유지한다. managed addon은 `addons.tf`가 원본이다 (2026-05-23).
- 하드코딩 금지, 입력은 `variables.tf`, 재사용 리소스는 `modules/`로 분리한다.

### Cost / Shutdown
- 셧다운 시 monitoring/Grafana 포함 모든 workload를 0으로 만들고 HPA도 제거한다 (`042fa47`).
- Ingress를 삭제하고 ALB가 0이 될 때까지 기다린다. Pod scale-down만으로는 ALB/Public IPv4 비용이 남는다 (2026-05-08).
- Karpenter stale Node finalizer를 강제 patch하지 않는다. 다음 up cycle의 controller 정리를 우선한다.

### Data Engineering
- Athena는 partition pruning을 강제하고 Bronze partition 조건은 `varchar` 타입을 맞춘다 (`ab32dd8`, `aa05ad9`, `5fd9b0e`).
- 이상 탐지는 단순 임계값이 아니라 Z-Score(σ>3)와 load 비율 등 다변량 조건을 OR 결합한다 (ADR-009).
- API Athena 쿼리에 `dt=D-1`을 고정하지 않는다. 최근 N일 내 `MAX(dt)`를 쓰고 inner/outer 모두 window 조건을 둔다 (`968fbfe`, `36784a6`).
- Firehose→S3는 Parquet + `year/month/day/hour` 동적 파티셔닝, Athena DDL은 Partition Projection을 사용한다.
- Airflow task는 멱등이어야 하며 XCom 대신 S3 경로를 전달한다. Flink 집계는 Watermark를 둔다.

### ML / SageMaker
- endpoint 미배포 시 `EndpointNotFound`를 노출하지 말고 `{"error":"predictor not deployed"}`를 반환한다 (`54a786f`, ADR-013).
- SageMaker 응답 parser는 JSON 배열과 CSV를 모두 지원한다 (`62ebc67`).
- SDK는 `Session(default_bucket=S3_BUCKET)`과 절대 `source_dir`를 사용한다 (`1a0a80f`, `95d0851`).
- Airflow IRSA에는 SageMaker PassRole과 CloudWatch logs read가 모두 필요하다 (`d9e28f1`, `81f7486`).
- `weekly_ml_retrain` 수동 실행의 `logical_date`는 `daily_etl` cron slot+2h와 일치시킨다.

### Kubernetes / Helm
- EKS Helm ServiceAccount는 chart가 생성한다. 외부 선생성 없이 `serviceAccount.annotations.eks.amazonaws.com/role-arn`만 설정한다.
- `helm upgrade`는 항상 `--version <pinned>`를 쓴다. Airflow chart는 현재 1.16.0이다.
- 무거운 SDK를 글로벌 `_PIP_ADDITIONAL_REQUIREMENTS`에 넣지 않는다. worker에만 격리하고 DAG import는 task callable 내부에서 한다 (`bdec9b5`).
- EC2 노드 강제 종료 뒤 존재하지 않는 node를 가리키는 stale `VolumeAttachment`를 정리한다 (2026-05-04).
- 인증 미들웨어 변경 시 probe path, `TestClient` fixture, Secrets Manager 조회/fail-closed 경로를 같은 변경에서 검증한다 (`9af8428`, `686f8ff`).
- `helm/airflow-values.yaml` 변경은 같은 turn에 `helm upgrade --version <pinned> --wait`까지 수행한다 (`a6a037f`). 계정/클러스터가 없으면 미배포 상태를 명시한다.
- shared/production EKS의 `kubectl exec`는 read-only도 사용자 명시 승인이 필요하다. 가능하면 ALB REST API를 쓴다.

## 2. Late-binding 배포 순서

ALB DNS/Grafana URL처럼 생성 후 결정되는 값은 `.env`에 선입력하지 않고 런타임 SSM 조회로 연결한다.

1. Terraform 전 사람이 Secrets Manager에 `/robot-telemetry/slack-webhook-url`, `/robot-telemetry/grafana-admin-password`, `/robot-telemetry/portal-basic-auth`, `/robot-telemetry/airflow-admin-password`를 저장한다.
2. `terraform apply`: EKS, Lambda, Kinesis, controller 등을 만든다. Lambda/API의 late-bound URL은 아직 비워 둔다.
3. GitHub Actions `k8s/apply`: 렌더된 manifest를 적용하고 Ingress/ALB DNS 할당을 기다린다.
4. `post-deploy`: API/Grafana DNS를 polling해 SSM `/robot-telemetry/{portal,grafana}-url`에 저장한다.
5. Lambda cold start/API startup이 SSM을 읽어 deep link와 iframe을 구성한다.

## 3. PRISM Demo 결정론

적용 범위는 `apps/prism_demo.py` + `prism/docker-compose.yml`의 demo 모드이며 production에는 적용하지 않는다.

- 변경 후 `PYTHONHASHSEED=2026 python3 -m pytest -q`를 통과시킨다.
- Bedrock은 반드시 `src/orchestration/llm_cache.py`를 거친다. offline cache miss는 `CacheReplayError`로 fail-fast한다.
- `prism/Dockerfile.app` COPY 경로와 compose `context: ..`의 repo-root 계약을 유지한다.
- `data/prism_demo.duckdb`와 `.env` 자격증명은 commit하지 않는다. 재현성은 `data/seed_data_sample.csv`와 seed로 보장한다.
- seed data는 CC BY 4.0 AI4I 2020만 사용한다.
- 상수: `random.Random(2026)`, `np.random.seed(2026)`, `PYTHONHASHSEED=2026`, mock_ts=`2026-05-22T03:00:00Z`; unit_revenue=180000, unit_defect_cost=50000, safety_violation=100000000, rul_hour_cost=25000; σ_max `<0.5 robust`, `<1.0 moderate`, 그 외 fragile.

## 4. 작업 라우팅

| 범위 | 담당 |
|---|---|
| 오늘 작업 브리핑 | `task-router` (`active.md`, 200자) |
| 사고/postmortem | `incident-archivist` (가드레일 후보 제안) |
| `terraform/`, `*.tf` | `terraform-engineer` |
| KDS/Firehose/Flink | `streaming-eng` |
| `dags/`, Airflow | `airflow-dag` |
| 비용/HPA/Karpenter | `cost-ops` |
| 큰 변경 리뷰 | `code-reviewer` |
| `src/orchestration/` PRISM | 메인 직접 수행 |

- 독립 작업은 fan-out, 의존 작업은 chain, 큰 변경은 구현 후 review gate를 쓴다. 파일 충돌 위험이 있으면 worktree를 격리한다.
- 메인은 라우팅·통합·최종 검증을 소유한다. 200줄 초과 파일이나 무거운 탐색은 Explore/도메인 agent에 위임한다.

## 5. Git·문서 운영

- 완료된 추적 파일은 별도 요청 없이 stage/commit/push한다. 일반 작업은 `main`, 큰 구조 변경만 사용자 요청 시 별도 branch를 쓴다.
- commit은 한국어 type prefix + `(mason N차)`를 쓰며 Co-Authored/Generated 문구를 넣지 않는다.
- commit/push/checkout 전 `git status`, branch, upstream을 확인한다. force push와 branch 삭제는 사용자 승인 없이는 금지한다.
- 사용자가 공개를 요청하지 않은 운영/계획 MD는 로컬에만 둔다. `active.md`는 새 작업만 append하고 AGENTS.md에는 영구 규칙만 둔다.
- 코드 변경은 targeted test→lint/typecheck/build/정적검사 순으로 검증하고, 실패나 미실행 항목을 숨기지 않는다.

## 6. 빠른 참조

- Production: `docs/INTERFACE.md`, `terraform/`, `helm/`, `k8s/`, `dags/`, `sql/`, `비용절감플랜/`, `.env.example`
- PRISM: `src/orchestration/`, `src/ml/`, `apps/`, `prism/`, `assets/`, `data/seed_data_sample.csv`
- Local-only: `docs/plan/`, `docs/superpowers/specs/`; archive: `legacy/`

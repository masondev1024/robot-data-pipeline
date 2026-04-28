# Session Handoff — 2026-04-28 (Windows → Mac)

## TL;DR
인프라는 이미 `terraform apply` 완료된 상태에서 이번 세션은 **데이터 흐름 회복 + Grafana 배포 + Bedrock 모델 통일**을 끝냈다. 발표 시연 가능 최소 형태(P0) 도달. 다음은 Flink anomaly → Slack 검증(P1)부터.

- 리전: `eu-west-1` / 계정: `827913617635` / 클러스터: `robot-telemetry-cluster`
- HEAD: `a8b4b2b` (이번 세션 변경은 모두 uncommitted — 아래 "동기화" 섹션 참조)
- Bedrock 모델: `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` (EU inference profile, Sonnet 4.5)

---

## ✅ 현재 작동 중 (검증 완료)

### 데이터 흐름
- Generator (K8s `robot-telemetry/robot-telemetry-generator`) → KDS `robot-telemetry-stream`: 분당 ~6,000 records
- Firehose `robot-telemetry-firehose` → S3 `s3://de-ai-06-smartfactory-bucket/bronze/year=YYYY/month=MM/day=DD/hour=HH/`: Parquet 1분 buffer로 적재
- Athena `robot_telemetry_db.bronze_robot_telemetry`: 세션 종료 시점 **73,415건** 카운트 통과 (계속 증가 중)
- Lambda `robot-anomaly-alert-lambda` ↔ KDS `robot-anomaly-alert-stream` 매핑됨, SNS `robot-anomaly-alerts` Slack Webhook 구독 활성. **단, Flink 측에서 alert 발행은 아직 미검증**

### API
- ALB: `k8s-robottel-robottel-6592ec7239-2016405795.eu-west-1.elb.amazonaws.com`
- `GET /` portal: 200 OK / `GET /healthz`: 200 OK

### Grafana (이번 세션 신규)
- ALB: `http://k8s-monitori-grafanai-2ac32d9244-945675115.eu-west-1.elb.amazonaws.com`
- 로그인: `admin / changeme123`
- 데이터소스 health 둘 다 OK:
  - **CloudWatch** (uid=`cloudwatch`, built-in)
  - **Athena** (uid=`athena`, plugin `grafana-athena-datasource v3.2.0` 자동 설치)
- 대시보드 4종 자동 import:
  - `Anomaly Detection Timeline` — Athena 기반
  - `Robot Fleet Status` — Athena 기반
  - `Pipeline Health` — CloudWatch 기반
  - `Robot Telemetry — Observability` — CloudWatch 기반

---

## 🎯 이번 세션 결정적 학습

### STS 리전 활성화가 IRSA의 첫 의심 지점
Generator pod이 Running이지만 KDS 전송 0건 → 로그를 보니 `RegionDisabledException: STS is not activated in this region`. 계정 단위로 eu-west-1 STS를 활성화하지 않으면 IRSA의 `AssumeRoleWithWebIdentity` 전체 실패. 활성화 위치: **AWS Console → IAM → Account settings → STS → eu-west-1 Active**. 이건 콘솔 토글이라 IaC로 잡히지 않는다. 다른 리전 새 계정에서 IRSA 막힐 때 가장 먼저 의심.

### 토큰 캐시는 pod 재시작으로 풀어야 함
STS 활성화 직후에도 botocore가 이전 실패 응답을 캐시 중이라 자동 회복 안 됨. `kubectl rollout restart deploy/<name>` 한 번이 깔끔.

### Pod 정상 작동 시 stdout 비어있는 게 정상
`src/generator/app.py`의 `print` 호출은 에러 케이스에서만 발동. 로그 비어있다고 죽은 게 아님 — 데이터 흐름은 KDS CloudWatch metrics로 검증.

### Firehose `DynamicPartitioning: false`는 timestamp 파티셔닝과 별개
Console에서 `false`로 보여도 prefix의 `!{timestamp:yyyy}` placeholder는 정상 작동. CLAUDE.md의 "Dynamic Partitioning" 요건은 timestamp 기반으로 만족.

---

## 📝 이번 세션 변경 사항 (모두 uncommitted)

### 신규 작성 파일 (Grafana 배포)
```
k8s/monitoring/grafana-namespace.yaml
k8s/monitoring/grafana-datasources.yaml
k8s/monitoring/grafana-dashboard-provider.yaml
k8s/monitoring/grafana-dashboards.yaml      # 4 dashboards 임베드, 303 lines
k8s/monitoring/grafana-deployment.yaml      # SA(IRSA) + Deployment + Service
```

### 클러스터에 적용된 변경 (kubectl로 직접)
- `kubectl rollout restart deploy/robot-telemetry-generator -n robot-telemetry` (STS 활성화 후 토큰 갱신용)
- `kubectl apply -f k8s/monitoring/` (Grafana 5 manifests + 기존 ingress 재적용)

### 콘솔 변경 (IaC 외)
- IAM Account settings → STS eu-west-1 활성화

### 변경되지 않은 untracked 파일들 (이전 세션부터)
풀스택 부활 작업이 commit 전에 그대로 남아있음:
```
terraform/cicd_gitops.tf
terraform/ebs_csi.tf
terraform/eks_and_iam.tf
terraform/karpenter.tf
terraform/modules/data_pipeline/alb_controller.tf
terraform/modules/data_pipeline/alb_controller_policy.json
terraform/modules/data_pipeline/iam_eks_irsa_full.tf
terraform/modules/data_pipeline/sns.tf
terraform/modules/data_pipeline/ssm.tf
terraform/modules/data_pipeline/xray.tf
```
이들은 이미 `terraform apply`로 클러스터에 반영된 상태이므로 단순히 git에 등록만 안 된 것. **Mac 가기 전 commit 권장** (아래 동기화 섹션).

⚠️ `terraform/.terraform.tfstate.lock.info`도 untracked로 보일 수 있음 — 이건 **stale lock 파일**이라 commit 금지. terraform 명령이 강제 종료된 흔적이므로 `terraform force-unlock <ID>` 또는 그냥 삭제. `.gitignore`에 `*.tfstate.lock.info` 패턴이 있으면 자연 무시됨.

---

## 📌 Addendum — HANDOFF 작성 후 추가 작업 (2026-04-28 PM)

### Bedrock 모델 ID 일괄 교체 (`plan_bedrock_model.md` [APPROVED] 후 폐기)
사용자가 Bedrock 장기 API 키 발급 후 로컬 테스트 중 `anthropic.claude-3-5-sonnet-20241022-v2:0`이 **eu-west-1에서 부재함을 발견**. 가용 모델 조회 후 `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` (EU inference profile, Claude Sonnet 4.5)로 결정.

**변경 5파일 / 11라인** (modified):
- `dags/robot_daily_etl.py:242` default
- `src/api/main.py:170` default
- `k8s/api/deployment.yaml:38` env value
- `tests/api/test_chat.py` 7곳 일괄
- `tests/etl/test_bedrock_report.py:226` assertion

**검증**: 로컬에서 신모델 호출 → "연결 성공" 응답 + 42/9 토큰 사용. IRSA `bedrock:InvokeModel` Resource `*`라 IAM 변경 불필요. `.env`의 `AWS_BEARER_TOKEN_BEDROC` → `AWS_BEARER_TOKEN_BEDROCK` 오타도 동시 정정.

**후속 정리**:
- `phases/4-serving/step5.md` (3곳), `phases/4-serving/step6.md` (1곳) 옛 모델 ID 정리
- `plan_bedrock_model.md` 폐기, `plan.md` AI Action Log에 한 줄 추가

⚠️ Mac에서 K8s에 반영하려면 추가 작업 필요:
1. `kubectl set env deployment/robot-telemetry-api -n robot-telemetry BEDROCK_MODEL_ID=eu.anthropic.claude-sonnet-4-5-20250929-v1:0`
   또는 `kubectl apply -f k8s/api/deployment.yaml`로 재배포
2. API 컨테이너에 `eu.` prefix 모델 호출 권한이 IRSA에 있는지 확인 (Resource `*`면 OK)

---

## 🔄 Mac으로 동기화

### 옵션 A — git push/pull (권장)
Windows에서 commit + push, Mac에서 pull. 이번 세션 작업이 보존되고 git history도 깨끗.

```bash
# Windows에서 (사용자 직접 실행)

# 1) 신규 untracked 파일들 추가 (인프라 IaC 등록 + Grafana + HANDOFF + 오늘의 Bedrock 메모)
git add k8s/monitoring/ \
        terraform/cicd_gitops.tf \
        terraform/ebs_csi.tf \
        terraform/eks_and_iam.tf \
        terraform/karpenter.tf \
        terraform/modules/data_pipeline/alb_controller.tf \
        terraform/modules/data_pipeline/alb_controller_policy.json \
        terraform/modules/data_pipeline/iam_eks_irsa_full.tf \
        terraform/modules/data_pipeline/sns.tf \
        terraform/modules/data_pipeline/ssm.tf \
        terraform/modules/data_pipeline/xray.tf \
        docs/HANDOFF.md

# 2) modified 파일들 — 의미 있는 것만 골라서 추가 (검토 후)
#    Bedrock 모델 교체분: dags, src/api/main.py, k8s/api/deployment.yaml, tests/api/test_chat.py, tests/etl/test_bedrock_report.py
#    phases md 정리: phases/4-serving/step5.md, step6.md
#    풀스택 부활 인프라 modified: terraform/main.tf, providers.tf, variables.tf, outputs.tf, modules/.../{cloudwatch,kinesis,lambda,outputs,s3,variables}.tf
#    plan.md AI Action Log 갱신
git add dags/robot_daily_etl.py \
        src/api/main.py \
        src/api/requirements.txt \
        k8s/api/deployment.yaml \
        k8s/generator/deployment.yaml \
        tests/api/test_chat.py \
        tests/etl/test_bedrock_report.py \
        phases/4-serving/step5.md \
        phases/4-serving/step6.md \
        plan.md \
        terraform/main.tf \
        terraform/providers.tf \
        terraform/variables.tf \
        terraform/outputs.tf \
        terraform/modules/data_pipeline/cloudwatch.tf \
        terraform/modules/data_pipeline/kinesis.tf \
        terraform/modules/data_pipeline/lambda.tf \
        terraform/modules/data_pipeline/outputs.tf \
        terraform/modules/data_pipeline/s3.tf \
        terraform/modules/data_pipeline/variables.tf

# 3) 삭제된 파일 처리 (.disabled → .tf 전환, 옛 iam.tf, flink.tf, WORK_LOG.md, plan_bedrock_model.md)
git add -u   # tracked 파일 삭제도 함께 stage

# 4) commit + push (HEAD = a8b4b2b 위로 1 커밋 더 + 기존 1 ahead까지 총 2개 푸시)
git commit -m "feat: Grafana 배포 + 풀스택 인프라 IaC 등록 + Bedrock 모델 ID 통일"
git push
```

⚠️ **검토 권장**:
- `.claude/settings.local.json`, `.claude/commands/review.md` modified는 **로컬 환경 전용**이라 커밋 제외 권장
- `.gitignore`도 modified — 의도된 변경이면 함께 커밋, 아니면 제외
- `flink/anomaly_detection.zip`, `terraform/modules/data_pipeline/lambda_alert.zip` modified — **빌드 산출물**이라 일반적으로 gitignore 대상. 시연용으로 commit이 필요한 상황이면 함께, 아니면 제외

### 옵션 B — patch 파일 (git 사용 못 할 때)
Windows에서 `git diff > session.patch && git status -s > untracked.txt`, Mac에서 적용.

---

## 💻 Mac 환경 셋업 체크리스트

```bash
# 1. AWS CLI 설치 + 같은 IAM 사용자(de-ai-06) credentials 설정
aws configure   # access key, secret, region=eu-west-1

# 2. kubeconfig 가져오기
aws eks update-kubeconfig --name robot-telemetry-cluster --region eu-west-1

# 3. 클러스터 접근 확인
kubectl get nodes
kubectl get pods -A

# 4. 코드 받기
cd ~/path/to/workspace
git clone <repo-url>  # 또는 기존 clone에서 git pull
cd robot-data-pipeline
```

---

## 🔍 Mac 들어가자마자 실행할 health check

```bash
# 데이터 흐름 살아있나
aws cloudwatch get-metric-statistics \
  --namespace AWS/Kinesis --metric-name IncomingRecords \
  --dimensions Name=StreamName,Value=robot-telemetry-stream \
  --start-time $(date -u -v-10M +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 --statistics Sum --region eu-west-1 \
  --query "sort_by(Datapoints,&Timestamp)[*].[Timestamp,Sum]" --output text

# K8s 상태
kubectl get pods -n robot-telemetry
kubectl get pods -n monitoring

# Athena 누적 카운트
aws athena start-query-execution \
  --query-string "SELECT count(*) FROM robot_telemetry_db.bronze_robot_telemetry" \
  --work-group robot-telemetry-workgroup --region eu-west-1

# Grafana 살아있나
curl -s http://k8s-monitori-grafanai-2ac32d9244-945675115.eu-west-1.elb.amazonaws.com/api/health
```

기대치: KDS 분당 6000 안팎, 모든 pod Running, Athena count 계속 증가, Grafana `{"status":"ok"}`.

---

## 📍 다음 단계 (P1 — 발표 임팩트)

### P1-1. Flink anomaly → Slack 끝까지 검증
가장 미검증 구간. AWS Console → Managed Service for Apache Flink → Studio Notebooks 진입. `flink/anomaly_detection.py` 코드를 노트북 환경에 붙여 실행 → Alert KDS에 record 떨어지는지 → Lambda 트리거 → Slack 채널 메시지 도착. SNS metric `NumberOfMessagesPublished` > 0 으로 정량 검증.

관련 파일: `flink/anomaly_detection.py`, `flink/deploy.sh`, `src/lambda/alert_handler.py`.

⚠️ Slack Webhook URL은 `terraform/variables.tf:47`의 default `https://hooks.slack.com/services/CHANGEME` — **실제 Webhook URL로 교체**됐는지 확인 필요. 안 됐으면 `terraform apply` 시 `-var slack_webhook_url=...`로 주입.

### P1-2. Generator anomaly trigger 강화
`src/generator/app.py`에 환경변수 `FORCE_ANOMALY_RATIO` 또는 SIGUSR1 시그널 → "지금부터 1분간 모든 로봇 모터 온도 강제 spike" 형태로 시연자가 제어 가능하게. 현재 `is_faulty` 플래그 70% 확률 spike는 시연 시점 통제 불가.

### P1-3. Grafana 대시보드 데이터소스 변수 매핑 확인
대시보드 JSON에 `${DS_ATHENA}` / `${DS_CLOUDWATCH}` 변수 참조가 있음. 첫 진입 시 datasource select 드롭다운이 뜰 수 있고, 안 뜨면 패널에 "datasource not found" 에러. 각 dashboard 한 번씩 열어서 확인 후 필요 시 JSON에서 변수를 직접 UID로 치환 (`{"type": "grafana-athena-datasource", "uid": "athena"}` / `{"type": "cloudwatch", "uid": "cloudwatch"}`).

---

## 📍 P2 (시간 남으면)

- Airflow 배포 (MWAA 또는 EKS Helm) → DAG `robot_daily_etl` 1회 trigger → bronze→silver→gold 단계 동작 시연
- SageMaker 권한 부여(현재 IAM에 `sagemaker:*` 없음) → `src/ml/train.py` 1회 실행 → Endpoint 호출 데모
- Bedrock 일일 리포트 단독 실행 (`dags/robot_daily_etl.py:_bedrock_report`)

---

## ⚠️ 알려진 이슈

| 이슈 | 우선순위 | 메모 |
|---|---|---|
| `kubernetes.io/ingress.class` annotation deprecated | low | 동작은 함. `spec.ingressClassName: alb`로 마이그레이션 권장 |
| Firehose `Compression: UNCOMPRESSED` | low | Parquet 자체에 SNAPPY 내장. 비용 최적화 시 추가 SNAPPY |
| API ECR 이미지 tagging이 `latest`만 | medium | 발표 후 SHA 태그로 deploy 추적성 확보 권장 |
| Karpenter는 컨트롤러만 동작, provisioned 노드 없음 | low | 일반 노드그룹 t3.large 3대로 충분, 시연에 불필요 |
| 현재 IAM `de-ai-06`에 `sagemaker:ListEndpoints` 없음 | medium | P2 SageMaker 데모 시 정책 추가 필요 |

---

## 📚 핵심 파일 인덱스 (자주 만질 영역)

**스트리밍** — `src/generator/app.py` · `flink/anomaly_detection.py` · `src/lambda/alert_handler.py`  
**배치/AI** — `dags/robot_daily_etl.py` · `sql/{bronze,silver,gold}_ddl.sql` · `src/ml/train.py`  
**시각화** — `grafana/dashboards/*.json` · `k8s/monitoring/*.yaml` (이번 세션 신규)  
**인프라** — `terraform/{eks_and_iam,karpenter,cicd_gitops}.tf` · `terraform/modules/data_pipeline/*.tf`  
**문서** — `docs/ARCHITECTURE.md` (메달리온 설계) · `CLAUDE.md` (프로젝트 규약) · `docs/HANDOFF.md` (이 파일)

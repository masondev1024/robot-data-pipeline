# Session Handoff — 2026-04-29 (Mac, P1 진입)

## TL;DR (2026-04-29 세션)
**P1-1(Slack 알람 경로) 사실상 완료, P1-2(시연 통제력) 코드 완료/배포 검증 대기.** SNS HTTPS 구독이 PendingConfirmation 상태로 영구 고착되는 구조적 한계를 발견하고 Lambda → Slack 직접 POST로 우회. 동시에 alert KDS에 분당 ~16 records가 정체불명으로 들어오는 걸 추적해 **Flink Studio Notebook이 이미 동작 중**이었다는 사실 확인 (HANDOFF 2026-04-28 표기와 다름). Generator에 SIGUSR1 핸들러 추가해 무대 위에서 `kubectl exec ... kill -USR1 1` 한 줄로 알람 폭주 시연 가능해짐.

- 리전: `eu-west-1` / 계정: `827913617635` / 클러스터: `robot-telemetry-cluster`
- HEAD: `88b9597` (작성 시점, ECR 새 이미지 push 검증 대기 중)
- Bedrock 모델: `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` (EU inference profile, Sonnet 4.5)

---

## 🆕 2026-04-29 세션 결과

### ✅ 완료
1. **Lambda → Slack 직접 POST 변경** (commit `6bfd47d`)
   - `src/lambda/alert_handler.py`: `sns.publish(...)` → `urllib.request` 로 Slack Webhook에 직접 POST
   - `terraform/modules/data_pipeline/lambda.tf`: env vars `SNS_TOPIC_ARN` 제거 + `SLACK_WEBHOOK_URL` 추가, `timeout = 10` 명시
   - `terraform/modules/data_pipeline/iam_eks_irsa_full.tf`: `lambda_alert_policy`에서 `sns:Publish` 제거
   - `tests/lambda/test_alert_handler.py`: 5건 SNS publish mock → urllib HTTPS POST mock (5/5 PASSED)
   - 검증: alert KDS에 mock record put → Lambda 트리거 → Slack 채널 도착 확인
   - SNS topic 자체는 유지(다른 통로 재활용 여지)

2. **Generator SIGUSR1 force-anomaly 윈도우** (commit `88b9597`)
   - `src/generator/app.py`: `_force_anomaly_until_ts` 모듈 전역 + `_should_spike` 헬퍼 + `_trigger_force_anomaly` SIGUSR1 핸들러
   - `tests/generator/test_force_anomaly.py`: 8 케이스 PASSED (회귀 43/43)
   - **시연 명령어**: `kubectl exec -n robot-telemetry deploy/robot-telemetry-generator -- kill -USR1 1` → 60초 동안 모든 로봇 spike → 자동 복귀
   - 윈도우 길이 조정: `kubectl set env ... FORCE_ANOMALY_DURATION_SEC=30`

3. **GitHub Actions workflow 빌드 컨텍스트 버그 정정** (commit `88b9597`)
   - `.github/workflows/k8s-deploy.yml`의 generator 빌드 단계: `docker build src/generator/` → `docker build -f src/generator/Dockerfile .`
   - 기존 워크플로는 Dockerfile의 `COPY src/generator/...` 경로와 어긋나 빌드 실패 상태였음

4. **claude-code 로컬 환경 문제 해결**
   - npm global prefix를 `/usr/local/...` (root 소유) → `~/.npm-global` (user 소유)로 변경
   - 옛 `/usr/local/bin/claude` symlink 및 `/usr/local/lib/node_modules/@anthropic-ai/` 정리
   - `~/.zshrc`에 `export PATH=~/.npm-global/bin:$PATH` 추가
   - 이제 `npm i -g @anthropic-ai/claude-code` 가 sudo 없이 동작

### 🔍 결정적 학습

**SNS HTTPS 구독은 Slack Webhook과 자동 연결 안 됨** — Slack Incoming Webhook은 SNS의 SubscribeURL을 GET하지 않아 구독이 영구 PendingConfirmation 상태. AWS 권장 패턴이 아님. Lambda에서 직접 POST 또는 AWS Chatbot 경유가 정답.

**Flink Studio Notebook이 실제로 동작 중** — HANDOFF 2026-04-28 문서엔 "미검증"으로 적혀 있었지만, alert KDS에 분당 ~16 records가 일정하게 들어오는 걸 추적한 결과 Flink가 이미 deploy되어 anomaly detection 중. 사용자가 threshold만 튜닝하면 됨. P1-1은 사실상 끝났다는 의미.

**Lambda timeout 3s는 빠듯함** — SSM get_parameter + urllib Slack POST + boto3 cold start 합치면 2.5~3초 소요. timeout 3s 기본값으로는 간헐적 실패. **10s로 상향 필수**.

### ⏳ 미검증/대기 중

- **Generator 새 이미지 deploy** — commit `88b9597` push 후 GitHub Actions가 이미지 빌드 → ECR push → kubectl rollout restart 진행 중. ECR `robot-telemetry-generator:latest` 디지털이 갱신되면 새 코드 반영. 자기 전 시점 ECR digest는 여전히 `5997968...` (2026-04-28 16:36 빌드)로 미갱신. 워크플로 실패 가능성 있어 GitHub Actions UI 확인 필요.
- **SIGUSR1 실 환경 검증** — 위 deploy 완료 후 `kubectl exec ... kill -USR1 1` 호출 → Slack 알람 폭주 → 60초 후 자동 복귀 확인 필요.

### 🟢 현재 상태 스냅샷 (자기 직전)

| 컴포넌트 | 상태 |
|---|---|
| Generator pod | Running (옛 이미지 `5997968...`, force-anomaly 미반영) |
| API pod | Running |
| Grafana | Running |
| Kinesis 메인 스트림 | 분당 ~6,000 records 유입 |
| Alert KDS | 분당 ~2-3 records (Flink threshold 튜닝 후) |
| Lambda | timeout=10s, env=SLACK_WEBHOOK_URL, ESM `Enabled` |
| SNS topic | 유지(Slack 구독은 PendingConfirmation, 실 사용 안 함) |
| Slack 알람 | 정상 도착 중, 분당 ~2-3개 |

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

## 📍 다음 단계 (2026-04-29 자고 일어난 후 우선순위)

### 🔥 P0 — 자고 일어나서 첫 번째로 할 것
**Generator 새 이미지 deploy 검증** (어젯밤 commit `88b9597` push 후 GitHub Actions 결과)

```bash
# 1) ECR latest digest가 갱신됐는지 (어젯밤 기준 5997968... 이면 미갱신)
aws ecr describe-images --repository-name robot-telemetry-generator \
  --region eu-west-1 --image-ids imageTag=latest \
  --query "imageDetails[0].{Digest:imageDigest, PushedAt:imagePushedAt}"

# 2) Pod의 imageID 확인 (digest가 ECR latest와 일치해야 새 코드 도는 중)
kubectl get pod -n robot-telemetry -l app=robot-telemetry-generator \
  -o jsonpath='{.items[0].status.containerStatuses[0].imageID}{"\n"}'

# 3) 새 코드 반영됐으면 SIGUSR1 시연 검증
kubectl exec -n robot-telemetry deploy/robot-telemetry-generator -- kill -USR1 1
kubectl logs -n robot-telemetry deploy/robot-telemetry-generator --tail=5
# → "force_anomaly_triggered" 이벤트 보여야 함, 이후 60초간 Slack 알람 폭주
```

**워크플로 실패 시**: GitHub Actions UI(`https://github.com/masondev1024/robot-data-pipeline/actions`)에서 최근 run 확인. 자주 발생하는 실패: ECR auth (OIDC role), Docker layer cache 미스, build context. 빌드 컨텍스트 버그는 commit `88b9597`에서 정정함 — 다른 원인이라면 로그 보고 대응.

### P1-1 — 사실상 완료
Flink Studio Notebook 동작 중, alert KDS → Lambda → Slack 흐름 살아있음. 재검증 필요한 케이스: threshold 튜닝 또는 Flink 노트북 세션 종료 시.

(이전 HANDOFF의 P1-1 원문):
> 가장 미검증 구간. AWS Console → Managed Service for Apache Flink → Studio Notebooks 진입. `flink/anomaly_detection.py` 코드를 노트북 환경에 붙여 실행 → Alert KDS에 record 떨어지는지 → Lambda 트리거 → Slack 채널 메시지 도착. SNS metric `NumberOfMessagesPublished` > 0 으로 정량 검증.

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
| Karpenter `general` NodePool spot/on-demand 혼합 운영 중 | low | 시연 스크립트 `scripts/load_demo.sh`로 부하 시 신규 노드 자동 프로비저닝, 종료 시 5분 내 회수 검증됨 |
| 현재 IAM `de-ai-06`에 `sagemaker:ListEndpoints` 없음 | medium | P2 SageMaker 데모 시 정책 추가 필요 |

---

## 📚 핵심 파일 인덱스 (자주 만질 영역)

**스트리밍** — `src/generator/app.py` · `flink/anomaly_detection.py` · `src/lambda/alert_handler.py`  
**배치/AI** — `dags/robot_daily_etl.py` · `sql/{bronze,silver,gold}_ddl.sql` · `src/ml/train.py`  
**시각화** — `grafana/dashboards/*.json` · `k8s/monitoring/*.yaml` (이번 세션 신규)  
**인프라** — `terraform/{eks_and_iam,karpenter,cicd_gitops}.tf` · `terraform/modules/data_pipeline/*.tf`  
**문서** — `docs/ARCHITECTURE.md` (메달리온 설계) · `CLAUDE.md` (프로젝트 규약) · `docs/HANDOFF.md` (이 파일)

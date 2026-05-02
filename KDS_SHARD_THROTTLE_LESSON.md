# KDS Shard Throttle — 학습 노트

> 2026-05-01 디버깅 세션에서 직접 겪은 사례를 정리. "Flink 이상탐지 알람이 안 온다" 한 줄 신고가 어떻게 KDS shard 한도 문제로 추적되었는지, 그리고 왜 단순한 "shard 늘리기"가 진짜 답이 아니었는지를 다룬다.

---

## 0. 사건 한 줄 요약

Generator pod 의 `ROBOT_COUNT` 가 yaml(50) ↔ cluster(1000) drift 상태에서 재기동되어 **분당 12만 record (= 2,000 RPS) 가 1개 shard 에 쏟아짐** → Flink Kinesis Consumer 의 GetRecords 가 read-throttle 3회 연속 실패 → source vertex `RuntimeException` → restart strategy 미설정이라 **job 전체 FAILED** → alert KDS 송신 끊김 → Lambda 호출 끊김 → Slack 알람 끊김.

웹훅 placeholder 와 별개의 문제가 같은 시점에 터져 "원인 두 겹" 형태였고, 메트릭은 거짓 양성으로 깨끗해 보였다.

---

## 1. Kinesis Data Streams Shard 한도 (Provisioned 모드)

shard 1개당 다음 한도가 있고, **둘 중 먼저 도달하는 쪽이 throttle 트리거**다.

| 방향 | 한도 |
|---|---|
| Write | **1,000 records/s** OR **1 MiB/s** |
| Read | **5 GetRecords/s** OR **2 MiB/s** |

- Read 한도가 "5 GetRecords API call/s" 인 점이 함정 — 한 호출에 최대 10,000 record 까지 가져올 수 있으나 호출 자체의 RPS 가 5 로 묶임.
- ON_DEMAND 모드는 자동 스케일이지만 query·byte 단가 모델이 달라 비용 패턴이 다름.

## 2. 부하 계산식 — 우리 프로젝트 기준

```
total_write_rps = pod_수 × ROBOT_COUNT × (1 / TICK_INTERVAL_SECONDS)
total_consumer_polling_rps = consumer_수 × 5  (default 200ms 주기)

write_한도 = shard_수 × 1,000 records/s
read_한도  = shard_수 × 5 GetRecords/s
```

이번 사례 대입:

```
write_rps = 1 × 1000 × (1 / 0.5) = 2,000 records/s
read_polling = (KDF + Flink) × 5 = 10 GetRecords/s
write_한도(shard 1) = 1,000 records/s          ← 2배 초과
read_한도(shard 1)  = 5 GetRecords/s           ← 2배 초과
```

→ write/read **양쪽 다 한도의 2배**. shard 1로는 구조적으로 못 받음.

[terraform/modules/data_pipeline/variables.tf](terraform/modules/data_pipeline/variables.tf) 의 주석에 "운영 기본 10, 발표 시연 시 -var=kds_main_shard_count=1" 이라 적혀 있는 이유 — 10000 robot 풀 부하는 원래 10 shard 를 전제로 설계됐다.

## 3. 한도 초과 시 무슨 일이 벌어지나

### Write 측 (Producer = Generator)
- KDS API가 `PutRecord/PutRecords` 응답에 `ErrorCode: ProvisionedThroughputExceededException` 부분 실패로 표시
- Generator 의 `_send_with_retry` ([src/generator/app.py:219-281](src/generator/app.py#L219-L281)) 가 실패 인덱스만 추려 지수 백오프 재시도 — 단기 throttle 흡수 가능
- 그러나 지속적 한도 초과면 max_attempts(3회) 후 record drop, `put_records_giving_up` 로그 출력

### Read 측 (Consumer = Flink)
- Flink Kinesis Connector 의 `KinesisProxy.getRecords` 가 `ProvisionedThroughputExceededException` 받으면 backoff 후 retry
- **기본 `scan.shard.getrecords.maxretries=3`** — 3연속 실패하면 source operator 가 `RuntimeException("Retries exceeded for getRecords operation - all 3 retry attempts failed")` 를 throw
- Source operator 가 죽으면 Flink 의 **Restart Strategy** 가 결정:
  - `NoRestartBackoffTimeStrategy` (Studio Notebook 기본 가능): job 전체 종료
  - `fixed-delay` / `exponential-delay`: 자동 재기동
- Job 이 죽으면 sink 로 못 보냄 → 알림 흐름 전체 정지

### 거짓 양성 함정 — 메트릭 OK 처럼 보임
- Lambda Invocations / Errors 메트릭은 Flink job 살아있을 때까지의 마지막 호출 분량만 보여줌
- "Lambda Errors = 0 이니 OK" 라고 결론짓기 쉽지만, **upstream(Flink) 이 죽었으면 Lambda 는 호출 자체를 안 받음** = Errors 0 이 너무 당연함
- 진짜 끊긴 지점은 **Flink job 상태**와 **alert KDS IncomingRecords**

## 4. 더 미묘한 시나리오 — Closed Parent Shard

`aws kinesis update-shard-count --target-shard-count 2` 로 1→2 split 하면 shard topology 가 이렇게 된다:

```
shardId-0  (CLOSED, EndingSequenceNumber 있음)
  ├─ shardId-1 (ACTIVE)
  └─ shardId-2 (ACTIVE)
```

Flink Kinesis Consumer 는 lineage 보존 위해 **closed parent shard 도 retention 기간(24h) 동안 polling 한다**. 즉 polling 부담은 즉시 1→3 으로 늘고, shard 추가의 깨끗한 효과는 24h 후에야 본다. split 직후 일시적으로 throttle 가 더 심해질 수도 있는 이유.

## 5. 진단 명령어 체인

증상 → 원인 추적 순서.

### 5-1. KDS 측 부하·throttle 메트릭
```bash
# Write 부하
aws cloudwatch get-metric-statistics --namespace AWS/Kinesis \
  --metric-name IncomingRecords \
  --dimensions Name=StreamName,Value=robot-telemetry-stream \
  --start-time "$(date -u -v-15M +%Y-%m-%dT%H:%M:%S)" \
  --end-time   "$(date -u +%Y-%m-%dT%H:%M:%S)" \
  --period 60 --statistics Sum --region eu-west-1

# Write throttle 발생 여부
aws cloudwatch get-metric-statistics --namespace AWS/Kinesis \
  --metric-name WriteProvisionedThroughputExceeded \
  --dimensions Name=StreamName,Value=robot-telemetry-stream ...

# Read throttle 발생 여부
aws cloudwatch get-metric-statistics --namespace AWS/Kinesis \
  --metric-name ReadProvisionedThroughputExceeded ...
```

`IncomingRecords ÷ 60 > shard_수 × 1000` 이면 write 한도 초과 가능성. throttle 메트릭이 0 이 아니면 확정.

### 5-2. Flink Job 상태 (Studio Notebook)
```bash
# 어떤 vertex 가 어디서 죽었는지 stack trace 추출
aws logs filter-log-events \
  --log-group-name /aws/kinesis-analytics/<app-name> \
  --filter-pattern 'switched from RUNNING to FAILED' \
  --start-time $(date -u -v-30M +%s)000 \
  --region eu-west-1
```

stack 에 `KinesisProxy.getRecords` 가 보이면 **read throttle 이 source 를 죽인 것** 으로 거의 확정.

### 5-3. Generator 부하 (cluster 실측)
```bash
kubectl -n robot-telemetry exec <generator-pod> -- printenv \
  | grep -E "ROBOT_COUNT|TICK_INTERVAL"
```

git yaml ↔ cluster live 가 다를 수 있으니 **반드시 cluster 쪽을 본다**. yaml만 보면 거짓 안심에 빠진다.

### 5-4. Rollout history 로 변경 시점 추적
```bash
kubectl -n robot-telemetry get rs -l app=robot-telemetry-generator \
  -o custom-columns='NAME:.metadata.name,REVISION:.metadata.annotations.deployment\.kubernetes\.io/revision,CREATED:.metadata.creationTimestamp,ROBOT_COUNT:.spec.template.spec.containers[0].env[?(@.name=="ROBOT_COUNT")].value' \
  --sort-by=.metadata.annotations."deployment\.kubernetes\.io/revision"
```

revision 별 ROBOT_COUNT 값이 보임 → 어느 revision 에서 변경됐는지 정확한 타임스탬프 확보.

## 6. 처방 옵션 비교

| 옵션 | 효과 | 비용 | 적용 시점 |
|---|---|---|---|
| **A. Shard 추가** | write/read 한도 비례 증가 | shard hour 단가 × 추가분 | `aws kinesis update-shard-count`, ACTIVE 까지 30s~수 분 |
| **B. Generator 부하 축소** | 한도 미달 상태로 복귀 | 0 | `kubectl set env` 또는 yaml + `kubectl apply` |
| **C. Source SQL 옵션** | 일시 throttle 내성 ↑ | 0 | `scan.shard.getrecords.maxretries=20`, `intervalmillis=500` |
| **D. Restart strategy** | source 죽어도 자동 복구 | 0 | TableEnvironment config |
| **E. ON_DEMAND 전환** | 자동 스케일 | 단가 모델 변경 | `update-stream-mode` |

C·D 는 **방어선**이지 근본 해결은 아니다. 부하가 한도 초과면 결국 또 죽는다 (단지 잠시 더 버틸 뿐). 근본은 A 또는 B.

C 옵션의 source SQL 예시:
```sql
WITH (
    'connector' = 'kinesis',
    'stream'    = 'robot-telemetry-stream',
    'aws.region'= 'eu-west-1',
    'scan.stream.initpos' = 'LATEST',
    'format'    = 'json',
    'scan.shard.getrecords.maxretries'     = '20',   -- default 3
    'scan.shard.getrecords.intervalmillis' = '500'   -- default 200(=5RPS) → 2RPS
)
```

D 옵션의 restart strategy (PyFlink Studio Notebook):
```python
st_env.get_config().set("restart-strategy.type", "fixed-delay")
st_env.get_config().set("restart-strategy.fixed-delay.attempts", "10")
st_env.get_config().set("restart-strategy.fixed-delay.delay", "10s")
```

## 7. 이번 사례 타임라인 (KST)

| 시각 | 이벤트 |
|---|---|
| 4/30 ~ 5/1 19:14 | Generator yaml=50, cluster=50, replicas=0/1 정상 |
| 5/1 19:56:07 | 누군가 `kubectl set env` 로 ROBOT_COUNT 50 → **1000** (yaml 미동기화) |
| 5/1 19:59:24 | replicas 0 → 1 (재기동) → write 2,000 RPS 시작 |
| 5/1 20:05~ | shard 1, write throttle + read throttle 동시 폭증 |
| 5/1 20:15~17 | ReadProvisionedThroughputExceeded 분당 141~155건 (피크) |
| **5/1 20:18:22** | **Flink source vertex FAILED** (`Retries exceeded`) |
| 5/1 20:17 이후 | Lambda invocation 끊김 (자연 결과) |
| 5/1 20:23 | Lambda webhook URL 별도 fix (다른 root cause) |
| 5/1 20:35 | shard 1→2 split — closed parent 부담 추가, 일시적으로 throttle 더 심해짐 |
| 5/1 21:00 ~ | (사용자 콘솔에서 Flink job 재실행 + ROBOT_COUNT 의도 확인) |
| 5/2 | yaml 동기화 commit 완료 |

## 8. 핵심 교훈 5가지

### 1) 메트릭은 거짓 양성을 잘 만든다
"Lambda Errors=0, Invocations 정상" 만 보면 OK 같지만, 코드가 try/except 로 감싼 외부 호출 (Slack POST 등) 은 **예외를 메트릭에 안 남긴다**. 200 OK 받은 placeholder 도 정상으로 보인다. **응답 status 만으로는 "도달했는지" 모른다.**

### 2) drift 는 cluster ↔ git 양쪽 다 봐야 한다
`kubectl set env` / `kubectl edit` 로 cluster 만 변경되면 yaml 은 그대로. 다음 `kubectl apply -f` 또는 비용 셧다운 후 재기동 사이클에 회귀한다. **변경했으면 반드시 yaml 도 같이 수정·commit**. 또는 GitOps (ArgoCD/Flux) 로 cluster 가 git 을 추종하게 강제.

### 3) shard 1 + 다중 consumer 는 시한폭탄
KDS 같은 stream 에 KDF + Flink + Lambda ESM 같은 polling consumer 가 다수 붙으면 **각자 5 RPS 씩 GetRecords** 호출. consumer 2개만 돼도 read 한도 5 RPS 즉시 초과. 시연/학습용 1 shard 쓸 거면 consumer 수도 같이 통제.

### 4) Flink default restart-strategy 를 의심하라
Studio Notebook 등에서 명시 안 하면 `NoRestartBackoffTimeStrategy` 일 수 있음. **1번 죽으면 끝**. 운영용으로는 무조건 `fixed-delay` 이상 설정. 단, restart 만 늘려놓고 부하 한도 초과를 안 풀면 retry 도 결국 다 죽는다.

### 5) Kinesis 메트릭은 4종 분리해서 본다

| 메트릭 | 의미 |
|---|---|
| `IncomingRecords` / `IncomingBytes` | producer 가 얼마나 쏟아붓는지 (write 부하) |
| `WriteProvisionedThroughputExceeded` | write 한도 초과로 거절된 record 수 |
| `OutgoingRecords` / `OutgoingBytes` | consumer 가 얼마나 가져갔는지 (read 부하) |
| `ReadProvisionedThroughputExceeded` | read 한도 초과로 거절된 GetRecords 수 |

증상 신고 받으면 **어느 메트릭이 비정상인지 먼저 분류** → 그다음 producer/consumer 어느 쪽 손볼지 결정.

## 9. 향후 운영 체크리스트

ROBOT_COUNT 또는 shard 수를 만질 때:

- [ ] 변경 후 `total_write_rps ≤ shard_수 × 1,000` 만족하는가?
- [ ] consumer 수 × 5 RPS ≤ shard_수 × 5 GetRecords/s 만족하는가? (즉 polling consumer 수가 shard 수 이하?)
- [ ] cluster 변경 시 yaml 도 수정·commit 했는가?
- [ ] terraform.tfvars 의 `kds_main_shard_count` 도 같이 갱신했는가? (다음 `terraform apply` 회귀 방지)
- [ ] Flink source SQL 에 `maxretries`, `intervalmillis` 옵션이 있는가?
- [ ] Flink restart-strategy 가 `NoRestart` 가 아닌가?
- [ ] Slack webhook URL 이 placeholder(`CHANGEME`) 가 아닌가? (Lambda env var 직접 확인)

## 참고 — 코드 위치

- Generator app: [src/generator/app.py](src/generator/app.py)
- Generator k8s: [k8s/generator/deployment.yaml](k8s/generator/deployment.yaml), [k8s/generator/hpa.yaml](k8s/generator/hpa.yaml)
- Flink 운영본: AWS Managed Flink Studio Notebook `de-ai-06-flink-studio-nb` (콘솔 only — 2026-05-02 부로 git mirror 폐기, ADR-010 REVISED 2 참조)
- Lambda alert handler: [src/lambda/alert_handler.py](src/lambda/alert_handler.py)
- KDS shard 변수: [terraform/variables.tf](terraform/variables.tf), [terraform/modules/data_pipeline/kinesis.tf](terraform/modules/data_pipeline/kinesis.tf)
- Glue Bronze schema: [sql/bronze_ddl.sql](sql/bronze_ddl.sql)

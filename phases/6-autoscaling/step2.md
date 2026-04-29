# Step 2: load-demo-script (부하 시연 E2E + HANDOFF 갱신)

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md` (전체 데이터/컴퓨트 흐름)
- `/docs/HANDOFF.md` (특히 "알려진 이슈" 표 — Karpenter 항목 위치 파악)
- `/k8s/api/hpa.yaml` (API HPA spec — 부하 트리거 임계치 확인)
- `/k8s/generator/hpa.yaml` (step 0 산출물 — Generator HPA spec)
- `/k8s/karpenter/nodepool.yaml` (step 1 산출물 — `general` NodePool 존재 확인)
- `/k8s/generator/deployment.yaml` (Generator env vars: `ROBOT_COUNT`, `TICK_INTERVAL_SECONDS`)
- `/scripts/` 디렉토리 구조 (기존 운영 스크립트 패턴 — 가능하면 일관 유지)
- `/plan.md` Phase 6 Task 6.3 — **읽기만, 수정 금지**

## 배경

step 0(Generator HPA)과 step 1(Karpenter NodePool)이 완료된 상태에서, 다음 흐름을 자동화된 시연 스크립트로 증명해야 한다:

```
부하 시작 → API HPA 1→N 확장 → 노드 capacity 부족 → Karpenter 신규 EC2(spot 우선) → 부하 종료 → 5분 내 노드 자동 회수
```

추가로 `docs/HANDOFF.md`의 "알려진 이슈" 표에 적힌 `Karpenter는 컨트롤러만 동작, provisioned 노드 없음` 항목이 더 이상 사실이 아니므로 갱신한다.

## 작업

### A) `scripts/load_demo.sh` 신규 작성

bash 스크립트 형태로 4단계 시연을 자동화한다. **시연자가 단계별로 출력을 보면서 진행할 수 있도록** 각 단계 사이에 `read -p "다음 단계로 진행 [Enter]"` 일시정지 + `kubectl` 출력으로 변화를 관찰할 수 있어야 한다.

스크립트 골격:

```bash
#!/usr/bin/env bash
set -euo pipefail

# 환경변수
NAMESPACE="${NAMESPACE:-robot-telemetry}"
API_DEPLOY="${API_DEPLOY:-robot-telemetry-api}"
GEN_DEPLOY="${GEN_DEPLOY:-robot-telemetry-generator}"
LOAD_DURATION="${LOAD_DURATION:-5m}"
LOAD_CONCURRENCY="${LOAD_CONCURRENCY:-50}"

# 사전 점검
command -v hey >/dev/null || { echo "ERROR: hey 미설치 (https://github.com/rakyll/hey)"; exit 1; }
command -v kubectl >/dev/null || { echo "ERROR: kubectl 미설치"; exit 1; }

API_ALB=$(kubectl get ingress -n "$NAMESPACE" robot-telemetry-api -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
[[ -z "$API_ALB" ]] && { echo "ERROR: API ALB 미생성"; exit 1; }

echo "=== Phase 1: API 부하 (hey ${LOAD_DURATION} @ ${LOAD_CONCURRENCY} concurrent) ==="
echo "  대상: http://${API_ALB}/api/predict"
hey -z "$LOAD_DURATION" -c "$LOAD_CONCURRENCY" \
    -m POST -H "Content-Type: application/json" \
    -d '{"robot_id":"ROBOT-00001","avg_motor_temp":85.0,"max_motor_temp":92.0,"battery_drain":12.0,"active_hours":8.0}' \
    "http://${API_ALB}/api/predict" &
HEY_PID=$!

read -rp "Phase 2로 진행 [Enter]"
echo "=== Phase 2: Generator ROBOT_COUNT 50 → 300 ==="
kubectl set env -n "$NAMESPACE" "deploy/${GEN_DEPLOY}" ROBOT_COUNT=300
echo "  10초 후 Generator pod CPU 추이:"
sleep 10
kubectl top pods -n "$NAMESPACE" -l app=robot-telemetry-generator || true
kubectl get hpa -n "$NAMESPACE"

read -rp "Phase 3로 진행 [Enter]"
echo "=== Phase 3: Karpenter 신규 노드 프로비저닝 관찰 ==="
echo "  현재 노드:"
kubectl get nodes -L karpenter.sh/capacity-type,karpenter.sh/nodepool,node.kubernetes.io/instance-type
echo "  Karpenter controller 로그(최근 50줄):"
kubectl logs -n karpenter deploy/karpenter --tail=50 | grep -E "launched|provisioned|nominated" || true

read -rp "Phase 4로 진행(부하 종료) [Enter]"
echo "=== Phase 4: 부하 제거 + 노드 자동 회수 ==="
kill "$HEY_PID" 2>/dev/null || true
kubectl set env -n "$NAMESPACE" "deploy/${GEN_DEPLOY}" ROBOT_COUNT=50
echo "  consolidation 대기(최대 5분)..."
for i in {1..30}; do
  sleep 10
  NODE_COUNT=$(kubectl get nodes -l karpenter.sh/nodepool -o name 2>/dev/null | wc -l | tr -d ' ')
  echo "  [${i}/30] Karpenter 노드 수: $NODE_COUNT"
  [[ "$NODE_COUNT" -le 1 ]] && break
done

echo "=== 시연 종료 ==="
kubectl get nodes -L karpenter.sh/capacity-type,karpenter.sh/nodepool
kubectl get hpa -n "$NAMESPACE"
```

사양 요점:
- 환경변수 override 가능(`NAMESPACE`, `LOAD_DURATION`, `LOAD_CONCURRENCY` 등)
- `set -euo pipefail`로 실패 시 즉시 중단
- 각 phase 사이 `read -p`로 시연자 통제
- `hey` 백그라운드 실행 + Phase 4에서 명시적 kill
- Phase 3에서 `kubectl get nodes -L karpenter.sh/capacity-type,karpenter.sh/nodepool`로 spot 사용 + general NodePool 사용 가시화
- Phase 4 회수 폴링은 최대 5분(30 × 10s)

스크립트 작성 후 `chmod +x scripts/load_demo.sh` 실행 권한 부여.

### B) `docs/HANDOFF.md` 알려진 이슈 표 갱신

다음 한 줄을 찾아서:

```markdown
| Karpenter는 컨트롤러만 동작, provisioned 노드 없음 | low | 일반 노드그룹 t3.large 3대로 충분, 시연에 불필요 |
```

다음으로 교체:

```markdown
| Karpenter `general` NodePool spot/on-demand 혼합 운영 중 | low | 시연 스크립트 `scripts/load_demo.sh`로 부하 시 신규 노드 자동 프로비저닝, 종료 시 5분 내 회수 검증됨 |
```

다른 표 항목/순서는 변경하지 마라.

## Acceptance Criteria

```bash
# 1) load_demo.sh 신규 + 실행 권한
test -f scripts/load_demo.sh && echo "OK: 파일 존재"
test -x scripts/load_demo.sh && echo "OK: 실행 권한"
bash -n scripts/load_demo.sh && echo "OK: bash syntax"

# 2) 4단계 시연 구조
grep -c "Phase [1-4]:" scripts/load_demo.sh | grep -q "^4$" && echo "OK: Phase 1~4 모두 포함"
grep -q "hey -z" scripts/load_demo.sh && echo "OK: hey 부하"
grep -q "kubectl set env.*ROBOT_COUNT=300" scripts/load_demo.sh && echo "OK: ROBOT_COUNT 증가"
grep -q "kubectl get nodes -L karpenter.sh/capacity-type" scripts/load_demo.sh && echo "OK: 노드 가시화"
grep -q "kubectl set env.*ROBOT_COUNT=50" scripts/load_demo.sh && echo "OK: ROBOT_COUNT 복원"

# 3) 안전 가드
grep -q "set -euo pipefail" scripts/load_demo.sh && echo "OK: strict mode"
grep -q 'command -v hey' scripts/load_demo.sh && echo "OK: hey 미설치 가드"
grep -q 'command -v kubectl' scripts/load_demo.sh && echo "OK: kubectl 미설치 가드"

# 4) HANDOFF 갱신
grep -q "Karpenter \`general\` NodePool spot/on-demand 혼합 운영 중" docs/HANDOFF.md && echo "OK: HANDOFF 갱신"
! grep -q "Karpenter는 컨트롤러만 동작, provisioned 노드 없음" docs/HANDOFF.md && echo "OK: 옛 항목 제거"
```

## 검증 절차

1. 위 AC 커맨드 모두 OK.
2. 아키텍처 체크리스트:
   - 4단계 흐름이 사용자 명세(API 부하 → Generator CPU ↑ → Karpenter 신규 노드 → 자동 회수)와 일치하는가?
   - `read -p` 일시정지가 각 단계 사이에 있어 시연자가 변화를 관찰 가능한가?
   - hey 프로세스가 Phase 4에서 명시적으로 종료되는가? (좀비 프로세스 방지)
   - HANDOFF 표에서 옛 항목이 정확히 제거되고 신규 항목으로 대체되었는가? (다른 항목 영향 없음)
3. `phases/6-autoscaling/index.json` step 2 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "scripts/load_demo.sh 4단계 시연 자동화(hey API 부하/ROBOT_COUNT 300/Karpenter 가시화/자동 회수 폴링) + docs/HANDOFF.md 알려진 이슈 항목 갱신"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

### 🚨 메타 파일 보호 (반드시 준수)

- **`/plan.md`(프로젝트 루트의 master plan)을 절대 수정/덮어쓰기/삭제하지 마라.** 본 step의 출력 산출물은 오직 `scripts/load_demo.sh`(신규) + `docs/HANDOFF.md`(알려진 이슈 표 1줄 교체) + `phases/6-autoscaling/index.json`(step 2 entry 갱신) **3종**이다.
- 프로젝트 루트의 `*.md`(plan.md, ARCHITECTURE.md 외) 어떤 것도 수정하지 마라.
- 다른 step 디렉토리 또는 같은 phase의 다른 step 파일(`step0.md`, `step1.md`)을 수정하지 마라.
- `docs/HANDOFF.md`에서 "알려진 이슈" 표 외 다른 섹션을 건드리지 마라. 특히 TL;DR, 데이터 흐름, 다음 단계 섹션은 보존.
- `k8s/`, `terraform/`, `src/`, `tests/` 어떤 파일도 수정하지 마라 — 본 step은 시연 스크립트와 HANDOFF만 다룬다.

### 구현 규칙

- `kubectl scale --replicas=0` 명령을 스크립트에 포함하지 마라. 이유: 데이터 흐름이 끊겨 시연 도중 KDS/Flink/Lambda 흐름이 무너진다.
- `terraform apply`/`terraform destroy`를 스크립트에 포함하지 마라. 이유: 본 스크립트는 K8s 레벨 시연이며, 인프라 변경은 별도 단계.
- `hey`/`kubectl`/`aws` 외 외부 도구(k6, vegeta, locust 등)를 도입하지 마라. 이유: 환경 의존성 최소화 — `hey`는 단일 Go 바이너리.
- 시연 단계 사이 `read -p` 없이 일직선으로 sleep만으로 진행하지 마라. 이유: 시연자가 변화를 보지 못하면 데모 가치 ↓.
- `set +e` 또는 에러 무시 패턴(`|| true`)을 핵심 단계(hey 실행, set env, kubectl get)에서 쓰지 마라. 이유: 실패 시 즉시 알아야 디버깅 가능. 단, "controller 로그 grep"처럼 매칭 없을 수 있는 부수 단계는 `|| true` 허용.
- HANDOFF 갱신 시 표의 다른 행(예: `kubernetes.io/ingress.class deprecated`, `Firehose Compression UNCOMPRESSED` 등)을 건드리지 마라.

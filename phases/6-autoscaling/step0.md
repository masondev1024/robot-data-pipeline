# Step 0: generator-hpa-replace (KEDA ScaledObject → 표준 HPA)

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md` (Compute Layer — Generator/API 레이아웃)
- `/docs/ADR.md` (k8s 배포 결정)
- `/k8s/api/hpa.yaml` (참조 패턴 — `behavior` 블록 + 메트릭 임계치 일관성 유지용)
- `/k8s/generator/hpa.yaml` (현재 KEDA `ScaledObject` + `TriggerAuthentication` — 폐기 대상)
- `/k8s/generator/deployment.yaml` (Generator Deployment 사양 — `resources.requests.cpu/memory` 확인)
- `/plan.md` Phase 6 Task 6.1 — **읽기만, 수정 금지**

## 배경

현재 `k8s/generator/hpa.yaml`은 KEDA `ScaledObject` + `TriggerAuthentication` 매니페스트인데:
1. 클러스터에 **KEDA operator가 설치되어 있지 않음** (`kubectl get scaledobject -A` → "the server doesn't have a resource type" 에러). 즉 한 번도 적용된 적 없는 청사진.
2. Generator는 **producer** 패턴이라 "KDS 샤드 수 → producer replica 증가" 인과가 어색. 정석은 consumer(Lambda/Spark Streaming) 측에 KEDA + KDS 트리거.
3. 시연 환경에서는 API HPA와 동일한 CPU/Mem 기반 표준 HPA가 일관성 + 단순성 측면에서 우월.

## 작업

`k8s/generator/hpa.yaml` 파일 내용을 **완전히 재작성**하여 KEDA 매니페스트 2개(`ScaledObject` + `TriggerAuthentication`)를 제거하고 표준 `HorizontalPodAutoscaler` 단일 매니페스트로 교체한다.

신규 내용 사양:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: robot-telemetry-generator-hpa
  namespace: robot-telemetry
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: robot-telemetry-generator
  minReplicas: 1
  maxReplicas: 5
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Pods
          value: 2
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 120
```

핵심 사양 근거:
- `maxReplicas: 5` — 시연 환경 적정. 10 이상은 KDS 메인 스트림 샤드 수(10)를 producer가 1:1 점유하는 비효율 유발.
- `cpu: 60% / memory: 80%` — `k8s/api/hpa.yaml`과 동일 (운영자 인지 부담 ↓).
- `behavior` 블록 — API HPA와 완전히 동일하게 두어 일관성 확보.
- `metadata.name: robot-telemetry-generator-hpa` — API HPA(`robot-telemetry-api-hpa`)와 네이밍 컨벤션 일치.

## Acceptance Criteria

```bash
# 1) 파일이 표준 HPA로 재작성됨 (KEDA 흔적 0)
grep -q "kind: HorizontalPodAutoscaler" k8s/generator/hpa.yaml && echo "OK: HPA kind"
grep -q "apiVersion: autoscaling/v2" k8s/generator/hpa.yaml && echo "OK: autoscaling/v2"
! grep -qE "keda\.sh|ScaledObject|TriggerAuthentication" k8s/generator/hpa.yaml && echo "OK: KEDA 잔재 없음"

# 2) 사양 일관성
grep -q "averageUtilization: 60" k8s/generator/hpa.yaml && echo "OK: CPU 60"
grep -q "averageUtilization: 80" k8s/generator/hpa.yaml && echo "OK: Mem 80"
grep -q "minReplicas: 1" k8s/generator/hpa.yaml && echo "OK: minReplicas"
grep -q "maxReplicas: 5" k8s/generator/hpa.yaml && echo "OK: maxReplicas"
grep -q "robot-telemetry-generator-hpa" k8s/generator/hpa.yaml && echo "OK: HPA name"

# 3) YAML 문법 검증 (kubectl 접근 불가 환경에서도 통과해야 함)
python3 -c "import yaml; yaml.safe_load(open('k8s/generator/hpa.yaml'))" && echo "OK: YAML valid"
```

## 검증 절차

1. 위 AC 커맨드 모두 OK.
2. 아키텍처 체크리스트:
   - `scaleTargetRef.name`이 실 Deployment(`robot-telemetry-generator`)와 일치하는가?
   - `behavior` 블록이 `k8s/api/hpa.yaml`과 같은 `stabilizationWindowSeconds` + policies 패턴인가?
   - KEDA 관련 어떤 키워드(keda.sh, ScaledObject, TriggerAuthentication, podIdentity)도 남지 않았는가?
3. `phases/6-autoscaling/index.json` step 0 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "k8s/generator/hpa.yaml KEDA → 표준 HPA 교체 (CPU 60/Mem 80, min 1/max 5, API HPA와 일관 behavior)"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

### 🚨 메타 파일 보호 (반드시 준수)

- **`/plan.md`(프로젝트 루트의 master plan)을 절대 수정/덮어쓰기/삭제하지 마라.** 본 step의 출력 산출물은 오직 `k8s/generator/hpa.yaml`(완전 재작성) + `phases/6-autoscaling/index.json`(step 0 entry 갱신) **2종**이다.
- 프로젝트 루트의 `*.md` 어떤 것도 수정하지 마라.
- 다른 step 디렉토리(`phases/0-setup/`, `phases/1-ingestion/`, `phases/2-batch/`, `phases/3-realtime/`, `phases/4-serving/`, `phases/5-hardening/`, `phases/6-autoscaling/step1.md`, `phases/6-autoscaling/step2.md`)를 수정하지 마라.
- `k8s/generator/deployment.yaml`을 수정하지 마라 — 본 step은 HPA 매니페스트만 다룬다.
- `k8s/api/hpa.yaml`을 수정하지 마라 — 참조용으로만 읽는다.
- `terraform/`, `src/`, `tests/`, `docs/` 어떤 파일도 수정하지 마라.

### 구현 규칙

- KEDA `ScaledObject`/`TriggerAuthentication` 매니페스트를 부분적으로 남기지 마라. 이유: 클러스터에 KEDA operator가 없어 apply 시 `NoMatchKind` 에러로 검증이 실패한다.
- `maxReplicas`를 10 이상으로 두지 마라. 이유: KDS 메인 스트림 10 shard에 producer replica 10이면 1:1 점유로 throughput 이득 없음.
- `apiVersion: autoscaling/v1`(legacy)을 사용하지 마라. 이유: `behavior` 블록과 multi-metric 지원은 v2부터.
- 새로운 `Deployment`/`Service`/`ConfigMap` 매니페스트를 추가하지 마라 — 본 step은 HPA 사양만 다룬다.
- 메트릭 타입을 `Pods` 또는 `Object`로 두지 마라 — `Resource`(CPU/Memory)만 사용한다.

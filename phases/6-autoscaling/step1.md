# Step 1: karpenter-nodepool-enhance (default 강화 + general 신설)

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md` (Compute Layer — Karpenter 정책 의도)
- `/docs/ADR.md` (Karpenter 채택 근거)
- `/k8s/karpenter/nodepool.yaml` (현재 매니페스트 — `default` NodePool + EC2NodeClass)
- `/k8s/karpenter/README.md` (taint 정책 컨텍스트, batch 워크로드 분리 의도)
- `/terraform/karpenter.tf` (Karpenter controller Helm 설치 사양 — 노드 IAM Role 이름 확인)
- `/plan.md` Phase 6 Task 6.2 — **읽기만, 수정 금지**

## 배경

현재 `k8s/karpenter/nodepool.yaml`은 `default` NodePool 단일이며 다음 한계를 가진다:

1. **Taint(`workload=batch:NoSchedule`) 강제** — 일반 Deployment(api/generator)가 toleration 없이는 이 노드에 스케줄되지 못해 시연 시 부하 흡수 불가. README는 batch 워크로드(Airflow worker 등) 전용으로 의도된 디자인이라 명시.
2. **`disruption.consolidationPolicy` 미명시** — Karpenter v1beta1 권장 필드 누락. `consolidateAfter: 30s`만으로는 동작하지만, 정책 명시 시 의도가 명확.
3. **Instance 타입이 t3 family로만 한정** — t3.large/xlarge/t3a.large/xlarge. AZ 제약 없음. **on-demand 단일** capacity-type. 시연 환경에서 spot/다양한 인스턴스 풀 활용 그림이 안 보임.

해결 방향: 기존 `default`는 batch 의도대로 보존(taint 유지) + 신규 `general` NodePool 추가(taintless, 다양성 + spot 우선) + 두 NodePool 모두 `disruption` 정책 보강.

## 작업

`k8s/karpenter/nodepool.yaml`을 다음 구조로 **완전히 재작성**한다:

### 1) 기존 `default` NodePool (batch 전용, taint 유지) — 정책만 보강

```yaml
apiVersion: karpenter.sh/v1beta1
kind: NodePool
metadata:
  name: default
spec:
  template:
    spec:
      requirements:
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["on-demand"]
        - key: node.kubernetes.io/instance-type
          operator: In
          values: ["t3.large", "t3.xlarge", "t3a.large", "t3a.xlarge"]
        - key: kubernetes.io/arch
          operator: In
          values: ["amd64"]
      nodeClassRef:
        name: default
      taints:
        - key: workload
          value: batch
          effect: NoSchedule
  limits:
    cpu: 100
    memory: 100Gi
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized   # 신규 명시
    consolidateAfter: 30s
    expireAfter: 720h
    budgets:
      - nodes: "10%"
        duration: 5m
        schedule: "0 9 * * mon-fri"
        reasons:
          - "Underutilized"
          - "Empty"
      - nodes: "100%"                                # Drifted는 즉시 교체
        reasons:
          - "Drifted"
```

### 2) 신규 `general` NodePool (taintless, 다양성 + spot 우선)

```yaml
---
apiVersion: karpenter.sh/v1beta1
kind: NodePool
metadata:
  name: general
spec:
  template:
    spec:
      requirements:
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["spot", "on-demand"]              # spot 우선 (cheapest 자연 선택)
        - key: karpenter.k8s.aws/instance-family
          operator: In
          values: ["c5", "c5a", "m5", "m5a", "t3", "t3a"]
        - key: karpenter.k8s.aws/instance-size
          operator: In
          values: ["medium", "large", "xlarge"]
        - key: topology.kubernetes.io/zone
          operator: In
          values: ["eu-west-1a", "eu-west-1b", "eu-west-1c"]
        - key: kubernetes.io/arch
          operator: In
          values: ["amd64"]
      nodeClassRef:
        name: default                                # EC2NodeClass는 공유
      # taints 없음 — 일반 deployment 자동 수용
  limits:
    cpu: 200
    memory: 200Gi
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 30s
    expireAfter: 720h
    budgets:
      - nodes: "20%"
        duration: 5m
      - nodes: "100%"
        reasons:
          - "Drifted"
```

### 3) 기존 `EC2NodeClass`는 그대로 유지

기존 `EC2NodeClass/default` 블록은 그대로 두고 두 NodePool이 `nodeClassRef.name: default`로 공유한다. 변경하지 않는다.

핵심 사양 근거:
- **`general` taintless** → API/Generator pod이 toleration 없이 자동 스케줄. 시연 시 Karpenter가 spot 우선으로 신규 노드 프로비저닝.
- **instance-family/size/zone 다양화** → 단일 타입 capacity 부족 시 자동 fallback, AZ 분산으로 가용성 ↑.
- **spot 우선** → `["spot", "on-demand"]` 순서. Karpenter는 cheapest 선택 정책이므로 자연스레 spot 위주, 부족 시 on-demand 폴백.
- **Drifted budget 100%** → NodePool spec 변경 시 즉시 노드 교체(점진 교체보다 시연/안정성 우월).
- **`general` limits 200 CPU / 200Gi** → `default`(100/100Gi)보다 큰 한도, 일반 워크로드 수용 여유.

## Acceptance Criteria

```bash
# 1) 두 NodePool + 단일 EC2NodeClass 구조
grep -c "kind: NodePool" k8s/karpenter/nodepool.yaml | grep -q "^2$" && echo "OK: NodePool 2개"
grep -c "kind: EC2NodeClass" k8s/karpenter/nodepool.yaml | grep -q "^1$" && echo "OK: EC2NodeClass 1개"
grep -q "name: default$" k8s/karpenter/nodepool.yaml && echo "OK: default NodePool"
grep -q "name: general$" k8s/karpenter/nodepool.yaml && echo "OK: general NodePool"

# 2) default NodePool — batch taint 보존
awk '/name: default$/,/^---$/' k8s/karpenter/nodepool.yaml | grep -q "value: batch" && echo "OK: default taint 보존"

# 3) general NodePool — taintless + 다양성 + spot
awk '/name: general$/,/^---$/' k8s/karpenter/nodepool.yaml | grep -q "spot" && echo "OK: general spot"
awk '/name: general$/,/^---$/' k8s/karpenter/nodepool.yaml | grep -q "instance-family" && echo "OK: instance-family"
awk '/name: general$/,/^---$/' k8s/karpenter/nodepool.yaml | grep -q "topology.kubernetes.io/zone" && echo "OK: zone 다양성"
! awk '/name: general$/,/^---$/' k8s/karpenter/nodepool.yaml | grep -qE "^\s+taints:" && echo "OK: general taintless"

# 4) Disruption 정책 보강
grep -c "consolidationPolicy: WhenEmptyOrUnderutilized" k8s/karpenter/nodepool.yaml | grep -q "^2$" && echo "OK: 두 NodePool 모두 consolidationPolicy 명시"
grep -q '"Drifted"' k8s/karpenter/nodepool.yaml && echo "OK: Drifted budget"

# 5) YAML 문법 검증 (multi-document)
python3 -c "import yaml; list(yaml.safe_load_all(open('k8s/karpenter/nodepool.yaml')))" && echo "OK: YAML valid"
```

## 검증 절차

1. 위 AC 커맨드 모두 OK.
2. 아키텍처 체크리스트:
   - 두 NodePool이 같은 `EC2NodeClass/default`를 참조하는가? (중복 NodeClass 만들지 않음)
   - `general` NodePool이 `taints` 키를 갖지 않는가? (있으면 일반 deployment 차단)
   - Capacity-type 값 순서가 `["spot", "on-demand"]`인가? (spot 선호 의도)
   - `default` NodePool의 batch taint가 보존되었는가?
3. `phases/6-autoscaling/index.json` step 1 업데이트:
   - 성공 → `"status": "completed"`, `"summary": "k8s/karpenter/nodepool.yaml: default NodePool 정책 보강(consolidationPolicy+Drifted budget) + 신규 general NodePool(taintless, instance-family/size/zone 다양화, spot/on-demand 혼합)"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`

## 금지사항

### 🚨 메타 파일 보호 (반드시 준수)

- **`/plan.md`(프로젝트 루트의 master plan)을 절대 수정/덮어쓰기/삭제하지 마라.** 본 step의 출력 산출물은 오직 `k8s/karpenter/nodepool.yaml`(완전 재작성) + `phases/6-autoscaling/index.json`(step 1 entry 갱신) **2종**이다.
- 프로젝트 루트의 `*.md` 어떤 것도 수정하지 마라.
- 다른 step 디렉토리 또는 같은 phase의 다른 step 파일(`phases/6-autoscaling/step0.md`, `phases/6-autoscaling/step2.md`)을 수정하지 마라.
- `k8s/karpenter/README.md`를 수정하지 마라 — 참조용.
- `terraform/karpenter.tf`를 수정하지 마라 — controller 사양은 본 step 범위 외.
- `k8s/api/`, `k8s/generator/`, `k8s/monitoring/` 어떤 파일도 수정하지 마라.

### 구현 규칙

- 기존 `default` NodePool의 taint(`workload=batch:NoSchedule`)를 제거하지 마라. 이유: `default`는 batch 워크로드 전용 디자인 — README와 의도 일관성 유지.
- 새 EC2NodeClass를 추가하지 마라. 이유: 두 NodePool 모두 `default`를 참조해야 단일 IAM Role/Subnet/SecurityGroup 정책 유지.
- `karpenter.sh/v1` 같은 GA 버전을 사용하지 마라. 이유: 본 프로젝트는 v1beta1 기준이며 `terraform/karpenter.tf`의 controller 버전과 일치해야 한다.
- `general` NodePool에 taint를 추가하지 마라 — 일반 deployment를 차단하는 순간 Task 6.3 부하 시연이 무력화된다.
- `expireAfter`를 `Never`로 두지 마라. 이유: 노드 lifecycle 상한이 없으면 OS 패치/AMI 갱신이 영원히 미뤄진다.
- `requirements`에 `karpenter.k8s.aws/instance-cpu` 같은 별도 제약을 새로 추가하지 마라 — instance-family/size 조합으로 충분히 통제됨.

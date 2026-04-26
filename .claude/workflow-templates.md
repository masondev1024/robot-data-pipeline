# Harness Control Prompts

## 1. Context Sync (작업 시작 전 문맥 동기화)
> "`CLAUDE.md`의 규칙과 `/docs/research.md`의 아키텍처를 읽고 숙지해. 이후 `/plan.md`를 열어 현재 할당된 Task가 무엇인지 파악하고 어떻게 구현할지 글로 먼저 브리핑해. 아직 코드는 쓰지 마."

## 2. Pre-flight (첫 실행 전 소크라테스식 검증)
> "아래 phase를 실행하기 전에 `--preflight` 플래그로 아키텍처 가정을 먼저 검증해. 시스템이 불분명한 가정 3가지를 역으로 질문하면 내가 확인한 뒤 Enter를 누를게."

```bash
python3 scripts/execute.py {task-name} --preflight
```

## 3. Terraform Code Generation (인프라 생성 시)
> "현재 `/plan.md`가 `[APPROVED]` 상태야. Phase 1의 [특정 Task]를 위한 Terraform 코드를 작성해. 작성 시 하드코딩을 피하고 `variables.tf`를 적극 활용하며, 작성 후 `terraform fmt` 기준에 맞게 정렬해."

## 4. Airflow DAG Generation (배치 파이프라인 생성 시)
> "Phase 2의 Airflow DAG를 작성해. 단, 데이터 엔지니어링 표준에 맞게 Task의 멱등성이 보장되어야 하며, S3의 특정 파티션을 덮어쓰는(Overwrite) 로직으로 구성해."

## 5. Hard Stop & Revert (오류 발생 시 통제)
> "[STOP] 지금 작성한 코드는 아키텍처 원칙에 어긋나. 코드를 억지로 수정하려 하지 말고 방금 생성/수정한 파일을 모두 원상 복구(Revert)해. 그리고 어디서 논리적 오류가 발생했는지 `/plan.md`에 원인만 기록해."

---

## Phase index.json 스키마 레퍼런스

```json
{
  "project": "<프로젝트명>",
  "phase": "<task-name>",
  "domain": "<terraform|python|sql|airflow|flink|k8s|mixed|default>",
  "steps": [
    {
      "step": 0,
      "name": "project-setup",
      "status": "pending",
      "depends_on": []
    },
    {
      "step": 1,
      "name": "core-logic",
      "status": "pending",
      "depends_on": [0]
    },
    {
      "step": 2,
      "name": "side-module",
      "status": "pending",
      "depends_on": []
    }
  ]
}
```

### `domain` 선택 기준

| domain | Librarian이 로드하는 docs |
|--------|--------------------------|
| `terraform` | ARCHITECTURE.md, ADR.md |
| `python` | ARCHITECTURE.md, ADR.md, research.md |
| `sql` | ARCHITECTURE.md, ADR.md |
| `airflow` | ARCHITECTURE.md, ADR.md |
| `flink` | ARCHITECTURE.md, ADR.md, research.md |
| `k8s` | ARCHITECTURE.md, ADR.md |
| `mixed` | ARCHITECTURE.md, ADR.md, research.md |
| `default` | 전체 docs/*.md (기본값) |

### `depends_on` 병렬화 패턴

```
step 0 ──────────────────────────────────────── step 2 (depends_on:[0])
step 1 (depends_on:[])  ─────────────────────── step 2 (depends_on:[0,1])

→ step 0과 step 1은 병렬 실행
→ step 2는 둘 다 완료 후 실행
```

- `"depends_on": []` → 즉시 실행 가능, 다른 step과 병렬로 스케줄됨
- `"depends_on": [N]` → step N 완료 후 실행
- `"depends_on": [M, N]` → step M과 N이 모두 완료된 후 실행

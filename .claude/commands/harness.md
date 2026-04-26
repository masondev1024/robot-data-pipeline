이 프로젝트는 Harness 프레임워크를 사용한다. 아래 워크플로우에 따라 작업을 진행하라.

---

## 워크플로우

### A. Pre-flight (소크라테스식 사전 검증)

phase를 처음 실행하기 전, 아래 명령어로 아키텍처 가정을 소크라테스식으로 검증한다.

```bash
python3 scripts/execute.py {task-name} --preflight
```

시스템이 실행 예정 step 파일들을 읽고, Claude 서브세션을 통해 아래를 수행한다:
- 아키텍처 가정 중 불분명한 부분 3가지를 질문 형식으로 출력
- 사용자가 내용을 확인하고 Enter를 입력하면 실행 시작
- `q` 입력 시 실행 중단 (plan.md 재검토 후 재실행)

Pre-flight는 plan.md를 작성하고 인간이 [APPROVED]를 입력하는 단방향 구조를 보완한다.
시스템이 먼저 "이 설계에서 가정이 불분명한 부분"을 역으로 질문하여 가정을 검증한다.

---

### B. 탐색

`/docs/` 하위 문서(PRD, ARCHITECTURE, ADR 등)를 읽고 프로젝트의 기획·아키텍처·설계 의도를 파악한다. 필요시 Explore 에이전트를 병렬로 사용한다.

---

### C. 논의

구현을 위해 구체화하거나 기술적으로 결정해야 할 사항이 있으면 사용자에게 제시하고 논의한다.

---

### D. Step 설계

사용자가 구현 계획 작성을 지시하면 여러 step으로 나뉜 초안을 작성해 피드백을 요청한다.

설계 원칙:

1. **Scope 최소화** — 하나의 step에서 하나의 레이어 또는 모듈만 다룬다.
2. **자기완결성** — 각 step 파일은 독립된 Claude 세션에서 실행된다. 외부 참조 금지.
3. **사전 준비 강제** — 관련 문서 경로와 이전 step 파일 경로를 명시한다.
4. **시그니처 수준 지시** — 인터페이스만 제시하고 구현은 에이전트 재량에 맡긴다.
5. **AC는 실행 가능한 커맨드** — `npm run build && npm test` 같은 실제 실행 커맨드를 포함한다.
6. **주의사항은 구체적으로** — "X를 하지 마라. 이유: Y" 형식으로 적는다.
7. **네이밍** — step name은 kebab-case slug.
8. **의존성 명시** — step 간 실행 순서는 `depends_on` 배열로 선언한다. 독립적인 step은 `[]`로 두어 병렬 실행을 유도한다.

---

### E. 파일 생성

**[중요]** 파일 생성 전 반드시 `/plan.md` 내 상태가 `[APPROVED]`로 변경되었는지 재확인하라. 승인되지 않았다면 생성을 중단하고 사용자에게 승인을 요청하라.

사용자가 승인하면 아래 파일들을 생성한다.

#### E-1. `phases/index.json` (전체 현황)

```json
{
  "phases": [
    { "dir": "0-setup",  "status": "pending" },
    { "dir": "1-ingestion", "status": "pending" }
  ]
}
```

#### E-2. `phases/{task-name}/index.json` (task 상세)

```json
{
  "project": "<프로젝트명>",
  "phase": "<task-name>",
  "domain": "<terraform|python|sql|airflow|flink|k8s|mixed|default>",
  "steps": [
    { "step": 0, "name": "project-setup", "status": "pending", "depends_on": [] },
    { "step": 1, "name": "core-types",    "status": "pending", "depends_on": [0] },
    { "step": 2, "name": "api-layer",     "status": "pending", "depends_on": [0] }
  ]
}
```

**`domain` 값 선택 기준:**

| domain | 로드되는 docs |
|--------|-------------|
| `terraform` | ARCHITECTURE.md, ADR.md |
| `python` | ARCHITECTURE.md, ADR.md, research.md |
| `sql` | ARCHITECTURE.md, ADR.md |
| `airflow` | ARCHITECTURE.md, ADR.md |
| `flink` | ARCHITECTURE.md, ADR.md, research.md |
| `k8s` | ARCHITECTURE.md, ADR.md |
| `mixed` | ARCHITECTURE.md, ADR.md, research.md |
| `default` | 전체 docs/*.md |

**`depends_on` 설계 원칙:**
- 의존 관계가 없는 step은 `"depends_on": []` — execute.py가 자동으로 병렬 실행
- step N이 step M의 출력물을 읽어야 한다면 `"depends_on": [M]`
- 여러 step이 동시에 완료되어야 실행 가능하다면 `"depends_on": [M, N]`

**상태 전이:**

| 전이 | 기록 필드 | 기록 주체 |
|------|----------|----------|
| → `completed` | `completed_at`, `summary` | Claude (summary), execute.py (timestamp) |
| → `error` | `failed_at`, `error_message` | Claude (message), execute.py (timestamp) |
| → `blocked` | `blocked_at`, `blocked_reason` | Claude (reason), execute.py (timestamp) |

#### E-3. `phases/{task-name}/step{N}.md` (각 step마다 1개)

```markdown
# Step {N}: {이름}

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md`
- {이전 step에서 생성/수정된 파일 경로}

## 작업

{구체적인 구현 지시. 파일 경로, 클래스/함수 시그니처, 로직 설명.}

## Acceptance Criteria

```bash
npm run build && npm test
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
3. `phases/{task-name}/index.json`의 해당 step을 업데이트한다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약"`
   - 실패 → `"status": "error"`, `"error_message": "구체적 에러"`
   - 사용자 개입 필요 → `"status": "blocked"`, `"blocked_reason": "사유"` 후 즉시 중단

## 금지사항

- {X를 하지 마라. 이유: Y}
```

---

### F. 실행

```bash
# 일반 실행
python3 scripts/execute.py {task-name}

# Pre-flight 포함 실행 (권장: 첫 실행 시)
python3 scripts/execute.py {task-name} --preflight

# 실행 후 push
python3 scripts/execute.py {task-name} --push
```

execute.py가 자동으로 처리하는 것:

- `feat-{task-name}` 브랜치 생성/checkout
- **Librarian** — CLAUDE.md + domain별 docs를 Claude 서브세션으로 요약하여 컨텍스트 격리
- **Future/Promise** — Librarian을 선행 스케줄링, Worker는 완료 시까지 블로킹
- **DAG 병렬 실행** — `depends_on`이 모두 completed인 step들을 동시 실행
- **컨텍스트 누적** — 완료된 step의 summary를 다음 step 프롬프트에 전달
- **자가 교정** — 실패 시 최대 3회 재시도 (이전 에러 메시지 피드백)
- **Auto-Healing** — MAX_RETRIES 소진 후 `git reset --hard HEAD` 자동 정리
- **2단계 커밋** — 코드 변경(`feat`)과 메타데이터(`chore`)를 분리 커밋

에러 복구:

- **error 발생 시**: `phases/{task-name}/index.json`에서 해당 step의 `status`를 `"pending"`으로 바꾸고 `error_message`를 삭제한 뒤 재실행.
- **blocked 발생 시**: `blocked_reason`에 적힌 사유를 해결한 뒤, `status`를 `"pending"`으로 바꾸고 `blocked_reason`을 삭제한 뒤 재실행.

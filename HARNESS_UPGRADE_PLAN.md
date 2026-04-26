# 하네스 고도화 및 아키텍처 검증 시스템 설계 사양 (v2.0)

본 문서는 `scripts/execute.py`의 하네스 시스템을 단순 실행 도구에서 **"아키텍처 가디언(Architecture Guardian)"**으로 격상시키기 위한 고도화 사양서입니다.

---

## 1. 분석: 현재 하네스의 한계와 개선 방향

현재 하네스는 단일 Phase 내의 Step 실행에는 최적화되어 있으나, 전체 프로젝트의 **수평적 연속성**과 **시각적 통제력**이 부족합니다. 이를 해결하기 위해 아래 3대 구조를 추가합니다.

### 🚩 [구조 1] Cross-Phase Validation (전역 페이즈 게이트웨이)
*   **개념**: Phase N이 시작되기 전, Phase N-1의 결과물이 단순히 "완료" 상태인 것을 넘어, 실제 인프라나 환경에 물리적으로 반영되었는지 "물리적 검증"을 수행합니다.
*   **구현**: `phases/index.json`에 `pre_gate_check` 스크립트 필드를 추가하고, 하네스가 이를 실행하여 통과하지 못하면 진입을 차단합니다.

### 📊 [구조 2] Resource Graph Visualization (DAG 시각화)
*   **개념**: 현재 진행 중인 Phase의 Step 간 의존성(`depends_on`)을 Mermaid.js 포맷이나 CLI Tree 뷰로 시각화합니다.
*   **구현**: `execute.py` 실행 시 현재의 DAG 상태를 `GRAPH.md`로 자동 생성하여 전체 공정률과 병목 구간을 한눈에 파악하게 합니다.

### 🧪 [구조 3] Simulation Mode (Socratic Auditor)
*   **개념**: 실제 코드를 작성하거나 파일을 수정하지 않고, 전체 Phase의 Librarian 요약과 Pre-flight 질문만 수집하여 **"통합 아키텍처 리포트"**를 생성합니다.
*   **구현**: `--simulate` 플래그를 통해 모든 Step의 잠재적 위험 요소를 사전에 리포트화하여, 사용자가 실행 전에 설계를 최종 승인할 수 있게 합니다.

---

## 2. 고도화 구현을 위한 상세 프롬프트 (AI 지시서)

아래는 위 구조를 실제 코드로 구현하기 위한 전문 프롬프트입니다.

### 🤖 실행 프롬프트: 하네스 고도화 엔진 (Guardian Update)

```markdown
당신은 'scripts/execute.py' 하네스를 고도화하는 시니어 도구 엔지니어입니다. 
다음 3가지 기능을 `execute.py`에 통합하고 `phases/` 구조를 업데이트하세요.

### Task 1: 전역 페이즈 게이트웨이 (Cross-Phase Gate)
1. `phases/index.json` (Root) 구조를 확장하여 각 phase마다 `validation` 객체를 추가할 수 있게 하세요.
2. `StepExecutor`에 `_run_phase_gate()` 메서드를 추가하여, 이전 phase가 물리적으로 완결되었는지 검증하는 shell command를 실행하세요.
   - 예: Phase 0 완료 후 `aws eks describe-cluster`를 실행해 실제 EKS 생성을 확인.

### Task 2: Mermaid DAG 시각화 도구
1. `StepExecutor` 내에 `_generate_dag_graph()` 메서드를 추가하세요.
2. 현재 phase의 `index.json`을 읽어 Mermaid.js의 `graph TD` 포맷으로 의존성 그래프를 생성하세요.
3. 현재 상태(pending, completed, error)에 따라 노드 색상을 다르게 표시(CSS 클래스 활용)하여 `phases/<phase>/DAG.md`로 저장하세요.

### Task 3: 통합 시뮬레이션 모드 (Architectural Auditor)
1. `--simulate` 명령줄 인자를 추가하세요.
2. 이 모드에서 하네스는 다음을 수행합니다:
   - 모든 Step에 대해 `Librarian` 요약과 `Pre-flight` 소크라테스 질문을 생성합니다.
   - 하지만 `_invoke_claude` (실제 파일 수정)는 호출하지 않습니다.
   - 모든 질문과 요약을 모아 `SIMULATION_REPORT.md`를 루트에 생성합니다.
3. 이를 통해 사용자가 실제 인프라 비용이나 코드 변경 없이 아키텍처의 모순을 미리 발견하게 하세요.

### 코드 품질 가이드라인
- 기존의 `Librarian` 및 `StepExecutor` 클래스 구조를 유지하며 확장하세요.
- 모든 기능은 `scripts/test_execute.py`를 통해 테스트 가능해야 합니다.
- 하위 호환성을 위해 기존 `index.json` 형식을 파괴하지 마세요.
```

---

## 3. 기대 효과: "Zero-Failure" 아키텍처

이 3가지 구조가 완성되면, 본 프로젝트는 다음과 같은 보증 수준을 갖게 됩니다:

1.  **논리적 보증**: Librarian이 도메인 규칙을 필터링하여 오개념 방지.
2.  **구조적 보증**: 시뮬레이션 모드를 통해 실행 전 모든 아키텍처 모순 해결.
3.  **물리적 보증**: 페이즈 게이트웨이를 통해 실제 인프라 정합성 강제.

---
**Next Action**: 위 프롬프트를 사용하여 하네스 고도화를 시작할 준비가 되셨습니까?

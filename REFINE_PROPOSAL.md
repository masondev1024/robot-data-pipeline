# 📋 Project Refinement Proposal: Operation-Centric Data Intelligence

**Status:** `DRAFT` (Action Required by AI Architect)
**Target:** AI-Driven E-commerce Data Intelligence Pipeline

## 1. 개요
현재의 아키텍처는 데이터 엔지니어링 관점에서는 타당하나, 실제 현업 운영자(정비반장, 작업자)가 직면할 **'시간적 시야각 결함'**과 **'UI 파편화'** 문제를 안고 있음. 또한 AI 하네스(`execute.py`)의 단일 컨텍스트 구조는 대규모 작업 시 추론 효율을 저하시킴. 이를 해결하기 위한 3대 핵심 리팩터링 과제를 제시함.

---

## 2. Core Task 1: AI Harness (`execute.py`) Upgrades
*OMC(Oh-My-ClaudeCode)의 아키텍처를 이식하여 개발 생산성과 안정성을 확보함.*

### 1.1 Context Isolation (Librarian Pattern)
- **Problem**: `cat ADR.md` 등 문서 전체를 읽으면 토큰이 낭비되고 모델의 구현 집중력이 흐트러짐.
- **Solution**: 
  - `execute.py` 내 `summarize_context()` 유틸리티 구현.
  - 별도 세션(Haiku 등 하위 모델 권장)을 통해 문서의 핵심 제약 사항만 추출하여 메인 세션에 주입.
- **Action**: `StepExecutor`가 Phase 진입 시 관련 문서를 요약하여 메모리에 적재하도록 로직 수정.

### 1.2 Socratic Pre-flight Hook
- **Problem**: 계획 수립 후 비판 없이 코딩을 시작하여 아키텍처 결함이 뒤늦게 발견됨.
- **Solution**: 
  - `pre_flight_check()` 메서드 추가.
  - `CLAUDE.md`의 Global Directives와 현재 계획의 충돌 여부를 AI가 자문자답하고, 모순 발견 시 사용자에게 역질문(Interview) 수행.

### 1.3 Auto-Healing & Dry-run Buffer
- **Problem**: 단순 Syntax 에러로 인한 `git reset --hard`가 잦아 작업 흐름이 끊김.
- **Solution**: 
  - `.workspace/` 임시 디렉토리에서 코드 생성 및 `ruff`, `terraform validate` 수행.
  - 성공 시에만 실제 경로로 이동 및 커밋.

---

## 3. Core Task 2: Real-time Data Intelligence (API/LLM)
*배치 데이터와 실시간 데이터를 결합하여 '지금 발생한 문제'에 답할 수 있게 함.*

### 2.1 Hybrid Context Retrieval (Athena Hybrid)
- **Problem**: AI API가 매일 00:00에 생성되는 Gold Table(Batch)만 참조함. 실시간 장애 대응 불가.
- **Solution**: 
  - `POST /api/chat` 요청 시, Gold Table(과거 통계) + Athena 실시간 파티션(최근 1시간 Silver Table)을 동시 쿼리.
  - 질문받은 로봇 ID의 최근 추세를 컨텍스트에 즉시 포함.

### 2.2 Actionable Slack Alerts
- **Problem**: Slack 알림이 단순 텍스트로만 전달되어 조치가 지연됨.
- **Solution**: 
  - Flink 알림 페이로드에 Grafana Deep Link(로봇 ID 기반) 포함.
  - AI Chat UI로 바로 연결되어 "이 로봇 분석해줘" 프롬프트가 자동 입력되는 URL 생성.

---

## 4. Core Task 3: Infrastructure & Simulation (Demo Readiness)
*프로젝트 발표 시 데이터 부재 문제를 해결하고 예지 보전 시나리오를 완성함.*

### 3.1 Historical Data Injector
- **Problem**: 발표 당일 데이터가 부족하여 통계적 통찰(AI 분석) 시연이 불가능함.
- **Solution**: 
  - `scripts/seed_data.py` 작성: 발표일 기준 과거 7일 치의 Parquet 파일을 S3 Bronze/Silver 경로에 직접 생성.
  - Airflow DAG를 수동 실행하여 Gold Table까지 빌드 완료.

### 3.2 Anomaly Scenario Generator
- **Problem**: 정상 데이터만 있으면 예지 보전을 보여줄 수 없음.
- **Solution**: 
  - 특정 로봇(예: `robot_99`)의 센서 값이 점진적으로 상승하다가 임계치를 넘는 '예지 보전 전용 시나리오' 데이터 셋 구축.

---

## 5. Technical Constraints (Strict)
- **No External Libraries**: Python 표준 라이브러리 위주로 `execute.py` 리팩터링.
- **Identity Preservation**: 기존 `execute.py`의 `argparse` 구조와 `progress_indicator` UI 유지.
- **Git Hard Reset Rule**: 프로덕션 코드에서의 직접적인 Patch 시도는 여전히 금지하며, `.workspace/` 내에서만 허용함.


# 1. 단일 컨텍스트 병목 해소 및 격리 (Context Isolation)

현재의 한계: execute.py가 모든 작업을 단일 세션에서 처리한다고 가정할 때, 코드를 수정하다가 인프라 문서를 읽어오면 불필요한 토큰이 누적되어(Token Melting) 추론 능력이 급감한다.

OMC 기반 개선안: 서브 에이전트(Librarian/Scout) 패턴을 도입해야 한다. 파일 탐색 및 읽기 프로세스를 별도의 서브 세션으로 분리하고, 해당 세션이 "요약된 핵심 정보"만 메인 작업 세션으로 전달하도록 execute.py 내에 컨텍스트 격리 계층(Isolation Layer)을 구축하는 것이 논리적으로 타당하다.

# 2. 순차 실행의 한계와 병렬화 (Parallel Orchestration)

현재의 한계: index.json의 배열 순서대로만 작동하는 강제 순차 실행(Sequential) 방식이다. 프론트엔드 API 연동과 백엔드 쿼리 최적화처럼 서로 의존성이 없는 작업조차 병목을 겪는다.

OMC 기반 개선안: OMC의 /ultrawork (다중 병렬 처리) 개념을 차용해야 한다. index.json 내 단계별 의존성 그래프(DAG)를 정의하고, 독립적인 작업은 멀티스레딩으로 동시 실행 후 결과를 병합(Merge)하는 오케스트레이션 단계로 파이프라인을 개편해야 실행 속도를 실질적으로 높일 수 있다.

# 3. 모놀리식 프롬프트의 해체 (Role-based Routing)

현재의 한계: CLAUDE.md 하나에 인프라(Terraform), 데이터베이스 룰, 디자인 가이드가 혼재되어 있다. 작업에 상관없이 모든 규칙을 로드하는 것은 비효율적이다.

OMC 기반 개선안: 32개의 전문 에이전트 방식을 참고하여 프롬프트를 모듈화해야 한다. execute.py가 현재 실행 중인 Phase의 성격을 파악하고, 필요한 가이드라인(예: UI 작업 시 UI_GUIDE.md만)을 동적으로 주입하는 스마트 라우팅 로직을 추가해야 한다.

# 4. 수동적 Human-in-the-loop의 능동적 전환 (Socratic Pre-flight)

현재의 한계: 시스템이 /plan.md를 작성하고 인간이 [APPROVED]를 입력하는 방식은 시스템의 계획에 인간이 끌려가는 단방향 구조다.

OMC 기반 개선안: OMC의 'Deep Interview' 프로세스를 적용해야 한다. 계획을 수립하기 전, 시스템이 요구사항의 모호함이나 아키텍처 결함(예: "Kinesis 보존 기간이 24시간인데, 배치 레이어의 처리 주파수와 정합성이 맞는가?")을 파악하고 역으로 사용자에게 질문하여 가정을 검증하는 소크라테스식 질의 단계를 파이프라인 최전선에 의무화해야 한다.

# 5. 극단적 롤백 규칙의 보완 (Architect-Worker Auto-Healing)

현재의 한계: 오류 발생 시 Patch를 금지하고 즉시 git reset --hard를 수행하는 피드포워드 규칙은 안전하지만, 단순 Syntax 에러 하나에도 전체 작업을 파기하는 극단적인 비효율을 초래한다.

OMC 기반 개선안: OMC의 /ralph (아키텍트 검증 기반 루프) 모델을 부분 도입할 필요가 있다. 코드 작성용 세션(Worker)과 작성된 코드를 평가하는 독립 세션(Critic)을 분리하여, 리셋 전 최대 2~3회의 자가 교정(Self-correction) 루프를 돌도록 execute.py의 예외 처리 로직을 고도화하는 것이 실현 가능성 및 생산성 측면에서 압도적으로 유리하다.


# 6. 서브 프로세스(Librarian)와 메인 프로세스(worker)를 비동기로 분리할 경우 생길 수 있는 문제 해결

서브 프로세스(Librarian)와 실제 코드를 작성하는 메인 프로세스(Worker)를 비동기로 분리할 경우, Librarian이 ADR.md의 핵심 제약 사항(예: "Kinesis Shard 1개 고정", "Parquet 포맷 변환 강제")을 파악하고 반환하기도 전에 Worker가 terraform/kinesis.tf 작성을 시작해버리면 컨텍스트 격리를 도입한 의미가 완전히 붕괴된다.

concurrent.futures를 활용한 Future/Promise 패턴 사용
작업의 완료 상태와 데이터 흐름 자체를 블로킹(Blocking) 조건으로 사용한다.
Librarian 스레드를 먼저 스케줄링하여 Future 객체를 반환받고, Worker 스레드는 실행 즉시 librarian_future.result()를 호출하도록 설계한다. 이 방식은 Librarian이 요약 텍스트를 반환할 때까지 Worker의 실행을 해당 라인에서 강제로 멈추게 하므로 경합을 원천 차단한다.
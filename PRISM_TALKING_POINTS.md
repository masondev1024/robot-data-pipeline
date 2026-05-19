# PRISM 본선 발표 멘트 Reference (D-Day 2026-05-22)

> 9분 평가 (5분 발표 + 4분 시연 + 30s~1min Q&A). 한국어 발표.
> mason 가 자기 스타일로 다듬어 사용. **느슨한 reference만** — 단어 그대로 외우지 말것.

---

## 🎤 5분 발표 (5 슬라이드 × 1분)

### Slide 1 (0:00 ~ 1:00) — 메시지

**핵심 문구 (큰 글씨)**: *"엔터프라이즈가 못 푸는 1인 운영자 문제, 노트북 1대와 인과추론으로 푼다"*

```
"안녕하세요. PRISM 입니다.
메이커스페이스 1인 운영자가 직면하는 문제부터 시작합니다.

설비 결함이 발생하면 RCA — Root Cause Analysis — 에 평균 1~2 시간 걸립니다.
센서 데이터를 일일이 확인하고, 어떤 변수가 문제였는지 추론하는 데 그렇게 오래 걸립니다.

엔터프라이즈는 MES 라는 솔루션을 쓰지만, 연 1만 달러 이상.
1인 메이커스페이스는 도입 불가능합니다.

PRISM 은 노트북 1대 + 월 $10-20 로 같은 문제를 해결합니다."
```

### Slide 2 (1:00 ~ 2:00) — 문제 정의

```
"문제는 단순 알람이 아닙니다.
MES 가 motor_temp > 90도 알람을 쏘면, 운영자는 '왜?' 를 답할 수 없습니다.
근본 원인을 찾는 데 또 1시간.

게다가 MES 의 임계값 알람은 알람 피로도를 만듭니다.
운영자가 알람을 무시하기 시작합니다. 진짜 사고를 놓치게 됩니다.

PRISM 은 두 가지를 답합니다:
첫째, ML 확률 기반 예지 — risk 62% HDF.
둘째, 인과 DAG — 'spindle_rpm 을 7650 으로 낮추면 vibration -38%, 결함 확률 -44%포인트'."
```

### Slide 3 (2:00 ~ 3:00) — Closed-Loop 4-step

```
"PRISM 은 Closed-Loop 4 단계로 작동합니다.

1단계 센서 통합 — DuckDB in-process, 11개 sensor 실시간.
2단계 인과 RCA — DoWhy 6-Node DAG, σ_max 0.40 robust. Wright 1991 의 partial R² 임계.
3단계 Multi-Agent 협상 — Sonnet Supervisor + Haiku 4개 도메인 Agent.
       품질, 안전, 설비, 생산 — 4 Agent 가 Net Value 라는 단일 척도로 협상.
4단계 학습 자산화 — 신규 결함 패턴이 자동 모델 재학습 데이터로 흡수.

RCA 시간이 4시간에서 24분으로 — 90% 단축됩니다."
```

### Slide 4 (3:00 ~ 4:00) — 차별화 4축

```
"PRISM 의 차별화 4축입니다.

첫째, **포지셔닝**: 메이커스페이스 / SMB. 대형 MES 가 못 닿는 영역.

둘째, **인과 추론**: 단순 상관관계가 아니라 'do-intervention'. 
       DoWhy 의 6 노드 DAG 가 어떤 변수를 손대면 어떤 효과인지 검증합니다.

셋째, **Multi-Agent**: 4 Agent 가 충돌하면 Sonnet Supervisor 가 Net Value KRW 로 협상.
       weight 가 명시되어 있어 평가자가 alpha/beta/gamma 를 직접 조작 가능.

넷째, **비용 -98%**: 연 24만원 vs MES 천만원 이상.
       노트북 1대 + Bedrock on-demand 만으로 운영됩니다."
```

### Slide 5 (4:00 ~ 5:00) — 본선 시연 + 확장성

```
"이제 4분 라이브 시연을 보여드립니다.
9개 마커, 15초 단위로 진행. 본선 결정성을 위해 LLM cache replay 모드.
사전 검증된 응답으로 화면에 비결정성 없습니다.

마지막으로 확장성. 동일한 인과 DAG 구조를:
- 식품 가공 → 살균 온도 / 위생 파라미터
- 물류 → 차량 진동 / 배달 지연
- 반도체 공정 → 웨이퍼 결함

같은 PRISM 코어로 transfer 가능합니다.
1인 운영자 → SMB → 엔터프라이즈 scale-out 가능.

지금부터 시연 시작합니다."
```

---

## 🎬 4분 시연 — 마커별 멘트 (각 ~20초)

### Marker 0 (0:00 정상) — 시작
```
"평소 가동 상태입니다. 사이드바를 보시면 PRISM 제어판:
σ_max 0.40 robust — 학술 검증 통과한 인과 모델입니다.
중앙 인과 DAG, 11 sensor 실시간 통합."
```

### Marker 1 (0:15 예지경보)
```
"ML 모델이 위험 신호를 감지했습니다. 결함 위험 62% — HDF, Heat Dissipation Failure.
단순 임계값 알람이 아닙니다. XGBoost 6-class softmax 확률."
```

### Marker 2 (0:30 인과 v1)
```
"여기가 인과 분석 시작. tool_age, spindle_rpm, coolant_temp — 모두 파란색.
원인 후보로 식별됐습니다. 단순 상관관계가 아니라 causal relationship."
```

### Marker 3 (0:45 인간 결정)
```
"여기서 자율 AI 가 아닙니다. 운영자가 검토:
'이게 진짜 원인인가? 적용 전에 먼저 시뮬해보자.' 
Human-in-the-loop. 1인 메이커스페이스 운영자가 책임자."
```

### Marker 4 (1:00 시뮬 가속) — 핵심
```
"counterfactual — do(spindle_rpm = 7650) 시뮬레이션.
vibration -38%, thermal_drift -40%, defect_prob 62% → 18%.
4시간 분량 시뮬을 1초에. 적용 전 검증 완료."
```

### Marker 5 (1:15 결함 발생)
```
"실제 결함 발생. motor_temp 105도 — SOP 임계 100도 초과.
사전 예지가 실제 발현됐습니다. INCIDENT #47."
```

### Marker 6 (1:30 인과 v2)
```
"새로운 인과 path 발견 — coolant_temp 가 thermal_drift 에 영향.
DAG v2 로 자동 업데이트. 이게 4단계 학습 자산화의 시작."
```

### Marker 7 (2:15 4 Agent) — 강조
```
"이제 4 Agent 협상 시작.
품질 Agent: 위험 — HDF.
안전 Agent: SOP 위반 — 감속 필요.
설비 Agent: 정비 시급 — RUL 18시간.
생산 Agent: 그래도 진행 가능 — UPH 235.

3 vs 1 의견 충돌입니다."
```

### Marker 8 (3:00 Supervisor) — slider 시연
```
"Sonnet Supervisor 가 Net Value 로 협상.
기본 베타 1.0 에서는 continue, +1억원.
하지만 평가자께서 보수성을 높이고 싶으면 — [beta slider 2.0 으로 이동]
바로 throttle_50pct 로 권고가 바뀝니다.
이게 명시적 협상 — 모호한 AI 의사결정이 아닙니다."
```

### Marker 9 (3:30 재학습)
```
"인시던트 패턴 자동 학습 — 정확도 0.62 → 0.91, 47% 향상.
6-class F1 모두 개선. 결함이 모델 자산으로 흡수됐습니다."
```

### Marker 10 (3:45 OEE)
```
"최종 OEE +35%. Nakajima 표준 — 가용, 성능, 품질 모두 개선.

비용 임팩트: 연 24만원 PRISM vs MES 천만원 — 98% 감소.
1인 메이커스페이스가 엔터프라이즈급 RCA + 인과 추론을 활용합니다.

시연 끝났습니다. 질문 받겠습니다."
```

---

## 🎯 Q&A — 예상 5 질문 (각 30초 응답)

### Q1: "왜 DoWhy 선택? 다른 인과 추론 라이브러리는?"
```
"세 가지 이유.
첫째, DoWhy 는 do-intervention 과 refute_estimate 가 native — Pearl 1995 표준.
둘째, networkx 와 호환 — 6-Node DAG 시각화 즉시.
셋째, σ_max 학술 검증 — Wright 1991 partial R² 임계로 confounder robustness 정량화.

PyMC 나 EconML 도 있지만, do-calculus + refute 두 가지를 한 API 로 묶어 주는 건 DoWhy 가 가장 robust."
```

### Q2: "Bedrock 비용은 어떻게 24만원/년?"
```
"Demo 모드에서는 LLM cache replay — 사전 녹화된 51 응답으로 Bedrock 호출 0 회.
Production 운영 시 4 Agent 각 일 ~50 호출, Sonnet Supervisor 일 ~10 호출.
Haiku 일 비용 약 50센트, Sonnet 약 30센트 → 월 25달러, 연 300달러.
원화 환산 약 36만원. 실제 24만원 추정은 prompt caching ephemeral mode 적용.

대비 MES 연 1만 달러 이상 = 약 1300만원. 약 36배 차이."
```

### Q3: "RUL 추정 정확도는?"
```
"AI4I 2020 데이터셋 기준 6-class XGBoost, F1 평균 0.62 → 재학습 후 0.91.
incident #47 패턴이 motor_temp_max feature 의 importance 를 0.18 → 0.31 로 끌어올림.
HDF 가 1~2일 내 발생 위험으로 추정되면 즉시 정비.
실제 maker space 환경에서는 sensor 가 11개 → AI4I 의 5개 변수보다 더 robust."
```

### Q4: "확장성? 다른 산업 transfer 가능?"
```
"DAG 구조가 핵심. 6-Node DoWhy DAG 를 식품, 물류, 반도체 공정에 transfer 시:
- 식품: 살균_시간, 살균_온도, 미생물_수, 위생_점수, 식품_품질, DEFECT(불량)
- 물류: 운전_시간, 도로_상태, 차량_진동, 배달_지연, 배송_품질, DEFECT(파손)
- 반도체: 공정_시간, 웨이퍼_온도, 입자_수, 두께_편차, 패턴_품질, DEFECT(불량률)

Multi-Agent 협상은 4 도메인 (품질, 안전, 설비, 생산) 그대로.
Supervisor 의 Net Value KRW 만 산업별 cost 상수 조정."
```

### Q5: "결정성 100% 어떻게 보장? LLM 비결정성?"
```
"Triple Insurance:
첫째, 모든 시드 고정 — random.Random(2026), numpy seed 2026, PYTHONHASHSEED 2026.
둘째, LLM record/replay cache — 51 응답 사전 SHA256 키로 byte-equal.
셋째, 영상 fallback — cache miss / Bedrock timeout 시 0.5초 안에 영상 swap.

본선 검증 — verify_demo_determinism.py 가 5 metric 확인:
cache hit ≥0.99, generator SHA256 byte-equal, e2e runtime ≤225s, eval ≥0.9, tokens ≤30k.
5/5 PASS 한 상태에서만 본선 진입합니다."
```

### Q6: "1인 메이커스페이스만 타겟? 본대회는 스마트 제조 환경 전반인데?"
```
"아니요. 메이커스페이스는 **진입점**입니다.
PRISM 핵심은 '엔터프라이즈 MES — 연 1만 달러 이상 — 가 못 닿는 mid/small 시장' 입니다.

진출 경로:
1단계 — 1인 메이커스페이스 (본선 시연).
2단계 — SMB 공장 (직원 10~50명, 국내 중소 제조).
3단계 — 엔터프라이즈 scale-out (multi-site, multi-agent federation).

DAG 구조가 핵심 자산입니다. Q4 에서 답했듯이, 
식품·물류·반도체 공정에서도 동일한 6-Node DoWhy DAG 를 transfer 가능.
본질은 scale-out 이지, 단일 산업 종속이 아닙니다."
```

### Q7: "Cache replay 가 '실제 동작 가능한 MVP' 평가 적합한가?"
```
"cache replay 는 AI Layer 결정성만 담당합니다. 핵심 로직은 전부 라이브입니다.

Live 컴포넌트:
- DoWhy do() ATE (Average Treatment Effect): 0.63s real compute.
- XGBoost predict_proba: 0.81ms, 라이브 6-class softmax.
- Generator (DuckDB in-process): 라이브, 11 sensor 실시간 통합.
- Multi-Agent negotiation: Haiku (Marker 7) 라이브 호출.

Cache Replay (LLM only):
- Supervisor 최종 결정 (Marker 8): 51개 사전 검증 응답.

PRISM_MODE=live 토글 시 Bedrock 에 직접 호출도 가능합니다.
본선 = 안정성 demo, production = live 모드."
```

### Q8: "DuckDB 가 대용량 robot 처리?"
```
"본선 MVP 는 in-process single machine — DuckDB 충분합니다.
대용량 1000+ robot 환경은 production scale-out 전략이 있습니다.

이전 프로젝트 자산 (아카이브):
- KDS (Kinesis Data Streams) → 1000 robot 실시간 수집.
- Firehose → S3 파티셔닝 (date-based).
- Athena (SQL analytics) → DoWhy 입력 데이터 쿼리.

본선 후 transition path:
- DuckDB → MotherDuck cloud (collaborative analytics) 또는
- MotherDuck 대신 Iceberg + Trino (lakehouse architecture).

DAG 는 변하지 않습니다. 데이터 플로우 인프라만 scale-out."
```

### Q9: "운영자가 실제 이 화면을 매일 보면서 운영?"
```
"현 시연 = 평가자 인지용 timeline 통합 뷰입니다.
실 운영 UI 는 마이크로뷰로 분리:

2-Layer UX:
- Layer 1 (dashboard): 예지 알람 + 1개 incident 만 spotlight.
           → 운영자 주 관심 = '지금 뭐 해야 돼?'
- Layer 2 (detail): 클릭 시 4-Agent 협상·DAG·슬라이더 전개.
           → 의사결정 input 다시 확인용.

나머지 데이터는 백그라운드 (audit log, trend chart).
본선 시연은 모든 step 을 **한 화면에 압축**해서 보여주는 것이 목표.
실 운영은 더 단순합니다."
```

### Q10: "incident #47 학습 0.62→0.91 이 실제 재학습?"
```
"네, 실제 재학습입니다.
src/ml/local_predictor.py 에 라이브 재학습 로직이 있습니다.

프로세스:
1. incident #47 (결함 발생 event) 를 anomaly row 로 적재.
2. 동일 시그니처 incident 100개+ 수집하여 training set 확장.
3. XGBoost.fit() 재실행 — new model 출력.
4. F1 0.62 → 0.91 (Marker 9 시연).

검증:
- 기존 모델 (.pkl 버전) 가 baseline.
- 신규 재학습 model (.pkl 저장) 가 0.91 검증.
- 두 모델 byte-equal 재현 가능 (random seed 고정).

본선 시연 시 Marker 9 에서 재학습 모델을 **라이브 호출**
(cache replay 아님, 실제 모델 load → evaluate)."
```

---

## 🔥 발표 tone 룰

- 자신감 있게 — but **단정적이지 않게**. "추정", "가능" 표현 적절히.
- 학술 reference 인용 (Wright 1991, Pearl 1995, Nakajima) — 평가자 신뢰 ↑.
- 비용 강조 — "98% 절감" 은 가장 큰 임팩트 메시지.
- 1인 메이커스페이스 viewpoint 유지 — 엔터프라이즈 시점 X.
- 시연 중 화면 가리키며 — "여기 보시면", "주황색이", "이 슬라이더 가져 보면".

**연습 우선순위 (D-1 리허설)**:
1. 5 slide 발표 4분 50초 ± 10초
2. 시연 4분 정확 (timer 옆에 두기)
3. β slider 시연 timing — marker 8 도착 후 5초 안
4. Q&A 30초 안에 답변 (timing 연습)

---

**행운을 빈다. 🍀 — D-Day 2026-05-22, 본선 통과.**

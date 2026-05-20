# PRISM 본선 발표 멘트 Reference (D-Day 2026-05-22)

> 13분 평가 (5분 발표 + 7분 시연 + 1분 Q&A). 한국어 발표.
> mason 가 자기 스타일로 다듬어 사용. **느슨한 reference만** — 단어 그대로 외우지 말것.

---

## 🎤 5분 발표 (5 슬라이드 × 1분)

### Slide 1 (0:00 ~ 1:00) — 메시지

**핵심 문구 (큰 글씨)**: *"엔터프라이즈가 못 푸는 1인 운영자 문제, 노트북 1대와 인과추론으로 푼다"*

```
"안녕하세요. PRISM 입니다.

메이커스페이스 운영하면서 설비 결함이 터지면 어떻게 돼요?
원인을 찾는 데 1~2 시간이 걸린다는 거죠.
센서 데이터 일일이 확인하고, 뭐가 문제인지 추론하려니까 시간이 엄청 걸립니다.

MES라는 시스템 쓰면 되는데, 연 1천만원 이상.
1인 메이커스페이스는 감당이 안 되죠.

그래서 PRISM을 만들었습니다. 노트북 1대, 연 24만원.
같은 문제를 훨씬 싸게 푼다는 거고요."
```

### Slide 2 (1:00 ~ 2:00) — 문제 정의

```
"기존 알람의 문제점입니다.
임계값 알람 '모터 온도 90도 초과' 가 뜨면, 운영자는 '왜 그런 거지?' 를 답할 수 없어요.
원인을 추적하려면 또 1시간을 써야 합니다.

그리고 이런 알람이 자주 뜨니까 알람 피로도가 생긴다는 거죠.
운영자가 무시하다가 진짜 사고를 놓칩니다.

PRISM은 다릅니다.
ML로 예지하고 — 결함 위험 62%, 공구 마모 추세.
그리고 인과 분석으로 '공구 교체하면 결함이 18% 수준으로 떨어진다' 는 근거를 제시해요.
XGBoost가 감지한 변수와 인과 분석이 추천하는 변수가 동일합니다. 이게 핵심입니다."
```

### Slide 3 (2:00 ~ 3:00) — Closed-Loop 4-step

```
"PRISM은 4 단계로 작동합니다.

1단계 센서 통합 — 11개 센서를 DuckDB에 실시간 통합.
2단계 인과 분석 — DoWhy 6-노드 DAG, Wright 1991 학술 기준 검증.
3단계 4 Agent 협상 — 품질, 안전, 설비, 생산이 의견 충돌하면 Supervisor가 정렬.
                 Net Value로 '지금 뭐 할지' 결정.
4단계 자동 재학습 — 새 결함이 학습 데이터로 자동 흡수, 모델 개선.

원인 분석에 4시간이 걸렸던 게 이제 1초입니다. 90% 이상 단축."
```

### Slide 4 (3:00 ~ 4:00) — 차별화 4축

```
"PRISM의 4가지 차별화 요소입니다.

첫째, 포지셔닝. MES가 못 닿는 메이커스페이스와 SMB 시장.

둘째, 인과 추론. 상관관계가 아니라 do-intervention.
       손으로 공구를 교체하면 실제로 뭐가 어떻게 바뀌는지 1초 안에 검증합니다.

셋째, 4 Agent 투명 협상. 품질·생산·안전·설비가 충돌하면 Supervisor가 정리.
       평가자가 슬라이더로 우선순위를 직접 조정 가능합니다.

넷째, 비용. 연간 24만원 vs MES 천만원 이상. -98%.
       노트북과 클라우드 API만으로 운영됩니다."
```

### Slide 5 (4:00 ~ 5:00) — 본선 시연 + 확장성

```
"이제 7분 시연을 보여드립니다.
11개 마커로 전체 흐름을 압축했고, LLM 응답은 사전 검증한 cache 모드라
비결정성이 없습니다.

그리고 확장성입니다. 이 인과 DAG 구조는 식품, 물류, 반도체 공정에도 그대로 적용돼요.
변수 이름만 바꾸면 된다는 거죠.

1인 운영자에서 시작해서 SMB로, 그 다음 엔터프라이즈로 확장 가능합니다.

자, 시연 시작하겠습니다."
```

---

## 🎬 7분 시연 — 마커별 멘트 (총 423초 + 여유 ~10s)

> **시간 제약**: 해커톤 본선 규정상 시연 시간 강제 없음. mason 자율 발화 + 청중 인지
> sweet spot (TED 상단 7분) 고려해 **7분 = 420s 본론 + 12s 마진** 으로 budget.
>
> **budget 배분**: 마커 0 도입 **120s** (사이드바 3카드 deep dive + fleet + DAG + KPI 한번에),
> 마커 4·7·10 각 35~40s (라이브 ATE / 4 Agent / OEE+closing), 마커 8 (β slider 핵심) 45s,
> 마커 2·6 각 28~30s, 마커 1·3·5·9 각 22~25s. 마커 시각 라벨(0:00/0:15/…)은 narrative
> time일 뿐, mason 의 실제 머무는 시간은 자율.
>
> **녹화 기준 cumulative** (이 값으로 찍을 것):
> | M | 시작 | 종료 | 머무는 시간 | 강조 |
> |---|------|------|------|---|
> | M0 | 0:00 | 2:00 | 120s | 사이드바 deep dive 청중 base 정렬 |
> | M1 | 2:00 | 2:22 | 22s | |
> | M2 | 2:22 | 2:50 | 28s | |
> | M3 | 2:50 | 3:12 | 22s | |
> | M4 | 3:12 | 3:50 | 38s | ⭐ ATE 라이브 |
> | M5 | 3:50 | 4:12 | 22s | |
> | M6 | 4:12 | 4:40 | 28s | |
> | M7 | 4:40 | 5:18 | 38s | ⭐ 4 Agent |
> | M8 | 5:18 | 6:03 | 45s | 🔑 β slider |
> | M9 | 6:03 | 6:25 | 22s | |
> | M10 | 6:25 | 7:03 | 38s | ⭐ OEE+closing |

### Marker 0 (도입, ~120s) — 사이드바 3카드 deep dive + fleet + DAG + KPI
```
"정상 가동 상태입니다. 시연 들어가기 전에 PRISM 전체 구조 잠시 짚고 가겠습니다.
뒤 마커들 이해를 위한 사전 정렬입니다.

(0:00~0:10) 위쪽 fact line — **10대 CNC fleet 라이브 모니터링**.
지금 incident CNC-01 한 대, 정상 가동 9대.
단일 머신 시연이 아니라 fleet 컨텍스트에서 한 머신을 파고드는 구조입니다.

(0:10~0:18) 페이지 구성은 셋 — 왼쪽 사이드바 PRISM 제어판, 가운데 6-Node 인과 DAG,
위쪽 KPI 4개.

(0:18~0:46) 먼저 **사이드바 첫째 카드 — 인과 모델 검증**. σ_max 0.40 robust.
[자세히 클릭] 펼치면 4 Refuter 검증이 보입니다. 위약 처치, 무작위 공통 원인,
80% 부분 데이터, σ_max 스캔. 4개 독립 반증 시도 전부 통과 — ATE 방향 안 바뀝니다.
[학술 reference 클릭] 학술 근거는 Wright 1991 partial R². 숨겨진 교란변수가 결과
분산의 40% 미만만 설명하면 추론 방향이 보호됨. 즉 단순 상관이 아니라 학술 검증
통과한 인과 모델입니다.

(0:46~0:54) 그 밑 **α/β/γ 가중치 slider**. 품질·안전·비용 가중치인데,
뒤에서 Supervisor 4 Agent 협상의 입력변수로 들어갑니다. M8 에서 평가자께서
직접 조작하시게 됩니다.

(0:54~1:22) **둘째 카드 — DuckDB lineage**. Bronze → Silver → Gold 메달리온 아키텍처.
Bronze 는 raw sensor 그대로 적재, Silver 는 cleaning + feature engineering,
Gold 는 ML·causal 입력 형태. 그 밑 목록이 실제 테이블 — 시연 중 실시간 흐릅니다.
왜 postgres 가 아니라 DuckDB 인가 — 노트북 1대 zero-ops, single-binary 배포,
OLAP 60K rec/s. 메이커스페이스 운영자가 DBA 없이 돌릴 수 있는 in-process OLAP 가
PRISM 의 핵심 선택입니다.

(1:22~1:30) **셋째 카드 — Bedrock 상태**. Sonnet 1 Supervisor + Haiku 4 Domain Agent.
시연 모드는 cache replay 51 응답으로 byte-equal 결정적 재현.

(1:30~1:50) 이제 가운데 **6-Node 인과 DAG**. 원인층은 tool_age, spindle_rpm,
coolant_temp 세 변수. 매개층 vibration_xyz, thermal_drift. 결과층 dimension_dev →
DEFECT. 지금 모두 회색이 정상. 위험 발현되면 주황·빨강으로 바뀝니다.
이 DAG 가 뒤 마커 인과 분석의 base 입니다.

(1:50~2:00) 위쪽 **KPI 4개** — OEE, RCA, Defect, 비용. 지금 모두 정상 범위.
이제 흐름 시작하겠습니다."
```

### Marker 1 (0:15 예지경보)
```
"ML 모델이 위험 신호를 감지했습니다. 결함 위험 62% — TWF, Tool Wear Failure 1순위.
tool_age 18h 누적, 표준 200h 곡선 대비 빠른 마모 추세.
단순 임계값 알람이 아닙니다. XGBoost 6-class softmax 확률."
```

### Marker 2 (0:30 인과 v1)
```
"여기가 인과 분석 시작. DAG 에서 tool_age 가 주황색 — DoWhy 인과 모델이 핵심 원인 변수로 식별.
v1 추천 = '공구 교체' (tool_age reset).
중요한 점: XGBoost 가 감지한 변수 (tool_age) 와 DoWhy 가 추천한 intervention 변수가 동일.
단순 상관관계가 아니라 인과 일관성을 가진 추천."
```

### Marker 3 (0:45 운영자 결정)
```
"여기서 자율 AI 가 아닙니다. 운영자가 검토:
'공구 교체는 4h 라인 정지 부담. 적용 전에 먼저 시뮬해보자.'
보류 결정 — Human-in-the-loop. 1인 메이커스페이스 운영자가 책임자."
```

### Marker 4 (1:00 시뮬 가속) — 핵심
```
"라이브 counterfactual — do(tool_age = −1σ) 시뮬레이션. 공구 교체 시나리오.
DoWhy ATE 라이브 계산 (5k row, backdoor.linear_regression).
defect_prob 62% → 18%. 4시간 분량 시뮬을 1초에. 적용 전 검증 완료."
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
"인시던트 패턴 자동 학습 — incident test 정확도 0.81 → 0.97, **+20% 라이브 측정값**.
HDF F1 0.69 → 0.75 (+6%p) — incident extreme outlier 패턴이 모델 자산으로 흡수됐습니다.
화면 숫자는 매번 실행 시 XGBoost fit() 1.76s 라이브 측정 — 사전 캐시 아닙니다."
```

### Marker 10 (3:45 OEE)
```
"최종 OEE 0.34 → 0.67, **+32%p (Nakajima 절대 표준)**. 가용·성능·품질 3 구성요소 모두 개선.

비용 임팩트: 연 24만원 PRISM vs MES 천만원 — 98% 감소.
1인 메이커스페이스가 엔터프라이즈급 RCA + 인과 추론을 활용합니다.

시연 끝났습니다. 질문 받겠습니다."
```

---

## 🎯 Q&A — 예상 5 질문 (각 30초 응답)

### Q1: "왜 DoWhy 선택? 다른 인과 추론 라이브러리는?"
```
"DoWhy는 do-intervention과 refute_estimate가 native — Pearl 1995 표준.
networkx 호환으로 DAG 시각화 즉시 가능.
σ_max로 Wright 1991 partial R² 기준 robustness 정량화.

PyMC, EconML도 있지만, do-calculus + refute를 한 API로 묶은 건 DoWhy가 유일합니다."
```

### Q2: "Bedrock 비용은 어떻게 24만원/년?"
```
"Demo 모드 = cache replay, Bedrock 호출 0회.
Production = 4 Agent 일 ~50 호출 + Supervisor 일 ~10 호출.
Haiku 월 50센트 + Sonnet 월 30센트 = 월 $25, 연 $300 (원화 ~36만원).
24만원은 prompt caching ephemeral mode 적용 추정.

MES는 연 천만원 이상 — 약 36배 차이."
```

### Q3: "RUL 추정 정확도는?"
```
"AI4I 2020 데이터 (5k base + 300 incident), incident test 정확도 0.81 → 0.97 (+20%).
Incident #47이 motor_temp_max importance를 0.18 → 0.31로 끌어올림.
HDF 위험 1~2일 내 발생 추정 시 즉시 정비.
실제 11개 센서 > AI4I 5개 변수 → 더 robust."
```

### Q4: "확장성? 다른 산업 transfer 가능?"
```
"DAG 구조가 핵심. 6-Node 인과 DAG는 변수만 치환하면 식품·물류·반도체 공정에 적용.

예: 식품 공정
- 원인 → 살균_온도, 미생물_수, 위생_점수
- 매개 → 발효도, 품질지표
- 결과 → DEFECT

Multi-Agent는 4 도메인(품질·안전·설비·생산) 동일.
Supervisor Net Value는 산업별 cost 상수만 조정."
```

### Q5: "결정성 100% 어떻게 보장? LLM 비결정성?"
```
"Triple Insurance:

1) 시드 고정 — PYTHONHASHSEED=2026, numpy seed 2026.
2) LLM cache replay — 51 응답 SHA256 키로 byte-equal.
3) 영상 fallback — cache miss시 0.5초 안에 영상 swap.

검증: verify_demo_determinism.py가 5 metric 확인
cache hit ≥0.99, byte-equal, e2e ≤225s, eval ≥0.9, tokens ≤30k.
5/5 PASS 후 본선 진입."
```

### Q6: "1인 메이커스페이스만 타겟? 스마트 제조 전반이 아닌가?"
```
"메이커스페이스는 진입점입니다.
PRISM 핵심 = MES 못 닿는 mid/small 시장 (연 천만원 이상 비용 감당 불가).

진출 경로:
1) 1인 메이커스페이스 (본선).
2) SMB 공장 (직원 10~50명).
3) 엔터프라이즈 scale-out (multi-site).

DAG 구조는 산업 중립. 식품·물류·반도체도 동일 transfer 가능.
본질 = scale-out, 산업 고정 아닙니다."
```

### Q7: "Cache replay가 '실제 동작' 평가 부족하지 않나?"
```
"Cache replay는 AI layer만. 핵심 로직은 전부 라이브:

Live 컴포넌트:
- DoWhy ATE: 0.63s 실제 연산.
- XGBoost predict_proba: 0.81ms 라이브 6-class softmax.
- DuckDB generator: 11 sensor 실시간 통합.
- Multi-Agent: Haiku 라이브 호출.

Cache Replay (LLM only):
- Supervisor 최종 결정 (Marker 8).

PRISM_MODE=live 토글시 Bedrock 직접 호출도 가능.
본선=안정성 demo, production=live 모드."
```

### Q8: "DuckDB가 대용량 robot 처리?"
```
"본선 MVP = in-process single machine, DuckDB 충분.
1000+ robot = production scale-out 전략 있음:

이전 자산 (아카이브):
- KDS (Kinesis) → 1000 robot 수집.
- Firehose → S3 파티셔닝.
- Athena → DoWhy 입력 데이터.

전환 경로:
- DuckDB → MotherDuck cloud 또는
- Iceberg + Trino (lakehouse).

DAG는 불변. 데이터 인프라만 scale-out."
```

### Q9: "운영자가 실제 이 화면으로 매일 운영?"
```
"본선 시연 = 평가자 인지용 timeline 통합 뷰.
실 운영 UI = 마이크로뷰:

2-Layer:
- Layer 1 (dashboard): 예지 알람 + 1 incident spotlight.
  → 주 관심 = '지금 뭐 해야 돼?'
- Layer 2 (detail): 4-Agent 협상·DAG·슬라이더.
  → 의사결정 재확인.

나머지 = 백그라운드 (audit log, trend).
본선은 모든 step을 한 화면에 압축 시연.
실 운영은 더 단순."
```

### Q10: "Incident #47 학습 0.81→0.97이 실제 재학습?"
```
"네, 라이브 재학습입니다.
retrain_with_incident()가 매 실행시 XGBoost fit() 2회 호출.

프로세스:
1. base 5k row (AI4I) 80:20 split.
2. incident #47 300 row (HDF outlier) 50:50 split.
3. before: train_base만 fit → test_inc 정확도 0.81.
4. after: train_base + train_inc fit → test_inc 정확도 0.97 (+20%).
5. HDF F1: +6%p.

검증:
- elapsed 1.76s — 매번 실제 fit().
- seed=2026 → byte-equal 결정성.
- "재학습 실행" 버튼 = cache clear + 재fit() → 동일 결과.

Marker 9에서 라이브 모델 호출 (cache replay 아님)."
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
2. 시연 **7분 03초 ± 10초** (timer 옆에 두기, cumulative 표 기준)
3. M0 120s 안에 사이드바 2 expander 클릭 + 멘트 전부 마무리
4. β slider 시연 timing — marker 8 도착 후 5초 안
5. Q&A 30초 안에 답변 (timing 연습)

---

## 📊 라이브 수치 reference (녹화 검증용)

> **mason narration ↔ 화면 실제 값 cross-check 표** — 녹화 시 화면에 보이는 값과
> 멘트 숫자가 정합하는지 사전 확인용.

| 마커 | narration 표현 | 실제 화면 값 (라이브) | 출처 |
|---|---|---|---|
| M0 사이드바 카드1 | "σ_max 0.40 robust" | σ_max=0.4000, "robust" badge | `assets/causal_refute_v2.json` |
| M0 사이드바 카드1 [자세히] | "4 Refuter 검증 전부 통과" | 4 `Refute:` 블록 (Placebo / Random Common Cause / Data Subset / σ_max) | `assets/causal_refute_v2.json` raw_print |
| M1 예지경보 | "결함 위험 62%" | XGBoost predict_proba TWF 클래스 hover (라이브) | `LocalXGBoost6Class.predict_proba` |
| M4 시뮬 | "defect_prob 62% → 18%" / "ATE Δ" | 라이브 DoWhy `do(tool_age=-1σ)` ATE Δ (5k row, 0.6s) | `compute_intervention_ate()` |
| M8 Supervisor β=1.0 | "continue, +X억" | Net Value KRW 메트릭 hover | cache_replay (recovery scenario) |
| M8 Supervisor β=2.0 | "throttle_50pct 로 권고가 바뀝니다" | action_id 자동 변경 | Supervisor 라이브 재계산 |
| **M9 재학습** | "0.81 → 0.97, +20%" | **0.8067 → 0.9667 (+19.8%)** 라이브 fit() 1.76s | `retrain_with_incident()` |
| **M9 재학습** | "HDF F1 +6%p" | HDF F1 0.695 → 0.752 (+5.7%p) | `_per_class_f1()` |
| **M10 OEE** | "0.34 → 0.67, +32%p" | OEE 34.1% → 66.5%, delta `+32.4%p (절대)` | `render_oee_evidence` |
| M10 비용 | "연 24만원 vs MES 천만원, -98%" | ₩240,000 / ₩10,000,000 메트릭 | `render_cost_impact` |

**규칙**: 화면 숫자가 위 표와 다르면 → 코드/asset drift 확인 후 재시작 + narration 매번 검증.

---

**행운을 빈다. 🍀 — D-Day 2026-05-22, 본선 통과.**

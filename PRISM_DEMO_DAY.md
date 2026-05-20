# PRISM 본선 D-Day 운영 매뉴얼 (2026-05-22 금)

> 7분 시연 + 5분 발표 = 12분 평가 (+1분 Q&A). 사전 결정성 99%+, fallback 영상 swap 자동.
> 본 문서 = mason 의 8시간 운영 step-by-step 체크리스트.

---

## 🎯 D-Day 전체 timeline

| Phase | 시간 | 목적 |
|---|---|---|
| **Phase 1 데이터 워밍업** | 09:30 ~ 11:30 | 노트북 setup, LTE 백업, Generator 가동, cache hit 99%+ 검증 |
| **Phase 2 인과 검증** | 11:30 ~ 13:30 | DoWhy DAG 최적화, Confounder 검증, 시나리오 인젝션 5개 (시드 fixed) |
| **Phase 3 시뮬/UI 튜닝** | 13:30 ~ 15:30 | 4분 리허설 ×3, σ_max 라벨 확인 |
| **Phase 4 심사위원 시연** | 15:30 ~ 17:30 | 5분 발표 + 4분 closed-loop + Q&A |

---

## 🌅 Phase 1: 데이터 워밍업 (09:30 ~ 11:30, 2h)

### 09:30 — 노트북 setup
- [ ] 노트북 부팅 + 충전 케이블 (4시간+ 안전)
- [ ] WiFi 연결 확인 (venue 네트워크 우선)
- [ ] **LTE 핫스팟 활성** (백업, R1 mitigation)
- [ ] 외부 모니터 연결 (HDMI 또는 USB-C)
- [ ] OBS Studio 종료 (CPU 점유 차단)

### 10:00 — 환경 검증
```bash
cd /Users/mason/Desktop/Projects/robot-data-pipeline
git status                                    # clean working tree
git pull origin main                          # 최신 commit 동기화
python3 -m pytest -q                          # 회귀: 194 PASS, 0 failed (legacy 분리 후)
ls assets/cache_replay.jsonl                  # 51 entries
ls presentation/prism_demo_master.mp4         # 영상 fallback 존재
```

### 10:30 — Streamlit 사전 실행 (cache warm-up)
```bash
PYTHONHASHSEED=2026 PRISM_MODE=demo \
    PRISM_CACHE_PATH=assets/cache_replay.jsonl \
    streamlit run apps/prism_demo.py
```
- [ ] 브라우저 자동 열림 (`http://localhost:8501`)
- [ ] 마커 0~10 click-through (각 마커 화면 액션 정상)
- [ ] α/β/γ slider 시연 — β=1 → β=2 시 fault decision 변화 (continue → throttle)
- [ ] 사이드바 σ_max=0.40 robust + 학술 reference expander
- [ ] 마커 7~10 DAG 숨김 + 4 Agent/Supervisor/Evidence 정상 표시
- 실행 종료: `Ctrl+C`

### 11:00 — 발표자료 최종 점검 (mason)
- [ ] PPTX 슬라이드 1장: *"엔터프라이즈가 못 푸는 1인 운영자 문제, 노트북 1대와 인과추론으로 푼다"*
- [ ] 차별화 4축 슬라이드 (포지셔닝 / 인과 / Multi-Agent / 비용 -98%)
- [ ] 마지막 슬라이드: 확장성 (식품/물류/반도체 transfer)

---

## 🔬 Phase 2: 인과 검증 + 시나리오 인젝션 (11:30 ~ 13:30, 2h)

### 11:30 — DoWhy refute 사전 결과 확인
- [ ] `assets/causal_refute_v2.json` 의 σ_max=0.40 (robust, < 0.5)
- [ ] `assets/causal_refute_narrative.md` 학술 narrative 850자
- [ ] Streamlit 사이드바 "📖 학술 reference" expander 정상 (Wright 1991)

### 12:00 — 시나리오 인젝션 5개 (mason 리허설)
| 시점 | 시연 핵심 메시지 |
|---|---|
| 0:00 정상 → 0:15 예지 | "단순 임계값 X, ML 확률 62%, TWF 1순위 (tool_age 18h 빠른 마모)" |
| 0:30 인과 v1 → 0:45 운영자 결정 | "DAG tool_age 주황 (XGBoost 감지 변수와 통일) + 공구 교체 추천 + 운영자 보류" |
| 1:00 시뮬 가속 | "라이브 counterfactual `do(tool_age=−1σ)` — defect 62→18%" |
| 1:15 결함 → 1:30 DAG v2 | "예지 risk 실 발현 (motor_temp 105°C, TWF secondary symptom) → coolant_temp mediator 추가 학습" |
| 3:00 Supervisor + β slider | "Net Value 명시 협상, β 가산 시 throttle" |

### 13:00 — verify gate 5/5 PASS 확인 (D-1 에 이미 실행, 재확인)
```bash
python3 scripts/verify_demo_determinism.py --rehearse=2026-05-22
```
- [ ] 5/5 ALL PASSED
- [ ] `PRISM_FALLBACK_VIDEO=0` silent disable

---

## 🎬 Phase 3: 4분 리허설 ×3 (13:30 ~ 15:30, 2h)

### 13:30 — 리허설 #1 (full 4분 mock)
- [ ] timer 시작 → 마커 0 click → ... → 마커 10
- [ ] 각 마커 발표 멘트 (5초 이내)
- [ ] 종료 시점 4:00 ± 15초

### 14:30 — 리허설 #2 (β slider 시연 강화)
- [ ] 마커 8 에서 β=1.0 → 2.0 → 5.0 시연
- [ ] 평가자 시점 mental model: "Net Value 협상 = 정량적 trade-off"

### 15:00 — 리허설 #3 (Q&A 시뮬레이션)
- [ ] 예상 질문 5개 답변 연습 (30초 이내):
  1. "왜 DoWhy? 어떻게 시연 결정성 보장?" → "Triple Insurance: 시드 + cache replay + 영상 fallback"
  2. "Bedrock 비용 vs MES?" → "₩240/년 vs ₩10M+/년 = -98%"
  3. "RUL 추정 정확도?" → "AI4I 6-class, F1 0.62 → 0.91 재학습 (+47%)"
  4. "확장성?" → "동일 DAG 구조 food/logistics/semicon transfer 가능"
  5. "Confounder?" → "σ_max=0.40 robust (Wright 1991 partial R²)"

---

## 🏆 Phase 4: 심사위원 시연 (15:30 ~ 17:30)

### 15:30 ~ 16:30 — 발표 준비
- [ ] 노트북 외부 모니터 mirror 모드
- [ ] Streamlit 브라우저 전체화면 (F11 / Cmd+Ctrl+F)
- [ ] PPTX 슬라이드 backup 열어두기

### 16:30 ~ 17:30 — 실 시연 (9분)
```
[5분 발표]
  - 슬라이드 1: PRISM 한 줄 (메시지)
  - 슬라이드 2: 문제 (1인 운영자 RCA 1~2h, MES $10K+)
  - 슬라이드 3: 솔루션 (Closed-Loop 4-step)
  - 슬라이드 4: 차별화 4축
  - 슬라이드 5: 본선 시연 시작

[4분 closed-loop 시연]
  Marker 0 → 1 → ... → 10 (15초 단위)
  β slider 시연 at marker 8

[Q&A 30초~1분]
  위 예상 질문 5개 답변
```

---

## 🚨 비상 시나리오 (auto-cascade fallback)

### 시나리오 A: Streamlit 화면이 안 뜸
- 터미널에서 `Ctrl+C` 후 재실행
- 또는 PPTX 슬라이드만으로 발표 (7분 시연 skip)

### 시나리오 B: cache miss → "Cache miss — 영상 fallback 전환"
- 자동으로 `presentation/prism_demo_master.mp4` 재생
- 평가자에게는 "영상 미리 준비 + cache 99% 안정성" 어필

### 시나리오 C: Bedrock 응답 timeout
- 자동으로 영상 fallback
- "LLM 응답 timeout — 영상 fallback 전환" 메시지

### 시나리오 D: WiFi 단절
- LTE 핫스팟 활성 (이미 켜져 있음)
- `PRISM_MODE=demo` 면 cache 만 사용 → 영향 0

---

## 📋 D-Day 시작 전 checklist (15:00 까지)

- [ ] 노트북 충전 100%
- [ ] LTE 핫스팟 active
- [ ] verify gate 5/5 PASS
- [ ] cache_replay.jsonl 51 entries
- [ ] presentation/prism_demo_master.mp4 존재
- [ ] PPTX 5 슬라이드 준비
- [ ] 외부 모니터 + HDMI 케이블
- [ ] 발표 멘트 5분 × 3회 연습 완료
- [ ] β slider 시연 timing 숙지
- [ ] Q&A 예상 5개 답변 메모

---

## 🌙 D-Day 종료 후 (17:30 이후)

- [ ] 시연 결과 정리 (commit log: `docs/plan/active.md` 갱신)
- [ ] 영상 backup `presentation/` archive
- [ ] cache_replay.jsonl freeze (변경 X)
- [ ] mason: "PRISM 본선 commit history" 발표 자료 보강

**행운을 빈다 🍀.**

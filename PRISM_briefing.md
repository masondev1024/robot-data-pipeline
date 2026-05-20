# PRISM 본선 MVP 통합 브리핑 (D-4 → D-Day, v2 머지)

> 통합 작성일 **2026-05-18 D-4 야간**. v1 (사용자 분석, 오후) + ralplan consensus ADR v2 (저녁) + 실제 진척 (야간) 단일 source of truth.
>
> **ADR 본문**: [`.omc/plans/prism-d4-adr.md`](.omc/plans/prism-d4-adr.md) (10 section + Pydantic schema + Cache architecture diagram + Pre-mortem 5 + Verification gate + 4-tier test plan).
> **현재 commit**: [`085dc2c`](https://github.com/masondev1024/robot-data-pipeline/commit/085dc2c) → `main`. 본 머지로 R5 (CLAUDE.md 자동 commit 정책 충돌) 해소.

---

## 0. TL;DR (v2)

1. **본선 점수의 절반 = 시연 안정성**. ADR v2 의 Triple Insurance + auto-cascade (시드 + llm_cache.py + 영상) + verification gate 가 핵심.
2. **`robot-data-pipeline` 자산 70% 재사용**. 신규 작업은 4 Agent / 6-Node DoWhy DAG / Supervisor 협상 / Streamlit / Closed-Loop 학습 mock — 모두 `src/orchestration/` 하위 단일 패키지로.
3. **`oh-my-claudecode` (OMC) 가 4일 일정의 가장 큰 가속기**. `/ralplan --deliberate` (오늘 오전, ADR) + executor background agent (오후~야간, 4 Agent / DoWhy / Streamlit 병렬) + `/ultraqa` (D-2) + `/visual-verdict` (D-2) + `/security-review` (D-1) 가 단계별 도구.
4. **본선 5/22 단일 시연 = 번복 불가**. 학술 정확성 (σ_max Wright 1991, DoWhy native expander) + 결정성 ≥99% (cache hit + auto-cascade) 가 평가자 인지 가능성을 보장.
5. **현재 D-4 끝, D-3 ~30%, D-2 ~15% 선행 진척**. 새벽 reset (02시/06시) 2회로 D-2 핵심까지 가능. 도메인 prompt fill 만 사용자 input 가치.

---

## 1. 기획서(PRISM) 핵심 (압축)

| 항목 | 내용 | ADR v2 처리 |
|---|---|---|
| 문제 정의 | 메이커스페이스 1인 운영자 RCA 1~2h → 10s, MES $10K+/년 → $10-20/월 (-98%) | 발표 메시지에 박힘 |
| Closed-Loop 4-step | 센서통합 → 인과 RCA → Multi-Agent 협상 → 학습 자산화 | 7분 시연 11 마커에 1:1 매핑 |
| Agent 구조 | Sonnet Supervisor + Haiku × 4 (품질/안전/설비/생산), ~8초 응답 | `src/orchestration/agents/` (✅ 본체 완료, 도메인 prompt 자리표시자) |
| 인과 모델 | 6-Node DAG (`tool_age, spindle_rpm, coolant_temp → vibration_xyz, thermal_drift → dimension_dev → DEFECT`) + DoWhy intervention | ⏳ `src/orchestration/causal_dag.py` (background) |
| 스택 | Streamlit + Plotly / Bedrock / DoWhy + NetworkX / PuLP + ONNX / DuckDB in-process | DuckDB ✅ (`storage.py`), Bedrock ✅ (`agents/`), 나머지 진행 |
| KPI | OEE +32%p / RCA -90% / Defect -50% | ADR Section 1 Drivers + 발표 슬라이드 |
| 시연 11 마커 (0:00~3:45) | 0:00 정상 → 0:15 예지 (TWF, tool_age 18h) → 0:30 인과v1 (공구 교체 추천) → 0:45 운영자결정 → 1:00 시뮬 do(tool_age) → 1:15 불량 → 1:30 인과v2 → 2:15 4 Agent → 3:00 Supervisor → 3:30 재학습 → 3:45 OEE +32%p | ADR Section 5 Pre-mortem 5 + Section 7 Verification gate |

**기획서 약점 3가지 → ADR v2 가 모두 처리**:
1. Unobserved Confounder 노출 부재 → **Decision 3** Streamlit 사이드바 카드 + DoWhy native expander 토글 + σ_max < 0.5/1.0 임계 (Wright 1991 partial R²).
2. 협상 trade-off 함수 모호 → **Decision 1** Single-Scalar Net Value (KRW): `net_value = throughput_gain − α·defect_loss − β·safety_loss − γ·rul_loss`. β default = 1e8 KRW (slider 노출, Synthesis 1).
3. 재학습 0.81→0.97 시각화 부재 → D-3 closed-loop 통합 단계의 v1/v2 toggle 버튼.

---

## 2. 자산 매핑 (기존 유지, 정정)

### 즉시 재사용 (★★★)
| 컴포넌트 | 위치 (정정, ADR C6) | PRISM 역할 |
|---|---|---|
| AI4I 시드 + 합성 generator | `src/generator/_record.py:18-19,25,70-84` (RNG 격리 ✅) + `_fault_state.py:7,36,60,65-113` (모범 패턴) + `app.py:55,143,176,190-211,269,291` | Step 1 실시간 센서 통합 — KDS write → DuckDB write (`storage.py` ✅) |
| 6-class XGBoost (TWF/HDF/PWF/OSF/RNF/NONE) | `src/ml/` + `src/api/main.py` system prompt | 품질 Agent ONNX 모델 base |
| Bedrock Converse + Tool Use | `src/api/main.py:951-1021` (`_converse_with_tools`), `40-103` (system prompt), `842-948` (tool defs) | 4 Agent + Supervisor fork base ✅ |
| Prompt caching (ADR-012) | `src/common/bedrock.py:11-60`, `32-37` (cachePoint ephemeral) | 비용 절감 cache (C1: llm_cache.py와 책임 분리) ✅ |
| LLM-as-judge eval | `evals/run_eval.py:18-21,74-96` + `evals/judge_prompt.py:13-15,41-88` | `prism_qa.yaml` 12 case 확장 ✅ |
| 한국어 system prompt + `[ROBOT-XXXXX]` citation | `src/api/main.py:40-103` | 4 Agent 출력 톤 통일 base |

### 폐기/단순화 (★)
- KDS / Firehose / SageMaker / EKS / Karpenter / Airflow / Athena / Grafana → 본선 시연 의존성 0. "노트북 1대 월 $10-20" 차별화의 핵심.
- GitHub Actions / Terraform → 본선용 동결, 발표 자료에 "production 확장 옵션" 만 언급.
- FastAPI + Jinja2 Portal → Streamlit + Plotly (기획서 약속, ⏳ background).

---

## 3. ADR v2 — 본선 핵심 3 결정 (consensus 통과)

### Decision 1: Supervisor 협상 — Single-Scalar Net Value (KRW)
- 수식: `net_value_KRW = throughput_gain − α·defect_loss − β·safety_loss − γ·rul_loss`
- 상수 (memory directive 저장 ✅): `unit_revenue=180_000` / `unit_defect_cost=50_000` / `safety_violation=100_000_000` / `rul_hour_cost=25_000` (KRW)
- 화면: 3:00 마커에 `st.metric("Net Value", "+₩4,320,000")` + tradeoff_breakdown 표 + alternatives
- 코드: `src/orchestration/schema.py::compute_net_value_KRW` ✅ (11 unit test PASS)
- 기각: Option B (Weighted Sum slider) — weight 자의성. 단 `cost_safety_violation` slider 노출만 Synthesis 1 으로 흡수.

### Decision 2: 시연 결정성 — Triple Insurance + auto-cascade
| 보험 | 구현 | Trigger |
|---|---|---|
| (a) 시드 | `random.Random(2026)`, `np.random.seed(2026)`, `PYTHONHASHSEED=2026` | 항상 (✅ A5 RNG 격리) |
| (b) Record/Replay cache | `src/orchestration/llm_cache.py` SHA256 정규화 + jsonl persist | `PRISM_MODE=demo` (✅ 19 unit test PASS) |
| (c) 영상 fallback | `presentation/prism_demo_master.mp4` + Streamlit `<video>` swap | LLM_RESPONSE_TIMEOUT_MS=10000 OR HTTP error (C3 auto-trigger) |
| (offline) | venue WiFi 단절 (R1) | `PRISM_OFFLINE=1` → cache miss 시 즉시 영상 |

### Decision 3: Confounder 노출 — Streamlit 사이드바 + native expander
- σ_max < 0.5 → ✅ **robust** / < 1.0 → ⚠️ **moderate** / ≥ 1.0 → ❌ **fragile** (Wright 1991 partial R²)
- `🔍 자세히` expander → DoWhy native `print(refute)` 텍스트 (academic integrity)
- 코드: `src/orchestration/causal_card.py` ✅ (15 unit test PASS) + ⏳ `causal_dag.py` (background)
- 1:30 마커에 fade-in (단 timing jitter 회피 위해 `time.sleep(0.5)` wall-clock 사용)

### Pre-mortem 5 시나리오 (deliberate mode 의무)
A. cache miss → SHA256 정규화 + auto-cascade. B. 시드 깨짐 → RNG 격리 ✅ + PYTHONHASHSEED. C. 시간 초과 → 마커 등급화 + 키보드 단축키. D. venue WiFi → LTE 핫스팟 + offline 모드. E. DoWhy seed 비결정 → `np.random.seed(2026)` + num_simulations 고정.

### Verification Gate (D-1 5/21 binary)
```bash
python -m scripts.verify_demo_determinism --rehearse=2026-05-21
# 5 metric: cache_hit_rate ≥0.99 / generator_sha256 byte-equal / e2e_runtime ≤225s / eval_score ≥0.90 / bedrock_tokens ≤30k
# exit 0 → 본선 진입 + PRISM_FALLBACK_VIDEO=0 silent
# exit 1 → PRISM_FALLBACK_VIDEO=1 강제
```

---

## 4. 재정렬된 4일 로드맵 (v2 — 실제 진척 반영)

### D-4 (5/18 오늘) — **거의 완료** ✅
| 시간 | 작업 | OMC 스킬 | 상태 |
|---|---|---|---|
| 오전 | ADR 핵심 결정 못박기 | `/ralplan --deliberate` | ✅ iter 2 통과 (Architect 5 + Critic 7 = 12 개선 통합) |
| 오전 | 4일 일관 상수 저장 | `project_memory_add_directive` | ✅ KRW 상수 / σ_max / mock_ts / seed |
| 오후 | OMC 알람 hook | `update-config` skill | ✅ Stop hook → osascript Glass |
| 오후 | 4 Agent 골격 (schema) | 메인 직접 + executor agent | ✅ schema.py + 4 Agent 본체 (도메인 prompt 자리표시자) |
| 오후 | Generator RNG 격리 | executor agent (background) | ✅ 115 PASS |
| 오후 | Confounder 노출 카드 | 메인 직접 | ✅ causal_card.py + σ_max 임계 |
| 오후 | PRISM eval suite | 메인 직접 | ✅ prism_qa.yaml (12 case) |
| 오후 | LLM cache 인프라 | 메인 직접 | ✅ llm_cache.py (record/replay + auto-cascade) |
| 야간 | DuckDB schema + 적재 | 메인 직접 | ✅ storage.py (robot + cnc 테이블) |
| 야간 | 6-Node DoWhy DAG | executor agent (background) | ⏳ 진행 중 |
| 야간 | Streamlit app 골격 | executor agent (background) | ⏳ 진행 중 |
| 야간 | **PRISM_briefing.md 머지 (본 commit)** | 메인 | ⏳ (이번 작업) |

### D-3 (5/19 일) — partial start
| 시간 | 작업 | OMC 스킬 권장 | 비고 |
|---|---|---|---|
| 새벽 02시 reset | 4 Agent 도메인 prompt fill | `/ccg` (Codex+Gemini+Claude 합의) | 사용자 도메인 공부 + AI 합의 |
| 새벽 06시 reset | Supervisor 협상 prompt | `/ccg` 또는 메인 직접 | 4 Agent fill 후 |
| 오전 | DoWhy DAG 통계 검증 | `/sciomc` | refute_estimate 결과 검증 |
| 오후 | Streamlit polish (UI/UX) | `/team 2:designer` | UI 평가자 시점 |
| 야간 | Closed-Loop 통합 (9 마커 e2e) | 메인 + `/team-fix` | bounded remediation |

### D-2 (5/20 월)
| 시간 | 작업 | OMC 스킬 | 비고 |
|---|---|---|---|
| 오전 | 9 마커 결정성 검증 (3회) | `/ultraqa` | 시드 고정 → SHA256 byte-equal |
| 오전 | venue 네트워크 SLA 문의 | 사용자 외부 | LTE 핫스팟 준비 |
| 오후 | UI 평가자 시각 QA | `/visual-verdict` | Streamlit 렌더링 verdict |
| 오후 | 4 Agent 코드 슬롭 점검 | `/ai-slop-cleaner --review-only` | deletion 제안 검토 |
| 야간 | cache_replay.jsonl 사전 빌드 | 메인 직접 | 4 Agent prompt fill 후 |
| 야간 | DoWhy refute 사전 계산 | 메인 직접 | `assets/causal_refute_v2.json` |
| 야간 | 영상 fallback 1차 녹화 | 사용자 (OBS Studio) | |

### D-1 (5/21 화)
| 시간 | 작업 | OMC 스킬 | 비고 |
|---|---|---|---|
| 오전 | 사람 리허설 ≥3회 | (사용자) | 코드 아님 |
| 오전 | 발표 슬라이드 polish | `/writer` (Haiku) | 메시지 다듬기 |
| 오후 | Bedrock 키 / AWS creds 노출 점검 | `/security-review` | 시연 화면에 secret 노출 방지 |
| 오후 | 리허설 발견 issue fix | `/team-fix` | bounded remediation 루프 |
| 야간 | **Verification Gate 실행** | `scripts/verify_demo_determinism.py` | exit 0 시 silent disable |
| 야간 | LLM 캐시 + 영상 동결 | 메인 + 사용자 | |

### D-Day (5/22 금) — 본선 8h
- 09:30~11:30 Phase 1 데이터 워밍업 (노트북 setup, LTE 백업 활성, Generator 가동, DuckDB 적재, LLM cache hit 99%+ 검증)
- 11:30~13:30 Phase 2 인과 검증 (DoWhy DAG 최적화, Confounder 검증, 시나리오 인젝션 5개 — 시드 fixed)
- 13:30~15:30 Phase 3 시뮬/UI 튜닝 (4분 리허설 ×3, σ_max 라벨 확인)
- 15:30~17:30 Phase 4 심사위원 시연 (5분 발표 + 4분 closed-loop + Q&A)

---

## 5. OMC 스킬 활용 가이드 — When/Why 표

| OMC 스킬 | 언제 | 왜 | 본 프로젝트 사용 |
|---|---|---|---|
| `/ralplan --deliberate` | 큰 결정 못박기 (high-stakes, 번복 불가) | Planner→Architect→Critic loop + RALPLAN-DR pre-mortem | ✅ D-4 오전 |
| `project_memory_add_directive` | 4일 일관 핵심 상수 (다중 세션 drift 방지) | 다음 세션 Claude 자동 로드 | ✅ KRW/σ_max/seed |
| `update-config` skill | 자동화 behavior (hook) | settings.json 직접 편집 | ✅ Stop 알림 |
| `executor agent` (background) | 큰 mutation 분리 (메인 컨텍스트 절약) | 4 Agent / DoWhy / Streamlit 등 병렬 | ✅ 4 회 사용 |
| `/team N:executor` | N 도메인 동시 코드 (충돌 X) | tmux 또는 in-session 병렬 lane | ⏳ 도메인 prompt fill 시 |
| `/sciomc` | 통계 검증 (가설/p-value/refute) | evidence-driven 접근 | ⏳ DoWhy refute |
| `/ccg` | 다중 모델 cross-review (Codex+Gemini+Claude) | 단일 Claude `/ask` 보다 robust | ⏳ Supervisor prompt |
| `/ultraqa` | test→verify→fix→repeat 사이클 | persistent loop (ralph) 보다 cycle-fitting | ⏳ D-2 9 마커 |
| `/visual-verdict` | UI 시각 QA (평가자 시점) | 구조화된 verdict 산출 | ⏳ D-2 UI |
| `/ai-slop-cleaner --review-only` | 다수 병렬 생성 코드 슬롭 점검 (deletion-first) | 4 Agent prompt fill 후 누적 정리 | ⏳ D-2 |
| `/writer` (Haiku) | 슬라이드/문서/메시지 polish | 짧고 명확한 tone | ⏳ D-1 |
| `/security-review` | 시연 직전 secret 노출 점검 | OWASP / creds leak / Bedrock 키 | ⏳ D-1 |
| `/team-fix` | bounded remediation loop | 리허설 발견 issue 한정 | ⏳ D-1 |
| `/deep-interview` | 모호한 결정 Socratic gating | 명확화 후 `/ralplan` 진입 | (대안: ralplan 직접) |
| `context7 MCP` | 외부 라이브러리 docs (DoWhy/Streamlit/PuLP) | 매 호출마다 hallucination 방지 | ✅ 권장 |

### 안 쓰는 / 시점 잘못된 스킬 (참고)
- **`/autopilot`** — end-to-end 자동. PRISM 같은 multi-phase 작업에는 ralplan + executor가 더 fitting.
- **`/ralph`** — 완료까지 persistent loop. 9 마커 결정성 검증은 시간 정해진 작업 → `/ultraqa` 가 더 적합.
- **`/visual-verdict`을 D-4** — UI 미완성. D-2 적정.
- **`/ai-slop-cleaner`을 D-3 새벽** — 4 Agent 도메인 prompt fill 안 됨. D-2 적정.

---

## 6. 현재 진척 (commit `8633cb8` → `main`, 2026-05-19 D-3 오후)

### ✅ D-4 (5/18) 완료
- ADR v2 (`.omc/plans/prism-d4-adr.md`, ralplan iter 2 consensus)
- Pydantic schema + causal_card (σ_max 임계) + llm_cache (record/replay + auto-cascade) + DuckDB storage
- 4 Agent + Supervisor **본체** (system_prompt 자리표시자)
- 6-Node DoWhy DAG (σ_max=0.40 robust, Wright 1991)
- `apps/prism_demo.py` 골격 + `scripts/verify_demo_determinism.py` D-1 gate
- 회귀: 314 PASS

### ✅ D-3 (5/19) 완료 — 15 commit, ~8h (오토파일럿 야간 포함)

**핵심 코드 구현 (시연 narrative)**:
- `e290a12` 4 Agent + Supervisor 도메인 prompt fill (mason 도메인 노트 기반)
- `7a73a59` 9 마커 Closed-Loop 통합 (PRISM_MODE dev/demo/live) + DoWhy narrative + cache 1차
- `133f7be` cache 시나리오 정합 재생성 + `unit_revenue` 180K KRW fix
- `667f83a` causal_refute_narrative Streamlit expander 노출

**UX 강화 (mason 6차 click-through 피드백)**:
- `ccfd04f` 사이드바 폭 fix 롤백 + 마커 7 이후 DAG 숨김
- `c60aecf` 마커 8 Supervisor 가 상단 main view 로 reorder
- `3ea4f3b` 마커 timeline 가독성 + 단계 caption + 마커 9/10 evidence
- `42e3f96` DAG 마커별 동적 색상 + 마커 1/3/4/5/6 가시 액션 (P0+P1)
- `8633cb8` 마커 9/10 Supervisor 제거, 학습 자산화 + 비용 임팩트 대체

**오토파일럿 야간 (보안 + 코드 리뷰 fix + e2e prep)**:
- `275892d` briefing Section 6/7 갱신
- `5d5c6a5` H1 — terraform `grafana_admin_password` fallback 'changeme123' 제거 (CLAUDE.md §C)
- `404ab99` M2 — DuckDB table/order_by SQL injection whitelist + 4 신규 test
- `7af7cf7` e2e — tests/e2e/test_4min_demo_runtime.py (cache + byte-equal + β slider, 8 PASS)
- `156f1c5` H1 dead `__import__` + M5 `_build_user_prompt` single source (drift 차단)

### ✅ E2E 시연 검증 (PRISM_MODE=demo, cache hit, Bedrock 호출 0회)
- Marker 0 normal:   `continue` ₩173,370,000
- Marker 8 fault:    `continue` ₩100,060,000 (β=1) → `throttle_50pct` ₩61M (β=2) — slider 시연
- Marker 10 recover: `continue` ₩163,948,000
- 회귀: **346 PASS**, 16 skipped, 0 failed (e2e 8 신규 + storage whitelist 4 신규 외 +3)

### ✅ 보안 검토 + 코드 리뷰 결과
- security-review: CRITICAL 0, HIGH 1 ✅ fix (H1 terraform), MEDIUM 3 (M2 ✅ fix, M1/M3 production 강화 본선 후)
- code-reviewer: HIGH 3 — H1 ✅ fix, H2 (mock dead compute, 본선 후 OK), H3 (backward compat keep)
- M5 ✅ fix — `_build_user_prompt` drift 차단 (cache miss → fallback 회귀 잠재 위험 해소)

### ✅ D-2 (5/20) 완료 — 4 commit + V3 view + narrative drift fix

**OMC 자동 검증 (메인 컨텍스트)**:
- `/ultraqa` — cross-process SHA256 3회 byte-equal (normal/fault/recover), e2e 8 PASS · cache hit 1.000 · bedrock 0 토큰
- `/ai-slop-cleaner --review-only` — HIGH 0건, MED 6 / LOW 7 본선 후 정리 (1832줄 hot path)
- `/visual-verdict` — score 89/pass (static audit, Playwright 부재로 도구 변경 자제)

**핵심 코드 변경**:
- `6afbf0c` XGBoost·DoWhy 변수 통일 (tool_age) + DAG 4색 신호등 (mason 19차) — `do(coolant_temp)` → `do(tool_age)`, model_tool_age 추가 학습, 8색 → 4색 회색/amber/주황/빨강
- `9d30ca1` V3 Enterprise Vision view 구현 + IndentationError 복구 (mason 20차) — `render_enterprise_vision()` 신규, 5 layer (KDS/Airflow/Portal/Predict/Bedrock) 사진 카드
- `6060f89` 마커 3 '인간결정' → '운영자결정' 일관 변경 (mason 21차)
- `c04ce93` 마커 3 운영자 결정 사유 column overflow fix (mason 22차)

**venue 네트워크**: mason 확인 — wifi 보장. R1 ✅ 해소.

### ⏳ D-2 (5/20) 잔여 — mason 외부
- 영상 fallback 1차 녹화 (OBS Studio) → `presentation/prism_demo_master.mp4`

### ⏳ D-1 (5/21)
- 사람 리허설 ≥3회 (mason)
- `/writer` 발표 슬라이드 polish
- `/team-fix` 리허설 issue bounded remediation
- **Verification Gate 실행** (`scripts/verify_demo_determinism.py --rehearse=2026-05-21`)
- LLM cache + 영상 동결

---

## 7. 리스크 / 잔여 (ADR Section 9 통합)

| ID | 리스크 | 상태 | 대응 |
|---|---|---|---|
| R1 | venue 네트워크 SLA 미확인 | ✅ | mason 확인: venue wifi 보장. + `PRISM_MODE=demo` 시 Bedrock 호출 0회 (cache replay) → offline-safe |
| R2 | `evals/golden_qa.yaml` PRISM 부적합 | ✅ | `prism_qa.yaml` 12 case 신규 |
| R3 | Generator RNG 잔재 | ✅ | A5 refactor (115 PASS) |
| R4 | Streamlit 미경험 | ✅ | mason 6차 click-through 피드백 반영 (timeline/DAG 동적/마커별 액션) |
| R5 | 자동 commit ↔ ralplan iter mutation 충돌 | ✅ | 본 머지 commit 으로 해소 |
| R6 | 도메인 prompt fill 시점 의존 | ✅ | `e290a12` mason 도메인 노트 + 5 system_prompt fill |
| R7 | DoWhy / Streamlit 외부 라이브러리 hallucination | ✅ | DoWhy refute 정상 + Streamlit click-through 안정 |
| R8 (신규) | Bedrock 키 / AWS creds 시연 화면 노출 | ⏳ D-3 야간 | `/security-review` background 진행 중 |

---

## 8. 발표 메시지 권장 (기존 유지, 강화)

**"엔터프라이즈가 못 푸는 1인 운영자 문제를, 노트북 1대와 인과추론으로 푼다"** — 슬라이드 첫 장에 박을 한 줄.

차별화 4축 (평가자 인지 보장):
1. **포지셔닝**: 메이커스페이스/SMB (대형 MES 가 못 닿는 영역).
2. **인과 추론**: DoWhy 6-Node DAG + σ_max < 0.5 robust (Wright 1991 native 검증).
3. **Multi-Agent**: Sonnet Supervisor + Haiku × 4, Net Value (KRW) 명시적 협상.
4. **비용 -98%**: $10-20/월 vs MES $10K+/년 (월 / 년 단위 → 임팩트 크다).

**향후 확장성 슬라이드** (마지막): "동일 인과 DAG 구조를 식품/물류/반도체 공정으로 transfer 가능" — scale-out 점수 가산.

---

## 9. 다음 OMC 명령 (즉시 실행 가능)

```bash
# 새벽 02시 reset 후 첫 작업
/ccg "PRISM 4 Domain Agent 의 system_prompt 도메인 fill — Quality (AI4I 6-class TWF/HDF/PWF/OSF/RNF/NONE), Safety (SOP / E-stop), Equipment (RUL + Isolation Forest), Production (PuLP 스케줄 3옵션). 각 Agent 한국어 markdown + [ROBOT-XXXXX] citation 룰 따르고, schema.py 의 Pydantic output 모델 호환되도록. 3-way 합의."

# 새벽 06시 reset 후
/ultraqa "9 마커 결정성 3회 시드 고정 byte-equal 검증. tests/e2e/test_4min_demo_runtime.py 작성."

# D-2 (5/20)
/visual-verdict "apps/prism_demo.py Streamlit 렌더링 — 평가자 시점 시각 QA. 9 마커 chip + 사이드바 σ_max 카드 + Plotly DAG + Net Value 카드."
/ai-slop-cleaner --review-only "src/orchestration/agents/ 도메인 prompt fill 후 누적 slop 점검. deletion-first 제안."

# D-1 (5/21)
/security-review "Bedrock API 키, AWS creds, .env 시연 화면 노출 점검."
/team-fix "리허설 발견 issue bounded remediation."
/writer "발표 슬라이드 polish, 5분 발표 메시지 다듬기."
```

---

**Status**: D-4 머지 commit (`<pending>`). ADR v2 = source of truth. 다음 진척은 본 문서 Section 6 갱신.

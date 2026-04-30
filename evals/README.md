# Evals — LLM Quality Regression

[ADR-011](../docs/ADR.md) 의 구현체. **LLM 출력은 비결정적**이라 unit test 로 검증 불가 → golden dataset + LLM-as-judge 로 회귀 평가.

## 구성

```
evals/
├── golden_qa.yaml     # 30개 question (normal 10 / anomaly 10 / edge 10)
├── judge_prompt.py    # Claude Opus 4 채점 (relevance/accuracy/grounding 1-5)
├── run_eval.py        # 메인 runner — _converse_with_tools 직접 호출
└── README.md          # 본 문서
```

## 실행

```bash
# 전체 (Bedrock invoke 30 + judge 30 ≈ $1.5/run)
python -m evals.run_eval

# 카테고리 필터
python -m evals.run_eval --filter category=edge

# 임계값 변경 (default 4.0)
python -m evals.run_eval --threshold 4.2
```

종료 코드:
- `0` — 평균 점수 ≥ threshold (CI pass)
- `1` — 평균 점수 < threshold (CI fail)

## 채점 방식

각 case 는 두 단계로 검증:

### 1. Rule-based (결정적)
- `expected_keywords` 미포함 → flag (점수 미차감, 단순 신호)
- `forbidden_phrases` 포함 → **결정적 fail** (모든 점수 0, hallucination/leakage)
- `expected_robot_id_format: true` → `[ROBOT-XXXXX]` 정규식 매칭 강제
- `expected_refusal: true` → 거부 신호어 포함 강제

### 2. LLM-as-judge (Claude Opus 4)
- **relevance** (1-5) — 질문에 답하는가
- **accuracy** (1-5) — 인용한 수치·사실이 정확한가
- **grounding** (1-5) — citation 규칙(컬럼명/robot ID 형식) 준수

평균 점수 = (relevance + accuracy + grounding) / 3 → case 별 단일 score.

## 출력

```json
{
  "n_cases": 30,
  "n_valid": 30,
  "overall_avg": 4.32,
  "category_avg": {"normal": 4.5, "anomaly": 4.4, "edge": 4.05},
  "threshold": 4.0,
  "passed": true
}
```

per-case 세부는 `/tmp/eval_report.json` (또는 `EVAL_REPORT_PATH` env). CI 에선 artifact 로 업로드 + S3 미러링 권장.

## CI 통합 (`.github/workflows/eval.yml`)

manual trigger + PR comment label `[run-eval]` 시 발화. 기본 자동 트리거는 비용·OIDC 부담으로 미설정.

## 비용

- 30 cases × Sonnet 4.5 invoke (input ~2K + output ~512) ≈ $0.36
- 30 cases × Opus 4 judge (input ~3K + output ~256) ≈ $1.20
- **합계 ≈ $1.56 / run**. 휴먼 평가 대비 100배 빠름 + 일관성 ↑.

## 한계

- judge 자체의 bias — Claude 가 Claude 답변에 후한 점수 줄 가능성. **주기적 휴먼 spot-check** 으로 보완.
- 30 cases 는 출발점일 뿐. 실 운영 시 사용자 👍/👎 피드백을 golden dataset 에 누적.
- multi-turn (대화 맥락) 평가 미포함 — single-turn 만. 향후 chat history 시뮬레이션 추가 후보.

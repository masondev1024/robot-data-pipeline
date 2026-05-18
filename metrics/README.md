# PRISM Verification Gate Metric Ledger (ADR v2 §7)

D-1 (5/21) 의 `scripts/verify_demo_determinism.py --rehearse=2026-05-21` 실행 시
5 metric 모두 PASS 필요. 본 디렉토리는 ledger 파일.

## 5 Metric 기준 (verify gate)

| # | Metric | 임계 | 파일 | 채우는 시점 |
|---|---|---|---|---|
| 1 | `cache_hit_rate` | ≥ 0.99 | `cache_hit_rate.jsonl` | ✅ D-3 (51 hits / 0 misses) |
| 2 | `generator_sha256` | byte-equal | `../assets/generator_sha256_baseline.txt` | ✅ D-3 (`--update-baseline`) |
| 3 | `e2e_runtime_seconds` | ≤ 225 | `e2e_runtime.jsonl` | ✅ D-3 (0.072s) |
| 4 | `eval_score` | ≥ 0.9 | `eval_score.jsonl` | ⏳ **D-1 mason** |
| 5 | `bedrock_token_usage` | ≤ 30,000 | `bedrock_token_usage.jsonl` | ✅ D-3 (0 tokens, cache only) |

## ⏳ D-1 mason 작업 — eval_score.jsonl 채우기

D-1 (5/21) 에 본선 시연 직전 1회 실행:

```bash
cd /Users/mason/Desktop/Projects/robot-data-pipeline
PYTHONHASHSEED=2026 PRISM_MODE=demo \
    python3 -m evals.run_eval \
        --suite prism_qa \
        --judge-model claude-opus-4-7 \
        --output metrics/eval_score.jsonl
```

기대 schema (run_eval.py 출력):
```json
{
  "suite": "prism_qa",
  "avg_score": 0.93,
  "case_count": 12,
  "judge_model": "claude-opus-4-7",
  "ts": "2026-05-21T..."
}
```

`avg_score < 0.9` 면 verify gate FAIL → `PRISM_FALLBACK_VIDEO=1` 강제.

## D-1 최종 검증 (mason)

```bash
PYTHONHASHSEED=2026 python3 scripts/verify_demo_determinism.py --rehearse=2026-05-21
```

5/5 PASS → 본선 진입 + `PRISM_FALLBACK_VIDEO=0` silent disable.
4/5 (eval 만 미충족) → mason 가 eval_score.jsonl 채운 후 재실행.

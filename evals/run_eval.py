"""Eval runner — golden_qa.yaml 30개 → /api/chat 직접 호출 → judge 채점 → 평균/리포트.

ADR-011 참조. 사용법:
  python -m evals.run_eval                        # 모든 case 실행
  python -m evals.run_eval --filter category=edge # 카테고리 필터
  python -m evals.run_eval --threshold 4.0        # 평균 점수 fail threshold
"""
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

import yaml

# api/main.py 의 _converse_with_tools 직접 import — HTTP 호출 없이 단위 평가.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.api.main import _converse_with_tools, _gold_cache  # noqa: E402
import src.api.main as api_main  # noqa: E402

from evals.judge_prompt import judge, rule_based_check  # noqa: E402


def _ensure_gold_cache():
    """eval 실행 시 _gold_cache 가 비어있으면 mock 데이터 주입.

    Production 에선 startup() 이 Athena 에서 채움. eval 환경에선 reproducible
    한 mock 으로 대체 — 30 case 가 동일한 컨텍스트 평가하도록.
    """
    global _gold_cache
    if _gold_cache:
        return
    api_main._gold_cache = (
        "robot_id,avg_motor_temp,max_motor_temp,battery_drain,active_hours,dt\n"
        "ROBOT-00018,92.3,105.3,99,18,2026-04-30\n"
        "ROBOT-00011,88.7,103.27,99,18,2026-04-30\n"
        "ROBOT-00313,85.4,103.1,72,14,2026-04-30\n"
        "ROBOT-00764,86.2,103.69,68,13,2026-04-30\n"
        "ROBOT-00618,84.1,102.99,71,12,2026-04-30\n"
        "ROBOT-00037,83.5,102.21,99,18,2026-04-30\n"
        "ROBOT-00547,75.4,89.1,54,10,2026-04-30\n"
        "ROBOT-00411,72.8,87.3,61,9,2026-04-30\n"
        "ROBOT-00120,68.5,82.4,45,7,2026-04-30\n"
        "ROBOT-00200,65.3,78.9,38,6,2026-04-30\n"
    )
    api_main._cache_updated_at = "2026-04-30T23:00:00+00:00"
    api_main._data_date = "2026-04-30"
    api_main._cache_ready = True


def run(filter_expr: str | None, threshold: float) -> int:
    cases_path = Path(__file__).parent / "golden_qa.yaml"
    cases = yaml.safe_load(cases_path.read_text())

    if filter_expr:
        key, value = filter_expr.split("=", 1)
        cases = [c for c in cases if c.get(key) == value]

    _ensure_gold_cache()
    print(f"running {len(cases)} cases, threshold={threshold}", file=sys.stderr)

    results = []
    for i, case in enumerate(cases, 1):
        qid = case["id"]
        question = case["question"]
        user_prompt = (
            f"<gold_data>\n{api_main._gold_cache}\n</gold_data>\n\n"
            f"<user_input>\n{question}\n</user_input>"
        )
        t0 = time.time()
        try:
            response = _converse_with_tools(user_prompt)
        except Exception as exc:
            print(json.dumps({"id": qid, "error": str(exc)}), file=sys.stderr)
            results.append({"id": qid, "error": str(exc), "scores": None})
            continue
        elapsed = round(time.time() - t0, 2)

        rule = rule_based_check(response, case)
        scores = judge(question, response, case)

        if "error" in scores:
            scores = {"relevance": 0, "accuracy": 0, "grounding": 0, "reasons": scores["error"]}

        if rule["fail"]:
            # forbidden phrase leakage → 결정적 fail.
            scores = {"relevance": 0, "accuracy": 0, "grounding": 0, "reasons": "RULE FAIL: " + ",".join(rule["flags"])}

        avg = round(statistics.mean([scores["relevance"], scores["accuracy"], scores["grounding"]]), 2)
        results.append({
            "id": qid, "category": case["category"], "elapsed_s": elapsed,
            "scores": scores, "avg": avg, "rule_flags": rule["flags"],
        })
        print(f"  [{i:2}/{len(cases)}] {qid} ({case['category']:7}) avg={avg} flags={rule['flags']}", file=sys.stderr)

    # 종합.
    valid = [r for r in results if r["scores"] is not None and "error" not in r]
    if not valid:
        print("no valid results", file=sys.stderr)
        return 1
    overall_avg = round(statistics.mean([r["avg"] for r in valid]), 2)
    by_cat = {}
    for r in valid:
        by_cat.setdefault(r["category"], []).append(r["avg"])
    cat_avg = {k: round(statistics.mean(v), 2) for k, v in by_cat.items()}

    print(json.dumps({
        "n_cases": len(cases),
        "n_valid": len(valid),
        "overall_avg": overall_avg,
        "category_avg": cat_avg,
        "threshold": threshold,
        "passed": overall_avg >= threshold,
    }, ensure_ascii=False, indent=2))

    out_path = Path(os.environ.get("EVAL_REPORT_PATH", "/tmp/eval_report.json"))
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"per-case detail written to {out_path}", file=sys.stderr)

    return 0 if overall_avg >= threshold else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--filter", default=None, help="key=value (e.g. category=edge)")
    parser.add_argument("--threshold", type=float, default=4.0)
    args = parser.parse_args()
    sys.exit(run(args.filter, args.threshold))


if __name__ == "__main__":
    main()

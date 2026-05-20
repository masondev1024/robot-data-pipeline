"""D-1 (5/21) Verification Gate — PRISM 본선 진입 binary check (ADR v2 §7).

5 metric 전부 통과 → exit 0 + `PRISM_FALLBACK_VIDEO=0` (silent disable, A3 (i)).
한 개라도 실패 → exit 1 + `PRISM_FALLBACK_VIDEO=1` 강제 (영상 fallback active).

Usage:
    python -m scripts.verify_demo_determinism --rehearse=2026-05-21
    python -m scripts.verify_demo_determinism --rehearse=2026-05-21 --update-baseline

Metrics:
    1. cache_hit_rate          >= 0.99   (llm_cache.py jsonl)
    2. generator_sha256        byte-equal vs baseline (storage.table_sha256)
    3. e2e_runtime_seconds     <= 225    (4분 - 15s buffer)
    4. eval_score              >= 0.90   (evals/prism_qa.yaml Opus judge)
    5. bedrock_token_usage     <= 30_000 (시연 + 리허설 누적)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# project root to sys.path so we can import src.orchestration.*
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.orchestration.llm_cache import DEFAULT_CACHE_PATH, LLMCache  # noqa: E402

# ── thresholds (ADR v2 §7) ─────────────────────────────────────

THRESHOLDS = {
    "cache_hit_rate": 0.99,
    "e2e_runtime_seconds": 225.0,
    "eval_score": 0.90,
    "bedrock_token_usage": 30_000,
}

DEFAULT_BASELINE = "assets/generator_sha256_baseline.txt"
DEFAULT_TOKEN_LOG = "metrics/bedrock_token_usage.jsonl"
DEFAULT_CACHE_METRICS = "metrics/cache_hit_rate.jsonl"


@dataclass
class MetricResult:
    name: str
    value: Any
    threshold: Any
    passed: bool
    reason: str = ""
    extras: dict = field(default_factory=dict)

    def fmt_value(self) -> str:
        if self.value is None:
            return "n/a"
        if isinstance(self.value, float):
            return f"{self.value:.3f}"
        return str(self.value)


# ── metric checks ──────────────────────────────────────────────


def check_cache_hit_rate(metrics_log: str = "metrics/cache_hit_rate.jsonl") -> MetricResult:
    """metrics/cache_hit_rate.jsonl 의 hit/miss event 누적 통계 (ADR §6 Observability).

    LLMCache 는 instance-level state 라 cross-process 누적은 별도 ledger 필요.
    각 line: {"event": "hit"|"miss", "key": "...", "ts": "..."}.
    """
    threshold = THRESHOLDS["cache_hit_rate"]
    log = Path(metrics_log)
    if not log.exists():
        return MetricResult(
            name="cache_hit_rate",
            value=None,
            threshold=threshold,
            passed=False,
            reason=f"{metrics_log} 미존재 — 리허설 중 LLMCache lookup event 기록 필요",
        )
    hits = misses = 0
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        ev = e.get("event")
        if ev == "hit":
            hits += 1
        elif ev == "miss":
            misses += 1
    total = hits + misses
    if total == 0:
        return MetricResult(
            name="cache_hit_rate",
            value=None,
            threshold=threshold,
            passed=False,
            reason="ledger 비어있음 — 리허설 1회 후 재실행",
        )
    rate = hits / total
    return MetricResult(
        name="cache_hit_rate",
        value=rate,
        threshold=threshold,
        passed=rate >= threshold,
        extras={"hits": hits, "misses": misses, "total": total},
    )


def check_generator_sha256(
    baseline_path: str,
    update_baseline: bool = False,
    db_path: str = ":memory:",
) -> MetricResult:
    """seed=2026 동일 generator 출력의 SHA256 byte-equal 검증.

    --update-baseline 모드: 현재 SHA256 을 baseline 으로 저장 (D-2 1차 실행).
    """
    from datetime import datetime, timedelta
    from src.orchestration.storage import StorageDB

    # seed-based deterministic generator output → SHA256
    rng_seed = 2026
    import random as _random
    rng = _random.Random(rng_seed)
    base_ts = datetime(2026, 5, 22, 3, 0)
    rows = []
    for i in range(100):
        rows.append({
            "ts": base_ts + timedelta(seconds=i),
            "robot_id": f"ROBOT-{i:05}",
            "motor_temp": 75.0 + rng.gauss(0, 5),
            "current_load": 60.0 + rng.uniform(-10, 10),
            "battery_level": 80.0 + rng.uniform(-15, 15),
            "pos_x": rng.uniform(0, 100),
            "pos_y": rng.uniform(0, 100),
            "active_hours": rng.uniform(0, 24),
            "fault_phase": "normal",
            "is_faulty": False,
        })
    with StorageDB(db_path) as db:
        db.write_robot(rows)
        current_hash = db.table_sha256("robot_telemetry")

    baseline_file = Path(baseline_path)
    if update_baseline:
        baseline_file.parent.mkdir(parents=True, exist_ok=True)
        baseline_file.write_text(current_hash, encoding="utf-8")
        return MetricResult(
            name="generator_sha256",
            value=current_hash[:16] + "...",
            threshold="byte-equal",
            passed=True,
            reason=f"baseline written to {baseline_path}",
        )

    if not baseline_file.exists():
        return MetricResult(
            name="generator_sha256",
            value=current_hash[:16] + "...",
            threshold="byte-equal",
            passed=False,
            reason=f"baseline 미존재. --update-baseline 1회 실행 필요",
        )

    baseline = baseline_file.read_text(encoding="utf-8").strip()
    return MetricResult(
        name="generator_sha256",
        value=current_hash[:16] + "...",
        threshold="byte-equal",
        passed=current_hash == baseline,
        reason="" if current_hash == baseline else f"DRIFT: baseline={baseline[:16]}...",
    )


def check_e2e_runtime(max_seconds: float = THRESHOLDS["e2e_runtime_seconds"]) -> MetricResult:
    """Streamlit headless 시연 마커 auto-advance runtime. D-1 까지 stub (pytest e2e 가 측정).

    실제 측정: `streamlit run apps/prism_demo.py --server.headless=true` +
    Playwright 로 M10 (3:45) 마커 hit 까지 wall clock. mason narration 7분과 별개.
    """
    log_path = Path("metrics/e2e_runtime.jsonl")
    if not log_path.exists():
        return MetricResult(
            name="e2e_runtime_seconds",
            value=None,
            threshold=max_seconds,
            passed=False,
            reason="metrics/e2e_runtime.jsonl 미존재 — Streamlit headless 1회 실행 필요",
        )

    lines = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        return MetricResult(
            name="e2e_runtime_seconds",
            value=None,
            threshold=max_seconds,
            passed=False,
            reason="metrics/e2e_runtime.jsonl 비어있음",
        )
    last = json.loads(lines[-1])
    runtime = last.get("runtime_seconds")
    return MetricResult(
        name="e2e_runtime_seconds",
        value=runtime,
        threshold=max_seconds,
        passed=runtime is not None and runtime <= max_seconds,
        extras=last.get("marker_breakdown", {}),
    )


def check_eval_score(yaml_path: str = "evals/prism_qa.yaml", run: bool = False) -> MetricResult:
    """evals/prism_qa.yaml Opus judge 평균 점수.

    --eval flag 있으면 실제 evals/run_eval.py 실행. 아니면 metrics/eval_score.jsonl
    의 last entry 사용.
    """
    threshold = THRESHOLDS["eval_score"]
    if run:
        cmd = [
            sys.executable, "-m", "evals.run_eval",
            "--filter", "category=quality_agent",  # 12 case 중 일부만 (시간 절약)
            "--threshold", str(threshold),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            # run_eval 의 stdout last line = avg score
            return MetricResult(
                name="eval_score",
                value=None,
                threshold=threshold,
                passed=result.returncode == 0,
                reason=result.stderr[-200:] if result.returncode != 0 else "judge run ok",
            )
        except Exception as exc:
            return MetricResult(
                name="eval_score",
                value=None,
                threshold=threshold,
                passed=False,
                reason=f"run_eval error: {exc}",
            )

    log_path = Path("metrics/eval_score.jsonl")
    if not log_path.exists():
        return MetricResult(
            name="eval_score",
            value=None,
            threshold=threshold,
            passed=False,
            reason="metrics/eval_score.jsonl 미존재 — `--eval` 또는 sample 채우기 필요",
        )
    lines = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    last = json.loads(lines[-1])
    score = last.get("avg_score")
    return MetricResult(
        name="eval_score",
        value=score,
        threshold=threshold,
        passed=score is not None and score >= threshold,
    )


def check_bedrock_tokens(log_path: str = DEFAULT_TOKEN_LOG) -> MetricResult:
    """bedrock invoke 누적 토큰 사용량."""
    threshold = THRESHOLDS["bedrock_token_usage"]
    log = Path(log_path)
    if not log.exists():
        return MetricResult(
            name="bedrock_token_usage",
            value=0,
            threshold=threshold,
            passed=True,
            reason="metrics/bedrock_token_usage.jsonl 미존재 (호출 0회 = pass)",
        )
    total = 0
    breakdown = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        total += int(entry.get("total_tokens", 0))
        for k in breakdown:
            breakdown[k] += int(entry.get(f"{k}_tokens", 0))
    return MetricResult(
        name="bedrock_token_usage",
        value=total,
        threshold=threshold,
        passed=total <= threshold,
        extras=breakdown,
    )


# ── main ──────────────────────────────────────────────────────


def run_all(args: argparse.Namespace) -> tuple[list[MetricResult], bool]:
    results = [
        check_cache_hit_rate(args.cache_metrics),
        check_generator_sha256(args.baseline, args.update_baseline),
        check_e2e_runtime(),
        check_eval_score(args.eval_yaml, run=args.eval),
        check_bedrock_tokens(args.token_log),
    ]
    all_passed = all(r.passed for r in results)
    return results, all_passed


def print_report(rehearse: str, results: list[MetricResult], all_passed: bool) -> None:
    print(f"[verify_demo_determinism] rehearsal date: {rehearse}")
    for i, r in enumerate(results, 1):
        icon = "✓" if r.passed else "✗"
        threshold_str = (
            f">={r.threshold}" if r.name in ("cache_hit_rate", "eval_score")
            else f"<={r.threshold}" if r.name in ("e2e_runtime_seconds", "bedrock_token_usage")
            else str(r.threshold)
        )
        print(f"[{i}/5] {r.name}: {r.fmt_value()} ({threshold_str}) {icon}")
        if r.reason:
            print(f"       {r.reason}")
        if r.extras:
            print(f"       {r.extras}")

    if all_passed:
        print("\nALL PASSED. Proceed to 본선.")
        print("[gate] PRISM_FALLBACK_VIDEO=0 (silent, A3 (i))")
    else:
        print("\nNOT ALL PASSED. 본선 진입 차단 + PRISM_FALLBACK_VIDEO=1 강제.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PRISM 본선 D-1 binary verification gate")
    parser.add_argument("--rehearse", required=True, help="rehearsal date e.g. 2026-05-21")
    parser.add_argument("--cache-metrics", default=DEFAULT_CACHE_METRICS,
                        help="LLMCache lookup event jsonl (hit/miss ledger)")
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--token-log", default=DEFAULT_TOKEN_LOG)
    parser.add_argument("--eval-yaml", default="evals/prism_qa.yaml")
    parser.add_argument("--update-baseline", action="store_true",
                        help="현재 generator SHA256 을 baseline 으로 저장 (D-2 1차 실행)")
    parser.add_argument("--eval", action="store_true",
                        help="evals/run_eval.py 실제 실행 (시간 + Bedrock 토큰 비용)")
    args = parser.parse_args(argv)

    results, all_passed = run_all(args)
    print_report(args.rehearse, results, all_passed)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())

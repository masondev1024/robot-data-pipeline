"""verify_demo_determinism.py 검증 (ADR v2 §7)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.verify_demo_determinism import (
    MetricResult,
    THRESHOLDS,
    check_bedrock_tokens,
    check_cache_hit_rate,
    check_e2e_runtime,
    check_eval_score,
    check_generator_sha256,
    main,
    run_all,
)


# ── check_cache_hit_rate ───────────────────────────────────────


def test_cache_hit_rate_empty_warmup(tmp_path: Path):
    r = check_cache_hit_rate(str(tmp_path / "absent.jsonl"))
    assert r.passed is False
    assert "미존재" in r.reason


def _write_cache_metrics(path: Path, hits: int, misses: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for i in range(hits):
        lines.append(json.dumps({"event": "hit", "key": f"k{i}"}))
    for i in range(misses):
        lines.append(json.dumps({"event": "miss", "key": f"x{i}"}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_cache_hit_rate_passes_when_above_threshold(tmp_path: Path):
    """99 hit + 1 miss = 0.99 → passed."""
    log = tmp_path / "cache_hit_rate.jsonl"
    _write_cache_metrics(log, hits=99, misses=1)
    r = check_cache_hit_rate(str(log))
    assert r.value == pytest.approx(0.99)
    assert r.passed is True


def test_cache_hit_rate_fails_below_threshold(tmp_path: Path):
    log = tmp_path / "cache_hit_rate.jsonl"
    _write_cache_metrics(log, hits=1, misses=2)
    r = check_cache_hit_rate(str(log))
    assert r.value == pytest.approx(1 / 3)
    assert r.passed is False


def test_cache_hit_rate_ledger_empty(tmp_path: Path):
    log = tmp_path / "cache_hit_rate.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("", encoding="utf-8")
    r = check_cache_hit_rate(str(log))
    assert r.passed is False
    assert "비어있음" in r.reason


# ── check_generator_sha256 ─────────────────────────────────────


def test_generator_sha256_update_baseline(tmp_path: Path):
    baseline = tmp_path / "baseline.txt"
    r = check_generator_sha256(str(baseline), update_baseline=True)
    assert r.passed is True
    assert baseline.exists()
    assert len(baseline.read_text(encoding="utf-8").strip()) == 64  # sha256 hex


def test_generator_sha256_byte_equal(tmp_path: Path):
    baseline = tmp_path / "baseline.txt"
    # 1차: write baseline
    check_generator_sha256(str(baseline), update_baseline=True)
    # 2차: same seed → byte-equal
    r = check_generator_sha256(str(baseline), update_baseline=False)
    assert r.passed is True


def test_generator_sha256_missing_baseline(tmp_path: Path):
    r = check_generator_sha256(str(tmp_path / "absent.txt"), update_baseline=False)
    assert r.passed is False
    assert "baseline 미존재" in r.reason


# ── check_e2e_runtime ──────────────────────────────────────────


def test_e2e_runtime_missing_log(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    r = check_e2e_runtime()
    assert r.passed is False
    assert "metrics/e2e_runtime.jsonl" in r.reason


def test_e2e_runtime_passes_under_threshold(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    log = tmp_path / "metrics" / "e2e_runtime.jsonl"
    log.parent.mkdir()
    log.write_text(json.dumps({"runtime_seconds": 200.0}) + "\n", encoding="utf-8")
    r = check_e2e_runtime()
    assert r.value == 200.0
    assert r.passed is True


def test_e2e_runtime_fails_over_threshold(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    log = tmp_path / "metrics" / "e2e_runtime.jsonl"
    log.parent.mkdir()
    log.write_text(json.dumps({"runtime_seconds": 250.0}) + "\n", encoding="utf-8")
    r = check_e2e_runtime()
    assert r.value == 250.0
    assert r.passed is False


# ── check_eval_score ───────────────────────────────────────────


def test_eval_score_missing_log_no_run(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    r = check_eval_score(run=False)
    assert r.passed is False
    assert "미존재" in r.reason or "필요" in r.reason


def test_eval_score_passes(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    log = tmp_path / "metrics" / "eval_score.jsonl"
    log.parent.mkdir()
    log.write_text(json.dumps({"avg_score": 0.93}) + "\n", encoding="utf-8")
    r = check_eval_score(run=False)
    assert r.value == 0.93
    assert r.passed is True


def test_eval_score_fails_under_threshold(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    log = tmp_path / "metrics" / "eval_score.jsonl"
    log.parent.mkdir()
    log.write_text(json.dumps({"avg_score": 0.85}) + "\n", encoding="utf-8")
    r = check_eval_score(run=False)
    assert r.passed is False


# ── check_bedrock_tokens ───────────────────────────────────────


def test_bedrock_tokens_no_log_passes(tmp_path: Path):
    r = check_bedrock_tokens(str(tmp_path / "absent.jsonl"))
    assert r.value == 0
    assert r.passed is True  # 호출 0회 = under budget


def test_bedrock_tokens_under_budget(tmp_path: Path):
    log = tmp_path / "tokens.jsonl"
    log.write_text(
        json.dumps({"total_tokens": 5000, "input_tokens": 4000, "output_tokens": 1000}) + "\n"
        + json.dumps({"total_tokens": 10000, "input_tokens": 7000, "output_tokens": 3000}) + "\n",
        encoding="utf-8",
    )
    r = check_bedrock_tokens(str(log))
    assert r.value == 15_000
    assert r.passed is True


def test_bedrock_tokens_over_budget(tmp_path: Path):
    log = tmp_path / "tokens.jsonl"
    log.write_text(
        json.dumps({"total_tokens": 35_000}) + "\n",
        encoding="utf-8",
    )
    r = check_bedrock_tokens(str(log))
    assert r.passed is False


# ── main exit code ─────────────────────────────────────────────


def test_main_exit_code_fail_when_baseline_missing(monkeypatch, tmp_path: Path, capsys):
    """전체 main() — 일부 metric fail → exit 1."""
    monkeypatch.chdir(tmp_path)
    code = main([
        "--rehearse", "2026-05-21",
        "--cache-metrics", str(tmp_path / "absent_cache_metrics.jsonl"),
        "--baseline", str(tmp_path / "absent_baseline.txt"),
        "--token-log", str(tmp_path / "absent_tokens.jsonl"),
    ])
    assert code == 1
    out = capsys.readouterr().out
    assert "verify_demo_determinism" in out
    assert "rehearsal date" in out
    assert "NOT ALL PASSED" in out


def test_main_exit_code_pass_with_warmed_baselines(monkeypatch, tmp_path: Path, capsys):
    """모든 metric pass → exit 0."""
    monkeypatch.chdir(tmp_path)

    # warm cache metrics (99 hit + 1 miss)
    cache_metrics = tmp_path / "metrics" / "cache_hit_rate.jsonl"
    _write_cache_metrics(cache_metrics, hits=99, misses=1)

    # warm baseline
    baseline = tmp_path / "baseline.txt"
    check_generator_sha256(str(baseline), update_baseline=True)

    # warm runtime + eval + tokens
    (tmp_path / "metrics" / "e2e_runtime.jsonl").write_text(
        json.dumps({"runtime_seconds": 200.0}) + "\n", encoding="utf-8")
    (tmp_path / "metrics" / "eval_score.jsonl").write_text(
        json.dumps({"avg_score": 0.95}) + "\n", encoding="utf-8")
    (tmp_path / "metrics" / "tokens.jsonl").write_text(
        json.dumps({"total_tokens": 25_000}) + "\n", encoding="utf-8")

    code = main([
        "--rehearse", "2026-05-21",
        "--cache-metrics", str(cache_metrics),
        "--baseline", str(baseline),
        "--token-log", str(tmp_path / "metrics" / "tokens.jsonl"),
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "ALL PASSED" in out
    assert "PRISM_FALLBACK_VIDEO=0" in out

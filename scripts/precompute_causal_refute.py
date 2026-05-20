"""사전 계산 CLI: DoWhy 6-Node DAG refute_estimate → assets/causal_refute_v2.json.

Usage:
    python -m scripts.precompute_causal_refute --seed 2026 --out assets/causal_refute_v2.json
"""

from __future__ import annotations

import argparse
import sys

from src.orchestration.causal_dag import (
    build_dag,
    compute_sigma_max,
    fit_causal_model,
    narrative_kr_for_sigma_max,
    serialize_refute_data,
    synthetic_sensor_data,
    _collect_raw_print,
)
from src.orchestration.causal_card import label_for_sigma_max


def main() -> None:
    parser = argparse.ArgumentParser(description="사전 계산: DoWhy refute_estimate → JSON")
    parser.add_argument("--seed", type=int, default=2026, help="np.random seed (default: 2026)")
    parser.add_argument(
        "--out",
        default="assets/causal_refute_v2.json",
        help="출력 JSON 경로 (default: assets/causal_refute_v2.json)",
    )
    parser.add_argument(
        "--num-simulations",
        type=int,
        default=100,
        help="placebo/random_cc/data_subset refuter 시뮬레이션 수 (default: 100)",
    )
    args = parser.parse_args()

    print(f"[precompute] seed={args.seed}, num_simulations={args.num_simulations}, out={args.out}")

    dag = build_dag()
    df = synthetic_sensor_data(n=5_000, seed=args.seed)
    model = fit_causal_model(df, dag)

    print("[precompute] compute_sigma_max 실행 중... (약 1-2분 소요)")
    sigma_max, summary = compute_sigma_max(model, num_simulations=args.num_simulations, seed=args.seed)

    print("[precompute] raw_print 수집 중... (4 refuter, σ_max=%.4f 포함)" % sigma_max)
    raw_print = _collect_raw_print(
        model, num_simulations=args.num_simulations, seed=args.seed, sigma_max=sigma_max,
    )

    serialize_refute_data(sigma_max=sigma_max, summary=summary, raw_print=raw_print, path=args.out)

    label = label_for_sigma_max(sigma_max)
    icon = {"robust": "✅", "moderate": "⚠️", "fragile": "❌"}[label]

    print(f"\n{icon}  sigma_max = {sigma_max:.4f}  [{label}]")
    print(f"   placebo p_value           = {summary['placebo']['p_value']}")
    print(f"   random_common_cause       = {summary['random_common_cause']['new_effect']:.4f}")
    print(f"   unobserved_common_cause   = {summary['unobserved_common_cause']['sigma_max']:.4f}")
    print(f"   data_subset new_effect    = {summary['data_subset']['new_effect']:.4f}")
    print(f"\n[precompute] 저장 완료 → {args.out}")


if __name__ == "__main__":
    main()

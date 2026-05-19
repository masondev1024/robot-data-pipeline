"""CNC 단일 머신 라이브 센서 generator (PRISM 본선 D-3).

결정성: seed=2026 고정 → 동일 t 입력 → 동일 출력 (시연 verify gate 통과).
schema: CNC_COLS 호환 (ts, machine_id, tool_age, spindle_rpm, coolant_temp,
                       vibration_xyz, thermal_drift, dimension_dev, defect)
causal structure: causal_dag.py synthetic_sensor_data() 와 동일 계수.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np


class CNCStreamGenerator:
    """CNC 1 머신 실시간 센서 샘플 생성기.

    Args:
        machine_id: 머신 식별자 (예: "CNC-01")
        seed: numpy 랜덤 시드 — 결정성 보장 (default 2026)
    """

    # 물리 상수
    _SPINDLE_BASE = 8500.0
    _SPINDLE_NOISE = 50.0
    _COOLANT_NORMAL = 22.0
    _COOLANT_FAULT = 28.0
    _FAULT_START_S = 30.0
    _FAULT_END_S = 60.0

    # causal_dag.py 와 동일 계수 (standardised)
    _VIB_TOOL_COEF = 0.4
    _VIB_SPINDLE_COEF = 0.6
    _VIB_NOISE_STD = 0.3
    _THERM_COOLANT_COEF = 0.7
    _THERM_NOISE_STD = 0.3
    _DIM_VIB_COEF = 0.5
    _DIM_THERM_COEF = 0.5
    _DIM_NOISE_STD = 0.2

    def __init__(self, machine_id: str = "CNC-01", seed: int = 2026) -> None:
        self.machine_id = machine_id
        self._seed = seed
        self._rng = np.random.default_rng(seed)

    def next_sample(self, t_seconds: float) -> dict[str, Any]:
        """t_seconds 기준 CNC 센서 샘플 1개 생성.

        결정성: 동일 t_seconds + 동일 seed → 동일 출력.
        numpy Generator 는 call order 에 따라 결과가 달라지므로
        각 호출에서 t 기반 독립 rng 를 생성해 결정성을 보장한다.

        Returns:
            CNC_COLS 호환 dict (ts 는 현재 UTC)
        """
        # t 기반 per-call rng — seed(t) 로 각 t 의 출력이 독립적으로 결정됨
        rng = np.random.default_rng([self._seed, int(t_seconds * 1000) & 0xFFFFFFFF])

        # tool_age: 시간 누적 (초 → 분 환산 *0.01)
        tool_age = t_seconds * 0.01

        # spindle_rpm: 8500 ± 50 noise
        spindle_rpm = self._SPINDLE_BASE + rng.normal(0, self._SPINDLE_NOISE)

        # coolant_temp: fault phase (30-60s) 28°C, 그 외 22°C
        if self._FAULT_START_S <= t_seconds < self._FAULT_END_S:
            coolant_temp = self._COOLANT_FAULT + rng.normal(0, 0.5)
        else:
            coolant_temp = self._COOLANT_NORMAL + rng.normal(0, 0.5)

        # 정규화 (causal_dag.py 의 표준화 변수 근사)
        tool_age_norm = (tool_age - 0.3) / 0.3  # 30s 기준 normalise
        spindle_norm = (spindle_rpm - self._SPINDLE_BASE) / self._SPINDLE_NOISE
        coolant_norm = (coolant_temp - self._COOLANT_NORMAL) / 3.0

        # causal structure (causal_dag.py 동일 계수)
        vibration_xyz = (
            self._VIB_TOOL_COEF * tool_age_norm
            + self._VIB_SPINDLE_COEF * spindle_norm
            + rng.normal(0, self._VIB_NOISE_STD)
        )
        thermal_drift = (
            self._THERM_COOLANT_COEF * coolant_norm
            + rng.normal(0, self._THERM_NOISE_STD)
        )
        dimension_dev = (
            self._DIM_VIB_COEF * vibration_xyz
            + self._DIM_THERM_COEF * thermal_drift
            + rng.normal(0, self._DIM_NOISE_STD)
        )

        # defect: Bernoulli(sigmoid(2 * dimension_dev))
        defect_prob = 1.0 / (1.0 + np.exp(-2.0 * dimension_dev))
        defect = bool(rng.random() < defect_prob)

        return {
            "ts": datetime.now(tz=timezone.utc).replace(tzinfo=None),
            "machine_id": self.machine_id,
            "tool_age": float(tool_age),
            "spindle_rpm": float(spindle_rpm),
            "coolant_temp": float(coolant_temp),
            "vibration_xyz": float(vibration_xyz),
            "thermal_drift": float(thermal_drift),
            "dimension_dev": float(dimension_dev),
            "defect": defect,
        }

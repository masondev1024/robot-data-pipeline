"""Fault state machine for realistic motor_temp episodes.

기존의 단발 spike(`is_faulty && random<0.05`)를 NORMAL → RAMPING → OVERHEATED
→ COOLING 라이프사이클로 교체. STUCK 은 별도 sub-state로, 일정 tick 동안 motor_temp
가 freeze 된다 (sensor freeze fault simulation).

Pure 함수 — RNG는 caller 가 random.Random 인스턴스로 주입한다 (재현 가능).
"""
from enum import Enum
from typing import Tuple


class Phase(str, Enum):
    NORMAL = "normal"
    RAMPING = "ramping"
    OVERHEATED = "overheated"
    COOLING = "cooling"
    STUCK = "stuck"


def init_state() -> dict:
    return {
        "phase": Phase.NORMAL,
        "ticks_remaining": 0,
        "peak_delta": 0.0,
        "ramp_total": 0,
        "cool_total": 0,
    }


def advance_phase(
    state: dict,
    profile: dict,
    params: dict,
    force_anomaly: bool,
    rng,
) -> Tuple[dict, float, bool]:
    """한 tick 분 state 전이 + 적용할 motor_temp delta + stuck 여부 반환.

    Returns:
        (new_state, temp_delta, is_stuck)
        - new_state: 갱신된 state dict (caller 가 다음 tick에 그대로 넘김)
        - temp_delta: base motor_temp 위에 더할 °C (NORMAL/STUCK 이면 0)
        - is_stuck: True 면 caller 가 motor_temp 를 직전 값으로 freeze
    """
    phase = state["phase"]
    ticks_remaining = state["ticks_remaining"]
    peak_delta = state["peak_delta"]

    # force window가 활성화되면 어느 phase 에서든 OVERHEATED 로 강제 (시연용)
    if force_anomaly:
        forced_peak = peak_delta if peak_delta > 0 else float(params["fault_peak_temp_delta"])
        new_state = {
            "phase": Phase.OVERHEATED,
            "ticks_remaining": int(params["fault_peak_ticks"]),
            "peak_delta": forced_peak,
            "ramp_total": int(params["fault_ramp_ticks"]),
            "cool_total": int(params["fault_cooldown_ticks"]),
        }
        delta = forced_peak + rng.gauss(0, 1.0)
        return new_state, delta, False

    if phase == Phase.NORMAL:
        is_faulty = bool(profile.get("is_faulty"))
        if is_faulty and rng.random() < float(params["fault_entry_prob"]):
            # RAMPING 진입: peak_delta 결정 (기본값 ± 노이즈)
            base_peak = float(params["fault_peak_temp_delta"])
            peak = base_peak + rng.uniform(-3.0, 3.0)
            ramp_ticks = int(params["fault_ramp_ticks"])
            new_state = {
                "phase": Phase.RAMPING,
                "ticks_remaining": ramp_ticks,
                "peak_delta": peak,
                "ramp_total": ramp_ticks,
                "cool_total": int(params["fault_cooldown_ticks"]),
            }
            # 첫 ramp tick 부터 약간의 delta 시작
            progress = 1.0 / ramp_ticks if ramp_ticks > 0 else 1.0
            return new_state, peak * progress, False

        if is_faulty and rng.random() < float(params["stuck_entry_prob"]):
            stuck_ticks = rng.randint(int(params["stuck_min_ticks"]), int(params["stuck_max_ticks"]))
            new_state = {
                "phase": Phase.STUCK,
                "ticks_remaining": stuck_ticks,
                "peak_delta": 0.0,
                "ramp_total": 0,
                "cool_total": 0,
            }
            return new_state, 0.0, True

        return state, 0.0, False

    if phase == Phase.RAMPING:
        new_remaining = ticks_remaining - 1
        ramp_total = state.get("ramp_total", 1) or 1
        # progress = 1 - (remaining / total) → 점점 1에 가까워짐
        progress = 1.0 - max(new_remaining, 0) / ramp_total
        delta = peak_delta * progress
        if new_remaining <= 0:
            new_state = {
                **state,
                "phase": Phase.OVERHEATED,
                "ticks_remaining": int(params["fault_peak_ticks"]),
            }
            # 마지막 tick은 거의 peak — 약간의 노이즈 추가
            return new_state, peak_delta + rng.gauss(0, 1.0), False
        new_state = {**state, "ticks_remaining": new_remaining}
        return new_state, delta, False

    if phase == Phase.OVERHEATED:
        new_remaining = ticks_remaining - 1
        delta = peak_delta + rng.gauss(0, 1.5)
        if new_remaining <= 0:
            cool_total = int(params["fault_cooldown_ticks"])
            new_state = {
                **state,
                "phase": Phase.COOLING,
                "ticks_remaining": cool_total,
                "cool_total": cool_total,
            }
            return new_state, delta, False
        new_state = {**state, "ticks_remaining": new_remaining}
        return new_state, delta, False

    if phase == Phase.COOLING:
        new_remaining = ticks_remaining - 1
        cool_total = state.get("cool_total", 1) or 1
        # ratio = remaining / total → 1에서 0으로 감소
        ratio = max(new_remaining, 0) / cool_total
        delta = peak_delta * ratio
        if new_remaining <= 0:
            return init_state(), 0.0, False
        new_state = {**state, "ticks_remaining": new_remaining}
        return new_state, delta, False

    if phase == Phase.STUCK:
        new_remaining = ticks_remaining - 1
        if new_remaining <= 0:
            return init_state(), 0.0, False
        new_state = {**state, "ticks_remaining": new_remaining}
        return new_state, 0.0, True

    # 안전: 알 수 없는 phase → reset
    return init_state(), 0.0, False

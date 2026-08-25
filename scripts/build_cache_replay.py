"""PRISM cache_replay.jsonl 재생성 스크립트 (D-3, 2026-05-19).

assets/cache_replay.jsonl 을 3 scenario × 4 candidate × 4 agent + 3 supervisor = 51 entries 로 재생성.
cache_key 는 Supervisor._build_user_prompt 와 정확히 동일한 user_prompt 를 사용.

실행:
    PYTHONHASHSEED=2026 python3 scripts/build_cache_replay.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path 에 추가
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from apps.prism_demo import _SCENARIOS, _CANDIDATE_ACTIONS, _MARKER_TO_SCENARIO  # noqa: E402
from src.orchestration.agents.quality import SYSTEM_PROMPT as Q_PROMPT  # noqa: E402
from src.orchestration.agents.safety import SYSTEM_PROMPT as S_PROMPT  # noqa: E402
from src.orchestration.agents.equipment import SYSTEM_PROMPT as E_PROMPT  # noqa: E402
from src.orchestration.agents.production import SYSTEM_PROMPT as P_PROMPT  # noqa: E402
from src.orchestration.supervisor import SUPERVISOR_SYSTEM_PROMPT, Supervisor  # noqa: E402
from src.orchestration.llm_cache import cache_key  # noqa: E402

# ── 출력 파일 ────────────────────────────────────────────────────────────────────
OUTPUT_PATH = _ROOT / "assets" / "cache_replay.jsonl"

# ── 모델 ID ─────────────────────────────────────────────────────────────────────
HAIKU_MODEL = "apac.anthropic.claude-3-haiku-20240307-v1:0"
SONNET_MODEL = "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"

# ── 시나리오 순서 (test_cache_replay.py 와 정합) ──────────────────────────────────
SCENARIO_ORDER = ["normal", "fault", "recover"]

# ── candidate action 순서 (test_cache_replay.py line 145 와 정합) ─────────────────
# test 에서: ["continue", "halt", "throttle_50pct", "schedule_maintenance"]
ACTION_ORDER = ["continue", "halt", "throttle_50pct", "schedule_maintenance"]

# ── 도메인 응답 매트릭스 ──────────────────────────────────────────────────────────
# 구조: RESPONSES[scenario][action][agent] = dict (Pydantic schema 통과 JSON)

RESPONSES: dict[str, dict[str, dict[str, dict]]] = {
    # ────────────────────────────────────────────────────────────
    # normal: motor_temp 85°C, defect_signal 0.05
    #   net_value(continue) = 247*4*18000 - 0.05*50000*247*4 - 0.02*100M - 0 = 17,784,000-2,470,000-2,000,000 = 13,314,000
    # ────────────────────────────────────────────────────────────
    "normal": {
        "continue": {
            "quality": {
                "numeric": {"defect_prob": 0.05, "top_failure_type": "NONE"},
                "narrative_kr": "[ROBOT-00018] motor_temp 85°C, defect_signal 0.05 — 정상 범위. "
                                "NONE 분류. continue 채택 시 결함 확률 5% 미만 유지.",
            },
            "safety": {
                "numeric": {"sop_violation": False, "estop_required": False, "safety_violation_prob": 0.02},
                "narrative_kr": "[ROBOT-00018] motor_temp 85°C — SOP 임계(100°C) 미달. "
                                "안전 위반 확률 2%, E-stop 불필요. continue 안전.",
            },
            "equipment": {
                "numeric": {"rul_hours": 240.0, "isolation_forest_score": 0.12},
                "narrative_kr": "[ROBOT-00018] tool_age 120h, vibration 0.8 — RUL 240h. "
                                "IsoForest +0.12 (안정 정상). continue 채택 시 설비 여유 충분.",
            },
            "production": {
                "numeric": {"throughput_uph": 247.0, "schedule_feasible": True, "lp_solution_id": "lp_continue_a1b2"},
                "narrative_kr": "[ROBOT-00018] 정상 가동. 표준 UPH 247 달성. "
                                "LP 솔루션 lp_continue_a1b2 — 스케줄 실행 가능.",
            },
        },
        "halt": {
            "quality": {
                "numeric": {"defect_prob": 0.0, "top_failure_type": "NONE"},
                "narrative_kr": "[ROBOT-00018] halt 채택 시 생산 중단 — 결함 발생 없음. "
                                "NONE 분류. 정상 상태에서의 불필요 정지.",
            },
            "safety": {
                "numeric": {"sop_violation": False, "estop_required": False, "safety_violation_prob": 0.0},
                "narrative_kr": "[ROBOT-00018] halt 채택 — 안전 위반 없음. "
                                "정상 상태에서의 정지로 안전 위반 확률 0%.",
            },
            "equipment": {
                "numeric": {"rul_hours": 240.0, "isolation_forest_score": 0.12},
                "narrative_kr": "[ROBOT-00018] halt 채택 — 설비 정지로 RUL 보존. "
                                "IsoForest +0.12 정상. 불필요 정지로 생산 손실만 발생.",
            },
            "production": {
                "numeric": {"throughput_uph": 0.0, "schedule_feasible": False, "lp_solution_id": "lp_halt_e5f6"},
                "narrative_kr": "[ROBOT-00018] halt — UPH 0. 정상 상태 불필요 정지. "
                                "LP lp_halt_e5f6 — 스케줄 불가. 생산 손실 발생.",
            },
        },
        "throttle_50pct": {
            "quality": {
                "numeric": {"defect_prob": 0.03, "top_failure_type": "NONE"},
                "narrative_kr": "[ROBOT-00018] throttle 50% — spindle_rpm 감속. "
                                "결함 확률 3%로 소폭 감소. NONE 분류.",
            },
            "safety": {
                "numeric": {"sop_violation": False, "estop_required": False, "safety_violation_prob": 0.01},
                "narrative_kr": "[ROBOT-00018] throttle 50% — motor_temp 감소 예상. "
                                "안전 위반 확률 1%. SOP 위반 없음.",
            },
            "equipment": {
                "numeric": {"rul_hours": 240.0, "isolation_forest_score": 0.15},
                "narrative_kr": "[ROBOT-00018] throttle 50% — 부하 감소로 RUL 240h 유지. "
                                "IsoForest +0.15 안정. 불필요 감속.",
            },
            "production": {
                "numeric": {"throughput_uph": 124.0, "schedule_feasible": False, "lp_solution_id": "lp_throttle50_c3d4"},
                "narrative_kr": "[ROBOT-00018] throttle 50% — UPH 124 (247×0.5). "
                                "LP lp_throttle50_c3d4 — 스케줄 불가 (UPH<200).",
            },
        },
        "schedule_maintenance": {
            "quality": {
                "numeric": {"defect_prob": 0.01, "top_failure_type": "NONE"},
                "narrative_kr": "[ROBOT-00018] schedule_maintenance — 생산 중단. "
                                "결함 발생 없음. NONE 분류. 정상 상태에서 불필요 정비.",
            },
            "safety": {
                "numeric": {"sop_violation": False, "estop_required": False, "safety_violation_prob": 0.01},
                "narrative_kr": "[ROBOT-00018] schedule_maintenance — 안전 위반 없음. "
                                "정기 정비 채택. 안전 위반 확률 1%.",
            },
            "equipment": {
                "numeric": {"rul_hours": 240.0, "isolation_forest_score": 0.15},
                "narrative_kr": "[ROBOT-00018] schedule_maintenance — 예방 정비로 RUL 240h 보존. "
                                "IsoForest +0.15. 정상 상태 불필요 정비.",
            },
            "production": {
                "numeric": {"throughput_uph": 0.0, "schedule_feasible": False, "lp_solution_id": "lp_maint_f7g8"},
                "narrative_kr": "[ROBOT-00018] schedule_maintenance — UPH 0 (horizon 내 정비). "
                                "LP lp_maint_f7g8 — 스케줄 불가. 불필요 생산 손실.",
            },
        },
    },
    # ────────────────────────────────────────────────────────────
    # fault: motor_temp 105°C, defect_signal 0.60
    #   net_value(continue)=-52,220,000 / throttle=-8,512,000 / maintenance=-1,000,000 / halt=0
    #   → halt 가 net_value 최고 (test_fault_scenario_supervisor_recommends_halt 통과)
    # ────────────────────────────────────────────────────────────
    "fault": {
        "continue": {
            "quality": {
                "numeric": {"defect_prob": 0.62, "top_failure_type": "HDF"},
                "narrative_kr": "[ROBOT-00018] motor_temp 105°C, defect_signal 0.60 — HDF 위험. "
                                "결함 확률 62%. continue 채택 시 고결함 지속.",
            },
            "safety": {
                "numeric": {"sop_violation": True, "estop_required": False, "safety_violation_prob": 0.40},
                "narrative_kr": "[ROBOT-00018] motor_temp 105°C — SOP 명백 위반. "
                                "안전 위반 확률 40%, sop_violation=True. E-stop 미발동(prob<0.5).",
            },
            "equipment": {
                "numeric": {"rul_hours": 18.0, "isolation_forest_score": -0.34},
                "narrative_kr": "[ROBOT-00018] HDF 고장 위험. RUL 18h — 24h 내 고장 임박. "
                                "IsoForest -0.34 (명확한 anomaly). continue 채택 시 조기 고장 위험.",
            },
            "production": {
                "numeric": {"throughput_uph": 235.0, "schedule_feasible": True, "lp_solution_id": "lp_continue_fault_a1b2"},
                "narrative_kr": "[ROBOT-00018] fault 상태 continue — UPH 235 (소폭 저하). "
                                "LP lp_continue_fault_a1b2 — 스케줄 가능(UPH≥200).",
            },
        },
        "halt": {
            "quality": {
                "numeric": {"defect_prob": 0.0, "top_failure_type": "NONE"},
                "narrative_kr": "[ROBOT-00018] halt 채택 — 생산 중단으로 결함 0. "
                                "NONE 분류. 설비 보호 최우선.",
            },
            "safety": {
                "numeric": {"sop_violation": False, "estop_required": False, "safety_violation_prob": 0.0},
                "narrative_kr": "[ROBOT-00018] halt 채택 — 즉시 정지로 안전 위반 0. "
                                "motor_temp 하강 예상. E-stop 불필요.",
            },
            "equipment": {
                "numeric": {"rul_hours": 180.0, "isolation_forest_score": -0.05},
                "narrative_kr": "[ROBOT-00018] halt 후 정비 — RUL 180h 회복 예상. "
                                "IsoForest -0.05 (경계 → 정상 회복). 설비 수명 보전.",
            },
            "production": {
                "numeric": {"throughput_uph": 0.0, "schedule_feasible": False, "lp_solution_id": "lp_halt_fault_e5f6"},
                "narrative_kr": "[ROBOT-00018] halt — UPH 0. 생산 중단. "
                                "LP lp_halt_fault_e5f6 — 스케줄 불가. 안전·설비 보호 우선.",
            },
        },
        "throttle_50pct": {
            "quality": {
                "numeric": {"defect_prob": 0.30, "top_failure_type": "HDF"},
                "narrative_kr": "[ROBOT-00018] throttle 50% — spindle_rpm 감속으로 결함 62%→30% 감소. "
                                "HDF 위험 지속. 부분 완화.",
            },
            "safety": {
                "numeric": {"sop_violation": False, "estop_required": False, "safety_violation_prob": 0.10},
                "narrative_kr": "[ROBOT-00018] throttle 50% — 부하 감소로 motor_temp 하강. "
                                "안전 위반 확률 10%. SOP 위반 해소.",
            },
            "equipment": {
                "numeric": {"rul_hours": 72.0, "isolation_forest_score": -0.15},
                "narrative_kr": "[ROBOT-00018] throttle 50% — 부하 감소로 RUL 72h 회복. "
                                "IsoForest -0.15 (경계 영역). 단기 완화 효과.",
            },
            "production": {
                "numeric": {"throughput_uph": 124.0, "schedule_feasible": False, "lp_solution_id": "lp_throttle50_fault_c3d4"},
                "narrative_kr": "[ROBOT-00018] throttle 50% — UPH 124 (247×0.5). "
                                "LP lp_throttle50_fault_c3d4 — 스케줄 불가(UPH<200).",
            },
        },
        "schedule_maintenance": {
            "quality": {
                "numeric": {"defect_prob": 0.05, "top_failure_type": "NONE"},
                "narrative_kr": "[ROBOT-00018] schedule_maintenance — 정비 후 결함 5%로 회복. "
                                "NONE 분류. HDF 원인 제거.",
            },
            "safety": {
                "numeric": {"sop_violation": False, "estop_required": False, "safety_violation_prob": 0.01},
                "narrative_kr": "[ROBOT-00018] schedule_maintenance — 정비 채택. "
                                "안전 위반 확률 1%. SOP 위반 해소.",
            },
            "equipment": {
                "numeric": {"rul_hours": 240.0, "isolation_forest_score": 0.05},
                "narrative_kr": "[ROBOT-00018] schedule_maintenance — 정비 후 RUL 240h 완전 복원. "
                                "IsoForest +0.05 (정상). 설비 수명 보전.",
            },
            "production": {
                "numeric": {"throughput_uph": 0.0, "schedule_feasible": False, "lp_solution_id": "lp_maint_fault_f7g8"},
                "narrative_kr": "[ROBOT-00018] schedule_maintenance — UPH 0 (horizon 내 정비). "
                                "LP lp_maint_fault_f7g8 — 스케줄 불가. 정비 후 생산 재개.",
            },
        },
    },
    # ────────────────────────────────────────────────────────────
    # recover: motor_temp 92°C, defect_signal 0.18
    #   net_value(continue) = 247*4*18000 - 0.18*50000*247*4 - 0.05*100M - 0 = 17,784,000-8,892,000-5,000,000 = 3,892,000
    # ────────────────────────────────────────────────────────────
    "recover": {
        "continue": {
            "quality": {
                "numeric": {"defect_prob": 0.18, "top_failure_type": "NONE"},
                "narrative_kr": "[ROBOT-00018] 회복 중 motor_temp 92°C — 결함 확률 18%로 감소. "
                                "NONE 분류. 재학습 모델 적용 후 0.62→0.18 개선.",
            },
            "safety": {
                "numeric": {"sop_violation": False, "estop_required": False, "safety_violation_prob": 0.05},
                "narrative_kr": "[ROBOT-00018] motor_temp 92°C — SOP 임계(100°C) 미달. "
                                "안전 위반 확률 5%. continue 가능.",
            },
            "equipment": {
                "numeric": {"rul_hours": 180.0, "isolation_forest_score": -0.05},
                "narrative_kr": "[ROBOT-00018] 회복 중 RUL 180h. IsoForest -0.05 (경계 → 정상 회복). "
                                "tool_age 185h 누적. continue 채택 시 생산 재개.",
            },
            "production": {
                "numeric": {"throughput_uph": 247.0, "schedule_feasible": True, "lp_solution_id": "lp_continue_recover_a1b2"},
                "narrative_kr": "[ROBOT-00018] 회복 후 표준 UPH 247 복원. "
                                "LP lp_continue_recover_a1b2 — 스케줄 실행 가능. OEE +32%p 달성.",
            },
        },
        "halt": {
            "quality": {
                "numeric": {"defect_prob": 0.0, "top_failure_type": "NONE"},
                "narrative_kr": "[ROBOT-00018] halt — 회복 중 불필요 정지. 결함 0. "
                                "NONE. 회복 시점 생산 기회 손실.",
            },
            "safety": {
                "numeric": {"sop_violation": False, "estop_required": False, "safety_violation_prob": 0.0},
                "narrative_kr": "[ROBOT-00018] halt — 안전 위반 없음. "
                                "회복 중 불필요 정지로 생산 손실만 발생.",
            },
            "equipment": {
                "numeric": {"rul_hours": 180.0, "isolation_forest_score": -0.05},
                "narrative_kr": "[ROBOT-00018] halt — 회복 중 정지로 RUL 180h 보존. "
                                "IsoForest -0.05. 불필요 정지.",
            },
            "production": {
                "numeric": {"throughput_uph": 0.0, "schedule_feasible": False, "lp_solution_id": "lp_halt_recover_e5f6"},
                "narrative_kr": "[ROBOT-00018] halt — UPH 0. 회복 시점 불필요 정지. "
                                "LP lp_halt_recover_e5f6 — 스케줄 불가.",
            },
        },
        "throttle_50pct": {
            "quality": {
                "numeric": {"defect_prob": 0.10, "top_failure_type": "NONE"},
                "narrative_kr": "[ROBOT-00018] throttle 50% — 회복 중 감속. 결함 10%. "
                                "NONE 분류. 과도한 보수 조치.",
            },
            "safety": {
                "numeric": {"sop_violation": False, "estop_required": False, "safety_violation_prob": 0.02},
                "narrative_kr": "[ROBOT-00018] throttle 50% — 부하 감소. 안전 위반 확률 2%. "
                                "SOP 위반 없음. 회복 중 과도 감속.",
            },
            "equipment": {
                "numeric": {"rul_hours": 180.0, "isolation_forest_score": 0.05},
                "narrative_kr": "[ROBOT-00018] throttle 50% — RUL 180h 유지. "
                                "IsoForest +0.05 정상. 회복 중 불필요 감속.",
            },
            "production": {
                "numeric": {"throughput_uph": 124.0, "schedule_feasible": False, "lp_solution_id": "lp_throttle50_recover_c3d4"},
                "narrative_kr": "[ROBOT-00018] throttle 50% — UPH 124. "
                                "LP lp_throttle50_recover_c3d4 — 스케줄 불가(UPH<200).",
            },
        },
        "schedule_maintenance": {
            "quality": {
                "numeric": {"defect_prob": 0.05, "top_failure_type": "NONE"},
                "narrative_kr": "[ROBOT-00018] schedule_maintenance — 회복 후 예방 정비. "
                                "결함 5%. NONE. 회복 시점 생산 기회 손실.",
            },
            "safety": {
                "numeric": {"sop_violation": False, "estop_required": False, "safety_violation_prob": 0.01},
                "narrative_kr": "[ROBOT-00018] schedule_maintenance — 안전 위반 1%. "
                                "회복 시점 예방 정비. 불필요 생산 손실.",
            },
            "equipment": {
                "numeric": {"rul_hours": 240.0, "isolation_forest_score": 0.10},
                "narrative_kr": "[ROBOT-00018] schedule_maintenance — 예방 정비로 RUL 240h 복원. "
                                "IsoForest +0.10 정상. 회복 후 설비 완전 회복.",
            },
            "production": {
                "numeric": {"throughput_uph": 0.0, "schedule_feasible": False, "lp_solution_id": "lp_maint_recover_f7g8"},
                "narrative_kr": "[ROBOT-00018] schedule_maintenance — UPH 0. "
                                "LP lp_maint_recover_f7g8 — 스케줄 불가. 회복 시점 불필요 정비.",
            },
        },
    },
}

# ── Supervisor 응답 매트릭스 ──────────────────────────────────────────────────────
# compute_net_value_KRW 기반 (unit_revenue=18,000 KRW, schema.py 기준)
# normal:  continue net=13,314,000 (1위)
# fault:   halt net=0 (1위), schedule_maintenance=-1,000,000 (2위), throttle=-8,512,000 (3위), continue=-52,220,000 (4위)
# recover: continue net=3,892,000 (1위)

SUPERVISOR_RESPONSES: dict[str, dict] = {
    "normal": {
        "decision": {
            "action_id": "continue",
            "net_value_KRW": 13_314_000.0,
            "alternatives": [
                {"action_id": "throttle_50pct",        "net_value_KRW": -1_116_000.0, "rank": 2},
                {"action_id": "schedule_maintenance",  "net_value_KRW": -1_000_000.0, "rank": 3},
                {"action_id": "halt",                  "net_value_KRW":          0.0, "rank": 4},
            ],
            "rationale_kr": (
                "continue 채택 — net_value ₩13,314,000 (2순위 대비 +₩14,430,000). "
                "정상 상태, UPH 247 풀가동. 결함 손실 미미, 안전 위반 없음."
            ),
            "tradeoff_breakdown": {
                "throughput_gain_KRW":  17_784_000.0,
                "defect_loss_KRW":      -2_470_000.0,
                "safety_loss_KRW":      -2_000_000.0,
                "rul_loss_KRW":                 0.0,
            },
        }
    },
    "fault": {
        "decision": {
            "action_id": "halt",
            "net_value_KRW": 0.0,
            "alternatives": [
                {"action_id": "schedule_maintenance",  "net_value_KRW":  -1_000_000.0, "rank": 2},
                {"action_id": "throttle_50pct",        "net_value_KRW":  -8_512_000.0, "rank": 3},
                {"action_id": "continue",              "net_value_KRW": -52_220_000.0, "rank": 4},
            ],
            "rationale_kr": (
                "halt 채택 — net_value ₩0 (2순위 대비 +₩1,000,000). "
                "motor_temp 105°C, safety_loss 4천만. continue 채택 시 손실 5.2억. "
                "β 슬라이더 증가 없이도 halt 1위."
            ),
            "tradeoff_breakdown": {
                "throughput_gain_KRW":  0.0,
                "defect_loss_KRW":      0.0,
                "safety_loss_KRW":      0.0,
                "rul_loss_KRW":         0.0,
            },
        }
    },
    "recover": {
        "decision": {
            "action_id": "continue",
            "net_value_KRW": 3_892_000.0,
            "alternatives": [
                {"action_id": "halt",                  "net_value_KRW":          0.0, "rank": 2},
                {"action_id": "throttle_50pct",        "net_value_KRW":  -1_756_000.0, "rank": 3},
                {"action_id": "schedule_maintenance",  "net_value_KRW":  -1_000_000.0, "rank": 4},
            ],
            "rationale_kr": (
                "continue 채택 — net_value ₩3,892,000 (2순위 대비 +₩3,892,000). "
                "회복 후 UPH 247 복원. 결함 18%, 안전 위반 5%. OEE +32%p 달성."
            ),
            "tradeoff_breakdown": {
                "throughput_gain_KRW":  17_784_000.0,
                "defect_loss_KRW":      -8_892_000.0,
                "safety_loss_KRW":      -5_000_000.0,
                "rul_loss_KRW":                 0.0,
            },
        }
    },
}


# Supervisor.staticmethod 직접 alias — single source of truth (D-3 code review M5).
# 별도 정의 시 1글자 drift → 51 entries 전량 cache miss → 시연 fallback_video 회귀 위험.
_build_user_prompt = Supervisor._build_user_prompt


def _build_supervisor_user_prompt(scenario_context: dict) -> str:
    """Supervisor negotiate 호출 시 사용하는 user_prompt (검증용)."""
    return (
        f"<scenario>\n{scenario_context}\n</scenario>\n"
        "위 시나리오의 4 Agent 출력을 바탕으로 net_value 최대 action 을 선택하고 SupervisorOutput JSON 을 반환하라."
    )


def build_entries() -> list[dict]:
    """51 entries 생성 (48 domain-agent + 3 supervisor).

    순서:
        normal × [continue, halt, throttle_50pct, schedule_maintenance] × [quality, safety, equipment, production]
        fault  × 동일
        recover × 동일
        supervisor × [normal, fault, recover]
    """
    entries = []

    # ── 48 domain-agent entries ──────────────────────────────────
    agent_prompts = [
        ("quality",    HAIKU_MODEL, Q_PROMPT),
        ("safety",     HAIKU_MODEL, S_PROMPT),
        ("equipment",  HAIKU_MODEL, E_PROMPT),
        ("production", HAIKU_MODEL, P_PROMPT),
    ]

    for scenario_id in SCENARIO_ORDER:
        scenario_context = _SCENARIOS[scenario_id]
        for action_id in ACTION_ORDER:
            user_prompt = _build_user_prompt(action_id, scenario_context)
            for agent_name, model_id, system_prompt in agent_prompts:
                response_dict = RESPONSES[scenario_id][action_id][agent_name]
                response_str = json.dumps(response_dict, ensure_ascii=False)
                # invoke() passes context=scenario_context as tool_state → must match
                key = cache_key(model_id, system_prompt, user_prompt, tool_state=scenario_context)
                entries.append({"key": key, "response": response_str})

    # ── 3 supervisor entries ─────────────────────────────────────
    for scenario_id in SCENARIO_ORDER:
        scenario_context = _SCENARIOS[scenario_id]
        user_prompt = _build_supervisor_user_prompt(scenario_context)
        response_dict = SUPERVISOR_RESPONSES[scenario_id]
        response_str = json.dumps(response_dict, ensure_ascii=False)
        key = cache_key(SONNET_MODEL, SUPERVISOR_SYSTEM_PROMPT, user_prompt, tool_state=None)
        entries.append({"key": key, "response": response_str})

    return entries


def main() -> None:
    entries = build_entries()

    # 중복 key 검증
    keys = [e["key"] for e in entries]
    assert len(keys) == len(set(keys)), f"중복 key 발생: {len(keys) - len(set(keys))} 개"
    assert len(entries) == 51, f"entry 수 불일치: {len(entries)} != 51"

    # 파일 덮어쓰기
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"cache_replay.jsonl 재생성 완료: {OUTPUT_PATH}")
    print(f"  entries: {len(entries)}")
    print(f"  domain-agent: 48  (3 scenario × 4 action × 4 agent)")
    print(f"  supervisor:    3  (3 scenario)")


if __name__ == "__main__":
    main()

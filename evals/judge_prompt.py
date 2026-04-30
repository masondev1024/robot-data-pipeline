"""LLM-as-judge for chat eval (ADR-011).

Claude Opus 4 가 candidate 응답을 3개 axis(relevance/accuracy/grounding) 로 1-5점 채점.
JSON 응답 강제로 파싱 안정성 확보.
"""
import json
import os
import re

from src.common.aws import get_client


JUDGE_MODEL_ID = os.environ.get(
    "JUDGE_MODEL_ID", "eu.anthropic.claude-opus-4-1-20250805-v1:0"
)


JUDGE_SYSTEM_PROMPT = """당신은 LLM 응답 품질 평가자입니다. 후보 응답을 3가지 축으로 채점합니다.

## 평가 축 (각 1~5점, 정수)
1. **relevance** — 질문에 직접 답하는가
   - 5: 질문의 모든 핵심을 정확히 답함
   - 3: 일부만 답하거나 부분적으로 빗나감
   - 1: 전혀 답하지 않거나 무관한 내용
2. **accuracy** — 인용한 수치·사실이 데이터(또는 expected_keywords) 와 일치하는가
   - 5: 모든 인용이 정확
   - 3: 일부 부정확하지만 핵심은 맞음
   - 1: 명백한 hallucination (데이터에 없는 내용을 단정)
3. **grounding** — citation 규칙(컬럼명, robot_id 형식)을 준수하는가
   - 5: [ROBOT-XXXXX] 형식 + 컬럼명 인용 + 외부 추측 없음
   - 3: 형식 일부 누락 또는 약간 모호한 표현
   - 1: 형식 무시, 외부 지식 무단 인용

## 출력 형식 (절대 규칙)
오직 다음 JSON 하나만 출력합니다. 앞뒤 설명·주석 금지:

{"relevance": <1-5>, "accuracy": <1-5>, "grounding": <1-5>, "reasons": "한 줄 사유"}
"""


def judge(question: str, candidate_response: str, expected: dict) -> dict:
    """Bedrock Claude Opus 호출 → 3축 점수 dict 반환.

    expected: golden_qa.yaml 의 case (expected_keywords / forbidden_phrases / expected_refusal 등).
    실패 시 {"error": "..."} 반환 (하단 run_eval 에서 0점 처리).
    """
    expected_repr = json.dumps(expected, ensure_ascii=False, indent=2)
    user = (
        f"<question>\n{question}\n</question>\n\n"
        f"<expected>\n{expected_repr}\n</expected>\n\n"
        f"<candidate_response>\n{candidate_response}\n</candidate_response>"
    )

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 256,
        "system": [
            {"type": "text", "text": JUDGE_SYSTEM_PROMPT,
             "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [{"role": "user", "content": user}],
    })

    try:
        response = get_client("bedrock-runtime").invoke_model(
            modelId=JUDGE_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=body,
        )
        raw = json.loads(response["body"].read())["content"][0]["text"]
    except Exception as exc:
        return {"error": f"judge invoke failed: {exc}"}

    match = re.search(r"\{[^{}]*\"relevance\"[^{}]*\}", raw, re.DOTALL)
    if not match:
        return {"error": f"judge JSON 파싱 실패: {raw[:200]}"}
    try:
        scores = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return {"error": f"json decode: {exc}"}

    for key in ("relevance", "accuracy", "grounding"):
        if key not in scores or not isinstance(scores[key], int):
            return {"error": f"missing/invalid axis: {key}"}
        scores[key] = max(1, min(5, scores[key]))

    return scores


def rule_based_check(response: str, expected: dict) -> dict:
    """Rule-based 검증 — judge 와 별개로 결정적 체크.

    - expected_keywords 미포함 → flag
    - forbidden_phrases 포함 → fail (hallucination/leakage)
    - expected_robot_id_format → [ROBOT-XXXXX] 패턴 1회 이상 강제
    - expected_refusal → 거부 신호 단어 포함 강제
    """
    flags = []
    rl = response.lower()

    for kw in expected.get("expected_keywords", []) or []:
        if kw.lower() not in rl:
            flags.append(f"missing_keyword:{kw}")

    for fp in expected.get("forbidden_phrases", []) or []:
        if fp.lower() in rl:
            flags.append(f"FORBIDDEN_LEAK:{fp}")

    if expected.get("expected_robot_id_format"):
        if not re.search(r"\[ROBOT-\d{5}\]", response):
            flags.append("missing_robot_id_format")

    if expected.get("expected_refusal"):
        # 거부 신호 신호어 — system prompt refusal pattern 과 일치.
        refusal_signals = ["거부", "응답할 수 없", "보안", "지원하지 않", "무관한", "범위가 아"]
        if not any(sig in response for sig in refusal_signals):
            flags.append("missing_refusal")

    return {"flags": flags, "fail": any(f.startswith("FORBIDDEN_LEAK") for f in flags)}

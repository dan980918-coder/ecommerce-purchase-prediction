"""Phase 9 - LLM 호출 백엔드.

API 키가 없으면(이번 세션 기본 상태) mock 백엔드를 사용한다 — 실제 LLM이
아니라 이미 주어진 segment_facts/model_predictions 메타데이터를 규칙적으로
재구성한 결정론적(deterministic) 응답이며, generated_by="mock"으로 명확히
표시한다. 사용자가 나중에 .env에 ANTHROPIC_API_KEY 또는 OPENAI_API_KEY를
추가하면 자동으로 실제 API를 호출한다.
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv

from src.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from src.llm.schemas import CRMReportInput

# 로컬 개발 환경에서 .env의 키를 os.environ에 로드한다(이미 gitignore 처리됨).
# Streamlit Cloud처럼 실제 환경변수/시크릿이 이미 주입된 배포 환경에서는
# 이 호출이 아무 효과가 없다 — override=False가 기본값이라 기존 환경변수를
# 덮어쓰지 않는다.
load_dotenv()

DEFAULT_ANTHROPIC_MODEL = os.environ.get("CRM_LLM_MODEL", "claude-sonnet-5")
DEFAULT_OPENAI_MODEL = os.environ.get("CRM_LLM_MODEL_OPENAI", "gpt-4o-mini")


def get_available_backend() -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "mock"


def _extract_json_text(raw_text: str) -> dict:
    """모델이 지시를 어기고 ```json 코드펜스로 감싸서 응답하는 경우까지 처리."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()
    return json.loads(text)


def _call_anthropic(report_input: CRMReportInput) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    message = client.messages.create(
        model=DEFAULT_ANTHROPIC_MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(report_input)}],
        thinking={"type": "disabled"},
    )
    # content[0]을 무조건 텍스트 블록으로 가정하면 안 됨 — 확장 사고(thinking)를
    # 지원하는 모델은 ThinkingBlock(.text 없음, .thinking만 있음)이 content[0]에
    # 먼저 올 수 있다(실제로 재현 확인: thinking 토큰이 max_tokens 예산을 먹어
    # JSON 응답이 중간에 잘리는 문제로 이어졌음). 이 작업은 이미 계산된 사실을
    # JSON으로 재구성하는 결정적 포맷팅 작업이라 thinking이 필요 없으므로 명시적으로
    # 끈다 — max_tokens 전량이 실제 출력에 쓰이도록. type=="text"인 블록만 찾아 이어 붙인다.
    text_blocks = [block.text for block in message.content if getattr(block, "type", None) == "text"]
    if not text_blocks:
        block_types = [getattr(block, "type", type(block).__name__) for block in message.content]
        raise RuntimeError(
            f"Anthropic 응답에 텍스트 블록이 없습니다 (content block types: {block_types}, "
            f"stop_reason={message.stop_reason!r}) — 모델/파라미터 설정을 확인하세요."
        )
    return _extract_json_text("".join(text_blocks))


def _call_openai(report_input: CRMReportInput) -> dict:
    import openai

    client = openai.OpenAI()
    response = client.chat.completions.create(
        model=DEFAULT_OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(report_input)},
        ],
    )
    return json.loads(response.choices[0].message.content)


def _call_mock(report_input: CRMReportInput) -> dict:
    """API 키 없이도 파이프라인 전체를 시연·테스트할 수 있는 결정론적 대체
    구현. 주어진 사실을 넘어서는 새 숫자나 인과 주장을 만들지 않는다."""
    actions: list[str] = []
    hypotheses: list[str] = []

    if not report_input.segment_facts and not report_input.model_predictions:
        actions.append("입력된 세그먼트/모델 예측 데이터가 없어 구체적인 액션을 제안할 수 없습니다.")
        return {"recommended_actions": actions, "testable_hypotheses": hypotheses}

    for seg in report_input.segment_facts:
        actions.append(
            f"[{seg.segment}] (고객 {seg.n_customers:,}명, 접촉 우선순위 {seg.priority}) "
            f"목적: {seg.crm_purpose}에 맞는 CRM 액션을 검토해볼 수 있습니다."
        )
        hypotheses.append(
            f"[{seg.segment}] 세그먼트에 목적에 맞는 CRM 액션을 적용하면 반응률이 "
            "달라질 수 있다는 가설은 A/B 테스트로 검증이 필요합니다."
        )

    for pred in report_input.model_predictions:
        hypotheses.append(
            f"{pred.model_name}({pred.label}) 모델의 상위 {pred.contact_rate_pct}% 타겟팅이 "
            f"실제 캠페인에서도 시뮬레이션과 유사한 포착률을 보이는지는 실제 실험으로 "
            "확인이 필요합니다."
        )

    return {"recommended_actions": actions, "testable_hypotheses": hypotheses}


def call_llm(report_input: CRMReportInput) -> tuple[dict, str]:
    """반환값: (파싱된 응답 dict, 실제 사용된 backend 식별자)"""
    backend = get_available_backend()
    if backend == "anthropic":
        return _call_anthropic(report_input), DEFAULT_ANTHROPIC_MODEL
    if backend == "openai":
        return _call_openai(report_input), DEFAULT_OPENAI_MODEL
    return _call_mock(report_input), "mock"

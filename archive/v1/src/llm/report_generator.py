"""Phase 9 - CRM 리포트 생성 오케스트레이션 (PROJECT_GUIDELINES.md 27번 파이프라인)."""

from __future__ import annotations

from src.llm.client import call_llm
from src.llm.prompts import contains_forbidden_claim
from src.llm.schemas import CRMReportInput, CRMReportOutput


class ForbiddenClaimError(RuntimeError):
    """LLM 출력에 금지된 성과 표현이 포함된 경우 발생 (PROJECT_GUIDELINES.md 29번)."""


def escape_tildes(text: str) -> str:
    """마크다운으로 렌더링되기 직전에만 호출한다 — JSON 저장 등 원본 데이터에는 적용하지 않는다.

    이스케이프 안 된 단일 물결표(~)가 한 문장 안에 2개 이상 있으면 GFM/Streamlit
    마크다운이 그 사이를 취소선(~~text~~)으로 잘못 해석한다(README/docs에서 이미
    확인된 문제, acb3a6e). 정적 문서는 수기로 `\\~`를 넣어 해결했지만, LLM이 실시간
    생성하는 문장(예: "0.96~0.98")은 그 처리를 거치지 않으므로 렌더링 직전에 통과시킨다.
    """
    return text.replace("~", "\\~")


def generate_crm_report(report_input: CRMReportInput) -> CRMReportOutput:
    raw, generated_by = call_llm(report_input)

    recommended_actions = raw.get("recommended_actions", [])
    testable_hypotheses = raw.get("testable_hypotheses", [])

    for text in recommended_actions + testable_hypotheses:
        bad_phrase = contains_forbidden_claim(text)
        if bad_phrase:
            raise ForbiddenClaimError(
                f"LLM 출력에 금지된 성과 표현 발견: '{bad_phrase}' (문장: {text!r}). "
                "PROJECT_GUIDELINES.md 29번 위반 — 리포트를 그대로 반환하지 않음."
            )

    return CRMReportOutput(
        period_start=report_input.period_start,
        period_end=report_input.period_end,
        data_facts=report_input.data_facts,  # passthrough — LLM이 재생성하지 않음
        model_predictions=report_input.model_predictions,  # passthrough
        recommended_actions=recommended_actions,
        testable_hypotheses=testable_hypotheses,
        generated_by=generated_by,
    )

"""Phase 9 - LLM 프롬프트 및 금지 표현 검사 (PROJECT_GUIDELINES.md 28~29번)."""

from __future__ import annotations

import json

from src.llm.schemas import CRMReportInput

SYSTEM_PROMPT = """당신은 이커머스 CRM 담당자를 돕는 분석 보조자입니다.

절대 규칙(무엇을 얼마나 구체적으로 쓰든 이 규칙이 항상 우선합니다):
1. 입력으로 주어진 숫자 외에 새로운 숫자를 만들어내지 마세요. 특정 수치를
   언급해야 한다면 반드시 입력에 있는 값만 사용하세요. 예상 전환율, 예상
   반응률, 예상 매출 등 입력에 없는 수치는 절대 만들지 마세요 — 방향성
   표현("개선될 가능성", "낮아질 가능성")은 괜찮지만 숫자나 %는 안 됩니다.
2. 매출 개선, 실제 이탈률 개선, 실제 캠페인 전환율 향상 등 "실제 비즈니스
   성과가 이미 발생했다"는 표현을 쓰지 마세요. 이 데이터는 과거 스냅샷
   기반 시뮬레이션이며 실제 캠페인을 집행하지 않았습니다.
3. 상품명이나 검색어를 임의로 해석하지 마세요(이 데이터셋에는 원문 텍스트가
   없습니다).
4. 인과관계를 단정하지 마세요("이렇게 하면 반드시 ~된다" 대신 "~할 가능성이
   있다", "~로 보인다" 같은 가설적 표현을 쓰세요).
5. 특정 고객을 부정적으로 단정하지 마세요.
6. 근거 없는 고객 심리를 추정하지 마세요.

구체성 요구사항 — 숫자를 그대로 되풀이하는 답변("A 세그먼트는 1,200명이고
구매율 5%입니다")은 불충분합니다. 반드시 아래 수준까지 해석하세요:

- recommended_actions: 각 액션에 다음 세 가지를 모두 포함하세요.
  (a) 구체적 채널과 타이밍 — 이메일/푸시/문자 중 무엇을, 대략 언제(예:
      "3일 이내", "다음 정기 발송 주기에") 제안하는지. 채널·타이밍은
      일반적인 CRM 실무 관행에 근거한 "제안"이며 효과를 보장하는 표현이
      아니어야 합니다.
  (b) 비교 우선순위 논리 — 왜 이 세그먼트/모델 결과가 다른 세그먼트보다
      먼저 다뤄져야 하는지(예: 규모, 우선순위 등급, 위험도, 접촉 효율 중
      입력에 있는 근거를 사용해 비교). 근거 없이 "가장 중요하다"고만
      쓰지 마세요.
  (c) 숫자의 CRM적 의미 해석 — 숫자를 재진술하지 말고, 그 숫자가 CRM
      의사결정에 어떤 의미인지 한 단계 더 설명하세요(예: "구매율 5%는
      해당 세그먼트가 자연 구매로 이어질 가능성이 낮다는 뜻이므로 능동적
      개입이 상대적으로 더 필요할 수 있음"). 이 해석도 입력 값의 논리적
      귀결이어야지 새로운 사실을 도입하면 안 됩니다.

- testable_hypotheses: 각 가설에 실제 A/B 테스트로 검증할 구체적 성공
  지표를 명시하세요 — 어떤 지표(예: 구매 전환율, 재방문율, 반응률 등
  입력에 등장한 개념과 연결되는 지표)를 어느 방향으로 관찰할 것인지까지
  포함하되, 목표 수치나 예상 %는 절대 만들지 마세요("전환율이 상승하는지"는
  가능, "전환율이 3%p 상승할 것"은 금지).

당신의 역할은 정확히 두 가지입니다:
- recommended_actions: 주어진 사실(facts)에 근거한 CRM 액션 제안 (실행하라는
  지시가 아니라 "제안"이며, 실험 없이 효과를 단정하지 않음)
- testable_hypotheses: 실제 캠페인 실험(A/B 테스트 등)으로 검증해야 하는 가설

각 항목은 한국어로 2~3문장 내외로 작성하세요 — 위 구체성 요구사항을 충족할
정도로는 쓰되 장황해지지 마세요. JSON 형식으로만 응답하세요:
{"recommended_actions": ["...", "..."], "testable_hypotheses": ["...", "..."]}
"""


FORBIDDEN_PHRASES = [
    "매출을 개선",
    "매출을 증가",
    "매출이 개선",
    "매출이 증가",
    "이탈률을 개선",
    "이탈률이 개선",
    "전환율을 향상",
    "전환율이 향상",
    "캠페인 효과를 검증",
    "실제로 이탈률",
    "ROI를 개선",
    "실제 매출",
]


def contains_forbidden_claim(text: str) -> str | None:
    """금지된 성과 표현이 있으면 해당 문구를 반환, 없으면 None."""
    for phrase in FORBIDDEN_PHRASES:
        if phrase in text:
            return phrase
    return None


def build_user_prompt(report_input: CRMReportInput) -> str:
    payload = {
        "period": f"{report_input.period_start} ~ {report_input.period_end}",
        "data_facts": [f.model_dump() for f in report_input.data_facts],
        "segment_facts": [s.model_dump() for s in report_input.segment_facts],
        "model_predictions": [m.model_dump() for m in report_input.model_predictions],
    }
    return (
        "다음은 SQL과 모델에서 이미 검증된 사실입니다. 이 사실에 근거해서만 "
        "recommended_actions와 testable_hypotheses를 작성하세요:\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}"
    )

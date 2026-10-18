import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.dashboard.data import format_count, show_data_period_notice, with_exact_help
from src.dashboard.theme import badge, inject_global_css, metric
from src.llm.client import get_available_backend
from src.llm.data_loader import build_report_input
from src.llm.report_generator import escape_tildes, generate_crm_report

st.set_page_config(page_title="AI CRM Report", page_icon="🤖", layout="wide")
inject_global_css()
st.title("AI CRM Report")
show_data_period_notice()

backend = get_available_backend()
if backend == "mock":
    st.warning(
        "⚠️ 현재 LLM API 키가 설정되어 있지 않아 **mock(모의) 백엔드**로 생성된 "
        "리포트입니다 — 실제 LLM이 문장을 생성한 것이 아니라, 세그먼트 메타데이터를 "
        "규칙적으로 재구성한 결정론적 대체 출력입니다. `.env`에 `ANTHROPIC_API_KEY` "
        "또는 `OPENAI_API_KEY`를 추가하면 자동으로 실제 LLM 호출로 전환됩니다."
    )
else:
    st.success(f"✅ 실제 LLM 백엔드({backend})로 생성된 리포트입니다.")

contact_rate = st.select_slider("Model Predictions 기준 접촉 비율", options=[5, 10, 20, 30], value=10)

report_input = build_report_input(contact_rate_pct=contact_rate)
output = generate_crm_report(report_input)

st.caption(f"생성 방식: {output.generated_by} | 기간: {output.period_start} ~ {output.period_end}")

# 우선순위 배지 — LLM이 우선순위를 판단하지 않고(PROJECT_GUIDELINES.md 27번), segment_facts에
# 실제로 들어있는 priority 값(SQL에서 이미 확정된 값)을 근거로 Python이 매핑한다.
# build_report_input()이 애초에 "높음" 이상 세그먼트만 골라 LLM에 전달하므로
# (data_loader.py HIGH_PRIORITY_LABELS), "중간/낮음" 배지는 이 리포트에 나타나지
# 않는다 — 모델 관련·일반 문장은 "참고"로 표시해 시각적 위계를 3단으로 유지한다.
PRIORITY_BADGE = {
    "매우 높음": ("매우 높음", "danger", "🔴"),
    "높음": ("높음", "warning", "🟠"),
    "높음(유지 목적)": ("높음", "warning", "🟠"),
}
PRIORITY_RANK = {"매우 높음": 2, "높음(유지 목적)": 1, "높음": 1}
GENERAL_BADGE = ("참고", "neutral", "⚪")


def _badge_for_action(text: str, segment_facts) -> tuple[str, str, str]:
    """action 문장에 언급된 세그먼트명을 찾아 그 세그먼트의 실제 priority로 배지를 정한다."""
    normalized_text = text.replace(" ", "").replace("_", "")
    best_priority, best_rank = None, -1
    for seg in segment_facts:
        normalized_seg = seg.segment.replace(" ", "").replace("_", "")
        if normalized_seg and normalized_seg in normalized_text:
            rank = PRIORITY_RANK.get(seg.priority, 0)
            if rank > best_rank:
                best_priority, best_rank = seg.priority, rank
    return PRIORITY_BADGE.get(best_priority, GENERAL_BADGE)


def _tone_for_fact(label: str) -> str:
    if "위험" in label:
        return "warning"
    if "비활성" in label:
        return "danger"
    return "neutral"


st.subheader("1. Data Facts (SQL에서 확인된 사실)")
# 4열 한 줄 배치는 좁은 화면(~1024px)에서 라벨·값이 잘려 2열씩 묶어 배치한다
# (Overview 페이지와 동일한 근거).
facts = output.data_facts
for row_start in range(0, len(facts), 2):
    row_facts = facts[row_start:row_start + 2]
    row_cols = st.columns(2)
    for i, (col, fact) in enumerate(zip(row_cols, row_facts)):
        metric(col, f"fact{row_start+i}", fact.label, f"{format_count(fact.value)}{fact.unit}",
               tone=_tone_for_fact(fact.label), help=with_exact_help(fact.value))

st.subheader("2. Model Predictions (모델 예측 결과)")
for m in output.model_predictions:
    st.markdown(
        f"- **{m.model_name}** ({m.label}), 상위 {m.contact_rate_pct}%: "
        f"Recall {m.recall*100:.1f}%, Lift {m.lift:.2f}배, Precision {m.precision*100:.1f}%"
    )
if not output.model_predictions:
    st.caption("해당 접촉 비율의 모델 예측 결과가 없습니다.")

st.subheader("3. Recommended Actions (제안된 CRM 액션)")
st.caption("배지는 LLM이 아니라 세그먼트의 실제 접촉 우선순위(SQL 확정값)를 근거로 표시합니다.")
for a in output.recommended_actions:
    label, tone, icon = _badge_for_action(a, report_input.segment_facts)
    st.markdown(f"{badge(label, tone, icon)}{escape_tildes(a)}", unsafe_allow_html=True)

st.subheader("4. Testable Hypotheses (실험으로 검증해야 하는 가설)")
for h in output.testable_hypotheses:
    st.markdown(f"- {escape_tildes(h)}")

st.markdown("---")
st.caption(
    "PROJECT_GUIDELINES.md 29번 원칙: 입력에 없는 숫자 생성 금지, 매출/이탈률 개선 등 실제 성과 "
    "표현 금지, 상품명·검색어 임의 해석 금지, 인과관계 단정 금지. 위반 문구가 감지되면 "
    "리포트 생성 자체가 예외로 중단됩니다(`src/llm/report_generator.py`)."
)

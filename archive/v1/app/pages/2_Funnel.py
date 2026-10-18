import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.dashboard.data import format_count, load_funnel_summary, show_data_period_notice
from src.dashboard.theme import BRAND, inject_global_css, metric, themed_layout

st.set_page_config(page_title="Funnel", page_icon="🔻", layout="wide")
inject_global_css()
st.title("고객 단위 퍼널")
show_data_period_notice()

st.caption(
    "💡 상품 단위 퍼널은 `page_visit.url`-상품(sku) 연결 불가로 구조적으로 불가능해 "
    "고객 단위 탐색→장바구니→구매 퍼널만 제공합니다 (근거: `docs/methodology.md`)."
)

funnel = load_funnel_summary()

stage_vals = [funnel["explore"], funnel["cart"], funnel["buy"]]
pct_initial = [v / stage_vals[0] * 100 for v in stage_vals]
pct_previous = [100.0, stage_vals[1] / stage_vals[0] * 100, stage_vals[2] / stage_vals[1] * 100]
funnel_text = [
    f"{v:,.0f}<br>초기 대비 {pi:.1f}%<br>직전 대비 {pp:.1f}%"
    for v, pi, pp in zip(stage_vals, pct_initial, pct_previous)
]

fig = go.Figure(
    go.Funnel(
        y=["탐색", "장바구니 추가", "구매"],
        x=stage_vals,
        text=funnel_text,
        textinfo="text",
        marker=dict(color=[BRAND, BRAND, BRAND], opacity=[1, 0.72, 0.5]),
        connector=dict(fillcolor="#EAF0FE", line=dict(color="#C7D7FB", width=1)),
    )
)
themed_layout(fig, height=380)
st.plotly_chart(fig, use_container_width=True)

st.subheader("정확한 값")
stage_df = pd.DataFrame(
    {"단계": ["탐색", "장바구니 추가", "구매"], "고객 수": stage_vals,
     "초기%": pct_initial, "직전%": pct_previous}
)
st.dataframe(
    stage_df.style.format({"고객 수": "{:,.0f}", "초기%": "{:.1f}%", "직전%": "{:.1f}%"}),
    use_container_width=True, hide_index=True,
    column_config={
        "단계": st.column_config.TextColumn(width="small"),
        "고객 수": st.column_config.TextColumn(width="medium"),
        "초기%": st.column_config.TextColumn(width="small"),
        "직전%": st.column_config.TextColumn(width="small"),
    },
)

st.subheader("구매자 경로 분해")
st.markdown(
    "구매자가 항상 \"탐색→장바구니→구매\" 경로를 거치는 것은 아닙니다. 실제 경로별 분해는 "
    "다음과 같습니다 (Phase 3 퍼널 분석 참고)."
)

total_buy = funnel["buy"]
explore_cart_buy = funnel["cart_to_buy"]
no_footprint = funnel["buy_with_no_footprint"]

c1, c2, c3, c4 = st.columns(4)
metric(c1, "path", "탐색→구매", format_count(explore_cart_buy),
       sub=f"구매의 {explore_cart_buy/total_buy*100:.1f}%", tone="positive",
       help=f"탐색→장바구니→구매 전체 경로 — 정확한 값: {explore_cart_buy:,.0f}")
metric(c2, "nofootprint", "기록 없음", format_count(no_footprint),
       sub=f"구매의 {no_footprint/total_buy*100:.1f}%", tone="warning",
       help=f"기록 없이 구매 — 정확한 값: {no_footprint:,.0f}")
metric(c3, "e2c", "탐색전환율", f"{funnel['explore_to_cart']/funnel['explore']*100:.2f}%",
       help="탐색→장바구니 전환율")
metric(c4, "c2b", "구매전환율", f"{funnel['cart_to_buy']/funnel['cart']*100:.2f}%",
       help="장바구니→구매 전환율")

st.caption(
    "'기록 없이 구매' 고객은 탐색·검색·장바구니 이벤트가 전혀 없이 구매만 기록된 경우로, "
    "데이터 로깅 범위 밖의 경로(앱 딥링크 등)일 가능성이 있습니다 — 원인은 데이터로 확정할 수 없습니다."
)

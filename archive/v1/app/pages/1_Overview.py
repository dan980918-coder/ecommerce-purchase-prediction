import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.dashboard.data import (
    format_count,
    load_funnel_summary,
    load_lifecycle_distribution,
    load_overview_kpis,
    show_data_period_notice,
    with_exact_help,
)
from src.dashboard.theme import (
    BRAND,
    DANGER,
    POSITIVE,
    WARNING,
    inject_global_css,
    metric,
    themed_layout,
)

st.set_page_config(page_title="Overview", page_icon="📊", layout="wide")
inject_global_css()
st.title("CRM Overview")
show_data_period_notice()

kpis = load_overview_kpis()
funnel = load_funnel_summary()

st.subheader("핵심 KPI")
total = kpis["total_customers"]
buyers = kpis["buyers"]
# 7열 한 줄 배치는 좁은 화면(~1200px, 흔한 노트북 해상도)에서 라벨·값이 잘려
# 4+3 분할로 되돌렸다 — 밀도보다 안 잘리는 게 우선이라는 판단.
r1 = st.columns(4)
metric(r1[0], "total", "전체 고객", format_count(total),
       help=with_exact_help(total, "전체 관측 고객"))
metric(r1[1], "buyers", "구매 고객", format_count(buyers),
       sub=f"전체의 {buyers/total*100:.1f}%",
       help=with_exact_help(buyers, "관측 기간 내 1회 이상 구매"))
metric(r1[2], "repeat", "반복구매", format_count(kpis["repeat_buyers"]),
       sub=f"구매 고객의 {kpis['repeat_buyers']/buyers*100:.1f}%", tone="positive",
       help=with_exact_help(kpis["repeat_buyers"], "반복구매 가능 고객 — 서로 다른 날짜에 2회 이상 구매"))
metric(r1[3], "cart", "장바구니", format_count(kpis["cart_customers"]),
       sub=f"전체의 {kpis['cart_customers']/total*100:.1f}%",
       help=with_exact_help(kpis["cart_customers"], "장바구니 고객"))

r2 = st.columns(3)
metric(r2[0], "atrisk", "비활성 위험", format_count(kpis["at_risk_customers"]),
       sub=f"구매 고객의 {kpis['at_risk_customers']/buyers*100:.1f}%", tone="warning",
       help=with_exact_help(kpis["at_risk_customers"], "마지막 구매 후 29~60일 경과 (docs/methodology.md 데이터 기반 임계값)"))
metric(r2[1], "inactive", "비활성 고객", format_count(kpis["inactive_customers"]),
       sub=f"구매 고객의 {kpis['inactive_customers']/buyers*100:.1f}%", tone="danger",
       help=with_exact_help(kpis["inactive_customers"], "마지막 구매 후 60일 초과 경과"))
metric(r2[2], "recent", "최근 전환", format_count(kpis["recent_converters"]),
       tone="positive",
       help=with_exact_help(kpis["recent_converters"], "최근 14일 구매 전환(최신 스냅샷) — mart_purchase_propensity 최신 snapshot_date 기준 will_purchase_14d=1"))

st.caption(
    "⚠️ '구매 비활성 위험/비활성' 고객 수는 관측 종료 시점 기준 단면입니다. 이 중 일부는 실제 "
    "이탈이 아니라 우측 검열(관측 종료로 인한 데이터 절단) 효과일 수 있습니다 — docs/limitations.md 참고."
)

st.markdown("---")

stage_vals = [funnel["explore"], funnel["cart"], funnel["buy"]]
pct_initial = [v / stage_vals[0] * 100 for v in stage_vals]
funnel_text = [f"{v:,.0f}<br>초기 대비 {pi:.1f}%" for v, pi in zip(stage_vals, pct_initial)]

col_funnel, col_lifecycle = st.columns([2, 1])
with col_funnel:
    st.subheader("핵심 퍼널 (고객 단위)")
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
    themed_layout(fig, height=330)
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        f"참고: 구매 고객 중 {funnel['buy_with_no_footprint']:,.0f}명"
        f"({funnel['buy_with_no_footprint']/funnel['buy']*100:.1f}%)은 탐색·장바구니 기록 없이 "
        "구매만 기록되어 위 경로를 거치지 않았습니다 (상품 단위 퍼널은 page_visit-sku 연결 불가로 "
        "구조적으로 불가능 — Phase 3 참고)."
    )

with col_lifecycle:
    st.subheader("라이프사이클 스냅샷")
    lc = load_lifecycle_distribution().sort_values("n", ascending=False)
    tone_color = {
        "비활성_고객": DANGER,
        "구매_비활성_위험_고객": WARNING,
        "구매_감소_고객": WARNING,
        "활성_구매_고객": POSITIVE,
        "복귀_고객": POSITIVE,
        "첫_관측_구매_고객": POSITIVE,
    }
    lc["color"] = lc["lifecycle_stage"].map(lambda s: tone_color.get(s, BRAND))
    fig2 = px.bar(
        lc.sort_values("n"), x="n", y="lifecycle_stage", orientation="h",
        labels={"n": "", "lifecycle_stage": ""},
    )
    fig2.update_traces(marker_color=lc.sort_values("n")["color"])
    themed_layout(fig2, height=270)
    fig2.update_xaxes(visible=False)
    st.plotly_chart(fig2, use_container_width=True)
    st.caption("자세한 정의·근거는 Lifecycle 페이지 참고.")

st.subheader("정확한 값")
stage_df = pd.DataFrame(
    {"단계": ["탐색", "장바구니 추가", "구매"], "고객 수": stage_vals,
     "초기%": pct_initial,
     "직전%": [100.0, funnel["cart"] / funnel["explore"] * 100, funnel["buy"] / funnel["cart"] * 100]}
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

import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.dashboard.data import format_count, load_lifecycle_distribution, show_data_period_notice
from src.dashboard.theme import BRAND, DANGER, POSITIVE, WARNING, inject_global_css, metric, themed_layout

st.set_page_config(page_title="Lifecycle", page_icon="🔄", layout="wide")
inject_global_css()
st.title("고객 라이프사이클")
show_data_period_notice()

st.caption(
    "관측 종료 시점(2022-12-08) 기준 상태 분포입니다. 임계값(14/28/60일)은 구매 간격 "
    "중앙값·p90 기반 산출 — 근거: `docs/methodology.md` \"라이프사이클 상태 임계값 확정\"."
)

df = load_lifecycle_distribution()

TONE_BY_STAGE = {
    "비활성_고객": "danger",
    "구매_비활성_위험_고객": "warning",
    "구매_감소_고객": "warning",
    "활성_구매_고객": "positive",
    "복귀_고객": "positive",
    "첫_관측_구매_고객": "positive",
}
TONE_COLOR = {"neutral": BRAND, "positive": POSITIVE, "warning": WARNING, "danger": DANGER}
df["tone"] = df["lifecycle_stage"].map(lambda s: TONE_BY_STAGE.get(s, "neutral"))

group = df.groupby("tone")["n"].sum()
st.caption("아래 4개 카드는 하단 8개 상태를 묶은 값입니다 — 정확한 구성은 각 ❓ 아이콘 참고.")
c1, c2, c3, c4 = st.columns(4)
metric(c1, "explore", "탐색군", format_count(group.get("neutral", 0)),
       sub=f"전체의 {group.get('neutral', 0)/df['n'].sum()*100:.1f}%",
       help="탐색_고객 + 장바구니_고객을 합친 값입니다")
metric(c2, "active", "활성군", format_count(group.get("positive", 0)),
       sub=f"전체의 {group.get('positive', 0)/df['n'].sum()*100:.1f}%", tone="positive",
       help="첫_관측_구매_고객 + 활성_구매_고객 + 복귀_고객을 합친 값입니다")
metric(c3, "declining", "위험군", format_count(group.get("warning", 0)),
       sub=f"전체의 {group.get('warning', 0)/df['n'].sum()*100:.1f}%", tone="warning",
       help="구매_비활성_위험_고객 + 구매_감소_고객을 합친 값입니다")
metric(c4, "inactive", "비활성", format_count(group.get("danger", 0)),
       sub=f"전체의 {group.get('danger', 0)/df['n'].sum()*100:.1f}%", tone="danger",
       help="비활성_고객 단일 상태입니다 (다른 상태와 합산 없음)")

st.subheader("상태별 분포")
plot_df = df.sort_values("n", ascending=True)
fig = px.bar(
    plot_df, x="n", y="lifecycle_stage", orientation="h",
    text=plot_df["pct"].map(lambda p: f"{p:.2f}%"),
    labels={"n": "고객 수", "lifecycle_stage": "상태"},
)
fig.update_traces(marker_color=plot_df["tone"].map(TONE_COLOR))
themed_layout(fig, height=420)
st.plotly_chart(fig, use_container_width=True)

st.subheader("정확한 값")
st.dataframe(
    df[["lifecycle_stage", "n", "pct"]], use_container_width=True, hide_index=True,
    column_config={
        "lifecycle_stage": st.column_config.TextColumn("상태", width="medium"),
        "n": st.column_config.TextColumn("고객 수", width="small"),
        "pct": st.column_config.NumberColumn("비중%", width="small", format="%.2f%%"),
    },
)

st.markdown("---")
st.warning(
    "구매_비활성_위험_고객 + 비활성_고객 = "
    f"{df[df['lifecycle_stage'].isin(['구매_비활성_위험_고객','비활성_고객'])]['n'].sum():,.0f}명 "
    "(구매 고객의 73.55%)이 '비활성 계열'로 보이지만, 이 중 상당수는 관측 종료로 인한 "
    "우측 검열 효과입니다(Phase 1 8.10: 구매자의 15.18%가 관측 종료 14일 이내 마지막 구매) — "
    "자세한 내용은 docs/limitations.md 참고."
)

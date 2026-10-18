import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.dashboard.data import format_count, load_segment_profile, show_data_period_notice, with_exact_help
from src.dashboard.theme import BRAND, DANGER, POSITIVE, WARNING, inject_global_css, metric, themed_layout

st.set_page_config(page_title="Segment Explorer", page_icon="🧩", layout="wide")
inject_global_css()
st.title("Segment Explorer")
show_data_period_notice()

st.caption(
    "규칙 기반 세그먼트 9개입니다 (PROJECT_GUIDELINES.md 17번 원칙에 따라 규칙 기반으로 "
    "구축 — 군집분석은 이 프로젝트에서 시도하지 않았다, "
    "`docs/data_dictionary.md` mart_customer_segment 참고)."
)

df = load_segment_profile()

SEGMENT_TONE = {
    "저관여_탐색형": "neutral",
    "구매_직전_탐색형": "positive",
    "장바구니_보류형": "warning",
    "구매_비활성형": "danger",
    "장바구니_이탈형": "danger",
    "반복구매_감소형": "warning",
    "첫_관측_구매_고관여형": "positive",
    "안정적_반복구매형": "positive",
    "복귀형": "positive",
}
TONE_COLOR = {"neutral": BRAND, "positive": POSITIVE, "warning": WARNING, "danger": DANGER}
df["tone"] = df["segment"].map(lambda s: SEGMENT_TONE.get(s, "neutral"))

# 접촉 우선순위 정렬 순위 — 텍스트 라벨을 정렬 가능한 순위로 매핑
PRIORITY_RANK = {"매우 높음": 5, "높음(유지 목적)": 4, "높음": 4, "중간": 3, "낮음": 2, "최하위": 1}
# 과접촉 위험 — 아이콘·배경색으로 즉시 구분 (매우 높음=적색 위험 ~ 매우 낮음=안전)
OVER_CONTACT_ICON = {
    "매우 높음": "🔴", "높음": "🟠", "중간": "🟡",
    "낮음~중간": "🟡", "낮음": "🟢", "매우 낮음": "🟢",
}
# 동일 우선순위 티어 내 2차 정렬용 순위(낮을수록 안전) — 안전하게 접촉 가능한
# 대상부터 보여주는 게 실무적으로 더 말이 된다는 사용자 판단에 따라, 인원수(n)
# 내림차순 대신 이 기준을 사용한다(2026-08-11, docs/methodology.md 참고).
OVER_CONTACT_RANK = {"매우 낮음": 1, "낮음": 2, "낮음~중간": 3, "중간": 4, "높음": 5, "매우 높음": 6}
OVER_CONTACT_BG = {
    "매우 높음": "#FEF2F2", "높음": "#FFF7ED", "중간": "#FFF7ED",
    "낮음~중간": "#FFFFFF", "낮음": "#F0FDF4", "매우 낮음": "#F0FDF4",
}

st.subheader("오늘의 액션 리스트 (접촉 우선순위 순)")
st.caption(
    "우선순위·과접촉 위험은 세그먼트 행동 데이터를 근거로 설계 시점에 정리한 정성적 판단입니다 "
    "(`reports/phase4_segment_profile.md` 근거) — 실제 접촉 이력 기반 피로도 측정치가 아닙니다."
)

action_df = df.copy()
action_df["priority_rank"] = action_df["priority"].map(PRIORITY_RANK).fillna(0)
action_df["over_contact_rank"] = action_df["over_contact_risk"].map(OVER_CONTACT_RANK).fillna(99)
action_df = action_df.sort_values(
    ["priority_rank", "over_contact_rank"], ascending=[False, True]
).reset_index(drop=True)
action_df.index = action_df.index + 1

action_df["과접촉 위험"] = action_df["over_contact_risk"].map(
    lambda v: f"{OVER_CONTACT_ICON.get(v, '⚪')} {v}"
)
display_df = action_df.rename(columns={
    "segment": "세그먼트", "n": "인원", "priority": "우선순위",
    "crm_purpose": "CRM 목적", "recommended_action": "추천 액션",
})[["세그먼트", "인원", "우선순위", "과접촉 위험", "CRM 목적", "추천 액션"]]


def _highlight_risk(val: str) -> str:
    category = val.split(" ", 1)[1] if " " in val else val
    bg = OVER_CONTACT_BG.get(category, "")
    return f"background-color: {bg}" if bg else ""


st.dataframe(
    display_df.style.format({"인원": format_count}).map(_highlight_risk, subset=["과접촉 위험"]),
    use_container_width=True,
    column_config={
        "세그먼트": st.column_config.TextColumn(width="medium"),
        "과접촉 위험": st.column_config.TextColumn(width="medium"),
        "CRM 목적": st.column_config.TextColumn(width="medium"),
        "추천 액션": st.column_config.TextColumn(width="large"),
    },
)

st.markdown("---")
st.subheader("세그먼트 상세")

selected = st.selectbox("세그먼트 선택", df["segment"].tolist())
row = df[df["segment"] == selected].iloc[0]
tone = SEGMENT_TONE.get(selected, "neutral")
total_n = df["n"].sum()

c1, c2, c3, c4 = st.columns(4)
metric(c1, "n", "고객 수", format_count(row["n"]), sub=f"전체의 {row['n']/total_n*100:.1f}%",
       tone=tone, help=with_exact_help(row["n"]))
metric(c2, "buyrate", "구매율", f"{row['buy_rate']*100:.1f}%", tone=tone)
metric(c3, "visit", "평균 방문 횟수", f"{row['avg_visit']:.1f}", tone=tone)
metric(c4, "purchases", "평균 구매 횟수", f"{row['avg_purchases']:.2f}", tone=tone)

col1, col2 = st.columns(2)
with col1:
    st.markdown(f"**CRM 목적**: {row['crm_purpose']}")
    st.markdown(f"**추천 액션**: {row['recommended_action']}")
with col2:
    st.markdown(f"**접촉 우선순위**: {row['priority']}")
    risk_icon = OVER_CONTACT_ICON.get(row["over_contact_risk"], "⚪")
    st.markdown(f"**과접촉 위험**: {risk_icon} {row['over_contact_risk']}")

st.markdown("---")
st.subheader("전체 세그먼트 비교")

plot_df = df.sort_values("n", ascending=True)
fig = px.bar(
    plot_df, x="n", y="segment", orientation="h",
    labels={"n": "고객 수", "segment": "세그먼트"},
)
fig.update_traces(marker_color=plot_df["tone"].map(TONE_COLOR))
themed_layout(fig, height=360)
st.plotly_chart(fig, use_container_width=True)

st.subheader("정확한 값")
st.dataframe(
    df[["segment", "n", "buy_rate", "avg_visit", "avg_search", "avg_purchases",
        "priority", "over_contact_risk", "crm_purpose"]],
    use_container_width=True, hide_index=True,
    column_config={
        "segment": st.column_config.TextColumn("세그먼트", width="medium"),
        "n": st.column_config.NumberColumn("인원", width="small", format="%d"),
        "buy_rate": st.column_config.NumberColumn("구매율", width="small", format="%.2f"),
        "avg_visit": st.column_config.NumberColumn("평균 방문", width="small", format="%.2f"),
        "avg_search": st.column_config.NumberColumn("평균 검색", width="small", format="%.2f"),
        "avg_purchases": st.column_config.NumberColumn("평균 구매", width="small", format="%.2f"),
        "priority": st.column_config.TextColumn("우선순위", width="small"),
        "over_contact_risk": st.column_config.TextColumn("과접촉 위험", width="small"),
        "crm_purpose": st.column_config.TextColumn("CRM 목적", width="large"),
    },
)

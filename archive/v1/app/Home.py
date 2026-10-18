import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.dashboard.data import show_data_period_notice
from src.dashboard.theme import inject_global_css

st.set_page_config(page_title="이커머스 CRM 타기팅 분석", page_icon="📊", layout="wide")
inject_global_css()

st.title("이커머스 고객 행동 퍼널 분석 및 CRM 타기팅 전략 설계")

st.markdown(
    """
이커머스에서 CRM에 쓸 수 있는 자원은 한정돼 있는데, 모든 고객에게 똑같이
메시지를 보내는 게 최선일까요? 고객의 탐색·장바구니·구매 행동을 보고,
어떤 고객에게 재활성화 메시지를, 어떤 고객에게 구매 유도 메시지를 먼저
보낼지 타기팅 우선순위를 매기는 분석 시스템입니다.
"""
)

show_data_period_notice()

st.markdown("---")
st.subheader("페이지 안내")

PAGES = [
    ("📊", "Overview", "핵심 KPI와 퍼널 요약"),
    ("🔻", "Funnel", "탐색→장바구니→구매 고객 단위 퍼널"),
    ("📈", "Cohort & Retention", "첫 관측 구매 주차 코호트별 재구매율"),
    ("🔄", "Lifecycle", "고객 라이프사이클 8개 상태 분포"),
    ("🧩", "Segment Explorer", "CRM 세그먼트별 특성과 추천 액션"),
    ("🎯", "Targeting Simulator", "접촉 비율별 모델 vs 규칙 기반 타기팅 비교"),
    ("📝", "AI CRM Report", "SQL 집계 기반 Data Facts/Model Predictions + LLM이 생성한 "
     "Recommended Actions/Testable Hypotheses (API 키 없으면 mock 백엔드로 동작)"),
]

cols = st.columns(3)
for i, (icon, title, desc) in enumerate(PAGES):
    with cols[i % 3]:
        with st.container(border=True, key=f"nav-card-{i}"):
            st.markdown(f"**{icon}&nbsp;&nbsp;{title}**")
            st.caption(desc)

st.caption("왼쪽 사이드바에서 페이지를 선택하세요.")

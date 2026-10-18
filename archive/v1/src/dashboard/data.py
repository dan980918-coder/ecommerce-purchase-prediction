"""Streamlit 대시보드 데이터 로더. data/dashboard/의 사전 집계 파일만 읽는다."""

from pathlib import Path

import pandas as pd
import streamlit as st

DASHBOARD_DIR = Path("data/dashboard")

DATA_PERIOD_CAPTION = (
    "📅 관측 기간: 2022-06-23 ~ 2022-12-08 (167일) — 최신 고객 행동이 아닌 "
    "특정 시점 스냅샷"
)


def format_count(n) -> str:
    """큰 숫자를 한국어 단위(만/억)로 축약 표시.

    st.metric은 좁은 컬럼에서 8자리 이상 숫자를 자동 줄바꿈하지 않고 "..."로
    잘라버린다 — 이 축약은 그 문제를 막기 위함이다. 소수점 없이 정수로만 표시해
    카드 폭이 좁아도(뷰포트/컬럼 수에 따라 가변적) 잘리지 않도록 여유를 둔다.
    정확한 값은 항상 help 파라미터 등으로 별도 표기한다(with_exact_help 참고).
    """
    n = float(n)
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n >= 100_000_000:
        return f"{sign}{n / 100_000_000:.0f}억"
    if n >= 10_000:
        return f"{sign}{n / 10_000:.0f}만"
    return f"{sign}{n:,.0f}"


def with_exact_help(value, existing_help: str = "") -> str:
    """format_count로 축약 표시할 때 st.metric의 help 툴팁에 정확한 값을 남긴다."""
    exact = f"정확한 값: {value:,.0f}"
    return f"{exact} — {existing_help}" if existing_help else exact


@st.cache_data
def load_overview_kpis() -> dict:
    df = pd.read_csv(DASHBOARD_DIR / "overview_kpis.csv")
    return dict(zip(df["metric"], df["value"]))


@st.cache_data
def load_funnel_summary() -> dict:
    df = pd.read_csv(DASHBOARD_DIR / "funnel_summary.csv")
    return dict(zip(df["stage_metric"], df["value"]))


@st.cache_data
def load_cohort_retention() -> pd.DataFrame:
    df = pd.read_csv(DASHBOARD_DIR / "cohort_retention.csv", parse_dates=["cohort_week"])
    return df


@st.cache_data
def load_lifecycle_distribution() -> pd.DataFrame:
    return pd.read_csv(DASHBOARD_DIR / "lifecycle_distribution.csv")


@st.cache_data
def load_segment_profile() -> pd.DataFrame:
    return pd.read_csv(DASHBOARD_DIR / "segment_profile.csv")


@st.cache_data
def load_targeting_simulation() -> pd.DataFrame:
    return pd.read_csv(DASHBOARD_DIR / "targeting_simulation.csv")


def show_data_period_notice() -> None:
    st.caption(DATA_PERIOD_CAPTION)

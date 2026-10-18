"""대시보드 공통 디자인 시스템 — 기능적(semantic) 색상, 다크 사이드바, Plotly 테마.

Amplitude/Mixpanel류 분석 대시보드를 참고: 브랜드 컬러 하나로 통일하지 않고, 상태를
색으로 구분한다 — positive(초록)=성장/양호, warning(주황)=위험 신호, danger(빨강)=이탈/
비활성, neutral(블루)=구조적 지표. .streamlit/config.toml의 [theme] 값과 대략 맞춘다.
"""

import streamlit as st

# --- 기능적 색상 ---
BRAND = "#2F6FED"
BRAND_SOFT = "#EFF4FF"
BRAND_TEXT = "#1D4ED8"

POSITIVE = "#16A34A"
POSITIVE_SOFT = "#F0FDF4"
POSITIVE_TEXT = "#15803D"

WARNING = "#F97316"
WARNING_SOFT = "#FFF7ED"
WARNING_TEXT = "#C2410C"

DANGER = "#DC2626"
DANGER_SOFT = "#FEF2F2"
DANGER_TEXT = "#B91C1C"

TEXT = "#111827"
MUTED = "#6B7280"
BORDER = "#E5E7EB"
BG_SUBTLE = "#F9FAFB"

SIDEBAR_BG = "#111827"
SIDEBAR_BG_ACTIVE = "#1F2937"
SIDEBAR_TEXT = "#D1D5DB"
SIDEBAR_TEXT_MUTED = "#9CA3AF"

TONE_ACCENT = {"neutral": BRAND, "positive": POSITIVE, "warning": WARNING, "danger": DANGER}
TONE_SOFT = {"neutral": "#FFFFFF", "positive": POSITIVE_SOFT, "warning": WARNING_SOFT, "danger": DANGER_SOFT}
TONE_TEXT = {"neutral": TEXT, "positive": POSITIVE_TEXT, "warning": WARNING_TEXT, "danger": DANGER_TEXT}

# 다중 시리즈 차트용 컬러웨이 — 브랜드 블루를 기본으로, 상태색을 보조로 사용
PLOTLY_COLORWAY = [BRAND, POSITIVE, WARNING, DANGER, "#8B5CF6", "#9CA3AF"]

FONT_FAMILY = (
    "'Pretendard Variable', Pretendard, -apple-system, BlinkMacSystemFont, "
    "'Segoe UI', system-ui, sans-serif"
)

_FONT_CSS_URL = (
    "https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/"
    "pretendardvariable-dynamic-subset.css"
)

_GLOBAL_CSS = f"""
<style>
@import url('{_FONT_CSS_URL}');

/* [data-testid="stIconMaterial"]는 Streamlit이 Material Symbols 폰트의 리게처
   (예: "keyboard_double_arrow_left" 텍스트 → 화살표 글리프)로 렌더링하는
   아이콘이다. 이 규칙에 포함시키면 리게처가 깨져 아이콘 대신 아이콘 이름
   텍스트가 그대로 노출된다(사이드바 접기 버튼 등) — 반드시 제외해야 한다. */
html, body, [class*="st-emotion"]:not([data-testid="stIconMaterial"]) {{
    font-family: {FONT_FAMILY} !important;
}}

.block-container {{
    padding-top: 1.5rem;
    padding-bottom: 2rem;
    max-width: 1400px;
}}

h1 {{
    font-weight: 800 !important;
    font-size: 1.65rem !important;
    letter-spacing: -0.02em;
    color: {TEXT};
    margin-bottom: 0.15rem !important;
}}
h2, h3 {{
    font-weight: 700 !important;
    font-size: 0.95rem !important;
    letter-spacing: -0.01em;
    color: {TEXT};
    margin-top: 1.1rem !important;
    margin-bottom: 0.4rem !important;
}}

p, li, [data-testid="stMarkdownContainer"] {{
    color: {TEXT};
    line-height: 1.55;
    font-size: 0.92rem;
}}

[data-testid="stHorizontalBlock"] {{
    gap: 0.55rem;
}}

/* --- Metric 카드: 고밀도, 톤별 기능색, 보조지표(delta 슬롯) --- */
[data-testid="stMetric"] {{
    background: #FFFFFF;
    border: 1px solid {BORDER};
    border-top: 3px solid {BRAND};
    border-radius: 4px;
    padding: 0.5rem 0.7rem 0.45rem;
}}
[data-testid="stMetricLabel"] {{
    color: {MUTED} !important;
    font-size: 0.68rem !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.02em;
}}
[data-testid="stMetricValue"] {{
    color: {TEXT} !important;
    font-weight: 800 !important;
    font-size: 1.7rem !important;
    letter-spacing: -0.02em;
    line-height: 1.2;
}}
[data-testid="stMetricDelta"] svg {{ display: none; }}
[data-testid="stMetricDelta"] {{
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    padding-top: 0.05rem;
}}

[class*="st-key-tone-positive"] [data-testid="stMetric"] {{
    background: {POSITIVE_SOFT}; border-top-color: {POSITIVE};
}}
[class*="st-key-tone-positive"] [data-testid="stMetricValue"] {{ color: {POSITIVE_TEXT} !important; }}

[class*="st-key-tone-warning"] [data-testid="stMetric"] {{
    background: {WARNING_SOFT}; border-top-color: {WARNING};
}}
[class*="st-key-tone-warning"] [data-testid="stMetricValue"] {{ color: {WARNING_TEXT} !important; }}

[class*="st-key-tone-danger"] [data-testid="stMetric"] {{
    background: {DANGER_SOFT}; border-top-color: {DANGER};
}}
[class*="st-key-tone-danger"] [data-testid="stMetricValue"] {{ color: {DANGER_TEXT} !important; }}

[data-testid="stCaptionContainer"] {{
    color: {MUTED} !important;
    font-size: 0.79rem;
}}

hr {{ border-color: {BORDER}; margin: 1rem 0 !important; }}

div[data-testid="stAlert"] {{
    border-radius: 6px;
    border: 1px solid {BORDER};
    padding: 0.55rem 0.8rem;
    font-size: 0.85rem;
}}

[data-testid="stDataFrame"] {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    overflow: hidden;
}}

[data-testid="stTable"] table {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    font-size: 0.85rem;
}}
[data-testid="stTable"] th {{
    color: {MUTED};
    font-weight: 600;
    background: {BG_SUBTLE};
}}

.crm-badge {{
    display: inline-block;
    padding: 0.08rem 0.55rem;
    border-radius: 999px;
    font-size: 0.7rem;
    font-weight: 700;
    margin-right: 0.45rem;
    white-space: nowrap;
    vertical-align: middle;
}}
.crm-badge-danger {{ background: {DANGER_SOFT}; color: {DANGER_TEXT}; }}
.crm-badge-warning {{ background: {WARNING_SOFT}; color: {WARNING_TEXT}; }}
.crm-badge-neutral {{ background: {BG_SUBTLE}; color: {MUTED}; }}

[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius: 6px !important; }}
[class*="st-key-nav-card"] [data-testid="stVerticalBlockBorderWrapper"] > div {{
    padding: 0.65rem 0.85rem 0.7rem !important;
}}
[class*="st-key-stat-table"] [data-testid="stVerticalBlockBorderWrapper"] > div {{
    padding: 0.7rem 0.9rem !important;
}}

/* --- 다크 사이드바 (Amplitude/Mixpanel 스타일) --- */
section[data-testid="stSidebar"] {{
    background-color: {SIDEBAR_BG} !important;
    border-right: none;
}}
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] label {{
    color: {SIDEBAR_TEXT} !important;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] {{
    border-radius: 5px;
    margin: 0.05rem 0.4rem;
    color: {SIDEBAR_TEXT_MUTED} !important;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"]:hover {{
    background-color: {SIDEBAR_BG_ACTIVE} !important;
    color: #FFFFFF !important;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] {{
    background-color: {SIDEBAR_BG_ACTIVE} !important;
    border-left: 3px solid {BRAND};
    color: #FFFFFF !important;
    font-weight: 600;
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] span {{
    color: #FFFFFF !important;
}}
section[data-testid="stSidebar"] hr {{ border-color: {SIDEBAR_BG_ACTIVE}; }}
</style>
"""


def inject_global_css() -> None:
    """모든 페이지 상단(set_page_config 직후)에서 호출해 공통 스타일을 적용한다."""
    st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)


def metric(
    column,
    key: str,
    label: str,
    value: str,
    sub: str | None = None,
    help: str | None = None,
    tone: str = "neutral",
) -> None:
    """톤(neutral/positive/warning/danger)이 적용된 고밀도 metric 카드를 렌더링한다.

    sub는 st.metric의 delta 슬롯을 재사용해 보조 지표(예: "구매 고객의 8.1%")를
    보여준다 — 방향성 있는 증감이 아니므로 delta_color="off"(화살표 없음)로 고정한다.
    """
    with column.container(key=f"tone-{tone}-{key}", border=False):
        st.metric(label, value, delta=sub, delta_color="off", help=help, border=True)


def badge(label: str, tone: str = "neutral", icon: str = "") -> str:
    """색상 배지 HTML 조각을 반환한다 (unsafe_allow_html=True인 st.markdown에서 사용)."""
    prefix = f"{icon} " if icon else ""
    return f'<span class="crm-badge crm-badge-{tone}">{prefix}{label}</span>'


def themed_layout(fig, height: int | None = None):
    """Plotly figure에 대시보드 공통 컬러·폰트·여백을 적용한다."""
    fig.update_layout(
        colorway=PLOTLY_COLORWAY,
        font=dict(family=FONT_FAMILY, color=TEXT, size=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=25, b=10),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    if height:
        fig.update_layout(height=height)
    fig.update_xaxes(gridcolor=BORDER, zeroline=False, linecolor=BORDER)
    fig.update_yaxes(gridcolor=BORDER, zeroline=False, linecolor=BORDER)
    return fig

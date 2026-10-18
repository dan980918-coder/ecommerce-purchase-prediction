import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.dashboard.data import format_count, load_targeting_simulation, show_data_period_notice, with_exact_help
from src.dashboard.theme import BRAND, MUTED, POSITIVE, inject_global_css, metric, themed_layout

st.set_page_config(page_title="Targeting Simulator", page_icon="🎯", layout="wide")
inject_global_css()
st.title("CRM Targeting Simulator")
show_data_period_notice()

st.caption(
    "테스트셋(out-of-sample, 2022-10-27/2022-11-10, 학습에 쓰이지 않은 시점) 기준 시뮬레이션입니다."
)

df = load_targeting_simulation()

model_choice = st.radio(
    "모델 선택", ["Model_A_churn (구매 비활성 위험)", "Model_B_propensity (향후 구매 가능성)"],
    horizontal=True,
)
model_key = "Model_A_churn" if model_choice.startswith("Model_A") else "Model_B_propensity"

labels_available = sorted(df[df["model"] == model_key]["label"].unique())
label_choice = st.radio("라벨(기간) 선택", labels_available, horizontal=True)

contact_rate = st.select_slider("접촉 비율", options=[5, 10, 20, 30], value=10)

sub = df[(df["model"] == model_key) & (df["label"] == label_choice) & (df["contact_rate_pct"] == contact_rate)]
main_policies = sub[~sub["policy"].str.startswith("모델_vs")]
compare_row = sub[sub["policy"].str.startswith("모델_vs")]


def _policy_color(name: str) -> str:
    if name.startswith("모델"):
        return POSITIVE
    if name.startswith("무작위"):
        return MUTED
    return BRAND


st.subheader(f"접촉 비율 {contact_rate}% — 정책별 비교")
fig = go.Figure()
fig.add_trace(go.Bar(
    x=main_policies["policy"], y=main_policies["recall"] * 100, name="Recall(%)",
    marker_color=main_policies["policy"].map(_policy_color),
))
fig.update_layout(yaxis_title="Recall (%)")
themed_layout(fig, height=360)
st.plotly_chart(fig, use_container_width=True)
st.caption("초록 막대(모델_LightGBM)가 규칙 기반 정책 대비 Recall 우위를 나타냅니다.")

st.subheader("정확한 값")
st.dataframe(
    main_policies[["policy", "n_selected", "n_actual_captured", "precision", "recall", "lift"]]
    .rename(columns={"policy": "정책", "n_selected": "선정 인원", "n_actual_captured": "실제 포착",
                      "precision": "Precision", "recall": "Recall", "lift": "Lift"}),
    use_container_width=True, hide_index=True,
)
if model_key == "Model_A_churn":
    st.caption(
        "💡 Model A는 AUC 기준으로 평가하는 게 적절합니다 (라벨 구조상 Lift 개선은 "
        "제한적, 근거: `docs/hypotheses.md` 9번)."
    )

if not compare_row.empty:
    r = compare_row.iloc[0]
    st.markdown("---")
    st.subheader("모델 vs 최근성 규칙 — 동일 Recall 달성 시 접촉 인원 비교")
    c1, c2, c3 = st.columns(3)
    metric(c1, "modeln", "모델 접촉 인원", format_count(r['n_selected']), help=with_exact_help(r['n_selected']))
    metric(c2, "rulen", "규칙 필요 인원", format_count(r['customers_needed_by_rule_for_same_recall']),
           help=with_exact_help(r['customers_needed_by_rule_for_same_recall'],
                                 "모델과 동일한 Recall을 최근성 규칙으로 달성하려면 필요한 접촉 인원"))
    metric(c3, "reduction", "접촉 인원 절감률", f"{r['contact_reduction_pct']:.2f}%", tone="positive")
    st.caption(
        f"→ 상위 {contact_rate}% 고객을 모델로 선정했을 때, 단순 최근성 기준보다 "
        f"동일한 포착률(Recall {r['recall']*100:.2f}%)을 {r['contact_reduction_pct']:.2f}% "
        "더 적은 인원으로 달성했습니다."
    )

"""data/dashboard/의 사전 검증된 집계 파일을 CRMReportInput으로 구성한다.

scripts/generate_crm_report.py(CLI)와 app/pages/7_AI_CRM_Report.py(대시보드)가
동일한 로직을 공유하기 위해 분리했다.
"""

from datetime import date
from pathlib import Path

import pandas as pd

from src.llm.schemas import CRMReportInput, DataFact, ModelPredictionFact, SegmentFact

DASHBOARD_DIR = Path("data/dashboard")
PERIOD_START = date(2022, 6, 23)
PERIOD_END = date(2022, 12, 8)

HIGH_PRIORITY_LABELS = ["매우 높음", "높음", "높음(유지 목적)"]


def build_report_input(contact_rate_pct: int = 10) -> CRMReportInput:
    kpi_df = pd.read_csv(DASHBOARD_DIR / "overview_kpis.csv")
    kpi = dict(zip(kpi_df["metric"], kpi_df["value"]))

    data_facts = [
        DataFact(label="전체 고객", value=kpi["total_customers"], unit="명"),
        DataFact(label="구매 고객", value=kpi["buyers"], unit="명"),
        DataFact(label="비활성 위험 고객", value=kpi["at_risk_customers"], unit="명"),
        DataFact(label="비활성 고객", value=kpi["inactive_customers"], unit="명"),
    ]

    seg_df = pd.read_csv(DASHBOARD_DIR / "segment_profile.csv")
    priority_segments = seg_df[seg_df["priority"].isin(HIGH_PRIORITY_LABELS)]
    segment_facts = [
        SegmentFact(
            segment=row["segment"],
            n_customers=int(row["n"]),
            buy_rate=float(row["buy_rate"]),
            crm_purpose=row["crm_purpose"],
            priority=row["priority"],
        )
        for _, row in priority_segments.iterrows()
    ]

    sim_df = pd.read_csv(DASHBOARD_DIR / "targeting_simulation.csv")
    model_rows = sim_df[
        (sim_df["policy"] == "모델_LightGBM") & (sim_df["contact_rate_pct"] == contact_rate_pct)
    ]
    model_predictions = [
        ModelPredictionFact(
            model_name=row["model"],
            label=row["label"],
            contact_rate_pct=int(row["contact_rate_pct"]),
            recall=float(row["recall"]),
            lift=float(row["lift"]),
            precision=float(row["precision"]),
        )
        for _, row in model_rows.iterrows()
    ]

    return CRMReportInput(
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        data_facts=data_facts,
        segment_facts=segment_facts,
        model_predictions=model_predictions,
    )

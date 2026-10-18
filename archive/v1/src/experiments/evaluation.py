"""Phase 8 - A/B 테스트 결과 평가.

이 프로젝트는 실제로 CRM을 발송한 적이 없다 — src/experiments/assignment.py가
만드는 건 "누구를 어느 그룹에 배정할지"까지다. exposure_df(실제로 누가 CRM을
받았고 그 후 KPI가 어땠는지 기록된 데이터)가 없으면 이 모듈은 어떤 형태로도
성과 수치를 계산하지 않는다 — 실행되지 않은 실험의 결과를 만들어낼 수는
없다(PROJECT_GUIDELINES.md 5번 "프로젝트에서 주장할 수 있는 것과 없는 것"
원칙). exposure_df가 주어지지 않으면 evaluate_experiment()는 모든 수치
필드가 비어 있는 status="미측정" 결과만 반환한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

STATUS_UNMEASURED = "미측정"
STATUS_MEASURED = "측정됨"


@dataclass
class ExperimentResult:
    status: str
    kpi_col: str | None = None
    n_treatment: int | None = None
    n_control: int | None = None
    mean_treatment: float | None = None
    mean_control: float | None = None
    diff: float | None = None
    lift_pct: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    p_value: float | None = None
    note: str = ""


def _unmeasured(kpi_col: str, note: str) -> ExperimentResult:
    return ExperimentResult(status=STATUS_UNMEASURED, kpi_col=kpi_col, note=note)


def evaluate_experiment(
    exposure_df: pd.DataFrame | None,
    kpi_col: str,
    confidence: float = 0.95,
) -> ExperimentResult:
    """Treatment/Control 그룹 간 kpi_col의 차이·lift·신뢰구간·p-value를 계산한다.

    exposure_df: client_id, group(Treatment/Control), kpi_col을 포함하는,
    실제로 CRM을 받은 뒤 관측된 KPI 데이터. 이게 None이거나 비어 있거나
    필요한 컬럼이 없으면, 또는 두 그룹 중 하나에 유효한 관측치가 전혀 없으면
    계산을 진행하지 않고 status="미측정"만 반환한다 — 가상의 결과를
    만들어내지 않는다.
    """
    if exposure_df is None or len(exposure_df) == 0:
        return _unmeasured(
            kpi_col,
            "exposure_df가 없어 실험 결과를 계산하지 않았다 — 실제 CRM 발송·수신 "
            "기록이 있어야 측정 가능하며, 이 프로젝트에서는 실행된 적이 없다.",
        )

    missing_cols = {"group", kpi_col} - set(exposure_df.columns)
    if missing_cols:
        return _unmeasured(
            kpi_col,
            f"exposure_df에 필요한 컬럼이 없어 계산하지 않았다: {sorted(missing_cols)}.",
        )

    treat = exposure_df.loc[exposure_df["group"] == "Treatment", kpi_col].dropna()
    ctrl = exposure_df.loc[exposure_df["group"] == "Control", kpi_col].dropna()
    if len(treat) == 0 or len(ctrl) == 0:
        return _unmeasured(
            kpi_col,
            "Treatment 또는 Control 그룹에 유효한 관측치가 없어 계산하지 않았다.",
        )

    mean_t, mean_c = float(treat.mean()), float(ctrl.mean())
    diff = mean_t - mean_c
    lift_pct = (mean_t / mean_c - 1) * 100 if mean_c != 0 else float("nan")

    # Welch's t-test — 두 그룹 표본 크기·분산이 다를 수 있다는 가정하에
    # 등분산을 요구하지 않는 쪽이 더 안전한 기본값이다.
    _, p_value = stats.ttest_ind(treat, ctrl, equal_var=False)

    se = np.sqrt(treat.var(ddof=1) / len(treat) + ctrl.var(ddof=1) / len(ctrl))
    z = stats.norm.ppf(0.5 + confidence / 2)
    ci_low, ci_high = diff - z * se, diff + z * se

    return ExperimentResult(
        status=STATUS_MEASURED,
        kpi_col=kpi_col,
        n_treatment=len(treat),
        n_control=len(ctrl),
        mean_treatment=mean_t,
        mean_control=mean_c,
        diff=diff,
        lift_pct=float(lift_pct),
        ci_low=float(ci_low),
        ci_high=float(ci_high),
        p_value=float(p_value),
    )

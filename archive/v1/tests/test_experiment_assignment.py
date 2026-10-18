"""Phase 8 실험 배정/평가 코드 검증.

evaluate_experiment()가 실제 exposure 데이터 없이는 절대로 "측정됨" 상태나
가짜 성과 수치를 반환하지 않는지가 이 파일에서 가장 중요하게 검증하는
부분이다(PROJECT_GUIDELINES.md 5번 원칙). 여기서 쓰는 더미 데이터는 이
테스트 함수 안에서만 존재하며 reports/나 README 등 어떤 산출물에도 쓰이지
않는다.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.experiments.assignment import (
    assign_treatment_control,
    check_balance,
    check_sample_ratio_mismatch,
)
from src.experiments.evaluation import STATUS_MEASURED, STATUS_UNMEASURED, evaluate_experiment


def _dummy_population(n: int = 4000, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "client_id": np.arange(n),
            "propensity_score": rng.random(n),
            "days_since_last_purchase": rng.integers(0, 90, n).astype(float),
            "n_page_visit_28d": rng.poisson(3, n).astype(float),
        }
    )


SCORE_BINS = [("상위10%", 0, 10), ("10~30%", 10, 30), ("30~50%", 30, 50)]


class TestAssignTreatmentControl:
    def test_only_customers_within_score_bins_are_assigned(self):
        df = _dummy_population()
        assigned = assign_treatment_control(df, "propensity_score", SCORE_BINS, seed=1)
        # 상위 50%까지만 정의했으므로 배정 인원은 모집단의 절반 근처여야 함
        assert 0.45 * len(df) <= len(assigned) <= 0.55 * len(df)
        assert set(assigned["segment"]) == {"상위10%", "10~30%", "30~50%"}

    def test_ratio_is_50_50_within_each_segment(self):
        df = _dummy_population()
        assigned = assign_treatment_control(df, "propensity_score", SCORE_BINS, seed=1)
        for seg, sub in assigned.groupby("segment"):
            n_treat = (sub["group"] == "Treatment").sum()
            n_ctrl = (sub["group"] == "Control").sum()
            assert abs(n_treat - n_ctrl) <= 1, f"{seg} 배정 비율이 50:50에서 크게 벗어남"

    def test_deterministic_given_same_seed(self):
        df = _dummy_population()
        a1 = assign_treatment_control(df, "propensity_score", SCORE_BINS, seed=7)
        a2 = assign_treatment_control(df, "propensity_score", SCORE_BINS, seed=7)
        pd.testing.assert_frame_equal(a1, a2)

    def test_no_result_or_outcome_columns_present(self):
        """배정표에는 발송 여부·성과 관련 컬럼이 절대 있으면 안 된다."""
        df = _dummy_population()
        assigned = assign_treatment_control(df, "propensity_score", SCORE_BINS, seed=1)
        forbidden = {"kpi", "revenue", "lift", "p_value", "outcome", "converted"}
        assert forbidden.isdisjoint(assigned.columns)


class TestCheckBalance:
    def test_returns_one_row_per_covariate_with_expected_columns(self):
        df = _dummy_population()
        assigned = assign_treatment_control(df, "propensity_score", SCORE_BINS, seed=1)
        assigned = assigned.merge(
            df[["client_id", "days_since_last_purchase", "n_page_visit_28d"]], on="client_id"
        )
        covariates = ["days_since_last_purchase", "n_page_visit_28d"]
        result = check_balance(assigned, covariates)
        assert list(result["covariate"]) == covariates
        assert {"n_treatment", "n_control", "mean_treatment", "mean_control", "p_value", "balanced"} <= set(
            result.columns
        )
        assert result["p_value"].between(0, 1).all()

    def test_randomized_assignment_is_usually_balanced(self):
        """동일 분포에서 무작위 배정했으므로 covariate 평균이 균형이어야 한다
        (통계 검정 특성상 항상 100% 보장은 아니지만, 고정 seed에서는 재현 가능)."""
        df = _dummy_population(n=8000, seed=3)
        assigned = assign_treatment_control(df, "propensity_score", SCORE_BINS, seed=3)
        assigned = assigned.merge(df[["client_id", "days_since_last_purchase"]], on="client_id")
        result = check_balance(assigned, ["days_since_last_purchase"])
        assert bool(result.loc[0, "balanced"]) is True


class TestCheckSampleRatioMismatch:
    def test_no_srm_for_intended_50_50_assignment(self):
        df = _dummy_population()
        assigned = assign_treatment_control(df, "propensity_score", SCORE_BINS, seed=1)
        result = check_sample_ratio_mismatch(assigned)
        assert (result["srm_detected"] == False).all()  # noqa: E712

    def test_srm_detected_for_artificially_skewed_assignment(self):
        df = _dummy_population()
        assigned = assign_treatment_control(df, "propensity_score", SCORE_BINS, seed=1)
        # 의도적으로 90:10에 가깝게 왜곡시켜 SRM이 실제로 걸리는지 확인
        skewed = assigned.copy()
        n = len(skewed)
        skewed["group"] = ["Treatment"] * int(n * 0.9) + ["Control"] * (n - int(n * 0.9))
        result = check_sample_ratio_mismatch(skewed)
        overall = result[result["segment"] == "전체"].iloc[0]
        assert bool(overall["srm_detected"]) is True


class TestEvaluateExperiment:
    def test_none_exposure_returns_unmeasured(self):
        result = evaluate_experiment(None, kpi_col="converted")
        assert result.status == STATUS_UNMEASURED
        assert result.diff is None
        assert result.lift_pct is None
        assert result.p_value is None

    def test_empty_exposure_returns_unmeasured(self):
        result = evaluate_experiment(pd.DataFrame(), kpi_col="converted")
        assert result.status == STATUS_UNMEASURED
        assert result.mean_treatment is None

    def test_missing_columns_returns_unmeasured(self):
        df = pd.DataFrame({"client_id": [1, 2], "group": ["Treatment", "Control"]})
        result = evaluate_experiment(df, kpi_col="converted")  # converted 컬럼 없음
        assert result.status == STATUS_UNMEASURED

    def test_one_sided_group_returns_unmeasured(self):
        df = pd.DataFrame(
            {"client_id": [1, 2, 3], "group": ["Treatment", "Treatment", "Treatment"], "converted": [1, 0, 1]}
        )
        result = evaluate_experiment(df, kpi_col="converted")
        assert result.status == STATUS_UNMEASURED

    def test_valid_exposure_returns_measured_with_correct_diff(self):
        """실제 발송 기록이 있는 경우에만 계산이 이뤄지는지, 계산 자체가
        맞는지 더미 데이터로 확인한다 — 이 값은 어떤 산출물에도 노출되지 않는다."""
        rng = np.random.default_rng(42)
        n = 2000
        df = pd.DataFrame(
            {
                "client_id": np.arange(n),
                "group": ["Treatment"] * (n // 2) + ["Control"] * (n // 2),
                "converted": np.concatenate(
                    [rng.binomial(1, 0.30, n // 2), rng.binomial(1, 0.20, n // 2)]
                ),
            }
        )
        result = evaluate_experiment(df, kpi_col="converted")
        assert result.status == STATUS_MEASURED
        assert result.n_treatment == n // 2
        assert result.n_control == n // 2
        assert result.mean_treatment == pytest.approx(df.loc[df["group"] == "Treatment", "converted"].mean())
        assert result.mean_control == pytest.approx(df.loc[df["group"] == "Control", "converted"].mean())
        assert result.diff == pytest.approx(result.mean_treatment - result.mean_control)
        assert result.p_value is not None and 0 <= result.p_value <= 1
        assert result.ci_low < result.ci_high

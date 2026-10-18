"""Phase 8 - A/B 테스트 Treatment/Control 배정 및 배정 품질 점검.

README "8. 향후 확장"에서 제안한 실험 설계(Model B 점수 구간별로 나눈 뒤
구간 내에서 Treatment/Control을 무작위 배정)를 실제로 실행하는 코드다.
여기서 만드는 건 "누구를 어느 그룹에 배정할지"와 "그 배정이 통계적으로
문제없는지"까지다 — 실제로 CRM을 보낸 적이 없으므로 실험 '결과'(Treatment가
더 나았는지)는 이 모듈이 다루지 않는다. 결과 계산은 src/experiments/evaluation.py
쪽 책임이며, 실제 발송 기록(exposure 데이터)이 없는 한 항상 미측정으로 남는다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def assign_treatment_control(
    df: pd.DataFrame,
    score_col: str,
    score_bins: list[tuple[str, float, float]],
    seed: int = 42,
) -> pd.DataFrame:
    """score_col 기준 상위 퍼센트 구간(score_bins)으로 고객을 나누고, 각 구간
    안에서 Treatment/Control을 50:50으로 무작위 배정한다.

    score_bins: (구간 라벨, 상위 퍼센트 하한, 상위 퍼센트 상한) 튜플 리스트.
        예: [("상위10%", 0, 10), ("10~30%", 10, 30), ("30~50%", 30, 50)]
        "상위 X%"는 score_col을 내림차순으로 정렬했을 때의 백분위(0=최고점)다.
        구간에 속하지 않는 고객(예: 하위 50%)은 결과에 포함되지 않는다.

    반환: client_id, score_col, segment(구간 라벨), group(Treatment/Control)만
    담은 배정표. 실제 발송 여부나 실험 결과 컬럼은 없다 — 이 함수는 배정만 한다.
    """
    d = df[["client_id", score_col]].copy()
    # rank(pct=True)는 낮은 값이 낮은 백분위가 되므로, 1에서 빼서 "상위 몇 %"로 뒤집는다.
    d["_pct_from_top"] = (1 - d[score_col].rank(pct=True, method="average")) * 100

    segments = []
    for label, lo, hi in score_bins:
        mask = (d["_pct_from_top"] >= lo) & (d["_pct_from_top"] < hi)
        seg = d.loc[mask, ["client_id", score_col]].copy()
        seg["segment"] = label
        segments.append(seg)

    if segments:
        assigned = pd.concat(segments, ignore_index=True)
    else:
        assigned = pd.DataFrame(columns=["client_id", score_col, "segment"])

    rng = np.random.default_rng(seed)
    group = pd.Series(index=assigned.index, dtype=object)
    for label, _, _ in score_bins:
        idx = assigned.index[assigned["segment"] == label]
        n = len(idx)
        if n == 0:
            continue
        half = n // 2
        arm = np.array(["Treatment"] * half + ["Control"] * (n - half))
        rng.shuffle(arm)
        group.loc[idx] = arm
    assigned["group"] = group

    return assigned.reset_index(drop=True)


def check_balance(assigned_df: pd.DataFrame, covariate_cols: list[str]) -> pd.DataFrame:
    """Treatment/Control 두 그룹 간 과거 행동 covariate가 통계적으로 균형
    잡혔는지 검정한다.

    covariate가 대부분 오른쪽으로 치우친 카운트형 변수(방문 수, 검색 수,
    구매 경과일 등)라 정규분포를 가정하는 t-test 대신 분포 가정이 필요 없는
    Mann-Whitney U 검정(양측)을 쓴다. p_value >= 0.05면 균형(balanced=True)으로
    본다 — 이 검정은 배정이 제대로 무작위화됐는지에 대한 사전 점검일 뿐,
    실험 결과가 아니다.
    """
    treat = assigned_df[assigned_df["group"] == "Treatment"]
    ctrl = assigned_df[assigned_df["group"] == "Control"]

    rows = []
    for col in covariate_cols:
        t_vals = treat[col].dropna()
        c_vals = ctrl[col].dropna()
        if len(t_vals) == 0 or len(c_vals) == 0:
            rows.append(
                {
                    "covariate": col,
                    "n_treatment": len(t_vals),
                    "n_control": len(c_vals),
                    "mean_treatment": np.nan,
                    "mean_control": np.nan,
                    "statistic": np.nan,
                    "p_value": np.nan,
                    "balanced": None,
                }
            )
            continue
        stat, p = stats.mannwhitneyu(t_vals, c_vals, alternative="two-sided")
        rows.append(
            {
                "covariate": col,
                "n_treatment": len(t_vals),
                "n_control": len(c_vals),
                "mean_treatment": float(t_vals.mean()),
                "mean_control": float(c_vals.mean()),
                "statistic": float(stat),
                "p_value": float(p),
                "balanced": bool(p >= 0.05),
            }
        )
    return pd.DataFrame(rows)


def check_sample_ratio_mismatch(assigned_df: pd.DataFrame, expected_ratio: float = 0.5) -> pd.DataFrame:
    """의도한 배정 비율(기본 50:50)이 세그먼트별·전체 기준으로 실제로
    깨지지 않았는지 카이제곱 적합도 검정으로 확인한다.

    SRM(Sample Ratio Mismatch) 점검은 관례적으로 일반 유의수준(0.05)보다
    엄격한 0.01을 기준으로 쓴다 — 배정 로직 자체의 버그를 잡기 위한
    점검이라, 우연에 의한 오탐을 줄이는 쪽이 더 중요하기 때문이다.
    """

    def _srm_row(sub: pd.DataFrame, label: str) -> dict:
        n_treat = int((sub["group"] == "Treatment").sum())
        n_ctrl = int((sub["group"] == "Control").sum())
        n = n_treat + n_ctrl
        if n == 0:
            return {
                "segment": label,
                "n_treatment": 0,
                "n_control": 0,
                "chi2": np.nan,
                "p_value": np.nan,
                "srm_detected": None,
            }
        expected = [n * expected_ratio, n * (1 - expected_ratio)]
        chi2, p = stats.chisquare([n_treat, n_ctrl], f_exp=expected)
        return {
            "segment": label,
            "n_treatment": n_treat,
            "n_control": n_ctrl,
            "chi2": float(chi2),
            "p_value": float(p),
            "srm_detected": bool(p < 0.01),
        }

    rows = [_srm_row(sub, seg) for seg, sub in assigned_df.groupby("segment")]
    rows.append(_srm_row(assigned_df, "전체"))
    return pd.DataFrame(rows)

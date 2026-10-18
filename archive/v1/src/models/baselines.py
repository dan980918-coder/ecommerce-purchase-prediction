"""PROJECT_GUIDELINES.md 20번 기준선: 무작위, 전체 평균, 최근성 규칙, 빈도 규칙, 라이프사이클 규칙.

모든 함수는 "값이 클수록 타겟(양성 클래스)일 가능성이 높다"는 방향으로
점수를 반환한다. 순위 기반 지표(AUC, Precision/Recall/Lift@K)는 점수의
스케일과 무관하지만, LogLoss/Brier 계산을 위해 마지막에 0~1로
min-max 정규화한다 — 규칙 기반 점수는 원래 보정된(calibrated) 확률이
아니므로, 이 지표들은 로지스틱회귀/LightGBM 대비 참고용으로만 해석한다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _minmax(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    lo, hi = np.nanmin(x), np.nanmax(x)
    if hi - lo < 1e-9:
        return np.full_like(x, 0.5)
    return (x - lo) / (hi - lo)


def random_score(n: int, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.random(n)


def overall_rate_score(n: int, rate: float) -> np.ndarray:
    return np.full(n, rate)


def recency_churn_score(days_since_last: pd.Series) -> np.ndarray:
    """구매 비활성(churn) 방향: 마지막 구매 후 경과일이 클수록 위험 높음."""
    filled = days_since_last.fillna(days_since_last.max() * 2 if days_since_last.notna().any() else 1)
    return _minmax(filled.values)


def frequency_churn_score(n_purchases_recent: pd.Series) -> np.ndarray:
    """구매 비활성(churn) 방향: 최근 구매 빈도가 낮을수록 위험 높음(역수 방향)."""
    return _minmax(-n_purchases_recent.fillna(0).values)


def frequency_propensity_score(n_purchases_so_far: pd.Series) -> np.ndarray:
    """구매성향(propensity) 방향: 누적 구매 횟수가 많을수록 재구매 가능성 높음."""
    return _minmax(n_purchases_so_far.fillna(0).values)


def lifecycle_tier_churn_score(days_since_last: pd.Series) -> np.ndarray:
    """mart_customer_lifecycle과 동일한 14/28/60일 임계값을 snapshot 시점
    기준으로 재적용한 순번형 위험 점수(0=활성 ~ 3=비활성)."""
    tier = pd.cut(
        days_since_last,
        bins=[-1, 14, 28, 60, np.inf],
        labels=[0, 1, 2, 3],
    ).astype(float)
    tier = tier.fillna(3)  # 구매 이력 자체가 없으면(Model B 전용) 최고 위험 취급
    return _minmax(tier.values)


def recency_propensity_score(days_since_last: pd.Series, has_history: pd.Series) -> np.ndarray:
    """구매성향(propensity) 방향: 최근성이 좋을수록(경과일 적을수록) 구매
    가능성 높음 — churn과 반대 방향. 구매 이력이 없는 고객은 recency 신호가
    없으므로 중간값으로 처리(다른 baseline인 frequency/visit 규칙이 이들을 구분)."""
    filled = days_since_last.copy()
    max_val = days_since_last.max() if days_since_last.notna().any() else 1
    filled = filled.fillna(max_val)
    score = 1 - _minmax(filled.values)
    score = np.where(has_history.values, score, np.nanmedian(score))
    return score


def visit_propensity_score(n_page_visit_recent: pd.Series, n_search_recent: pd.Series) -> np.ndarray:
    """구매성향(propensity) 방향: 최근 방문·검색이 많을수록 구매 가능성 높음."""
    combined = n_page_visit_recent.fillna(0) + 3 * n_search_recent.fillna(0)  # 검색은 더 강한 의도 신호
    return _minmax(combined.values)

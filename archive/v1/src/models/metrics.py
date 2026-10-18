"""PROJECT_GUIDELINES.md 22번 모델 평가 지표: Precision/Recall/Lift@K, Brier, Calibration."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)


def precision_recall_lift_at_k(y_true: np.ndarray, y_score: np.ndarray, k_pct: float) -> dict:
    n = len(y_true)
    k = max(1, int(round(n * k_pct / 100)))
    order = np.argsort(-y_score)
    top_k_idx = order[:k]
    n_true_in_top_k = y_true[top_k_idx].sum()
    n_true_total = y_true.sum()
    base_rate = n_true_total / n if n else 0.0

    precision = n_true_in_top_k / k if k else 0.0
    recall = n_true_in_top_k / n_true_total if n_true_total else 0.0
    lift = precision / base_rate if base_rate else 0.0

    return {
        "k_pct": k_pct,
        "n_selected": k,
        "n_true_in_selected": int(n_true_in_top_k),
        f"precision_at_{int(k_pct)}pct": precision,
        f"recall_at_{int(k_pct)}pct": recall,
        f"lift_at_{int(k_pct)}pct": lift,
    }


def calibration_table(y_true: np.ndarray, y_score: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    df = pd.DataFrame({"y_true": y_true, "y_score": y_score})
    df["bin"] = pd.qcut(df["y_score"], q=n_bins, duplicates="drop")
    agg = df.groupby("bin", observed=True).agg(
        mean_predicted=("y_score", "mean"),
        actual_rate=("y_true", "mean"),
        n=("y_true", "size"),
    ).reset_index(drop=True)
    return agg


def customers_needed_for_recall(y_true: np.ndarray, y_score: np.ndarray, target_recall: float) -> int:
    """target_recall(0~1)을 달성하려면 이 점수로 정렬했을 때 상위 몇 명을
    선택해야 하는지 반환. PROJECT_GUIDELINES.md 23번 "동일 포착률에 필요한 접촉 고객 수"."""
    y_true = np.asarray(y_true)
    y_score = np.asarray(y_score, dtype=float)
    total_true = y_true.sum()
    if total_true == 0:
        return len(y_true)
    order = np.argsort(-y_score)
    cum_true = np.cumsum(y_true[order])
    target_count = target_recall * total_true
    idx = int(np.searchsorted(cum_true, target_count, side="left"))
    return min(idx + 1, len(y_true))


def full_evaluation(y_true: np.ndarray, y_score: np.ndarray, base_rate_train: float | None = None) -> dict:
    y_true = np.asarray(y_true)
    y_score = np.asarray(y_score, dtype=float)

    # AUC/PR-AUC/LogLoss/Brier은 스코어가 상수(모든 값 동일)인 기준선에서는
    # 정의되지 않거나(AUC) 경고를 유발할 수 있어 예외 처리한다.
    try:
        auc = roc_auc_score(y_true, y_score)
    except ValueError:
        auc = float("nan")
    try:
        pr_auc = average_precision_score(y_true, y_score)
    except ValueError:
        pr_auc = float("nan")

    y_score_clipped = np.clip(y_score, 1e-6, 1 - 1e-6)
    logloss = log_loss(y_true, y_score_clipped, labels=[0, 1])
    brier = brier_score_loss(y_true, y_score_clipped)

    result = {
        "roc_auc": auc,
        "pr_auc": pr_auc,
        "log_loss": logloss,
        "brier_score": brier,
        "actual_positive_rate": float(y_true.mean()),
        "n": len(y_true),
    }
    for k_pct in (5, 10, 20):
        k_result = precision_recall_lift_at_k(y_true, y_score, k_pct)
        for key in (f"precision_at_{k_pct}pct", f"recall_at_{k_pct}pct", f"lift_at_{k_pct}pct"):
            result[key] = k_result[key]
    return result

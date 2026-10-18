"""Phase 6 - Model A: 구매 비활성 위험 예측 (PROJECT_GUIDELINES.md 18, 20~22번).

시간순 분할(snapshot_date 기준): Train 6개(07-21~09-29) / Val 1개(10-13) /
Test 2개(10-27, 11-10). 근거는 reports/phase6_model_a_results.md 참고.

기준선(무작위/전체평균/최근성/빈도/라이프사이클) -> 로지스틱 회귀 -> LightGBM
순으로 비교한다 (PROJECT_GUIDELINES.md 20번 "복잡한 모델이 단순 규칙보다 나은지 확인").

학습·평가 공통 로직은 src/models/train_pipeline.py에 있다 — 이 파일은 Model A
고유의 설정값(FEATURE_COLS, 기준선, 결측 처리 방식)만 정의하는 얇은 wrapper다.
TRAIN_SNAPSHOTS/VAL_SNAPSHOTS/TEST_SNAPSHOTS/split_data는 tests/unit/test_model_split.py,
scripts/build_targeting_simulation.py, scripts/generate_figures.py가 이 모듈에서
직접 import하므로 공통 모듈의 정의를 그대로 re-export한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.models.baselines import (
    frequency_churn_score,
    lifecycle_tier_churn_score,
    recency_churn_score,
)
from src.models.train_pipeline import (
    TEST_SNAPSHOTS,
    TRAIN_SNAPSHOTS,
    VAL_SNAPSHOTS,
    ModelSpec,
    run,
    split_data,
)

FEATURE_COLS = [
    "days_since_last_purchase",
    "n_purchase_occasions_so_far",
    "n_purchase_days_so_far",
    "avg_purchase_gap_days_so_far",
    "n_purchases_7d",
    "n_purchases_14d",
    "n_purchases_28d",
    "n_categories_so_far",
    "avg_category_repurchase_rate",
    "n_page_visit_28d",
    "n_search_query_28d",
    "n_add_to_cart_28d",
    "n_remove_from_cart_28d",
]

SPEC = ModelSpec(
    mart_table="mart_churn_target",
    feature_cols=FEATURE_COLS,
    label_cols=["churn_14d", "churn_28d"],
    output_prefix="phase6_model_a",
    baselines=[
        ("최근성_규칙", lambda d: recency_churn_score(d["days_since_last_purchase"])),
        ("구매빈도_규칙", lambda d: frequency_churn_score(d["n_purchases_28d"])),
        ("라이프사이클_규칙", lambda d: lifecycle_tier_churn_score(d["days_since_last_purchase"])),
    ],
    lr_impute_with_flag_cols=["avg_purchase_gap_days_so_far", "avg_category_repurchase_rate"],
)


def main():
    run(SPEC)


if __name__ == "__main__":
    main()

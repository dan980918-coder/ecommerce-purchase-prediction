"""Phase 6 - Model B: 향후 구매 가능성 예측 (PROJECT_GUIDELINES.md 19, 20~22번).

mart_purchase_propensity 사용 — Model A(mart_churn_target)보다 넓은 모집단
(구매 이력 없는 고관여 탐색/장바구니 고객 포함). "구매함"이 소수 클래스라
Model A와 반대로 Lift@K가 더 유의미하게 나올 것으로 기대(보고서에서 비교).

시간순 분할은 Model A와 동일한 snapshot_date 기준(Train 6/Val 1/Test 2).

학습·평가 공통 로직은 src/models/train_pipeline.py에 있다 — 이 파일은 Model B
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
    frequency_propensity_score,
    recency_propensity_score,
    visit_propensity_score,
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
    "has_purchase_history",
    "days_since_last_purchase",
    "n_purchase_occasions_so_far",
    "avg_category_repurchase_rate",
    "n_page_visit_28d",
    "n_search_query_28d",
    "n_add_to_cart_28d",
    "n_remove_from_cart_28d",
]

SPEC = ModelSpec(
    mart_table="mart_purchase_propensity",
    feature_cols=FEATURE_COLS,
    label_cols=["will_purchase_14d", "will_purchase_28d"],
    output_prefix="phase6_model_b",
    baselines=[
        ("최근성_규칙", lambda d: recency_propensity_score(d["days_since_last_purchase"], d["has_purchase_history"])),
        ("구매빈도_규칙", lambda d: frequency_propensity_score(d["n_purchase_occasions_so_far"])),
        ("방문검색_규칙", lambda d: visit_propensity_score(d["n_page_visit_28d"], d["n_search_query_28d"])),
    ],
    lr_impute_with_flag_cols=["avg_category_repurchase_rate"],
    lr_impute_no_flag_cols=["days_since_last_purchase"],
    lr_passthrough_cols=["has_purchase_history"],
    lgb_cast_int_cols=["has_purchase_history"],
)


def main():
    run(SPEC)


if __name__ == "__main__":
    main()

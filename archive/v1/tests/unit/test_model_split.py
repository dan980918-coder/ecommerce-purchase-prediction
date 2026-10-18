"""Phase 6 시간순 분할이 실제로 미래 누수 없이 이루어지는지 검증 (PROJECT_GUIDELINES.md 9, 21번)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.train_model_a import FEATURE_COLS as MODEL_A_FEATURES
from scripts.train_model_a import TEST_SNAPSHOTS as A_TEST
from scripts.train_model_a import TRAIN_SNAPSHOTS as A_TRAIN
from scripts.train_model_a import VAL_SNAPSHOTS as A_VAL
from scripts.train_model_b import FEATURE_COLS as MODEL_B_FEATURES
from scripts.train_model_b import TEST_SNAPSHOTS as B_TEST
from scripts.train_model_b import TRAIN_SNAPSHOTS as B_TRAIN
from scripts.train_model_b import VAL_SNAPSHOTS as B_VAL


def test_model_a_split_is_chronological():
    assert max(A_TRAIN) < min(A_VAL) < min(A_TEST)
    assert set(A_TRAIN) & set(A_VAL) == set()
    assert set(A_VAL) & set(A_TEST) == set()
    assert set(A_TRAIN) & set(A_TEST) == set()


def test_model_b_split_is_chronological():
    assert max(B_TRAIN) < min(B_VAL) < min(B_TEST)
    assert set(B_TRAIN) & set(B_VAL) == set()
    assert set(B_VAL) & set(B_TEST) == set()


def test_model_a_and_b_use_same_split_boundaries():
    # 두 모델을 같은 시점 기준으로 비교할 수 있어야 하므로 분할 경계가 동일해야 함
    assert A_TRAIN == B_TRAIN
    assert A_VAL == B_VAL
    assert A_TEST == B_TEST


def test_no_label_columns_in_features():
    label_like = {"churn_14d", "churn_28d", "will_purchase_14d", "will_purchase_28d",
                  "label_purchase_14d", "label_purchase_28d", "label_inactive_14d", "label_inactive_28d"}
    assert not (set(MODEL_A_FEATURES) & label_like)
    assert not (set(MODEL_B_FEATURES) & label_like)


def test_9_snapshots_fully_partitioned():
    all_snapshots = set(A_TRAIN) | set(A_VAL) | set(A_TEST)
    assert len(all_snapshots) == 9

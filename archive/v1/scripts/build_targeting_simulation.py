"""Phase 7 - CRM 타기팅 시뮬레이션 (PROJECT_GUIDELINES.md 23~24번).

Model A(churn_target), Model B(purchase_propensity) 각각의 테스트셋(out-of-sample,
2022-10-27/11-10)에서 정책별(무작위/최근성/모델) 접촉 비율(5/10/20/30%)에
따른 성과를 비교한다. "최근성 규칙"을 공통 비교 기준으로 삼아 두 모델 간
개선폭을 일관되게 비교할 수 있게 한다.

결과는 data/processed/crm.duckdb의 mart_targeting_simulation 테이블과
reports/phase7_targeting_simulation.md로 저장한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.train_model_a import FEATURE_COLS as A_FEATURES
from scripts.train_model_a import TEST_SNAPSHOTS, TRAIN_SNAPSHOTS, VAL_SNAPSHOTS
from scripts.train_model_a import split_data as split_a
from scripts.train_model_b import FEATURE_COLS as B_FEATURES
from scripts.train_model_b import split_data as split_b
from src.models.baselines import (
    lifecycle_tier_churn_score,
    random_score,
    recency_churn_score,
    recency_propensity_score,
)
from src.models.metrics import customers_needed_for_recall, precision_recall_lift_at_k
from src.models.train_pipeline import fit_lightgbm

CONFIG_PATH = Path("config/paths.yaml")
REPORT_DIR = Path("reports")
CONTACT_RATES = [5, 10, 20, 30]


def compare_model_vs_rule(model_name, label_col, y_true, model_score, rule_score, rule_name="최근성_규칙"):
    records = []
    for rate in CONTACT_RATES:
        model_r = precision_recall_lift_at_k(y_true, model_score, rate)
        target_recall = model_r[f"recall_at_{rate}pct"]
        n_needed_rule = customers_needed_for_recall(y_true, rule_score, target_recall)
        n_model = model_r["n_selected"]
        reduction_pct = (1 - n_model / n_needed_rule) * 100 if n_needed_rule else 0.0
        records.append(
            {
                "model": model_name,
                "label": label_col,
                "contact_rate_pct": rate,
                "policy": f"모델_vs_{rule_name}_동일recall비교",
                "n_total": len(y_true),
                "n_selected": n_model,
                "n_actual_captured": model_r["n_true_in_selected"],
                "precision": None,
                "recall": target_recall,
                "lift": None,
                "customers_needed_by_rule_for_same_recall": n_needed_rule,
                "contact_reduction_pct": reduction_pct,
            }
        )
    return records


def simulate_policy(model_name, label_col, policy_name, y_true, y_score, rows_all):
    records = []
    for rate in CONTACT_RATES:
        r = precision_recall_lift_at_k(y_true, y_score, rate)
        records.append(
            {
                "model": model_name,
                "label": label_col,
                "contact_rate_pct": rate,
                "policy": policy_name,
                "n_total": len(y_true),
                "n_selected": r["n_selected"],
                "n_actual_captured": r["n_true_in_selected"],
                "precision": r[f"precision_at_{rate}pct"],
                "recall": r[f"recall_at_{rate}pct"],
                "lift": r[f"lift_at_{rate}pct"],
            }
        )
    return records


def main():
    with open(CONFIG_PATH) as f:
        paths = yaml.safe_load(f)
    con = duckdb.connect(str(paths["database_path"]))

    all_rows = []

    # ---------------- Model A: churn ----------------
    df_a = con.sql("SELECT * FROM mart_churn_target").df()
    train_a, val_a, test_a = split_a(df_a)
    for label_col in ["churn_14d", "churn_28d"]:
        gbm = fit_lightgbm(train_a[A_FEATURES], train_a[label_col].values, val_a[A_FEATURES], val_a[label_col].values)
        y_test = test_a[label_col].values
        model_score = gbm.predict(test_a[A_FEATURES])
        recency_score = recency_churn_score(test_a["days_since_last_purchase"])
        lifecycle_score = lifecycle_tier_churn_score(test_a["days_since_last_purchase"])
        rand_score = random_score(len(y_test))

        all_rows += simulate_policy("Model_A_churn", label_col, "무작위", y_test, rand_score, test_a)
        all_rows += simulate_policy("Model_A_churn", label_col, "최근성_규칙", y_test, recency_score, test_a)
        all_rows += simulate_policy("Model_A_churn", label_col, "라이프사이클_규칙", y_test, lifecycle_score, test_a)
        all_rows += simulate_policy("Model_A_churn", label_col, "모델_LightGBM", y_test, model_score, test_a)
        all_rows += compare_model_vs_rule("Model_A_churn", label_col, y_test, model_score, recency_score)
        print(f"Model A {label_col} 완료")

    # ---------------- Model B: propensity ----------------
    df_b = con.sql("SELECT * FROM mart_purchase_propensity").df()
    train_b, val_b, test_b = split_b(df_b)
    train_b_feat = train_b.copy(); train_b_feat["has_purchase_history"] = train_b_feat["has_purchase_history"].astype(int)
    val_b_feat = val_b.copy(); val_b_feat["has_purchase_history"] = val_b_feat["has_purchase_history"].astype(int)
    test_b_feat = test_b.copy(); test_b_feat["has_purchase_history"] = test_b_feat["has_purchase_history"].astype(int)

    for label_col in ["will_purchase_14d", "will_purchase_28d"]:
        gbm = fit_lightgbm(
            train_b_feat[B_FEATURES], train_b_feat[label_col].values,
            val_b_feat[B_FEATURES], val_b_feat[label_col].values,
        )
        y_test = test_b[label_col].values
        model_score = gbm.predict(test_b_feat[B_FEATURES])
        recency_score = recency_propensity_score(test_b["days_since_last_purchase"], test_b["has_purchase_history"])
        rand_score = random_score(len(y_test))

        all_rows += simulate_policy("Model_B_propensity", label_col, "무작위", y_test, rand_score, test_b)
        all_rows += simulate_policy("Model_B_propensity", label_col, "최근성_규칙", y_test, recency_score, test_b)
        all_rows += simulate_policy("Model_B_propensity", label_col, "모델_LightGBM", y_test, model_score, test_b)
        all_rows += compare_model_vs_rule("Model_B_propensity", label_col, y_test, model_score, recency_score)
        print(f"Model B {label_col} 완료")

    result_df = pd.DataFrame(all_rows)
    con.sql("CREATE OR REPLACE TABLE mart_targeting_simulation AS SELECT * FROM result_df")
    n = con.sql("SELECT COUNT(*) FROM mart_targeting_simulation").fetchone()[0]
    print(f"\nmart_targeting_simulation: {n} rows")

    REPORT_DIR.mkdir(exist_ok=True)
    result_df.to_csv(REPORT_DIR / "phase7_targeting_simulation.csv", index=False)
    print(f"Saved: {REPORT_DIR / 'phase7_targeting_simulation.csv'}")


if __name__ == "__main__":
    main()

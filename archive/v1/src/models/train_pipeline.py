"""Phase 6 - Model A/B 공통 학습 파이프라인.

scripts/train_model_a.py와 scripts/train_model_b.py는 구조가 거의 동일하다
(시간순 분할 -> 기준선 5종 -> 로지스틱 회귀 -> LightGBM -> 결과 CSV 저장).
차이는 mart 테이블명, FEATURE_COLS, 라벨 컬럼, 기준선 함수 목록, 결측 처리
방식뿐이라 그 차이만 ModelSpec으로 넘기고 나머지는 여기 하나로 모은다.

TRAIN_SNAPSHOTS/VAL_SNAPSHOTS/TEST_SNAPSHOTS와 split_data()는 Model A/B가
완전히 동일하게 쓰며, tests/unit/test_model_split.py와
scripts/build_targeting_simulation.py, scripts/generate_figures.py가
`scripts.train_model_a`/`scripts.train_model_b`에서 이 이름들을 직접 import
하므로, 각 wrapper 파일에서 이 모듈의 이름을 그대로 re-export한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from src.models.baselines import overall_rate_score, random_score
from src.models.metrics import full_evaluation

CONFIG_PATH = Path("config/paths.yaml")
REPORT_DIR = Path("reports")

TRAIN_SNAPSHOTS = ["2022-07-21", "2022-08-04", "2022-08-18", "2022-09-01", "2022-09-15", "2022-09-29"]
VAL_SNAPSHOTS = ["2022-10-13"]
TEST_SNAPSHOTS = ["2022-10-27", "2022-11-10"]

RESULT_COLS = [
    "label", "split", "method", "n", "actual_positive_rate", "roc_auc", "pr_auc",
    "log_loss", "brier_score",
    "precision_at_5pct", "recall_at_5pct", "lift_at_5pct",
    "precision_at_10pct", "recall_at_10pct", "lift_at_10pct",
    "precision_at_20pct", "recall_at_20pct", "lift_at_20pct",
]


@dataclass
class ModelSpec:
    mart_table: str
    feature_cols: list[str]
    label_cols: list[str]  # 2개(예: churn_14d/28d) — 첫 번째 라벨에서만 feature importance 저장
    output_prefix: str  # 결과 파일명 접두어 (phase6_model_a / phase6_model_b)
    baselines: list[tuple[str, Callable[[pd.DataFrame], np.ndarray]]]
    lr_impute_with_flag_cols: list[str] = field(default_factory=list)  # median 대체 + '_missing' 플래그 컬럼 추가
    lr_impute_no_flag_cols: list[str] = field(default_factory=list)  # median 대체만(플래그 없음)
    lr_passthrough_cols: list[str] = field(default_factory=list)  # 결측 없음 — 타입 캐스팅만(bool -> int)
    lgb_cast_int_cols: list[str] = field(default_factory=list)  # LightGBM에 넘기기 전 int로 캐스팅할 컬럼


def split_data(df: pd.DataFrame):
    df = df.copy()
    df["snapshot_date_str"] = df["snapshot_date"].astype(str)
    train = df[df["snapshot_date_str"].isin(TRAIN_SNAPSHOTS)]
    val = df[df["snapshot_date_str"].isin(VAL_SNAPSHOTS)]
    test = df[df["snapshot_date_str"].isin(TEST_SNAPSHOTS)]
    assert len(train) + len(val) + len(test) == len(df), "분할 후 행 수 합이 원본과 다름 — 날짜 매칭 오류"
    return train, val, test


def prepare_lr_features(spec: ModelSpec, train, val, test):
    impute_cols = spec.lr_impute_with_flag_cols + spec.lr_impute_no_flag_cols
    medians = {col: train[col].median() for col in impute_cols}

    def transform(d):
        d = d.copy()
        for col in spec.lr_passthrough_cols:
            d[col] = d[col].astype(int)
        for col in spec.lr_impute_with_flag_cols:
            d[f"{col}_missing"] = d[col].isna().astype(int)
            d[col] = d[col].fillna(medians[col])
        for col in spec.lr_impute_no_flag_cols:
            d[col] = d[col].fillna(medians[col])
        return d

    train_t, val_t, test_t = transform(train), transform(val), transform(test)
    cols = spec.feature_cols + [f"{c}_missing" for c in spec.lr_impute_with_flag_cols]

    scaler = StandardScaler()
    X_train = scaler.fit_transform(train_t[cols])
    X_val = scaler.transform(val_t[cols])
    X_test = scaler.transform(test_t[cols])
    return X_train, X_val, X_test


def fit_lightgbm(train_feat: pd.DataFrame, y_train, val_feat: pd.DataFrame, y_val):
    """scripts/train_model_a.py, scripts/train_model_b.py, scripts/build_targeting_simulation.py가
    공유하는 LightGBM 학습 설정 — 하이퍼파라미터를 한 곳에서만 정의한다."""
    train_ds = lgb.Dataset(train_feat, label=y_train)
    val_ds = lgb.Dataset(val_feat, label=y_val, reference=train_ds)
    return lgb.train(
        params={
            "objective": "binary",
            "metric": "auc",
            "verbosity": -1,
            "seed": 42,
        },
        train_set=train_ds,
        num_boost_round=500,
        valid_sets=[val_ds],
        callbacks=[lgb.early_stopping(30, verbose=False)],
    )


def run_for_label(spec: ModelSpec, df: pd.DataFrame, label_col: str):
    train, val, test = split_data(df)
    y_train = train[label_col].values
    y_val = val[label_col].values
    y_test = test[label_col].values
    train_rate = y_train.mean()

    results = []

    def record(method, split_name, y_true, y_score):
        m = full_evaluation(y_true, y_score)
        m["method"] = method
        m["split"] = split_name
        m["label"] = label_col
        results.append(m)

    # --- 기준선 ---
    for split_name, d, y in [("val", val, y_val), ("test", test, y_test)]:
        record("무작위", split_name, y, random_score(len(y)))
        record("전체_평균", split_name, y, overall_rate_score(len(y), train_rate))
        for name, fn in spec.baselines:
            record(name, split_name, y, fn(d))

    # --- 로지스틱 회귀 ---
    X_train, X_val, X_test = prepare_lr_features(spec, train, val, test)
    lr = LogisticRegression(max_iter=1000)
    lr.fit(X_train, y_train)
    record("로지스틱_회귀", "val", y_val, lr.predict_proba(X_val)[:, 1])
    record("로지스틱_회귀", "test", y_test, lr.predict_proba(X_test)[:, 1])

    # --- LightGBM ---
    train_feat = train[spec.feature_cols].copy()
    val_feat = val[spec.feature_cols].copy()
    test_feat = test[spec.feature_cols].copy()
    for d in (train_feat, val_feat, test_feat):
        for col in spec.lgb_cast_int_cols:
            d[col] = d[col].astype(int)

    gbm = fit_lightgbm(train_feat, y_train, val_feat, y_val)
    record("LightGBM", "val", y_val, gbm.predict(val_feat))
    record("LightGBM", "test", y_test, gbm.predict(test_feat))

    return results, gbm


def run(spec: ModelSpec) -> pd.DataFrame:
    with open(CONFIG_PATH) as f:
        paths = yaml.safe_load(f)
    con = duckdb.connect(str(paths["database_path"]), read_only=True)

    df = con.sql(f"SELECT * FROM {spec.mart_table}").df()
    print(f"전체 행 수: {len(df):,}")

    all_results = []
    for i, label_col in enumerate(spec.label_cols):
        print(f"\n{'=' * 80}\n{label_col}\n{'=' * 80}")
        results, gbm = run_for_label(spec, df, label_col)
        all_results.extend(results)
        for r in results:
            print(
                f"[{r['split']}] {r['method']:14s} AUC={r['roc_auc']:.4f} "
                f"PR-AUC={r['pr_auc']:.4f} Lift@10%={r['lift_at_10pct']:.2f} "
                f"Precision@10%={r['precision_at_10pct']:.4f} Recall@10%={r['recall_at_10pct']:.4f}"
            )
        if i == 0:
            importances = pd.DataFrame(
                {"feature": spec.feature_cols, "importance": gbm.feature_importance(importance_type="gain")}
            ).sort_values("importance", ascending=False)
            print("\nLightGBM feature importance (gain):")
            print(importances.to_string(index=False))
            importances.to_csv(REPORT_DIR / f"{spec.output_prefix}_feature_importance.csv", index=False)

    result_df = pd.DataFrame(all_results)[RESULT_COLS]
    REPORT_DIR.mkdir(exist_ok=True)
    result_df.to_csv(REPORT_DIR / f"{spec.output_prefix}_results.csv", index=False)
    print(f"\nSaved: {REPORT_DIR / (spec.output_prefix + '_results.csv')}")
    return result_df

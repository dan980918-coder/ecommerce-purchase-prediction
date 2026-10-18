"""Phase 8 - A/B 테스트 배정표 생성 (README "8. 향후 확장"에서 제안한 실험
설계의 실행 준비 단계).

mart_purchase_propensity의 최신 snapshot_date(모집단)를 Model B(will_purchase_14d
라벨로 학습, Train/Val snapshot 기준)의 예측 확률로 채점한 뒤, 상위 10%/
10~30%/30~50% 구간별로 Treatment/Control을 50:50 무작위 배정하고 배정
품질(balance check, SRM check)까지 확인한다.

주의: 이 스크립트가 만드는 건 배정표와 배정 품질 점검까지다. 실제로 CRM을
발송한 적이 없으므로 "Treatment가 더 나았다" 같은 실험 결과는 이 산출물
어디에도 없다 — 결과는 실제 발송 기록(exposure 데이터)이 생긴 뒤
src/experiments/evaluation.py의 evaluate_experiment()로 계산해야 하며,
그 전까지는 항상 미측정이다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.train_model_b import FEATURE_COLS as B_FEATURES
from scripts.train_model_b import split_data
from src.experiments.assignment import (
    assign_treatment_control,
    check_balance,
    check_sample_ratio_mismatch,
)
from src.models.train_pipeline import fit_lightgbm

CONFIG_PATH = Path("config/paths.yaml")
REPORT_DIR = Path("reports")

SCORE_BINS = [
    ("상위10%", 0, 10),
    ("10~30%", 10, 30),
    ("30~50%", 30, 50),
]
COVARIATE_COLS = [
    "days_since_last_purchase",
    "n_page_visit_28d",
    "n_search_query_28d",
    "n_purchase_occasions_so_far",
]
LABEL_COL = "will_purchase_14d"
SEED = 42


def main():
    with open(CONFIG_PATH) as f:
        paths = yaml.safe_load(f)
    con = duckdb.connect(str(paths["database_path"]), read_only=True)

    df = con.sql("SELECT * FROM mart_purchase_propensity").df()
    df["has_purchase_history"] = df["has_purchase_history"].astype(int)

    train, val, _test = split_data(df)
    latest_snapshot = df["snapshot_date"].max()
    population = df[df["snapshot_date"] == latest_snapshot].copy()
    print(f"기준 snapshot_date: {latest_snapshot} / 모집단: {len(population):,}명")

    gbm = fit_lightgbm(
        train[B_FEATURES], train[LABEL_COL].values,
        val[B_FEATURES], val[LABEL_COL].values,
    )
    population["propensity_score"] = gbm.predict(population[B_FEATURES])

    assigned = assign_treatment_control(
        population, score_col="propensity_score", score_bins=SCORE_BINS, seed=SEED
    )
    assigned = assigned.merge(
        population[["client_id"] + COVARIATE_COLS], on="client_id", how="left"
    )
    print(f"배정 인원: {len(assigned):,}명 (구간 정의 밖 고객 제외)")

    balance = check_balance(assigned, COVARIATE_COLS)
    srm = check_sample_ratio_mismatch(assigned)

    REPORT_DIR.mkdir(exist_ok=True)
    assigned[["client_id", "propensity_score", "segment", "group"]].to_csv(
        REPORT_DIR / "phase8_experiment_assignment.csv", index=False
    )

    seg_counts = assigned.groupby(["segment", "group"]).size().unstack(fill_value=0)
    bins_desc = ", ".join(f"{label}(상위 {lo}~{hi}%)" for label, lo, hi in SCORE_BINS)

    lines = [
        "# Phase 8 - A/B 테스트 배정표",
        "",
        "이 문서는 실험 **설계·배정** 산출물이다. 실제로 CRM을 발송한 적이 없으므로 "
        '"Treatment가 Control보다 나았다" 같은 실험 결과는 포함하지 않는다 — 결과는 '
        "실제 발송 기록이 생긴 뒤 `src/experiments/evaluation.py`의 "
        "`evaluate_experiment()`로 계산해야 하며, 그 전까지는 항상 **미측정**이다.",
        "",
        f"- 기준 snapshot_date: `{latest_snapshot}`",
        f"- 채점 모델: Model B LightGBM (`{LABEL_COL}` 라벨로 학습, Train/Val snapshot 기준)",
        f"- 모집단 크기: {len(population):,}명",
        f"- 배정 인원: {len(assigned):,}명 (구간 정의({bins_desc}) 밖 고객은 배정표에서 제외)",
        "",
        "## 구간별 배정 인원",
        "",
        seg_counts.to_markdown(),
        "",
        "## Balance check (Mann-Whitney U, 양측)",
        "",
        "과거 행동 covariate가 Treatment/Control 간 통계적으로 균형 잡혔는지 확인한다 "
        "(p_value >= 0.05면 균형 — 이 값은 실험 결과가 아니라 배정이 제대로 "
        "무작위화됐는지에 대한 사전 점검이다).",
        "",
        balance.to_markdown(index=False),
        "",
        "## Sample Ratio Mismatch check (카이제곱)",
        "",
        "의도한 배정 비율(50:50)이 실제로 깨지지 않았는지 확인한다 "
        "(p_value < 0.01이면 SRM 의심 — SRM 점검에 통상 쓰이는 엄격한 유의수준).",
        "",
        srm.to_markdown(index=False),
        "",
    ]

    with open(REPORT_DIR / "phase8_experiment_assignment.md", "w") as f:
        f.write("\n".join(lines))

    print(f"Saved: {REPORT_DIR / 'phase8_experiment_assignment.csv'}")
    print(f"Saved: {REPORT_DIR / 'phase8_experiment_assignment.md'}")


if __name__ == "__main__":
    main()

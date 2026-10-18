"""포트폴리오용 정적 그래프 생성 (EDA 5종 + 분석결과 6종) -> reports/figures/*.png

기존 파이프라인 산출물(mart, reports/*.csv)을 최대한 재사용하고, 없는 것만
DuckDB에서 새로 집계한다. 파이프라인 SQL/마트는 수정하지 않는다.
"""

import sys
from pathlib import Path

import duckdb
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import yaml

matplotlib.use("Agg")
# 주의: sns.set_theme()이 matplotlib rcParams(폰트 포함)를 초기화하므로
# 반드시 set_theme을 먼저 호출한 뒤 폰트를 재설정해야 한글이 깨지지 않는다.
sns.set_theme(style="whitegrid")
plt.rcParams["font.family"] = "AppleGothic"
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 110
plt.rcParams["savefig.dpi"] = 150
plt.rcParams["font.size"] = 11

FIG_DIR = Path("reports/figures")
FIG_DIR.mkdir(parents=True, exist_ok=True)

with open("config/paths.yaml") as f:
    PATHS = yaml.safe_load(f)


def get_con():
    return duckdb.connect(PATHS["database_path"], read_only=True)


def savefig(fig, name):
    path = FIG_DIR / name
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {path}")


# ---------------- EDA 1: 일별 이벤트량 추이 ----------------
def fig01_daily_event_volume():
    con = get_con()
    df = con.sql(
        """
        SELECT activity_date,
               SUM(n_page_visit) AS page_visit,
               SUM(n_search_query) AS search_query,
               SUM(n_add_to_cart) AS add_to_cart,
               SUM(n_remove_from_cart) AS remove_from_cart,
               SUM(n_product_buy) AS product_buy
        FROM int_customer_daily_activity
        GROUP BY activity_date ORDER BY activity_date
        """
    ).df()

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    for col in ["page_visit", "search_query"]:
        axes[0].plot(df["activity_date"], df[col], label=col, linewidth=1.2)
    axes[0].set_ylabel("이벤트 수")
    axes[0].set_title("일별 이벤트량 추이 — page_visit / search_query (좌축 규모가 커서 분리)")
    axes[0].legend()

    for col in ["add_to_cart", "remove_from_cart", "product_buy"]:
        axes[1].plot(df["activity_date"], df[col], label=col, linewidth=1.2)
    axes[1].set_ylabel("이벤트 수")
    axes[1].set_xlabel("날짜")
    axes[1].set_title("일별 이벤트량 추이 — add_to_cart / remove_from_cart / product_buy")
    axes[1].legend()

    fig.suptitle("이벤트 타입별 일별 발생량 (2022-06-23 ~ 2022-12-08)", y=1.02, fontsize=14)
    savefig(fig, "01_daily_event_volume.png")


# ---------------- EDA 2: 고객당 이벤트 수 분포 (long-tail, log) ----------------
def fig02_customer_event_count_distribution():
    con = get_con()
    df = con.sql(
        """
        SELECT client_id,
               (n_page_visit + n_search_query + n_add_to_cart + n_purchases) AS total_events
        FROM mart_customer_360
        WHERE (n_page_visit + n_search_query + n_add_to_cart + n_purchases) > 0
        """
    ).df()

    fig, ax = plt.subplots(figsize=(9, 6))
    ax.hist(df["total_events"], bins=np.logspace(0, np.log10(df["total_events"].max()), 60), color="#4C72B0")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("고객당 총 이벤트 수 (log scale)")
    ax.set_ylabel("고객 수 (log scale)")
    ax.set_title(f"고객당 이벤트 수 분포 (long-tail)\n중앙값={df['total_events'].median():.0f}, 평균={df['total_events'].mean():.1f}, 최댓값={df['total_events'].max():,}")
    savefig(fig, "02_customer_event_count_distribution.png")


# ---------------- EDA 3: 구매 간격 분포 (p50/p90 표시) ----------------
def fig03_purchase_gap_distribution():
    con = get_con()
    df = con.sql(
        """
        SELECT DISTINCT client_id, event_ts, days_since_prev_purchase_occasion AS gap
        FROM int_customer_purchase_history
        WHERE days_since_prev_purchase_occasion IS NOT NULL
        """
    ).df()
    p50 = df["gap"].median()
    p90 = df["gap"].quantile(0.9)

    fig, ax = plt.subplots(figsize=(9, 6))
    ax.hist(df["gap"], bins=range(0, 181, 3), color="#55A868", edgecolor="white", linewidth=0.3)
    ax.axvline(p50, color="#C44E52", linestyle="--", linewidth=2, label=f"p50 (중앙값) = {p50:.1f}일")
    ax.axvline(p90, color="#8172B2", linestyle="--", linewidth=2, label=f"p90 = {p90:.1f}일")
    ax.set_xlabel("재구매까지 걸린 일수 (occasion 단위)")
    ax.set_ylabel("빈도")
    ax.set_title("고객 구매 간격(재구매 텀) 분포")
    ax.legend()
    savefig(fig, "03_purchase_gap_distribution.png")


# ---------------- EDA 4: price_bucket별 전환율·제거율 ----------------
def fig04_price_bucket_conversion():
    con = get_con()
    df = con.sql(
        """
        WITH add_pairs AS (
            SELECT DISTINCT c.client_id, c.sku, p.price_bucket,
                   MIN(c.event_ts) OVER (PARTITION BY c.client_id, c.sku) AS first_add_ts
            FROM stg_add_to_cart c JOIN stg_product_properties p ON c.sku = p.sku
        ),
        buy_first AS (SELECT client_id, sku, MIN(event_ts) AS buy_ts FROM stg_product_buy GROUP BY client_id, sku),
        remove_any AS (SELECT DISTINCT client_id, sku FROM stg_remove_from_cart)
        SELECT ap.price_bucket, COUNT(*) AS n_added,
               SUM(CASE WHEN b.buy_ts IS NOT NULL AND b.buy_ts >= ap.first_add_ts THEN 1 ELSE 0 END) AS n_converted,
               SUM(CASE WHEN r.client_id IS NOT NULL THEN 1 ELSE 0 END) AS n_removed
        FROM add_pairs ap
        LEFT JOIN buy_first b ON ap.client_id=b.client_id AND ap.sku=b.sku
        LEFT JOIN remove_any r ON ap.client_id=r.client_id AND ap.sku=r.sku
        GROUP BY ap.price_bucket ORDER BY ap.price_bucket
        """
    ).df()
    df["conversion_rate"] = df["n_converted"] / df["n_added"] * 100
    df["removal_rate"] = df["n_removed"] / df["n_added"] * 100

    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(df["price_bucket"], df["conversion_rate"], label="전환율(%)", color="#4C72B0", linewidth=1.8)
    ax.plot(df["price_bucket"], df["removal_rate"], label="제거율(%)", color="#C44E52", linewidth=1.8)
    ax.axvspan(60, 79, color="#55A868", alpha=0.12, label="전환율 최고 구간(60~79)")
    ax.set_xlabel("price_bucket (0=최저가 ~ 99=최고가, 순위형 구간)")
    ax.set_ylabel("비율 (%)")
    ax.set_title("가격 구간(price_bucket)별 장바구니 추가→구매 전환율 / 제거율")
    ax.legend()
    df.to_csv(FIG_DIR.parent / "adhoc_price_bucket_conversion_full.csv", index=False)
    savefig(fig, "04_price_bucket_conversion_removal.png")


# ---------------- EDA 5: 고객별 이벤트 타입 보유 개수 분포 ----------------
def fig05_event_type_count_distribution():
    df = pd.read_csv("reports/phase1_customer_event_type_distribution.csv")
    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.bar(df["n_event_types"], df["n_clients"], color="#4C72B0")
    for b, pct in zip(bars, df["pct"]):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{pct:.1f}%", ha="center", va="bottom", fontsize=10)
    ax.set_yscale("log")
    ax.set_xlabel("보유한 이벤트 타입 수")
    ax.set_ylabel("고객 수 (log scale)")
    ax.set_title("고객별 이벤트 타입 보유 개수 분포")
    savefig(fig, "05_customer_event_type_count_distribution.png")


# ---------------- 결과 6: 퍼널 차트 ----------------
def fig06_funnel_chart():
    df = pd.read_csv("data/dashboard/funnel_summary.csv")
    d = dict(zip(df["stage_metric"], df["value"]))
    stages = ["탐색", "장바구니 추가", "구매"]
    values = [d["explore"], d["cart"], d["buy"]]

    fig, ax = plt.subplots(figsize=(8, 6))
    colors = ["#4C72B0", "#55A868", "#C44E52"]
    bars = ax.barh(stages[::-1], values[::-1], color=colors[::-1], height=0.5)
    for b, v in zip(bars, values[::-1]):
        pct = v / values[0] * 100
        ax.text(b.get_width(), b.get_y() + b.get_height() / 2, f"  {v:,.0f}명 ({pct:.1f}%)", va="center", fontsize=11)
    ax.set_xlabel("고객 수")
    ax.set_title("고객 단위 퍼널: 탐색 → 장바구니 추가 → 구매")
    ax.set_xlim(0, values[0] * 1.25)
    savefig(fig, "06_funnel_chart.png")


# ---------------- 결과 7: 코호트 리텐션 히트맵 ----------------
def fig07_cohort_retention_heatmap():
    df = pd.read_csv("data/dashboard/cohort_retention.csv", parse_dates=["cohort_week"])
    df = df.sort_values("cohort_week")
    heat = df.set_index(df["cohort_week"].dt.strftime("%Y-%m-%d"))[
        ["repurchase_7d_rate", "repurchase_14d_rate", "repurchase_28d_rate"]
    ] * 100
    heat.columns = ["7일", "14일", "28일"]

    fig, ax = plt.subplots(figsize=(6, 10))
    sns.heatmap(heat, annot=True, fmt=".1f", cmap="YlGnBu", ax=ax, cbar_kws={"label": "재구매율 (%)"})
    ax.set_title("코호트(첫 관측 구매 주차)별 재구매율 히트맵")
    ax.set_ylabel("코호트 주차")
    ax.set_xlabel("재구매 기준 기간")
    savefig(fig, "07_cohort_retention_heatmap.png")


# ---------------- 결과 8: 라이프사이클 상태 분포 ----------------
def fig08_lifecycle_distribution():
    df = pd.read_csv("data/dashboard/lifecycle_distribution.csv").sort_values("n", ascending=True)
    fig, ax = plt.subplots(figsize=(9, 6))
    bars = ax.barh(df["lifecycle_stage"], df["n"], color=sns.color_palette("viridis", len(df)))
    for b, pct in zip(bars, df["pct"]):
        ax.text(b.get_width(), b.get_y() + b.get_height() / 2, f"  {pct:.2f}%", va="center", fontsize=9)
    ax.set_xscale("log")
    ax.set_xlabel("고객 수 (log scale)")
    ax.set_title("고객 라이프사이클 8단계 분포 (관측 종료 시점 기준)")
    savefig(fig, "08_lifecycle_distribution.png")


# ---------------- 결과 9: 세그먼트별 고객 수·구매율 ----------------
def fig09_segment_distribution():
    df = pd.read_csv("data/dashboard/segment_profile.csv").sort_values("n", ascending=True)
    fig, ax1 = plt.subplots(figsize=(10, 6))
    bars = ax1.barh(df["segment"], df["n"], color="#4C72B0", alpha=0.8, label="고객 수")
    ax1.set_xscale("log")
    ax1.set_xlabel("고객 수 (log scale)")
    ax1.set_title("세그먼트별 고객 수 및 구매율")

    ax2 = ax1.twiny()
    ax2.plot(df["buy_rate"] * 100, df["segment"], "o-", color="#C44E52", label="구매율(%)")
    ax2.set_xlabel("구매율 (%)")
    ax2.set_xlim(-5, 105)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="lower right")
    savefig(fig, "09_segment_distribution.png")


# ---------------- 결과 10: Model A/B ROC + Lift curve ----------------
def fig10_model_roc_lift():
    sys.path.insert(0, str(Path(".").resolve()))
    from sklearn.metrics import roc_curve, auc

    from scripts.train_model_a import (
        FEATURE_COLS as A_FEATURES,
        split_data as split_a,
    )
    from scripts.train_model_b import (
        FEATURE_COLS as B_FEATURES,
        split_data as split_b,
    )
    import lightgbm as lgb

    con = get_con()

    def train_and_score(df, split_fn, feature_cols, label_col, cast_bool_col=None):
        train, val, test = split_fn(df)
        if cast_bool_col:
            for d in (train, val, test):
                d[cast_bool_col] = d[cast_bool_col].astype(int)
        y_train, y_val, y_test = train[label_col].values, val[label_col].values, test[label_col].values
        train_ds = lgb.Dataset(train[feature_cols], label=y_train)
        val_ds = lgb.Dataset(val[feature_cols], label=y_val, reference=train_ds)
        gbm = lgb.train(
            {"objective": "binary", "metric": "auc", "verbosity": -1, "seed": 42},
            train_ds, num_boost_round=500, valid_sets=[val_ds],
            callbacks=[lgb.early_stopping(30, verbose=False)],
        )
        return y_test, gbm.predict(test[feature_cols])

    df_a = con.sql("SELECT * FROM mart_churn_target").df()
    y_a, score_a = train_and_score(df_a, split_a, A_FEATURES, "churn_14d")

    df_b = con.sql("SELECT * FROM mart_purchase_propensity").df()
    y_b, score_b = train_and_score(df_b, split_b, B_FEATURES, "will_purchase_14d", cast_bool_col="has_purchase_history")

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))

    # ROC
    for y, score, name, color in [(y_a, score_a, "Model A (churn_14d)", "#C44E52"), (y_b, score_b, "Model B (will_purchase_14d)", "#4C72B0")]:
        fpr, tpr, _ = roc_curve(y, score)
        axes[0].plot(fpr, tpr, label=f"{name} (AUC={auc(fpr, tpr):.3f})", color=color, linewidth=2)
    axes[0].plot([0, 1], [0, 1], "k--", linewidth=1, label="무작위 (AUC=0.5)")
    axes[0].set_xlabel("False Positive Rate")
    axes[0].set_ylabel("True Positive Rate")
    axes[0].set_title("ROC Curve (test set, LightGBM)")
    axes[0].legend()

    # Lift curve
    lifts_at_10 = {}
    for y, score, name, color in [(y_a, score_a, "Model A (churn_14d)", "#C44E52"), (y_b, score_b, "Model B (will_purchase_14d)", "#4C72B0")]:
        order = np.argsort(-score)
        y_sorted = np.asarray(y)[order]
        base_rate = y_sorted.mean()
        pct_range = np.arange(1, 101)
        lifts = []
        n = len(y_sorted)
        for pct in pct_range:
            k = max(1, int(n * pct / 100))
            lifts.append((y_sorted[:k].mean() / base_rate) if base_rate > 0 else np.nan)
        axes[1].plot(pct_range, lifts, label=name, color=color, linewidth=2)
        lifts_at_10[name] = lifts[9]  # pct_range[9] == 10(%)
    axes[1].axhline(1.0, color="k", linestyle="--", linewidth=1, label="무작위 (Lift=1.0)")

    # 강조 1: Model A — Lift@10%가 무작위 기준선 근처에 눌려 있음 (인사이트 3, "1.0~1.07")
    lift_a_10 = lifts_at_10["Model A (churn_14d)"]
    axes[1].scatter([10], [lift_a_10], s=80, facecolors="none", edgecolors="#C44E52", linewidths=2, zorder=5)
    axes[1].annotate(
        "Lift 개선 미미\n(1.0~1.07)",
        xy=(10, lift_a_10), xytext=(28, 2.8),
        fontsize=9, color="#C44E52", fontweight="bold", ha="center",
        arrowprops=dict(arrowstyle="->", color="#C44E52", lw=1.5),
    )

    # 강조 2: Model B — Lift@10% (인사이트 4에서 언급한 6.23배)
    lift_b_10 = lifts_at_10["Model B (will_purchase_14d)"]
    axes[1].scatter([10], [lift_b_10], s=80, facecolors="none", edgecolors="#4C72B0", linewidths=2, zorder=5)
    axes[1].annotate(
        f"{lift_b_10:.2f}배",
        xy=(10, lift_b_10), xytext=(35, lift_b_10 + 1.8),
        fontsize=10, color="#4C72B0", fontweight="bold", ha="center",
        arrowprops=dict(arrowstyle="->", color="#4C72B0", lw=1.5),
    )

    axes[1].set_xlabel("접촉 비율 (상위 %)")
    axes[1].set_ylabel("Lift")
    axes[1].set_title("Lift Curve (test set, LightGBM)")
    axes[1].legend()

    fig.suptitle("Model A vs Model B — ROC / Lift 비교 (out-of-sample test)", y=1.02, fontsize=14)
    savefig(fig, "10_model_roc_lift_curves.png")


# ---------------- 결과 11: 타기팅 시뮬레이션 결과 ----------------
def fig11_targeting_simulation():
    df = pd.read_csv("reports/phase7_targeting_simulation.csv")
    df = df[~df["policy"].str.startswith("모델_vs")]

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    for model_name, ax, label_filter in [
        ("Model_A_churn", axes[0], "churn_14d"),
        ("Model_B_propensity", axes[1], "will_purchase_14d"),
    ]:
        sub = df[(df["model"] == model_name) & (df["label"] == label_filter)]
        for policy in sub["policy"].unique():
            p = sub[sub["policy"] == policy].sort_values("contact_rate_pct")
            ax.plot(p["contact_rate_pct"], p["lift"], marker="o", label=policy)
        ax.set_xlabel("접촉 비율 (%)")
        ax.set_ylabel("Lift")
        ax.set_title(f"{model_name} ({label_filter})")
        ax.legend(fontsize=8)
        ax.set_xticks([5, 10, 20, 30])

    fig.suptitle("타기팅 시뮬레이션 — 접촉 비율별 정책 간 Lift 비교 (test set)", y=1.02, fontsize=14)
    savefig(fig, "11_targeting_simulation_results.png")


# ---------------- 결과 12: 구매자 909,210명 경로 분해 (README 인사이트 1) ----------------
def fig12_buyer_path_breakdown():
    df = pd.read_csv("reports/tables/phase3_funnel_buyer_path_breakdown.csv")
    df = df[df["is_buyer"].astype(str) == "True"].copy()
    label_map = {
        ("O", "O"): "탐색O · 장바구니O",
        ("O", "X"): "탐색O · 장바구니X",
        ("X", "O"): "탐색X · 장바구니O",
        ("X", "X"): "탐색X · 장바구니X (기록 없는 구매)",
    }
    df["label"] = [label_map[(e, c)] for e, c in zip(df["has_explore"], df["has_cart"])]
    df = df.sort_values("n_customers", ascending=True).reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(9, 4.5))
    colors = ["#C44E52" if "기록 없는" in l else "#4C72B0" for l in df["label"]]
    bars = ax.barh(df["label"], df["n_customers"], color=colors)
    for b, n, pct, lbl in zip(bars, df["n_customers"], df["pct_of_buyers"], df["label"]):
        is_highlight = "기록 없는" in lbl
        text = f"  {n:,.0f}명 ({pct:.2f}%)" + ("  ← 인사이트 1" if is_highlight else "")
        ax.text(
            b.get_width(), b.get_y() + b.get_height() / 2, text, va="center", fontsize=10,
            fontweight="bold" if is_highlight else "normal",
            color="#8B0000" if is_highlight else "black",
        )

    # 강조: "탐색X·장바구니X (기록 없는 구매)" 막대 — 인사이트 1(28.46%)
    hpos = df.index[df["label"].str.contains("기록 없는")][0]
    hbar = bars[hpos]
    ax.add_patch(plt.Rectangle(
        (0, hbar.get_y()), hbar.get_width(), hbar.get_height(),
        fill=False, edgecolor="#8B0000", linewidth=2.5, zorder=5,
    ))
    ax.annotate(
        "탐색 기록 없음",
        xy=(hbar.get_width() * 0.15, hbar.get_y() + hbar.get_height() / 2),
        fontsize=10, fontweight="bold", color="white", va="center", ha="left",
    )
    ax.set_xlabel("구매자 수 (전체 909,210명 중)")
    ax.set_title("구매자의 탐색·장바구니 기록 유무별 경로 분해")
    ax.set_xlim(0, df["n_customers"].max() * 1.35)
    savefig(fig, "12_buyer_path_breakdown.png")


# ---------------- 결과 13: 장바구니 세그먼트 3분할 (README 인사이트 2) ----------------
def fig13_cart_segment_split():
    con = get_con()
    df = con.sql(
        """
        SELECT
            CASE WHEN segment = '장바구니_보류형' THEN '장바구니_보류형\n(제거 이벤트 없음, 미결정)'
                 WHEN cart_removal_subtype = 'fast_removal' THEN '장바구니_이탈형 - fast_removal\n(6시간 이내 제거)'
                 ELSE '장바구니_이탈형 - slow_removal\n(6시간 초과 후 제거)' END AS grp,
            COUNT(*) AS n
        FROM mart_customer_segment
        WHERE segment IN ('장바구니_보류형', '장바구니_이탈형')
        GROUP BY 1
        """
    ).df().sort_values("n", ascending=True).reset_index(drop=True)
    total = df["n"].sum()

    colors = ["#C44E52" if "보류형" in g else ("#DD8452" if "fast" in g else "#4C72B0") for g in df["grp"]]
    fig, ax = plt.subplots(figsize=(9, 4))
    bars = ax.barh(df["grp"], df["n"], color=colors)
    for b, n, g in zip(bars, df["n"], df["grp"]):
        is_highlight = "보류형" in g
        text = f"  {n:,.0f}명 ({n/total*100:.1f}%)" + ("  ← 인사이트 2" if is_highlight else "")
        ax.text(
            b.get_width(), b.get_y() + b.get_height() / 2, text, va="center", fontsize=10,
            fontweight="bold" if is_highlight else "normal",
            color="#8B0000" if is_highlight else "black",
        )

    # 강조: 장바구니_보류형(제거 이벤트 없음) 막대 — 인사이트 2(79.38%)
    hpos = df.index[df["grp"].str.contains("보류형")][0]
    hbar = bars[hpos]
    ax.add_patch(plt.Rectangle(
        (0, hbar.get_y()), hbar.get_width(), hbar.get_height(),
        fill=False, edgecolor="#8B0000", linewidth=2.5, zorder=5,
    ))
    ax.annotate(
        "제거 이벤트 없음",
        xy=(hbar.get_width() * 0.1, hbar.get_y() + hbar.get_height() / 2),
        fontsize=10, fontweight="bold", color="white", va="center", ha="left",
    )
    ax.set_xlabel("고객 수 (장바구니 활동 있는 비구매자 1,772,451명 중)")
    ax.set_title("장바구니 미전환 고객 3분할: 보류 vs 이탈(빠름/느림)")
    ax.set_xlim(0, df["n"].max() * 1.3)
    savefig(fig, "13_cart_segment_split.png")


# ---------------- 결과 14: 카테고리별 재구매율 (README 인사이트 5) ----------------
def fig14_category_repurchase_rate():
    df = pd.read_csv("reports/adhoc_category_repurchase_rate_n100plus.csv")
    overall_avg = df["repurchase_rate_pct"].mean()
    top = df.sort_values("repurchase_rate_pct", ascending=False).head(2)

    labels = ["전체 평균\n(표본 100명+ 카테고리 2,074개)"] + [
        f"카테고리 {int(r.category)}\n(고객 {r.n_customers:,.0f}명)" for r in top.itertuples()
    ]
    values = [overall_avg] + list(top["repurchase_rate_pct"])
    colors = ["#6B7280", "#C44E52", "#DD8452"]

    fig, ax = plt.subplots(figsize=(7, 4.5))
    bars = ax.bar(labels, values, color=colors)
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.2f}%", ha="center", va="bottom", fontsize=11)

    # 강조: 카테고리 1096(28.59%, z=95.9) — 인사이트 5에서 유의미 사례로 인용한 값
    hbar = bars[1]
    ax.add_patch(plt.Rectangle(
        (hbar.get_x(), 0), hbar.get_width(), hbar.get_height(),
        fill=False, edgecolor="#8B0000", linewidth=2.5, zorder=5,
    ))
    ax.annotate(
        "z=95.9\n(우연 아님)",
        xy=(hbar.get_x() + hbar.get_width() / 2, hbar.get_height()),
        xytext=(hbar.get_x() + hbar.get_width() / 2, hbar.get_height() * 0.55),
        fontsize=10, fontweight="bold", color="white", ha="center", va="center",
    )
    ax.set_ylabel("재구매율 (%)")
    ax.set_title("카테고리별 재구매율 — 전체 평균 vs 상위 카테고리")
    ax.set_ylim(0, max(values) * 1.2)
    savefig(fig, "14_category_repurchase_rate.png")


if __name__ == "__main__":
    steps = [
        fig01_daily_event_volume,
        fig02_customer_event_count_distribution,
        fig03_purchase_gap_distribution,
        fig04_price_bucket_conversion,
        fig05_event_type_count_distribution,
        fig06_funnel_chart,
        fig07_cohort_retention_heatmap,
        fig08_lifecycle_distribution,
        fig09_segment_distribution,
        fig10_model_roc_lift,
        fig11_targeting_simulation,
        fig12_buyer_path_breakdown,
        fig13_cart_segment_split,
        fig14_category_repurchase_rate,
    ]
    for step in steps:
        print(f"\n=== {step.__name__} ===")
        step()
    print("\n전체 완료")

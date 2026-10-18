"""가설 H1~H6 검증: 구간화, WoE/IV, Wilson CI, 방향 확인, 안정성, 판정.

판정 기준은 고정이며 결과를 보고 바꾸지 않는다:
  채택 = 핵심 변수 IV>=0.02 AND Spearman 부호 일치 AND 높은끝>낮은끝 AND 배수CI하한>1
"""
import json
import os

import duckdb
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

os.makedirs("docs", exist_ok=True)

DB_PATH = "data/v2.duckdb"
con = duckdb.connect(DB_PATH, read_only=True)
df = con.execute("SELECT * FROM training_features").fetchdf()
con.close()
print("학습 피처 테이블 로드:", df.shape)

Z = 1.96
MIN_BIN_FRAC = 0.05
TOTAL_N = len(df)
MIN_BIN_N = TOTAL_N * MIN_BIN_FRAC

HYPOTHESES = {
    "H1": {
        "label": "최근에 활동한 고객일수록 곧 구매할 가능성이 높다",
        "core": "h1_days_since_last_activity", "core_dir": "lower_better",
        "aux": {"h1_days_since_last_visit": "lower_better",
                "h1_days_since_last_cart_add": "lower_better",
                "h1_active_days_last30": "higher_better"},
    },
    "H2": {
        "label": "장바구니에 담아두고 아직 사지도 빼지도 않은 상품이 있는 고객은 구매 가능성이 높다",
        "core": "h2_pending_items", "core_dir": "higher_better",
        "aux": {"h2_has_pending": "higher_better", "h2_pending_items_last7": "higher_better"},
    },
    "H3": {
        "label": "과거에 구매한 적 있는 고객은 구매 가능성이 높다",
        "core": "h3_purchase_count", "core_dir": "higher_better",
        "aux": {"h3_days_since_last_purchase": "lower_better", "h3_unique_skus_bought": "higher_better"},
    },
    "H4": {
        "label": "실제 검색을 한 고객은 구매 가능성이 높다",
        "core": "h4_real_search_count", "core_dir": "higher_better",
        "aux": {"h4_unique_queries": "higher_better", "h4_real_search_last7": "higher_better"},
    },
    "H5": {
        "label": "최근 활동이 늘어나는 고객은 구매 가능성이 높다",
        "core": "h5_activity_growth_ratio", "core_dir": "higher_better",
        "aux": {"h5_active_days_growth_ratio": "higher_better"},
    },
    "H6": {
        "label": "장바구니에서 상품을 뺀 고객은 담기만 한 고객보다 구매 가능성이 낮다",
        "core": "h6_removal_ratio", "core_dir": "lower_better",
        "aux": {"h6_removal_last7": "lower_better"},
    },
}
REFERENCE_VARS = {"ref_default_search_flag": "lower_better"}  # 판정에 쓰지 않음, IV만 기록


def greedy_merge(counts_series, min_count):
    groups, cur, cur_sum = [], [], 0
    for idx, c in counts_series.items():
        cur.append(idx); cur_sum += c
        if cur_sum >= min_count:
            groups.append(cur); cur, cur_sum = [], 0
    if cur:
        if groups:
            groups[-1].extend(cur)
        else:
            groups.append(cur)
    mapping = {}
    for new_i, idxs in enumerate(groups):
        for i in idxs:
            mapping[i] = new_i
    return mapping, len(groups)


def bin_variable(series, is_binary=False, na_label="결측", zero_threshold=0.3, n_qbins=10):
    s = series.copy()
    is_na = s.isna()
    labels = pd.Series(index=s.index, dtype=object)
    labels[is_na] = na_label

    if is_binary:
        non_na = ~is_na
        labels[non_na] = s[non_na].astype(int).astype(str)
        bin_order = ["0", "1"]
        return labels, bin_order

    non_na_vals = s[~is_na]
    zero_share = (non_na_vals == 0).mean() if len(non_na_vals) else 0
    use_zero = zero_share >= zero_threshold
    if use_zero:
        is_zero = (~is_na) & (s == 0)
        labels[is_zero] = "0"
        rest_mask = (~is_na) & (~is_zero)
    else:
        rest_mask = ~is_na

    rest_vals = s[rest_mask]
    bin_order = ["0"] if use_zero else []
    if len(rest_vals) > 0:
        try:
            qcodes = pd.qcut(rest_vals, q=n_qbins, duplicates="drop").cat.codes
        except ValueError:
            qcodes = pd.Series(0, index=rest_vals.index)
        counts = qcodes.value_counts().sort_index()
        mapping, n_groups = greedy_merge(counts, MIN_BIN_N)
        merged = qcodes.map(mapping)
        for i in range(n_groups):
            lbl = f"Q{i+1}"
            labels[rest_mask & (merged == i).reindex(labels.index, fill_value=False)] = lbl
            bin_order.append(lbl)
    return labels, bin_order


def wilson_ci(successes, n, z=Z):
    if n == 0:
        return (np.nan, np.nan)
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0, center - half), min(1, center + half))


def woe_iv_table(labels, outcome):
    tmp = pd.DataFrame({"bin": labels, "outcome": outcome})
    grp = tmp.groupby("bin")["outcome"].agg(n="count", good="sum")
    grp["bad"] = grp["n"] - grp["good"]
    grp["good_adj"] = grp["good"] + 0.5
    grp["bad_adj"] = grp["bad"] + 0.5
    total_good, total_bad = grp["good_adj"].sum(), grp["bad_adj"].sum()
    grp["good_dist"] = grp["good_adj"] / total_good
    grp["bad_dist"] = grp["bad_adj"] / total_bad
    grp["woe"] = np.log(grp["good_dist"] / grp["bad_dist"])
    grp["iv_component"] = (grp["good_dist"] - grp["bad_dist"]) * grp["woe"]
    grp["purchase_rate"] = grp["good"] / grp["n"]
    ci = grp.apply(lambda r: wilson_ci(r["good"], r["n"]), axis=1)
    grp["ci_low"] = ci.map(lambda t: t[0])
    grp["ci_high"] = ci.map(lambda t: t[1])
    iv = grp["iv_component"].sum()
    return grp, iv


def iv_strength(iv):
    if iv < 0.02:
        return "없음"
    if iv < 0.1:
        return "약함"
    if iv < 0.3:
        return "중간"
    return "강함"


def rate_ratio_ci(p_high, n_high, p_low, n_low, z=Z):
    if p_high <= 0 or p_low <= 0 or n_high == 0 or n_low == 0:
        return (np.nan, np.nan, np.nan)
    ratio = p_high / p_low
    se = np.sqrt((1 - p_high) / (n_high * p_high) + (1 - p_low) / (n_low * p_low))
    return (ratio, ratio * np.exp(-z * se), ratio * np.exp(z * se))


def spearman_rank_corr(x, y):
    rx, ry = pd.Series(x).rank(), pd.Series(y).rank()
    if rx.nunique() < 2 or ry.nunique() < 2:
        return np.nan
    return rx.corr(ry)


def analyze_variable(df, col, direction, is_binary=False, na_label="결측"):
    labels, bin_order = bin_variable(df[col], is_binary=is_binary, na_label=na_label)
    grp, iv = woe_iv_table(labels, df["outcome"])
    grp = grp.reindex([b for b in bin_order if b in grp.index] +
                       [b for b in grp.index if b not in bin_order])  # 순서: bin_order 먼저, 결측/특수 뒤
    ordered = [b for b in bin_order if b in grp.index]
    if len(ordered) >= 2:
        ranks = list(range(1, len(ordered) + 1))
        rates = grp.loc[ordered, "purchase_rate"].values
        spearman = spearman_rank_corr(ranks, rates)
        if direction == "higher_better":
            low_end, high_end = ordered[0], ordered[-1]
            expected_sign = 1
        else:
            low_end, high_end = ordered[-1], ordered[0]
            expected_sign = -1
        p_high, n_high = grp.loc[high_end, "purchase_rate"], grp.loc[high_end, "n"]
        p_low, n_low = grp.loc[low_end, "purchase_rate"], grp.loc[low_end, "n"]
        ratio, ci_lo, ci_hi = rate_ratio_ci(p_high, n_high, p_low, n_low)
        spearman_ok = (not np.isnan(spearman)) and (np.sign(spearman) == expected_sign)
        rate_ok = p_high > p_low
        ci_ok = (not np.isnan(ci_lo)) and ci_lo > 1
    else:
        spearman, ratio, ci_lo, ci_hi = np.nan, np.nan, np.nan, np.nan
        spearman_ok = rate_ok = ci_ok = False
        high_end = low_end = None
        p_high = p_low = np.nan

    return {
        "col": col, "direction": direction, "iv": iv, "strength": iv_strength(iv),
        "bin_table": grp.reset_index().rename(columns={"index": "bin"}),
        "bin_order": ordered, "spearman": spearman, "spearman_ok": spearman_ok,
        "high_end": high_end, "low_end": low_end, "p_high": p_high, "p_low": p_low,
        "rate_ok": rate_ok, "ratio": ratio, "ratio_ci_low": ci_lo, "ratio_ci_high": ci_hi, "ci_ok": ci_ok,
        "labels": labels,
    }


BINARY_COLS = {"h2_has_pending", "h4_real_search_last7", "h6_removal_last7", "ref_default_search_flag",
               "h5_no_prior_activity"}

all_results = {}
verdicts = {}
for hname, hdef in HYPOTHESES.items():
    print(f"\n===== {hname}: {hdef['label']} =====")
    core_res = analyze_variable(df, hdef["core"], hdef["core_dir"], is_binary=hdef["core"] in BINARY_COLS,
                                 na_label="이전활동없음" if hdef["core"].startswith("h5_") else "결측")
    verdict = "채택" if (core_res["iv"] >= 0.02 and core_res["spearman_ok"]
                        and core_res["rate_ok"] and core_res["ci_ok"]) else "기각"
    print("핵심 변수:", hdef["core"], "IV=", round(core_res["iv"], 4), core_res["strength"], "판정:", verdict)
    print(core_res["bin_table"][["n", "good", "purchase_rate", "ci_low", "ci_high"]].to_string())

    aux_results = {}
    for aux_col, aux_dir in hdef["aux"].items():
        r = analyze_variable(df, aux_col, aux_dir, is_binary=aux_col in BINARY_COLS,
                              na_label="이전활동없음" if aux_col.startswith("h5_") else "결측")
        aux_results[aux_col] = r
        print("  보조:", aux_col, "IV=", round(r["iv"], 4), r["strength"],
              "방향지지:", r["spearman_ok"] and r["rate_ok"])

    # 안정성: 핵심 변수 라벨을 고정한 채 기준일별 IV
    stability = {}
    for d in sorted(df["reference_date"].unique()):
        mask = df["reference_date"] == d
        _, iv_d = woe_iv_table(core_res["labels"][mask], df.loc[mask, "outcome"])
        stability[d] = round(float(iv_d), 4)
    print("  안정성(기준일별 IV):", stability)

    all_results[hname] = {
        "core": core_res, "aux": aux_results, "stability": stability, "verdict": verdict,
    }
    verdicts[hname] = verdict

# 참고 변수
ref_results = {}
for col, direction in REFERENCE_VARS.items():
    r = analyze_variable(df, col, direction, is_binary=col in BINARY_COLS)
    ref_results[col] = r
    print(f"\n참고 변수 {col}: IV=", round(r["iv"], 4), r["strength"])

# ---------- JSON 저장 (bin_table, labels 제외하고 요약만) ----------
def summarize(res):
    return {
        "col": res["col"], "direction": res["direction"], "iv": round(float(res["iv"]), 4),
        "strength": res["strength"], "bin_order": res["bin_order"],
        "bins": res["bin_table"][["bin", "n", "good", "purchase_rate", "ci_low", "ci_high"]].rename(
            columns={"bin": "bin_label"}).to_dict(orient="records"),
        "spearman": None if pd.isna(res["spearman"]) else round(float(res["spearman"]), 4),
        "spearman_ok": bool(res["spearman_ok"]),
        "high_end": res["high_end"], "low_end": res["low_end"],
        "p_high": None if pd.isna(res["p_high"]) else round(float(res["p_high"]), 5),
        "p_low": None if pd.isna(res["p_low"]) else round(float(res["p_low"]), 5),
        "rate_ok": bool(res["rate_ok"]),
        "ratio": None if pd.isna(res["ratio"]) else round(float(res["ratio"]), 3),
        "ratio_ci_low": None if pd.isna(res["ratio_ci_low"]) else round(float(res["ratio_ci_low"]), 3),
        "ratio_ci_high": None if pd.isna(res["ratio_ci_high"]) else round(float(res["ratio_ci_high"]), 3),
        "ci_ok": bool(res["ci_ok"]),
    }

output = {"n_training_rows": TOTAL_N, "min_bin_n": MIN_BIN_N, "hypotheses": {}, "reference": {}}
for hname, r in all_results.items():
    output["hypotheses"][hname] = {
        "label": HYPOTHESES[hname]["label"], "verdict": r["verdict"],
        "core": summarize(r["core"]), "aux": {k: summarize(v) for k, v in r["aux"].items()},
        "stability": r["stability"],
    }
for col, r in ref_results.items():
    output["reference"][col] = summarize(r)

with open("docs/hypothesis_results.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2, default=str)
print("\nwrote docs/hypothesis_results.json")

# ---------- 그림 1: iv_by_hypothesis.png ----------
plt.rcParams["font.family"] = "AppleGothic"
plt.rcParams["axes.unicode_minus"] = False

rows = []
for hname, hdef in HYPOTHESES.items():
    rows.append((f"{hname} 핵심: {hdef['core']}", all_results[hname]["core"]["iv"], True))
    for aux_col in hdef["aux"]:
        rows.append((f"{hname} 보조: {aux_col}", all_results[hname]["aux"][aux_col]["iv"], False))
for col in REFERENCE_VARS:
    rows.append((f"참고: {col}", ref_results[col]["iv"], False))

iv_df = pd.DataFrame(rows, columns=["변수", "IV", "is_core"]).sort_values("IV")
fig, ax = plt.subplots(figsize=(9, max(6, len(iv_df) * 0.35)))
colors = ["tab:orange" if c else "tab:blue" for c in iv_df["is_core"]]
ax.barh(iv_df["변수"], iv_df["IV"], color=colors)
for x in [0.02, 0.1, 0.3]:
    ax.axvline(x, color="gray", linestyle="--", linewidth=1)
ax.set_xlabel("IV")
ax.set_title("가설별 변수 IV (주황=핵심 변수, 파랑=보조/참고, 점선=0.02/0.1/0.3 기준)")
fig.tight_layout()
fig.savefig("docs/figures/iv_by_hypothesis.png", dpi=150)
print("saved docs/figures/iv_by_hypothesis.png")

# ---------- 그림 2: core_signals.png ----------
overall_rate = df["outcome"].mean()
fig, axes = plt.subplots(3, 2, figsize=(13, 13))
for ax, (hname, hdef) in zip(axes.flat, HYPOTHESES.items()):
    r = all_results[hname]["core"]
    bt = r["bin_table"].set_index("bin").reindex(r["bin_order"])
    x = range(len(bt))
    ax.bar(x, bt["purchase_rate"], yerr=[bt["purchase_rate"] - bt["ci_low"], bt["ci_high"] - bt["purchase_rate"]],
           capsize=3, color="steelblue")
    ax.axhline(overall_rate, color="red", linestyle="--", linewidth=1, label="학습 전체 평균 구매율")
    ax.set_xticks(list(x))
    ax.set_xticklabels(bt.index, rotation=45, ha="right", fontsize=8)
    ax.set_title(f"{hname}: {hdef['core']}\nIV={r['iv']:.3f} ({r['strength']}), 판정={all_results[hname]['verdict']}")
    ax.set_ylabel("구매율")
    ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig("docs/figures/core_signals.png", dpi=150)
print("saved docs/figures/core_signals.png")

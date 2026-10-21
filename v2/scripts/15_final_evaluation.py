"""4단계 최종 평가: 최종 평가 기준일(2022-11-23)을 "한 번만" 연다.

00_analysis_rules.md 7번(4단계 데이터 사용 순서)에 따라, 이 스크립트를 실행하기
전까지는 11-23의 구매 결과를 한 번도 연 적이 없어야 한다. 실행 후에는 모델·변수·
설정을 바꾸지 않는다. 판정 기준(H7/H8)은 사전에 고정되어 있다.
"""
import json
import os
import pickle
import sys

import duckdb
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from _features import build_features, shift, CORE_AUX_COLS, FLAG_COLS, COUNT_LIKE_COLS  # noqa: E402

os.makedirs("docs", exist_ok=True)
os.makedirs("verification", exist_ok=True)
SEED = 42

DB_PATH = "data/v2.duckdb"
con = duckdb.connect(DB_PATH)
con.execute("SET threads=4")
con.execute("SET memory_limit='6GB'")
con.execute(f"SET temp_directory='{os.path.abspath('data/tmp')}'")
con.execute("SET preserve_insertion_order=false")

FINAL_DATE = "2022-11-23"
results = {}

with open("data/final_model.pkl", "rb") as f:
    model_bundle = pickle.load(f)
print("불러온 최종 모델:", model_bundle["model_name"],
      "기본값검색표시 유지:", model_bundle["keeps_default_search_flag"])


def score_with_final_model(df):
    name = model_bundle["model_name"]
    keep = model_bundle["keeps_default_search_flag"]
    if name == "LightGBM":
        booster = model_bundle["lightgbm_model"] if keep else model_bundle["lightgbm_model_noflag"]
        cols = model_bundle["lightgbm_cols"] if keep else model_bundle["lightgbm_cols_noflag"]
        return pd.Series(booster.predict(df[cols], num_iteration=booster.best_iteration), index=df.index)
    else:
        m = model_bundle["logistic_model"] if keep else model_bundle["logistic_model_noflag"]
        cols = model_bundle["logistic_cols"] if keep else model_bundle["logistic_cols_noflag"]
        return pd.Series(m.predict_proba(df[cols].fillna(0).values)[:, 1], index=df.index)


def add_transforms(df, caps):
    for c in CORE_AUX_COLS:
        df[f"{c}_missing"] = df[c].isna().astype(int)
    for c in COUNT_LIKE_COLS:
        df[f"{c}_log1p"] = np.log1p(df[c].fillna(0))
    for c in CORE_AUX_COLS:
        src = f"{c}_log1p" if c in COUNT_LIKE_COLS else c
        df[f"{c}_capped"] = df[src].fillna(0).clip(upper=caps[c])
    return df


print("\n== 최종 평가 모집단(2022-11-23) 변수·결과 생성 — 이번 호출이 11-23 구매 결과를 처음이자 마지막으로 연다 ==")
final_pop = con.execute(
    f"SELECT client_id FROM pop_{FINAL_DATE.replace('-', '')}_clean ORDER BY client_id"
).fetchdf()
print("최종 평가 모집단 인원:", len(final_pop))
final_feat = build_features(con, final_pop, FINAL_DATE)
out_start, out_end = shift(FINAL_DATE, 0), shift(FINAL_DATE, 14)
final_outcome = con.execute(
    f"""SELECT p.client_id, CASE WHEN b.client_id IS NOT NULL THEN 1 ELSE 0 END AS outcome
        FROM pop_{FINAL_DATE.replace('-', '')}_clean p
        LEFT JOIN (SELECT DISTINCT client_id FROM clean_product_buy
                    WHERE timestamp >= '{out_start}' AND timestamp < '{out_end}') b
        ON p.client_id = b.client_id"""
).fetchdf()
final_df = final_feat.merge(final_outcome, on="client_id", how="left")
final_df = add_transforms(final_df, model_bundle["caps_p999"])
print("최종 평가 테이블 크기:", final_df.shape, "구매자 수:", int(final_df["outcome"].sum()),
      "구매율:", round(final_df["outcome"].mean() * 100, 4), "%")
results["final_population"] = {"n": len(final_df), "n_purchasers": int(final_df["outcome"].sum()),
                                 "purchase_rate_pct": round(final_df["outcome"].mean() * 100, 4)}
final_df.to_parquet("data/tmp/final_df.parquet")

rng_tie = np.random.default_rng(SEED)
final_tiebreak = pd.Series(rng_tie.random(len(final_df)), index=final_df.index)
rng_rand = np.random.default_rng(SEED)
final_random_score = pd.Series(rng_rand.random(len(final_df)), index=final_df.index)

final_scores = {
    "무작위": final_random_score,
    "최근활동순(현행기준)": -final_df["h1_days_since_last_activity"].fillna(1e9),
    "단순2단계규칙": final_df["ref_other_than_browsing"] * 1_000_000
                      - final_df["h1_days_since_last_activity"].fillna(1e9),
    model_bundle["model_name"] + "(최종모델)": score_with_final_model(final_df),
}


def evaluate_ranking(score, outcome, tiebreak, fractions=(0.05, 0.10, 0.20)):
    n = len(score)
    order = pd.DataFrame({"score": score, "tiebreak": tiebreak, "outcome": outcome}).sort_values(
        ["score", "tiebreak"], ascending=[False, False])
    total_pos = int(outcome.sum())
    out = {}
    for frac in fractions:
        k = int(round(n * frac))
        top = order.iloc[:k]
        captured = int(top["outcome"].sum())
        out[frac] = {"n_sent": k, "n_captured": captured,
                      "capture_rate": round(captured / total_pos, 5) if total_pos else None,
                      "per_10k": round(captured / k * 10000, 2) if k else None}
    return out


# ========== 3-1. 기본 결과 ==========
print("\n## 3-1. 기본 결과 (방법 4개 x 발송량 3개)")
basic_table = {}
for name, score in final_scores.items():
    basic_table[name] = evaluate_ranking(score, final_df["outcome"], final_tiebreak)
    print(name, basic_table[name])
results["basic_table"] = basic_table

with open("docs/final_evaluation_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/final_evaluation_results.json (3-1까지)")

# ========== 3-2. H7: 같은 발송량에서 현행 기준보다 더 많은 구매 고객을 포함하는가 ==========
print("\n## 3-2. H7")
final_model_name = model_bundle["model_name"] + "(최종모델)"
outcome_arr = final_df["outcome"].values.astype(np.int64)
n_total = len(outcome_arr)


def top_k_captured_precise(score_arr, tiebreak_arr, outcome_arr, k):
    """1회성 계산용(정확한 동률 처리, seed=42 난수로 구분) — lexsort, O(n log n)."""
    order = np.lexsort((-tiebreak_arr, -score_arr))
    return int(outcome_arr[order[:k]].sum())


def top_k_captured_fast(score_arr, outcome_arr, k):
    """부트스트랩 1,000회 반복용(동률은 argpartition의 결정론적이지만 비지정 순서로 처리) — O(n)."""
    n = len(score_arr)
    if k >= n:
        return int(outcome_arr.sum())
    idx = np.argpartition(-score_arr, k - 1)[:k]
    return int(outcome_arr[idx].sum())


def bootstrap_diffs_all(scoreA, scoreB, scoreC, outcome_arr, fractions, n_boot=1000, seed=SEED):
    """scoreA(최종모델) vs scoreB(최근활동순), scoreA vs scoreC(단순2단계규칙)를
    같은 재표본(고객 단위 복원추출)으로 한 번에 계산해 재표본 비용을 공유한다."""
    n = len(outcome_arr)
    rng_b = np.random.default_rng(seed)
    out = {frac: {"vs_recency": np.empty(n_boot, dtype=np.int64),
                  "vs_simple": np.empty(n_boot, dtype=np.int64)} for frac in fractions}
    for i in range(n_boot):
        idx = rng_b.integers(0, n, n)
        sA, sB, sC, o = scoreA[idx], scoreB[idx], scoreC[idx], outcome_arr[idx]
        for frac in fractions:
            k = int(round(n * frac))
            capA = top_k_captured_fast(sA, o, k)
            capB = top_k_captured_fast(sB, o, k)
            capC = top_k_captured_fast(sC, o, k)
            out[frac]["vs_recency"][i] = capA - capB
            out[frac]["vs_simple"][i] = capA - capC
    return out


tiebreak_arr = final_tiebreak.values
model_score_arr = final_scores[final_model_name].values
recency_score_arr = final_scores["최근활동순(현행기준)"].values
simple_score_arr = final_scores["단순2단계규칙"].values

print("부트스트랩 1,000회 (고객 단위 복원추출, seed=42) 계산 중 — 몇 분 걸릴 수 있음")
FRACTIONS = (0.05, 0.10, 0.20)
boot_out = bootstrap_diffs_all(model_score_arr, recency_score_arr, simple_score_arr, outcome_arr, FRACTIONS)

h7_main, h7_ref = {}, {}
for frac in FRACTIONS:
    k = int(round(n_total * frac))
    capA = top_k_captured_precise(model_score_arr, tiebreak_arr, outcome_arr, k)
    capB = top_k_captured_precise(recency_score_arr, tiebreak_arr, outcome_arr, k)
    capC = top_k_captured_precise(simple_score_arr, tiebreak_arr, outcome_arr, k)

    diffs_r = boot_out[frac]["vs_recency"]
    ci_low_r, ci_high_r = np.percentile(diffs_r, [2.5, 97.5])
    h7_main[frac] = {"n_sent": k, "captured_model": capA, "captured_recency": capB,
                      "diff": capA - capB, "ci95_low": float(ci_low_r), "ci95_high": float(ci_high_r)}
    print(f"발송 {frac*100:.0f}% (모델 vs 최근활동순):", h7_main[frac])

    diffs_s = boot_out[frac]["vs_simple"]
    ci_low_s, ci_high_s = np.percentile(diffs_s, [2.5, 97.5])
    h7_ref[frac] = {"n_sent": k, "captured_model": capA, "captured_simple_rule": capC,
                     "diff": capA - capC, "ci95_low": float(ci_low_s), "ci95_high": float(ci_high_s)}
    print(f"발송 {frac*100:.0f}% (모델 vs 단순2단계규칙, 참고):", h7_ref[frac])

verdict_flags = [v["ci95_low"] > 0 for v in h7_main.values()]
if all(verdict_flags):
    h7_verdict = "채택"
elif any(verdict_flags):
    which = [f"{int(frac*100)}%" for frac, v in h7_main.items() if v["ci95_low"] > 0]
    h7_verdict = f"부분채택({','.join(which)})"
else:
    h7_verdict = "기각"
print("H7 판정:", h7_verdict)
results["h7_main"] = h7_main
results["h7_verdict"] = h7_verdict
results["h7_vs_simple_rule"] = h7_ref

# 발송량 절감: 최근활동순 상위10%가 잡는 구매 고객 수를 최종모델은 몇 % 발송으로 달성하는가
target_captured = h7_main[0.10]["captured_recency"]
order_model = pd.DataFrame({"score": model_score_arr, "tiebreak": tiebreak_arr,
                             "outcome": outcome_arr}).sort_values(["score", "tiebreak"], ascending=[False, False])
cum_captured = order_model["outcome"].cumsum().values
needed_k = int(np.searchsorted(cum_captured, target_captured) + 1)
needed_pct = needed_k / n_total * 100
reduction_pct = (1 - needed_k / h7_main[0.10]["n_sent"]) * 100
print(f"\n발송량 절감: 최근활동순 상위10%가 잡는 구매자 {target_captured}명을 최종모델은 "
      f"상위 {needed_pct:.2f}% 발송으로 달성 (발송량 {reduction_pct:.1f}% 감소)")
results["send_volume_reduction"] = {
    "target_captured_by_recency_top10pct": target_captured,
    "model_needed_pct": round(needed_pct, 3), "model_needed_n": needed_k,
    "reduction_pct_vs_recency_top10pct_volume": round(reduction_pct, 2),
}

with open("docs/final_evaluation_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/final_evaluation_results.json (H7까지)")

# ========== 3-3. H8: 적정 발송량이 존재하는가 ==========
print("\n## 3-3. H8")
op_name = (final_model_name if model_bundle.get("operational_recommendation") == "모델"
           else "단순2단계규칙")
# operational_recommendation은 검증 단계(models_results.json)에서 결정된 값을 그대로 쓴다.
with open("docs/models_results.json", encoding="utf-8") as f:
    models_results = json.load(f)
operational_recommendation = models_results["rule3_operational_recommendation"]["recommendation"]
op_score_arr = model_score_arr if operational_recommendation == "모델" else simple_score_arr
op_label = final_model_name if operational_recommendation == "모델" else "단순2단계규칙"
print("운영 권고안(검증 단계에서 결정):", operational_recommendation, "->", op_label)

SEGMENTS = [(0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20), (0.20, 0.30), (0.30, 0.50), (0.50, 1.00)]


def segment_efficiency(score_arr, tiebreak_arr, outcome_arr, segments):
    order = pd.DataFrame({"score": score_arr, "tiebreak": tiebreak_arr, "outcome": outcome_arr}).sort_values(
        ["score", "tiebreak"], ascending=[False, False]).reset_index(drop=True)
    n = len(order)
    out = {}
    for lo, hi in segments:
        i0, i1 = int(round(n * lo)), int(round(n * hi))
        seg = order.iloc[i0:i1]
        cnt = len(seg)
        captured = int(seg["outcome"].sum())
        out[f"{int(lo*100)}~{int(hi*100)}%"] = {
            "n": cnt, "captured": captured,
            "per_1000": round(captured / cnt * 1000, 3) if cnt else None,
        }
    return out


h8_op = segment_efficiency(op_score_arr, tiebreak_arr, outcome_arr, SEGMENTS)
h8_recency = segment_efficiency(recency_score_arr, tiebreak_arr, outcome_arr, SEGMENTS)
print("운영 권고안 구간별 1,000건당 구매 고객 수:", h8_op)
print("최근활동순 구간별 1,000건당 구매 고객 수:", h8_recency)

first_seg_val = h8_op["0~5%"]["per_1000"]
mid_seg_val = h8_op["15~20%"]["per_1000"]
h8_verdict = "채택" if (first_seg_val and mid_seg_val is not None and mid_seg_val <= first_seg_val / 2) else "기각"
print(f"H8 판정: {h8_verdict} (0~5% 구간 {first_seg_val} vs 15~20% 구간 {mid_seg_val})")
results["h8_operational_segments"] = h8_op
results["h8_recency_segments"] = h8_recency
results["h8_verdict"] = h8_verdict
results["h8_operational_method"] = op_label

with open("docs/final_evaluation_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/final_evaluation_results.json (H8까지)")

# ========== 3-4. 한계 정량화 ==========
print("\n## 3-4. 한계 정량화")
visit_only_mask = (
    final_df["h1_days_since_last_visit"].notna() & final_df["h1_days_since_last_cart_add"].isna()
    & (final_df["h3_purchase_count"] == 0) & (final_df["h4_real_search_count"] == 0)
).values
purchaser_mask = outcome_arr == 1
n_visit_only_purchasers = int((visit_only_mask & purchaser_mask).sum())
n_total_purchasers = int(purchaser_mask.sum())
share_vo_purchasers = n_visit_only_purchasers / n_total_purchasers
print(f"최종평가 구매 고객 중 방문만 하던 고객 비중: {n_visit_only_purchasers}/{n_total_purchasers} "
      f"({share_vo_purchasers*100:.2f}%)")

limitation = {"n_visit_only_purchasers": n_visit_only_purchasers, "n_total_purchasers": n_total_purchasers,
              "share_pct": round(share_vo_purchasers * 100, 3), "by_method_top10pct_capture_of_vo": {}}
for name, score in final_scores.items():
    score_arr_m = score.values
    k = int(round(n_total * 0.10))
    order = np.lexsort((-tiebreak_arr, -score_arr_m))
    idx = order[:k]
    captured_vo = int((visit_only_mask[idx] & purchaser_mask[idx]).sum())
    rate = captured_vo / n_visit_only_purchasers if n_visit_only_purchasers else None
    limitation["by_method_top10pct_capture_of_vo"][name] = {
        "captured": captured_vo, "rate_pct": round(rate * 100, 3) if rate is not None else None,
    }
    print(name, "방문전용 구매자 중 상위10% 발송 포착:", captured_vo, f"({rate*100:.2f}%)" if rate else "")
results["limitation_quantification"] = limitation

with open("docs/final_evaluation_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/final_evaluation_results.json (한계정량화까지)")

# ========== 3-5. 민감도 확인 ==========
print("\n## 3-5. 민감도 확인")
sensitivity = {}

# (a) 속도 봇 제외를 하지 않은 경우: 11-23 window에 해당하는 속도봇(약 80명)을 다시 포함
print("(a) 속도 봇 제외 미적용")
w30_start_f, w30_end_f = shift(FINAL_DATE, -30), shift(FINAL_DATE, 0)
union_sql_f = " UNION ALL ".join(
    f"SELECT client_id FROM clean_{t} WHERE timestamp >= '{w30_start_f}' AND timestamp < '{w30_end_f}'"
    for t in ["product_buy", "add_to_cart", "remove_from_cart", "page_visit", "search_query"]
)
pop_with_speedbot = con.execute(f"""
    SELECT DISTINCT client_id FROM ({union_sql_f}) u
    WHERE client_id NOT IN (SELECT client_id FROM bot_clients)
    ORDER BY client_id
""").fetchdf()
added_ids = pop_with_speedbot[~pop_with_speedbot["client_id"].isin(final_df["client_id"])]
print("다시 포함되는 속도봇 인원:", len(added_ids))
if len(added_ids) > 0:
    added_feat = build_features(con, added_ids, FINAL_DATE, pop_table_name="cur_pop_addedbot")
    con.register("added_ids_df", added_ids[["client_id"]])
    added_outcome = con.execute(
        f"""SELECT a.client_id, CASE WHEN b.client_id IS NOT NULL THEN 1 ELSE 0 END AS outcome
            FROM added_ids_df a
            LEFT JOIN (SELECT DISTINCT client_id FROM clean_product_buy
                        WHERE timestamp >= '{out_start}' AND timestamp < '{out_end}') b
            ON a.client_id = b.client_id"""
    ).fetchdf()
    added_df = added_feat.merge(added_ids[["client_id"]], on="client_id").merge(
        added_outcome.drop_duplicates("client_id"), on="client_id", how="left")
    added_df["outcome"] = added_df["outcome"].fillna(0).astype(int)
    added_df = add_transforms(added_df, model_bundle["caps_p999"])
    added_df["score_model"] = score_with_final_model(added_df).values
    added_df["score_simple"] = (added_df["ref_other_than_browsing"] * 1_000_000
                                 - added_df["h1_days_since_last_activity"].fillna(1e9))
    combined_n = n_total + len(added_df)
    combined_score_model = np.concatenate([model_score_arr, added_df["score_model"].values])
    combined_score_simple = np.concatenate([simple_score_arr, added_df["score_simple"].values])
    combined_outcome = np.concatenate([outcome_arr, added_df["outcome"].values])
    combined_tiebreak = np.concatenate([tiebreak_arr, np.random.default_rng(SEED).random(len(added_df))])
    k10_combined = int(round(combined_n * 0.10))
    cap_model_a = top_k_captured_precise(combined_score_model, combined_tiebreak, combined_outcome, k10_combined)
    cap_simple_a = top_k_captured_precise(combined_score_simple, combined_tiebreak, combined_outcome, k10_combined)
    sensitivity["a_no_speedbot_exclusion"] = {
        "n_added": len(added_df), "n_population": combined_n,
        "model_capture10_rate": round(cap_model_a / int(combined_outcome.sum()), 5),
        "simple_capture10_rate": round(cap_simple_a / int(combined_outcome.sum()), 5),
        "model_capture10_n": cap_model_a, "simple_capture10_n": cap_simple_a,
    }
else:
    sensitivity["a_no_speedbot_exclusion"] = {"n_added": 0, "note": "11-23 모집단 창에 해당하는 속도봇 없음"}
print(sensitivity["a_no_speedbot_exclusion"])

# (b) 결과 기간에서 2022-12-04 하루 제외
print("(b) 결과 기간에서 2022-12-04 제외")
outcome_no1204 = con.execute(
    f"""SELECT p.client_id,
               CASE WHEN b.client_id IS NOT NULL THEN 1 ELSE 0 END AS outcome
        FROM pop_{FINAL_DATE.replace('-', '')}_clean p
        LEFT JOIN (SELECT DISTINCT client_id FROM clean_product_buy
                    WHERE timestamp >= '{out_start}' AND timestamp < '{out_end}'
                      AND CAST(strptime(timestamp,'%Y-%m-%d %H:%M:%S') AS DATE) <> DATE '2022-12-04') b
        ON p.client_id = b.client_id"""
).fetchdf()
outcome_no1204 = outcome_no1204.set_index("client_id").reindex(final_df["client_id"])["outcome"].fillna(0).astype(int).values
k10 = int(round(n_total * 0.10))
cap_model_b = top_k_captured_precise(model_score_arr, tiebreak_arr, outcome_no1204, k10)
cap_simple_b = top_k_captured_precise(simple_score_arr, tiebreak_arr, outcome_no1204, k10)
total_pos_no1204 = int(outcome_no1204.sum())
sensitivity["b_exclude_1204"] = {
    "n_purchasers_no1204": total_pos_no1204,
    "model_capture10_rate": round(cap_model_b / total_pos_no1204, 5) if total_pos_no1204 else None,
    "simple_capture10_rate": round(cap_simple_b / total_pos_no1204, 5) if total_pos_no1204 else None,
    "model_capture10_n": cap_model_b, "simple_capture10_n": cap_simple_b,
}
print(sensitivity["b_exclude_1204"])

# (c) 기본값 검색 표시를 반대로 처리
print("(c) 기본값 검색 표시 반대 처리")
keep = model_bundle["keeps_default_search_flag"]
if model_bundle["model_name"] == "LightGBM":
    opp_booster = model_bundle["lightgbm_model_noflag"] if keep else model_bundle["lightgbm_model"]
    opp_cols = model_bundle["lightgbm_cols_noflag"] if keep else model_bundle["lightgbm_cols"]
    opp_score = pd.Series(opp_booster.predict(final_df[opp_cols], num_iteration=opp_booster.best_iteration),
                           index=final_df.index).values
else:
    opp_m = model_bundle["logistic_model_noflag"] if keep else model_bundle["logistic_model"]
    opp_cols = model_bundle["logistic_cols_noflag"] if keep else model_bundle["logistic_cols"]
    opp_score = opp_m.predict_proba(final_df[opp_cols].fillna(0).values)[:, 1]
cap_model_c = top_k_captured_precise(opp_score, tiebreak_arr, outcome_arr, k10)
sensitivity["c_opposite_default_search_flag"] = {
    "original_decision": "유지" if keep else "제거", "opposite_decision": "제거" if keep else "유지",
    "model_capture10_rate_opposite": round(cap_model_c / n_total_purchasers, 5),
    "model_capture10_rate_original": h7_main[0.10]["captured_model"] / n_total_purchasers,
    # 단순 2단계 규칙은 검색 변수를 쓰지 않아 이 변경의 영향을 받지 않는다(기준값과 동일).
    "simple_capture10_rate_unaffected": h7_ref[0.10]["captured_simple_rule"] / n_total_purchasers,
}
print(sensitivity["c_opposite_default_search_flag"])

results["sensitivity"] = sensitivity
with open("docs/final_evaluation_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/final_evaluation_results.json (민감도까지)")

# ========== 3-6. 그림 ==========
print("\n## 3-6. 그림")
plt.rcParams["font.family"] = "AppleGothic"
plt.rcParams["axes.unicode_minus"] = False

# capture_curve.png
fig, ax = plt.subplots(figsize=(9, 6))
x_fracs = np.linspace(0.005, 1.0, 200)
for name, score in final_scores.items():
    order = np.lexsort((-tiebreak_arr, -score.values))
    sorted_outcome = outcome_arr[order]
    cum = np.cumsum(sorted_outcome)
    ys = [cum[int(round(f * n_total)) - 1] / n_total_purchasers for f in x_fracs]
    ax.plot(x_fracs * 100, ys, label=name)
for f in (5, 10, 20):
    ax.axvline(f, color="gray", linestyle=":", linewidth=0.8)
ax.set_xlabel("발송 비율(%)")
ax.set_ylabel("누적 포착률")
ax.set_title("방법별 누적 포착률 곡선 (최종평가 2022-11-23)")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig("docs/figures/capture_curve.png", dpi=150)
print("saved docs/figures/capture_curve.png")

# marginal_efficiency.png
fig, ax = plt.subplots(figsize=(9, 5))
seg_labels = list(h8_op.keys())
op_vals = [h8_op[s]["per_1000"] for s in seg_labels]
rec_vals = [h8_recency[s]["per_1000"] for s in seg_labels]
x = np.arange(len(seg_labels))
ax.bar(x - 0.2, op_vals, width=0.4, label=f"운영 권고안({op_label})")
ax.bar(x + 0.2, rec_vals, width=0.4, label="최근활동순(현행기준)")
ax.set_xticks(x)
ax.set_xticklabels(seg_labels, rotation=30, ha="right")
ax.set_ylabel("구간 내 1,000건당 구매 고객 수")
ax.set_title("발송 순위 구간별 한계 효율")
ax.legend()
ax.grid(alpha=0.3, axis="y")
fig.tight_layout()
fig.savefig("docs/figures/marginal_efficiency.png", dpi=150)
print("saved docs/figures/marginal_efficiency.png")

# h6_confound.png (P3 결과 재사용)
with open("docs/prechecks_results.json", encoding="utf-8") as f:
    prechecks = json.load(f)
p3cell = pd.DataFrame(prechecks["p3_controlled_comparison"])
fig, ax = plt.subplots(figsize=(9, 5))
buckets = ["1건", "2~3건", "4~9건", "10건+"]
groups = ["0", "0초과~0.5", "0.5초과"]
xw = 0.25
xbase = np.arange(len(buckets))
for i, g in enumerate(groups):
    vals = []
    for b in buckets:
        row = p3cell[(p3cell["담기구간"] == b) & (p3cell["제거비율그룹"] == g)]
        vals.append(row["구매율"].iloc[0] * 100 if len(row) and pd.notna(row["구매율"].iloc[0]) else 0)
    ax.bar(xbase + (i - 1) * xw, vals, width=xw, label=f"제거비율 {g}")
ax.set_xticks(xbase)
ax.set_xticklabels(buckets)
ax.set_xlabel("신호 기간 담기 건수 구간")
ax.set_ylabel("구매율(%)")
ax.set_title("담기 건수 구간별 x 제거비율 그룹별 구매율 (P3, 학습 기준일)")
ax.legend()
ax.grid(alpha=0.3, axis="y")
fig.tight_layout()
fig.savefig("docs/figures/h6_confound.png", dpi=150)
print("saved docs/figures/h6_confound.png")

# ========== 3-7. 검증용 내보내기 (집계만, 고객 단위 아님) ==========
print("\n## 3-7. 검증용 CSV 내보내기")
model_score_series = final_scores[final_model_name]
deciles = pd.qcut(model_score_series.rank(method="first"), 10, labels=[f"D{i}" for i in range(10, 0, -1)])
decile_df = pd.DataFrame({"decile": deciles, "outcome": final_df["outcome"].values}).groupby(
    "decile", observed=True).agg(n=("outcome", "size"), n_purchasers=("outcome", "sum")).reset_index()
decile_df.to_csv("verification/test_deciles.csv", index=False)
print("saved verification/test_deciles.csv")
print(decile_df.to_string(index=False))

topk_rows = []
for name, tbl in basic_table.items():
    for frac in (0.05, 0.10, 0.20):
        topk_rows.append({"method": name, "send_pct": int(frac * 100),
                           "n_sent": tbl[frac]["n_sent"], "n_captured": tbl[frac]["n_captured"]})
topk_df = pd.DataFrame(topk_rows)
topk_df.to_csv("verification/test_topk.csv", index=False)
print("saved verification/test_topk.csv")
print(topk_df.to_string(index=False))

con.close()
print("\n최종 평가 전체 완료")

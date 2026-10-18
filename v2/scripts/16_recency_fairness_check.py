"""최종 평가 비교 기준(현행 최근활동순) 공정성 확인.

00_analysis_rules.md를 따른다. 모델·설정은 바꾸지 않는다. 이미 연 11-23 결과를
다시 쓰되, 비교 기준(현행 최근활동순) 쪽의 정렬 정밀도만 추가로 점검한다.
"""
import json
import os
import pickle
import sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from _features import shift  # noqa: E402

SEED = 42
DB_PATH = "data/v2.duckdb"
con = duckdb.connect(DB_PATH, read_only=True)
con.execute("SET threads=4")
con.execute("SET memory_limit='6GB'")

FINAL_DATE = "2022-11-23"
results = {}

# ---------- 1. 코드로 정렬 단위 확인 ----------
print("## 1. 현행 기준(최근활동순) 정렬 단위 코드 확인")
with open("scripts/_features.py") as f:
    lines = f.readlines()
cited = "".join(lines[39:43])  # 0-indexed 39..42 = 1-indexed 40..43
print("_features.py:40-43 ===")
print(cited)
results["code_citation"] = {"file": "scripts/_features.py", "lines": "40-43", "code": cited}
print("판단: total_seconds()/86400 로 계산 — 날짜만 보는 .dt.date/.dt.floor('D') 등은 전혀 쓰이지 않는다. "
      "즉 현재 '최근활동순' 정렬은 이미 일 단위가 아니라 초 단위(타임스탬프 그대로)다.")
results["conclusion_granularity"] = "초 단위(이미 raw timestamp와 동일한 순서) — 일 단위 아님"

# ---------- 모집단 재구성 ----------
final_df = pd.read_parquet("data/tmp/final_df.parquet")
n_total = len(final_df)
with open("data/final_model.pkl", "rb") as f:
    model_bundle = pickle.load(f)


def score_with_final_model(df):
    name = model_bundle["model_name"]
    keep = model_bundle["keeps_default_search_flag"]
    if name == "LightGBM":
        booster = model_bundle["lightgbm_model"] if keep else model_bundle["lightgbm_model_noflag"]
        cols = model_bundle["lightgbm_cols"] if keep else model_bundle["lightgbm_cols_noflag"]
        return booster.predict(df[cols], num_iteration=booster.best_iteration)
    else:
        m = model_bundle["logistic_model"] if keep else model_bundle["logistic_model_noflag"]
        cols = model_bundle["logistic_cols"] if keep else model_bundle["logistic_cols_noflag"]
        return m.predict_proba(df[cols].fillna(0).values)[:, 1]


model_score_arr = score_with_final_model(final_df)
outcome_arr = final_df["outcome"].values.astype(np.int64)
rng_tie = np.random.default_rng(SEED)
tiebreak_arr = rng_tie.random(n_total)  # 15_final_evaluation.py와 동일 seed·동일 길이 -> 동일 재현
recency_days_arr = final_df["h1_days_since_last_activity"].fillna(1e9).values
recency_score_current = -recency_days_arr

k10 = int(round(n_total * 0.10))

# ---------- 1-2. 상위10% 경계 동률 고객 수 ----------
print("\n## 1-2. 11-23 모집단, 상위10% 경계 동률 고객 수 (현행 기준)")
sorted_scores = np.sort(recency_score_current)[::-1]
boundary_value = sorted_scores[k10 - 1]
n_tied_at_boundary = int((recency_score_current == boundary_value).sum())
n_inside_with_boundary_value = int((sorted_scores[:k10] == boundary_value).sum())
print(f"경계 순위(k={k10})의 점수값과 정확히 같은 값을 가진 고객 수: {n_tied_at_boundary}명 "
      f"(그중 {n_inside_with_boundary_value}명이 현재 tiebreak로 상위10% 안에 포함)")
results["boundary_ties"] = {
    "k": k10, "n_tied_total": n_tied_at_boundary, "n_tied_included_by_tiebreak": n_inside_with_boundary_value,
    "boundary_days_since_last_activity": float(-boundary_value),
}

with open("docs/fairness_check_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/fairness_check_results.json (1까지)")

# ---------- 2. 마지막 활동 "시각"(원시 타임스탬프) 기준 정렬 ----------
print("\n## 2. 마지막 활동 시각(원시 timestamp) 기준 정렬과 비교")
ids_sql = ",".join(str(int(c)) for c in final_df["client_id"])
w60_start, w60_end = shift(FINAL_DATE, -60), shift(FINAL_DATE, 0)
union_sql = " UNION ALL ".join(
    f"SELECT client_id, timestamp FROM clean_{t} WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}' "
    f"AND client_id IN ({ids_sql})"
    for t in ["product_buy", "add_to_cart", "remove_from_cart", "page_visit", "search_query"]
)
last_ts_df = con.execute(f"""
    SELECT client_id, max(timestamp) AS last_ts FROM ({union_sql}) u GROUP BY client_id
""").fetchdf()
final_df = final_df.merge(last_ts_df, on="client_id", how="left")
# 문자열 'YYYY-MM-DD HH:MM:SS'는 그대로 사전식 정렬이 시간 순서와 같다(00_analysis_rules.md 5번 자료와 동일 전제)
recency_score_bysec = final_df["last_ts"].fillna("0000-00-00 00:00:00").values  # 문자열 자체를 정렬 키로 사용

# 두 정렬이 실제로 같은지(=이미 초 단위였는지) 직접 확인.
# 문자열 timestamp를 사전식 순서를 보존하는 정수 키로 바꿔(factorize, sort=True) 동일한
# lexsort(+seed=42 tiebreak) 방식으로 비교한다 — pandas rank(method="first")의 등장순 동률 처리는
# tiebreak_arr과 달라 비교가 불공정해지므로 쓰지 않는다.
codes, _ = pd.factorize(recency_score_bysec, sort=True)  # 0=가장 오래된 시각 ... max=가장 최근 시각
order_current = np.lexsort((-tiebreak_arr, -recency_score_current))
order_bysec_idx = np.lexsort((-tiebreak_arr, -codes))
same_top_k = len(set(order_current[:k10]).symmetric_difference(set(order_bysec_idx[:k10])))
print(f"기존 정렬 vs 시각 기준 정렬: 상위10% 집합 차이(대칭차집합) = {same_top_k}명 "
      f"(0이면 완전히 동일한 집합)")
results["ranking_identical_check"] = {"symmetric_diff_at_top10pct": same_top_k}

cap_bysec_5 = int(outcome_arr[order_bysec_idx[:int(round(n_total*0.05))]].sum())
cap_bysec_10 = int(outcome_arr[order_bysec_idx[:k10]].sum())
cap_bysec_20 = int(outcome_arr[order_bysec_idx[:int(round(n_total*0.20))]].sum())
cap_cur_5 = int(outcome_arr[order_current[:int(round(n_total*0.05))]].sum())
cap_cur_10 = int(outcome_arr[order_current[:k10]].sum())
cap_cur_20 = int(outcome_arr[order_current[:int(round(n_total*0.20))]].sum())

total_pos = int(outcome_arr.sum())
comparison_table = {}
for frac, cap_cur, cap_sec in [(0.05, cap_cur_5, cap_bysec_5), (0.10, cap_cur_10, cap_bysec_10),
                                 (0.20, cap_cur_20, cap_bysec_20)]:
    k = int(round(n_total * frac))
    comparison_table[frac] = {
        "현행(h1_days_since_last_activity)_포착": cap_cur,
        "현행_포착률": round(cap_cur/total_pos, 5), "현행_1만건당": round(cap_cur/k*10000, 2),
        "시각기준(raw timestamp)_포착": cap_sec,
        "시각기준_포착률": round(cap_sec/total_pos, 5), "시각기준_1만건당": round(cap_sec/k*10000, 2),
        "두_기준_차이": cap_sec - cap_cur,
    }
    print(f"{frac*100:.0f}%:", comparison_table[frac])
results["comparison_table"] = comparison_table

# 부트스트랩: 모델 vs 시각기준 정렬 (동일 seed=42, 동일 방식)
print("\n부트스트랩(모델 vs 시각기준 정렬, 1,000회, seed=42)")


def top_k_captured_fast(score_arr, outcome_arr, k):
    n = len(score_arr)
    if k >= n:
        return int(outcome_arr.sum())
    idx = np.argpartition(-score_arr, k - 1)[:k]
    return int(outcome_arr[idx].sum())


# 시각 문자열을 정렬 가능한 float 키로 변환(사전식 순서를 그대로 보존하는 랭크)
bysec_numeric = codes.astype(np.float64)  # factorize로 만든, 시각 순서를 보존하는 정수 키(위에서 계산)

boot_diffs = {f: np.empty(1000, dtype=np.int64) for f in (0.05, 0.10, 0.20)}
rng_b = np.random.default_rng(SEED)
for i in range(1000):
    idx = rng_b.integers(0, n_total, n_total)
    sA, sB, o = model_score_arr[idx], bysec_numeric[idx], outcome_arr[idx]
    for frac in (0.05, 0.10, 0.20):
        k = int(round(n_total * frac))
        capA = top_k_captured_fast(sA, o, k)
        capB = top_k_captured_fast(sB, o, k)
        boot_diffs[frac][i] = capA - capB

h7_bysec = {}
for frac in (0.05, 0.10, 0.20):
    k = int(round(n_total * frac))
    diffs = boot_diffs[frac]
    ci_low, ci_high = np.percentile(diffs, [2.5, 97.5])
    cap_model = int(outcome_arr[np.argsort(-model_score_arr)[:k]].sum())
    cap_sec = comparison_table[frac]["시각기준(raw timestamp)_포착"]
    h7_bysec[frac] = {"n_sent": k, "captured_model": cap_model, "captured_recency_bysec": cap_sec,
                       "diff": cap_model - cap_sec, "ci95_low": float(ci_low), "ci95_high": float(ci_high)}
    print(f"{frac*100:.0f}%:", h7_bysec[frac])
results["h7_vs_bysec_recency"] = h7_bysec

with open("docs/fairness_check_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/fairness_check_results.json (2까지)")

# ---------- 3. 발송량 절감률(시각 기준) ----------
print("\n## 3. 발송량 절감률 (시각 기준)")
target_captured_bysec = comparison_table[0.10]["시각기준(raw timestamp)_포착"]
order_model_desc = np.argsort(-model_score_arr)
cum_captured_model = np.cumsum(outcome_arr[order_model_desc])
needed_k_bysec = int(np.searchsorted(cum_captured_model, target_captured_bysec) + 1)
needed_pct_bysec = needed_k_bysec / n_total * 100
reduction_pct_bysec = (1 - needed_k_bysec / k10) * 100
print(f"시각기준 상위10%가 잡는 구매자 {target_captured_bysec}명을 모델은 상위 {needed_pct_bysec:.2f}% 발송으로 달성"
      f" (발송량 {reduction_pct_bysec:.1f}% 감소)")
results["send_volume_reduction_bysec"] = {
    "target_captured": int(target_captured_bysec), "model_needed_pct": round(needed_pct_bysec, 3),
    "model_needed_n": needed_k_bysec, "reduction_pct": round(reduction_pct_bysec, 2),
}

# ---------- 4. 방문만 하던 구매 고객 포착률(시각 기준) ----------
print("\n## 4. 방문만 하던 구매 고객 포착률 (시각 기준)")
visit_only_mask = (
    final_df["h1_days_since_last_visit"].notna() & final_df["h1_days_since_last_cart_add"].isna()
    & (final_df["h3_purchase_count"] == 0) & (final_df["h4_real_search_count"] == 0)
).values
purchaser_mask = outcome_arr == 1
n_vo_purchasers = int((visit_only_mask & purchaser_mask).sum())
captured_vo_bysec = int((visit_only_mask[order_bysec_idx[:k10]] & purchaser_mask[order_bysec_idx[:k10]]).sum())
captured_vo_current = int((visit_only_mask[order_current[:k10]] & purchaser_mask[order_current[:k10]]).sum())
rate_bysec = captured_vo_bysec / n_vo_purchasers
rate_current = captured_vo_current / n_vo_purchasers
print(f"방문전용 구매자 {n_vo_purchasers}명 중 시각기준 상위10% 포착: {captured_vo_bysec}명({rate_bysec*100:.2f}%), "
      f"기존(현행) 상위10% 포착: {captured_vo_current}명({rate_current*100:.2f}%)")
results["visit_only_capture_bysec"] = {
    "n_visit_only_purchasers": n_vo_purchasers,
    "captured_bysec": captured_vo_bysec, "rate_bysec_pct": round(rate_bysec * 100, 3),
    "captured_current": captured_vo_current, "rate_current_pct": round(rate_current * 100, 3),
}

with open("docs/fairness_check_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("\nwrote docs/fairness_check_results.json (최종)")
con.close()
print("공정성 확인 완료")

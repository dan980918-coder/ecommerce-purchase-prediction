"""3단계 결과에 대한 확인 작업: 봇 판정, 누수 점검, 신호의 실제 힘.

00_analysis_rules.md를 따른다. 처리 방침은 정하지 않고 확인 결과만 기록한다.
검증(11-07)·최종평가(11-23) 기준일의 구매 결과는 계산하지 않는다.
"""
import json
import os
import sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from _pseudonym import pseudonymize  # noqa: E402

os.makedirs("docs", exist_ok=True)

DB_PATH = "data/v2.duckdb"
con = duckdb.connect(DB_PATH)
con.execute("SET threads=4")
con.execute("SET memory_limit='5GB'")
con.execute("SET preserve_insertion_order=false")

RAW = "data/raw"
CUTOFF = "2022-11-22 00:00:00"
TABLES = ["product_buy", "add_to_cart", "remove_from_cart", "page_visit", "search_query"]

# 실제 client_id는 v2/data/client_pseudonym_map.csv(git 제외)에서만 조회한다.
pmap = pd.read_csv("data/client_pseudonym_map.csv")
CID_36 = int(pmap.loc[pmap["pseudonym"] == "고객00036", "client_id"].iloc[0])
CID_40 = int(pmap.loc[pmap["pseudonym"] == "고객00040", "client_id"].iloc[0])
print("고객00036 ->", CID_36, "/ 고객00040 ->", CID_40)

results = {}

# ========== A. 봇 판정 결과 확인 ==========
print("\n### A-1. 교차 극단 1,183명 포함 여부 + 신호값 ==========")
extreme_sets = {}
for t in TABLES:
    cnt = con.execute(
        f"SELECT client_id, count(*) AS n FROM read_parquet('{RAW}/{t}.parquet') GROUP BY client_id"
    ).fetchdf()
    p999 = cnt["n"].quantile(0.999)
    extreme_sets[t] = set(cnt.loc[cnt["n"] > p999, "client_id"].tolist())
candidate_ids = [cid for cid in set.union(*extreme_sets.values())
                 if sum(cid in extreme_sets[t] for t in TABLES) >= 3]
print("교차 극단 후보 수:", len(candidate_ids))
in_candidates = {CID_36: CID_36 in candidate_ids, CID_40: CID_40 in candidate_ids}
print("고객00036 포함?", in_candidates[CID_36], "/ 고객00040 포함?", in_candidates[CID_40])
results["a1_candidate_membership"] = {"고객00036": in_candidates[CID_36], "고객00040": in_candidates[CID_40]}

# 신호값 재계산 (09_bot_flags.py와 동일 로직, 두 고객만)
id_list_sql = f"{CID_36},{CID_40}"
frames = []
for t in ["add_to_cart", "remove_from_cart", "page_visit", "search_query"]:
    df = con.execute(
        f"""SELECT client_id, timestamp FROM clean_{t}
            WHERE client_id IN ({id_list_sql}) AND timestamp < '{CUTOFF}'"""
    ).fetchdf()
    frames.append(df)
combined = pd.concat(frames, ignore_index=True)
combined["ts"] = pd.to_datetime(combined["timestamp"], format="%Y-%m-%d %H:%M:%S")

signal_values = {}
for cid, name in [(CID_36, "고객00036"), (CID_40, "고객00040")]:
    sub = combined[combined["client_id"] == cid]
    if len(sub):
        minute_counts = sub.groupby(sub["ts"].dt.floor("min")).size()
        max_per_min = int(minute_counts.max())
        hour_per_day = sub.groupby(sub["ts"].dt.date)["ts"].apply(lambda s: s.dt.hour.nunique())
        days_over_18 = int((hour_per_day >= 18).sum())
    else:
        max_per_min, days_over_18 = 0, 0
    atc = con.execute(
        f"""SELECT client_id, timestamp, sku FROM clean_add_to_cart
            WHERE client_id = {cid} AND timestamp < '{CUTOFF}' ORDER BY timestamp, sku"""
    ).fetchdf()
    if len(atc) >= 2:
        atc["prev_sku"] = atc["sku"].shift(1)
        repeat_rate = float((atc["sku"] == atc["prev_sku"]).mean())
    else:
        repeat_rate = None
    signal_values[name] = {
        "속도_1분최대건수(pre-11/22, 4테이블결합)": max_per_min,
        "속도_신호(>=60)": max_per_min >= 60,
        "수면없음_18시간대이상_일수(pre-11/22)": days_over_18,
        "수면없음_신호(>=3일)": days_over_18 >= 3,
        "기계적반복_add건수(pre-11/22)": len(atc),
        "기계적반복_직전sku반복률": repeat_rate,
        "기계적반복_신호(>=20건&80%+)": (len(atc) >= 20 and repeat_rate is not None and repeat_rate >= 0.8),
    }
    print(name, signal_values[name])
results["a1_signal_values"] = signal_values

print("\n### A-2. 고객00040: 1분 최대 건수 원본 vs 정제 비교 (page_visit) ==========")
pv_raw = con.execute(
    f"SELECT timestamp, url FROM read_parquet('{RAW}/page_visit.parquet') WHERE client_id = {CID_40}"
).fetchdf()
pv_raw["ts"] = pd.to_datetime(pv_raw["timestamp"], format="%Y-%m-%d %H:%M:%S")
pv_raw["minute"] = pv_raw["ts"].dt.floor("min")
raw_minute_counts = pv_raw.groupby("minute").size()
raw_max_minute = raw_minute_counts.idxmax()
raw_max_count = int(raw_minute_counts.max())

pv_clean = con.execute(
    f"SELECT timestamp, url FROM clean_page_visit WHERE client_id = {CID_40}"
).fetchdf()
pv_clean["ts"] = pd.to_datetime(pv_clean["timestamp"], format="%Y-%m-%d %H:%M:%S")
pv_clean["minute"] = pv_clean["ts"].dt.floor("min")
clean_minute_counts = pv_clean.groupby("minute").size()
clean_count_in_raw_max_minute = int(clean_minute_counts.get(raw_max_minute, 0))
clean_max_minute = clean_minute_counts.idxmax()
clean_max_count = int(clean_minute_counts.max())

events_in_minute = pv_raw[pv_raw["minute"] == raw_max_minute][["timestamp", "url"]].sort_values("timestamp")
n_distinct_url_in_minute = events_in_minute["url"].nunique()
n_duplicate_rows_in_minute = len(events_in_minute) - len(events_in_minute.drop_duplicates())

print("원본 1분 최대:", raw_max_count, "at", raw_max_minute)
print("정제 후 전체 1분 최대:", clean_max_count, "at", clean_max_minute)
print("원본 최대 발생 분(", raw_max_minute, ") 안의 정제 후 건수:", clean_count_in_raw_max_minute)
print("그 1분 안 완전중복 행 수(원본 기준, 중복 제거로 사라질 행):",
      raw_max_count - clean_count_in_raw_max_minute)
print("그 1분 안 고유 url 수:", n_distinct_url_in_minute)
print(events_in_minute.head(10).to_string())

results["a2_customer40_minute_burst"] = {
    "raw_max_count": raw_max_count, "raw_max_minute": str(raw_max_minute),
    "clean_max_count": clean_max_count, "clean_max_minute": str(clean_max_minute),
    "clean_count_in_raw_max_minute": clean_count_in_raw_max_minute,
    "duplicates_removed_in_that_minute": raw_max_count - clean_count_in_raw_max_minute,
    "n_distinct_url_in_minute": int(n_distinct_url_in_minute),
    "sample_events": events_in_minute.head(15).astype(str).to_dict(orient="records"),
}

print("\n### A-3. 고객00036: 구매 외 테이블에서도 반복 패턴 확인 ==========")
repeat_other_tables = {}
for t in ["add_to_cart", "remove_from_cart"]:
    df = con.execute(
        f"SELECT timestamp, sku FROM clean_{t} WHERE client_id = {CID_36} ORDER BY timestamp, sku"
    ).fetchdf()
    if len(df) >= 2:
        df["prev_sku"] = df["sku"].shift(1)
        rate = float((df["sku"] == df["prev_sku"]).mean())
    else:
        rate = None
    repeat_other_tables[t] = {"n_rows": len(df), "n_distinct_sku": int(df["sku"].nunique()) if len(df) else 0,
                               "직전sku반복률": rate}
    print(t, repeat_other_tables[t])
# product_buy 비교용
pb = con.execute(
    f"SELECT timestamp, sku FROM clean_product_buy WHERE client_id = {CID_36} ORDER BY timestamp, sku"
).fetchdf()
pb["prev_sku"] = pb["sku"].shift(1)
repeat_other_tables["product_buy(참고)"] = {
    "n_rows": len(pb), "n_distinct_sku": int(pb["sku"].nunique()),
    "직전sku반복률": float((pb["sku"] == pb["prev_sku"]).mean()) if len(pb) >= 2 else None,
}
print("product_buy(참고)", repeat_other_tables["product_buy(참고)"])
results["a3_customer36_repeat_other_tables"] = repeat_other_tables

print("\n### A-4. 두 고객의 활동 기간 vs 11/22 ==========")
activity_range = {}
for cid, name in [(CID_36, "고객00036"), (CID_40, "고객00040")]:
    parts = []
    for t in TABLES:
        d = con.execute(
            f"SELECT min(timestamp) mn, max(timestamp) mx FROM read_parquet('{RAW}/{t}.parquet') WHERE client_id = {cid}"
        ).fetchone()
        if d[0] is not None:
            parts.append(d)
    mn = min(p[0] for p in parts)
    mx = max(p[1] for p in parts)
    activity_range[name] = {"min_ts": mn, "max_ts": mx, "entirely_before_cutoff": mx < CUTOFF,
                             "spans_across_cutoff": mn < CUTOFF <= mx}
    print(name, activity_range[name])
results["a4_activity_range"] = activity_range

print("\n### A-5. '1분' 정의 코드 확인 ==========")
results["a5_minute_definition_code"] = {
    "07_abnormal_clients.py:128": 'minute_counts = sub.groupby(sub["ts"].dt.floor("min")).size()',
    "09_bot_flags.py:79": 'minute_counts = combined.groupby(["client_id", combined["ts"].dt.floor("min")]).size()',
    "동일여부": True,
    "설명": "두 스크립트 모두 pandas .dt.floor('min')으로 분 단위 내림(정시 00초 기준 고정 1분 구간)을 쓴다. 슬라이딩 60초 창이 아니다.",
}
print(results["a5_minute_definition_code"])

print("\n### A-6. 1,183명 전체 정제 전후 1분 최대 건수 비교 (pre-11/22, 4테이블 결합) ==========")
id_list_all = ",".join(str(c) for c in candidate_ids)
raw_frames = []
for t in ["add_to_cart", "remove_from_cart", "page_visit", "search_query"]:
    df = con.execute(
        f"""SELECT client_id, timestamp FROM read_parquet('{RAW}/{t}.parquet')
            WHERE client_id IN ({id_list_all}) AND timestamp < '{CUTOFF}'"""
    ).fetchdf()
    raw_frames.append(df)
raw_combined = pd.concat(raw_frames, ignore_index=True)
raw_combined["minute"] = pd.to_datetime(raw_combined["timestamp"], format="%Y-%m-%d %H:%M:%S").dt.floor("min")
raw_max_per_client = raw_combined.groupby(["client_id", "minute"]).size().groupby("client_id").max()

clean_frames = []
for t in ["add_to_cart", "remove_from_cart", "page_visit", "search_query"]:
    df = con.execute(
        f"""SELECT client_id, timestamp FROM clean_{t}
            WHERE client_id IN ({id_list_all}) AND timestamp < '{CUTOFF}'"""
    ).fetchdf()
    clean_frames.append(df)
clean_combined = pd.concat(clean_frames, ignore_index=True)
clean_combined["minute"] = pd.to_datetime(clean_combined["timestamp"], format="%Y-%m-%d %H:%M:%S").dt.floor("min")
clean_max_per_client = clean_combined.groupby(["client_id", "minute"]).size().groupby("client_id").max()

comp = pd.DataFrame({"raw_max": raw_max_per_client, "clean_max": clean_max_per_client}).fillna(0)
comp = comp.reindex(candidate_ids).fillna(0)
n_lost_extremity = int(((comp["raw_max"] >= 60) & (comp["clean_max"] < 60)).sum())
n_raw_over60 = int((comp["raw_max"] >= 60).sum())
n_clean_over60 = int((comp["clean_max"] >= 60).sum())
print("원본 기준 1분 60건 이상 고객 수:", n_raw_over60)
print("정제 후 1분 60건 이상 고객 수:", n_clean_over60)
print("중복 제거로 60건 미만으로 떨어진 고객 수:", n_lost_extremity)
results["a6_dedup_effect_on_speed_signal"] = {
    "n_candidates": len(candidate_ids),
    "n_raw_max_minute_over60": n_raw_over60,
    "n_clean_max_minute_over60": n_clean_over60,
    "n_lost_extremity_due_to_dedup": n_lost_extremity,
}

with open("docs/checks_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("\nwrote docs/checks_results.json (중간 저장, A 섹션까지)")
print("A 섹션 완료")

# ========== B. 누수 점검 ==========
print("\n### B-1. 코드 줄 번호로 경계 확인 ==========")
results["b1_code_lines"] = {
    "신호(기준일 00:00 미만)": [
        "11_build_features.py:42  w60_start, w60_end = shift(d, -60), shift(d, 0)",
        "11_build_features.py:61,72,83,105,108,111,142,160,169,175,213,219,230  "
        "WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}'  (w60_end=기준일 00:00, 강한 부등호 <)",
    ],
    "결과(기준일 00:00 이상)": [
        "10_build_snapshots.py:65-66  out_start = shift_days(d, 0); out_end = shift_days(d, 14)",
        "10_build_snapshots.py:74  WHERE timestamp >= '{out_start}' AND timestamp < '{out_end}'  "
        "(out_start=기준일 00:00, >= 포함)",
    ],
    "결론": "신호는 '< 기준일 00:00'(기준일 자체 제외), 결과는 '>= 기준일 00:00'(기준일 자체 포함). "
            "정각에 찍힌 이벤트는 결과 쪽에 들어가고 신호 쪽에는 절대 들어가지 않는다 — 경계 중복 없음.",
}
print(results["b1_code_lines"])

print("\n### B-2. 기준일 정각 이벤트 건수 및 귀속 ==========")
TRAINING_DATES = ["2022-08-22", "2022-09-05", "2022-09-19", "2022-10-03", "2022-10-17"]
con2 = duckdb.connect(DB_PATH)
con2.execute("SET threads=4")
con2.execute("SET memory_limit='5GB'")
midnight_counts = {}
for d in TRAINING_DATES:
    ts = f"{d} 00:00:00"
    cnt = 0
    for t in TABLES:
        n = con2.execute(f"SELECT count(*) FROM clean_{t} WHERE timestamp = '{ts}'").fetchone()[0]
        cnt += n
    midnight_counts[d] = cnt
    print(d, "정각 이벤트 건수(5개 테이블 합):", cnt, "-> 결과(outcome) 창에 귀속(신호 창에는 포함 안 됨)")
results["b2_midnight_boundary_events"] = midnight_counts

print("\n### B-3. 무작위 5명 원본 대조 ==========")
sample_date = TRAINING_DATES[0]
sample_rows = con2.execute(
    f"SELECT client_id, outcome FROM training_snapshot WHERE reference_date = '{sample_date}' "
    f"ORDER BY random() LIMIT 5"
).fetchdf()
w60_start_s = (pd.Timestamp(sample_date) - pd.Timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
w60_end_s = sample_date + " 00:00:00"
out_start_s = w60_end_s
out_end_s = (pd.Timestamp(sample_date) + pd.Timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")

audit_rows = []
pseudo_map = dict(zip(sample_rows["client_id"], pseudonymize(sample_rows["client_id"].tolist())))
for cid in sample_rows["client_id"]:
    buys = con2.execute(
        f"SELECT timestamp FROM clean_product_buy WHERE client_id = {int(cid)} ORDER BY timestamp"
    ).fetchdf()
    signal_buys = buys[(buys["timestamp"] >= w60_start_s) & (buys["timestamp"] < w60_end_s)]
    outcome_buys = buys[(buys["timestamp"] >= out_start_s) & (buys["timestamp"] < out_end_s)]
    stored = con2.execute(
        f"SELECT h3_purchase_count, outcome FROM training_features "
        f"WHERE client_id = {int(cid)} AND reference_date = '{sample_date}'"
    ).fetchdf()
    row = {
        "고객": pseudo_map[cid],
        "저장된_h3_purchase_count": int(stored["h3_purchase_count"].iloc[0]) if len(stored) else None,
        "신호기간_실제구매건수": len(signal_buys),
        "저장된_outcome": int(stored["outcome"].iloc[0]) if len(stored) else None,
        "결과기간_실제구매건수": len(outcome_buys),
        "신호건수_일치": (len(stored) > 0 and int(stored["h3_purchase_count"].iloc[0]) == len(signal_buys)),
        "outcome_일치": (len(stored) > 0 and int(stored["outcome"].iloc[0]) == int(len(outcome_buys) > 0)),
        "결과기간_구매가_신호건수에_섞이지_않음": (
            len(stored) > 0 and int(stored["h3_purchase_count"].iloc[0]) == len(signal_buys)
        ),
    }
    audit_rows.append(row)
    print(row)
results["b3_random5_audit"] = audit_rows
results["b3_sample_date"] = sample_date

with open("docs/checks_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("\nwrote docs/checks_results.json (중간 저장, B 섹션까지)")

# ========== C. 신호의 실제 힘 ==========
print("\n### C-1. 0/기록없음 구간 제외 IV 재계산 ==========")
train_df = con2.execute("SELECT * FROM training_features").fetchdf()
con2.close()

Z = 1.96


def woe_iv(labels, outcome):
    tmp = pd.DataFrame({"bin": labels, "outcome": outcome})
    grp = tmp.groupby("bin")["outcome"].agg(n="count", good="sum")
    grp["bad"] = grp["n"] - grp["good"]
    grp["good_adj"], grp["bad_adj"] = grp["good"] + 0.5, grp["bad"] + 0.5
    tg, tb = grp["good_adj"].sum(), grp["bad_adj"].sum()
    grp["good_dist"], grp["bad_dist"] = grp["good_adj"] / tg, grp["bad_adj"] / tb
    grp["woe"] = np.log(grp["good_dist"] / grp["bad_dist"])
    iv = ((grp["good_dist"] - grp["bad_dist"]) * grp["woe"]).sum()
    return float(iv), int(grp["n"].sum())


def greedy_merge(counts_series, min_count):
    groups, cur, cur_sum = [], [], 0
    for idx, c in counts_series.items():
        cur.append(idx); cur_sum += c
        if cur_sum >= min_count:
            groups.append(cur); cur, cur_sum = [], 0
    if cur:
        (groups[-1].extend(cur) if groups else groups.append(cur))
    mapping = {}
    for new_i, idxs in enumerate(groups):
        for i in idxs:
            mapping[i] = new_i
    return mapping


def iv_excluding_zero_missing(df, col, has_zero_bin):
    s = df[col]
    if has_zero_bin:
        subset = df[(~s.isna()) & (s != 0)]
    else:
        subset = df[~s.isna()]
    if len(subset) < 1000 or subset[col].nunique() < 2:
        return None, len(subset)
    min_bin_n = max(1, len(subset) * 0.05)
    try:
        codes = pd.qcut(subset[col], q=10, duplicates="drop").cat.codes
    except ValueError:
        return None, len(subset)
    counts = codes.value_counts().sort_index()
    mapping = greedy_merge(counts, min_bin_n)
    labels = codes.map(mapping).astype(str)
    if labels.nunique() < 2:
        return None, len(subset)
    iv, n = woe_iv(labels, subset["outcome"])
    return iv, n


CORE_VARS = {
    "h1_days_since_last_activity": False,  # 구조적으로 0/결측 구간 없음
    "h2_pending_items": True,
    "h3_purchase_count": True,
    "h4_real_search_count": True,
    "h5_activity_growth_ratio": True,  # "0" + "이전활동없음" 모두 제외
    "h6_removal_ratio": True,  # "0" + 결측(담기없음) 모두 제외
}
original_iv = {"h1_days_since_last_activity": 0.5546, "h2_pending_items": 0.4044,
               "h3_purchase_count": 1.6325, "h4_real_search_count": 0.4473,
               "h5_activity_growth_ratio": 0.7359, "h6_removal_ratio": 1.3601}

iv_comparison = {}
for col, has_zero in CORE_VARS.items():
    iv_excl, n_excl = iv_excluding_zero_missing(train_df, col, has_zero)
    iv_comparison[col] = {
        "원래_IV(0/결측_포함)": original_iv[col],
        "0_결측_제외_IV": iv_excl,
        "제외_후_표본수": n_excl,
        "비고": "구조적으로 0/결측 구간 없음(해당없음)" if col == "h1_days_since_last_activity" else "",
    }
    print(col, iv_comparison[col])
results["c1_iv_excluding_zero"] = iv_comparison

print("\n### C-2. 방문만 하고 다른 행동이 없는 고객 비중과 구매율 ==========")
visit_only = (
    train_df["h1_days_since_last_visit"].notna()
    & train_df["h1_days_since_last_cart_add"].isna()
    & (train_df["h3_purchase_count"] == 0)
    & (train_df["h4_real_search_count"] == 0)
)
n_visit_only = int(visit_only.sum())
share_visit_only = n_visit_only / len(train_df)
purchase_rate_visit_only = float(train_df.loc[visit_only, "outcome"].mean())
purchase_rate_overall = float(train_df["outcome"].mean())
print("방문만 한 고객 수:", n_visit_only, "/ 전체:", len(train_df), f"({share_visit_only*100:.2f}%)")
print("방문만 한 고객 구매율:", round(purchase_rate_visit_only * 100, 4), "%")
print("전체 평균 구매율:", round(purchase_rate_overall * 100, 4), "%")
results["c2_visit_only_segment"] = {
    "n_visit_only": n_visit_only, "n_total": len(train_df),
    "share_pct": round(share_visit_only * 100, 3),
    "purchase_rate_pct": round(purchase_rate_visit_only * 100, 4),
    "overall_purchase_rate_pct": round(purchase_rate_overall * 100, 4),
}

with open("docs/checks_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("\nwrote docs/checks_results.json (최종)")

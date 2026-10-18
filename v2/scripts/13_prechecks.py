"""4단계 사전 확인: P1(속도 봇, 전체 고객) / P2(방문만 고객 비중) / P3(H6 원인).

00_analysis_rules.md를 따른다. P1에서 해당 인원이 1,000명을 넘으면 즉시 멈추고
보고한다(그 결과만 출력하고 이후 코드는 실행하지 않는다).
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

CUTOFF = "2022-11-22 00:00:00"
NONBUY_TABLES = ["add_to_cart", "remove_from_cart", "page_visit", "search_query"]
TRAINING_DATES = ["2022-08-22", "2022-09-05", "2022-09-19", "2022-10-03", "2022-10-17"]

results = {}

# ========== P1. 속도 기준 봇 판정 (전체 고객) ==========
print("## P1. 속도 기준 봇 판정 (전체 고객, pre-11/22, 구매 제외 4테이블 결합)")
print("메모리 부족 1차 재시도도 정체되어, 테이블별 사전집계 -> parquet -> 재결합 방식으로 전환함(v2/data/tmp 사용).")
try:
    _existing_n = con.execute("SELECT count(*) FROM speed_bot_candidates").fetchone()[0]
    _already_done = True
    print(f"speed_bot_candidates 테이블이 이미 존재(재실행 캐시 사용), {_existing_n}명 — 재계산 생략")
except duckdb.CatalogException:
    _already_done = False

os.makedirs("data/tmp", exist_ok=True)
con.execute("SET memory_limit='6GB'")
con.execute("SET threads=2")
con.execute(f"SET temp_directory='{os.path.abspath('data/tmp')}'")
con.execute("SET preserve_insertion_order=false")

# 2. 테이블별로 (client_id, 분)별 건수를 먼저 집계해 parquet로 저장
per_table_parquet = []
for t in ([] if _already_done else NONBUY_TABLES):
    out_path = f"data/tmp/minute_counts_{t}.parquet"
    con.execute(f"""
        COPY (
          SELECT client_id, date_trunc('minute', strptime(timestamp,'%Y-%m-%d %H:%M:%S')) AS minute,
                 count(*) AS n
          FROM clean_{t} WHERE timestamp < '{CUTOFF}'
          GROUP BY client_id, minute
        ) TO '{out_path}' (FORMAT PARQUET)
    """)
    per_table_parquet.append(out_path)
    print("저장:", out_path)

# 3. 4개 parquet을 (client_id, 분) 기준으로 합산한 뒤 최대값 계산
if not _already_done:
    read_union = " UNION ALL ".join(f"SELECT * FROM read_parquet('{p}')" for p in per_table_parquet)
    try:
        con.execute(f"""
            CREATE OR REPLACE TABLE speed_bot_candidates AS
            WITH combined AS (
              SELECT client_id, minute, sum(n) AS n FROM ({read_union}) u GROUP BY client_id, minute
            )
            SELECT client_id, max(n) AS max_per_min FROM combined
            GROUP BY client_id HAVING max(n) >= 60
        """)
        results["p1_method"] = "테이블별 사전집계 -> parquet(v2/data/tmp, git 제외) -> 재결합(1회) -> 최대값"
    except duckdb.OutOfMemoryException:
        print("재결합도 메모리 부족 — client_id 해시값 기준 8분할 처리로 전환")
        con.execute("CREATE OR REPLACE TABLE speed_bot_candidates (client_id BIGINT, max_per_min BIGINT)")
        for bucket in range(8):
            con.execute(f"""
                INSERT INTO speed_bot_candidates
                WITH combined AS (
                  SELECT client_id, minute, sum(n) AS n FROM ({read_union}) u
                  WHERE hash(client_id) % 8 = {bucket}
                  GROUP BY client_id, minute
                )
                SELECT client_id, max(n) AS max_per_min FROM combined
                GROUP BY client_id HAVING max(n) >= 60
            """)
            print(f"해시 분할 {bucket+1}/8 처리 완료")
        results["p1_method"] = "테이블별 사전집계 -> parquet(v2/data/tmp, git 제외) -> 재결합 1회 OOM -> client_id 해시 8분할 재처리"
    for p in per_table_parquet:
        os.remove(p)
else:
    results["p1_method"] = "테이블별 사전집계 -> parquet -> 재결합 1회 OOM -> client_id 해시 8분할 재처리 (이전 실행 결과 재사용)"
con.execute("SET threads=4")
n_speed_bot = con.execute("SELECT count(*) FROM speed_bot_candidates").fetchone()[0]
print("속도 기준 해당 인원(전체):", n_speed_bot)
results["p1_n_total"] = n_speed_bot

# 각 기준일 모집단에 실제 포함된 인원
pop_overlap = {}
for d in TRAINING_DATES + ["2022-11-07", "2022-11-23"]:
    tag = d.replace("-", "")
    try:
        n = con.execute(
            f"SELECT count(*) FROM pop_{tag} p JOIN speed_bot_candidates s ON p.client_id = s.client_id"
        ).fetchone()[0]
        pop_overlap[d] = n
    except duckdb.CatalogException:
        pop_overlap[d] = None
print("기준일별 모집단 포함 인원:", pop_overlap)
results["p1_population_overlap"] = pop_overlap

with open("docs/prechecks_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)

if n_speed_bot > 1000:
    print(f"\n*** 중단 조건 충족: 속도 기준 해당 인원 {n_speed_bot}명 > 1,000명 — 제외하지 않고 멈춘다 ***")
    con.close()
    sys.exit(0)

print(f"\n속도 기준 해당 인원 {n_speed_bot}명 <= 1,000명 — 모집단에서 제외하고 계속 진행한다.")

# 표본 10명(seed=42) 패턴 요약
all_ids = con.execute("SELECT client_id FROM speed_bot_candidates").fetchdf()["client_id"].tolist()
rng = np.random.default_rng(42)
sample_ids = rng.choice(all_ids, size=min(10, len(all_ids)), replace=False).tolist()
pseudo_map = dict(zip(sample_ids, pseudonymize([int(c) for c in sample_ids])))

frames = []
for t in NONBUY_TABLES:
    df = con.execute(
        f"SELECT client_id, timestamp, "
        f"{'sku' if t in ('add_to_cart','remove_from_cart') else ('url' if t=='page_visit' else 'query')} AS target "
        f"FROM clean_{t} WHERE client_id IN ({','.join(str(int(c)) for c in sample_ids)}) AND timestamp < '{CUTOFF}'"
    ).fetchdf()
    df["table"] = t
    frames.append(df)
sample_events = pd.concat(frames, ignore_index=True)
sample_events["ts"] = pd.to_datetime(sample_events["timestamp"], format="%Y-%m-%d %H:%M:%S")

cart_presence = con.execute(
    f"SELECT DISTINCT client_id FROM clean_add_to_cart WHERE client_id IN ({','.join(str(int(c)) for c in sample_ids)})"
).fetchdf()["client_id"].tolist()
buy_presence = con.execute(
    f"SELECT DISTINCT client_id FROM clean_product_buy WHERE client_id IN ({','.join(str(int(c)) for c in sample_ids)})"
).fetchdf()["client_id"].tolist()

rows = []
for cid in sample_ids:
    sub = sample_events[sample_events["client_id"] == cid].sort_values("ts")
    minute_counts = sub.groupby(sub["ts"].dt.floor("min")).size()
    max_per_min = int(minute_counts.max())
    max_minute = minute_counts.idxmax()
    sub_in_max = sub[sub["ts"].dt.floor("min") == max_minute]
    n_distinct_target = sub_in_max["target"].nunique()
    same_ts_counts = sub.groupby("ts").size()
    max_same_ts = int(same_ts_counts.max())
    active_days = sub["ts"].dt.date.nunique()
    gaps = sub["ts"].diff().dt.total_seconds().dropna()
    gap_median = float(gaps.median()) if len(gaps) else None
    rows.append({
        "고객": pseudo_map[cid], "1분최대건수": max_per_min,
        "그1분내고유url_sku수": int(n_distinct_target),
        "동일타임스탬프최대행수": max_same_ts, "활동일수": active_days,
        "이벤트간격중앙값(초)": gap_median,
        "add_to_cart등장": cid in cart_presence, "product_buy등장": cid in buy_presence,
    })
sample_df = pd.DataFrame(rows)
print("\n표본 10명 패턴:")
print(sample_df.to_string(index=False))
results["p1_sample10"] = sample_df.to_dict(orient="records")

with open("docs/prechecks_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/prechecks_results.json (P1까지)")

# ---------- P1 재계산: 속도봇 제외한 스냅샷/변수/가설판정 ----------
# 이후 P2·P3·모델링·최종평가는 전부 이 속도봇 제외 결과(= 아래에서 덮어쓰는
# pop_*/outcome_*/training_snapshot/training_features)를 "현재" 정제 계층으로 쓴다.
# 3-5번 민감도 확인에서 "(a) 속도 봇 제외를 하지 않은 경우"와 비교하기 위해
# 원래(제외 전) 수치는 docs/snapshot_results.json·hypothesis_results.json에 그대로 남겨둔다.
print("\n## P1 재계산: 속도봇 제외 후 스냅샷/가설 재검증 (이후 단계의 기본 모집단이 됨)")
con.execute("SET threads=4")
con.execute("SET memory_limit='6GB'")
con.execute("SET preserve_insertion_order=false")


def shift(d, days):
    return (pd.Timestamp(d) + pd.Timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


EVENT_TABLES = ["clean_product_buy", "clean_add_to_cart", "clean_remove_from_cart",
                 "clean_page_visit", "clean_search_query"]
ALL_DATES = TRAINING_DATES + ["2022-11-07", "2022-11-23"]
SAMPLE_TARGET, SEED = 100_000, 42

print("모집단 재계산(전체 7개 기준일, 속도봇 제외)")
for d in ALL_DATES:
    tag = d.replace("-", "")
    win_start, win_end = shift(d, -30), shift(d, 0)
    union_sql2 = " UNION ALL ".join(
        f"SELECT client_id FROM {t} WHERE timestamp >= '{win_start}' AND timestamp < '{win_end}'"
        for t in EVENT_TABLES
    )
    con.execute(f"""
        CREATE OR REPLACE TABLE pop_{tag} AS
        SELECT DISTINCT client_id FROM ({union_sql2}) u
        WHERE client_id NOT IN (SELECT client_id FROM bot_clients)
          AND client_id NOT IN (SELECT client_id FROM speed_bot_candidates)
    """)
    n = con.execute(f"SELECT count(*) FROM pop_{tag}").fetchone()[0]
    print(d, "모집단(속도봇 제외 후):", n)

purchase_rate_compare = {}
sample_frames = []
for d in TRAINING_DATES:
    tag = d.replace("-", "")
    out_start, out_end = shift(d, 0), shift(d, 14)
    con.execute(f"""
        CREATE OR REPLACE TABLE outcome_{tag} AS
        SELECT p.client_id, CASE WHEN b.client_id IS NOT NULL THEN 1 ELSE 0 END AS outcome
        FROM pop_{tag} p
        LEFT JOIN (SELECT DISTINCT client_id FROM clean_product_buy
                    WHERE timestamp >= '{out_start}' AND timestamp < '{out_end}') b
        ON p.client_id = b.client_id
    """)
    df = con.execute(f"SELECT client_id, outcome FROM outcome_{tag}").fetchdf()
    n, n_pos = len(df), int(df["outcome"].sum())
    purchase_rate_compare[d] = {"n_population_new": n, "n_purchasers_new": n_pos,
                                 "purchase_rate_new": round(n_pos / n, 5)}
    frac = min(1.0, SAMPLE_TARGET / n)
    sampled = df.groupby("outcome", group_keys=False).apply(lambda g: g.sample(frac=frac, random_state=SEED))
    sampled = sampled.copy()
    sampled["reference_date"] = d
    sample_frames.append(sampled)
    print(d, purchase_rate_compare[d])

with open("docs/snapshot_results.json", encoding="utf-8") as f:
    orig_snapshot = json.load(f)
for d in TRAINING_DATES:
    purchase_rate_compare[d]["purchase_rate_orig"] = orig_snapshot["training_outcome"][d]["purchase_rate"]
    purchase_rate_compare[d]["n_population_orig"] = orig_snapshot["training_outcome"][d]["n_population"]
results["p1_purchase_rate_compare"] = purchase_rate_compare
print("\n구매율 비교(원래 vs 속도봇 제외):")
for d, v in purchase_rate_compare.items():
    print(d, "원래=", v["purchase_rate_orig"], "제외후=", v["purchase_rate_new"])

training_snapshot = pd.concat(sample_frames, ignore_index=True)
con.register("training_snapshot_df", training_snapshot)
con.execute("CREATE OR REPLACE TABLE training_snapshot AS SELECT * FROM training_snapshot_df")
print("training_snapshot 덮어씀(속도봇 제외), 행 수:", len(training_snapshot))


def events_union_sql(start, end, tables=("product_buy", "add_to_cart", "remove_from_cart",
                                           "page_visit", "search_query")):
    return " UNION ALL ".join(
        f"SELECT client_id, timestamp FROM clean_{t} WHERE timestamp >= '{start}' AND timestamp < '{end}'"
        for t in tables
    )


print("\n변수(H1~H6) 재생성 중 (training_features 덮어씀)")
all_feature_frames = []
for d in TRAINING_DATES:
    w60_start, w60_end = shift(d, -60), shift(d, 0)
    w30_start, w14_start, w7_start = shift(d, -30), shift(d, -14), shift(d, -7)
    prior46_start, prior46_end = shift(d, -60), shift(d, -14)

    pop = con.execute(f"SELECT client_id FROM training_snapshot WHERE reference_date = '{d}'").fetchdf()
    con.register("cur_pop_df", pop)
    con.execute("CREATE OR REPLACE TEMP TABLE cur_pop AS SELECT * FROM cur_pop_df")
    feat = pop.set_index("client_id")

    last_activity = con.execute(
        f"""SELECT p.client_id, max(u.timestamp) AS last_ts FROM cur_pop p
            LEFT JOIN ({events_union_sql(w60_start, w60_end)}) u ON p.client_id = u.client_id
            GROUP BY p.client_id"""
    ).fetchdf()
    last_activity["h1_days_since_last_activity"] = (
        pd.Timestamp(d) - pd.to_datetime(last_activity["last_ts"], format="%Y-%m-%d %H:%M:%S")
    ).dt.total_seconds() / 86400
    feat = feat.join(last_activity.set_index("client_id")[["h1_days_since_last_activity"]])

    buys = con.execute(
        f"""SELECT p.client_id, count(b.timestamp) AS n_buys FROM cur_pop p
            LEFT JOIN (SELECT client_id, timestamp FROM clean_product_buy
                       WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}') b
            ON p.client_id = b.client_id GROUP BY p.client_id"""
    ).fetchdf()
    feat = feat.join(buys.set_index("client_id")[["n_buys"]].rename(
        columns={"n_buys": "h3_purchase_count"}))
    feat["h3_purchase_count"] = feat["h3_purchase_count"].fillna(0)

    pending_union = f"""
        SELECT client_id, sku, timestamp, 0 AS kind_priority, 'add' AS kind
          FROM clean_add_to_cart WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}'
        UNION ALL
        SELECT client_id, sku, timestamp, 1 AS kind_priority, 'remove' AS kind
          FROM clean_remove_from_cart WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}'
        UNION ALL
        SELECT client_id, sku, timestamp, 2 AS kind_priority, 'buy' AS kind
          FROM clean_product_buy WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}'
    """
    pending = con.execute(
        f"""WITH ev AS ({pending_union}),
             ranked AS (SELECT *, row_number() OVER (
                 PARTITION BY client_id, sku ORDER BY timestamp DESC, kind_priority ASC) AS rn FROM ev)
             SELECT client_id, sku FROM ranked WHERE rn = 1 AND kind = 'add'"""
    ).fetchdf()
    pending_count = pending.groupby("client_id").size().rename("h2_pending_items")
    feat = feat.join(pending_count)
    feat["h2_pending_items"] = feat["h2_pending_items"].fillna(0)

    searches = con.execute(
        f"""SELECT p.client_id, count(s.timestamp) AS n_real FROM cur_pop p
            LEFT JOIN (SELECT client_id, timestamp FROM clean_search_query_real
                       WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}') s
            ON p.client_id = s.client_id GROUP BY p.client_id"""
    ).fetchdf()
    feat = feat.join(searches.set_index("client_id")[["n_real"]].rename(
        columns={"n_real": "h4_real_search_count"}))
    feat["h4_real_search_count"] = feat["h4_real_search_count"].fillna(0)

    recent14_cnt = con.execute(
        f"""SELECT p.client_id, count(u.timestamp) AS n FROM cur_pop p
            LEFT JOIN ({events_union_sql(w14_start, w60_end)}) u ON p.client_id = u.client_id
            GROUP BY p.client_id"""
    ).fetchdf().set_index("client_id")["n"]
    prior46_cnt = con.execute(
        f"""SELECT p.client_id, count(u.timestamp) AS n FROM cur_pop p
            LEFT JOIN ({events_union_sql(prior46_start, prior46_end)}) u ON p.client_id = u.client_id
            GROUP BY p.client_id"""
    ).fetchdf().set_index("client_id")["n"]
    recent14_avg = recent14_cnt.reindex(feat.index).fillna(0) / 14
    prior46_avg = prior46_cnt.reindex(feat.index).fillna(0) / 46
    ratio = recent14_avg / prior46_avg
    ratio[prior46_avg == 0] = float("nan")
    feat = feat.join(ratio.rename("h5_activity_growth_ratio"))

    add_cnt = con.execute(
        f"""SELECT client_id, count(*) AS n FROM clean_add_to_cart
            WHERE client_id IN (SELECT client_id FROM cur_pop)
              AND timestamp >= '{w60_start}' AND timestamp < '{w60_end}' GROUP BY client_id"""
    ).fetchdf().set_index("client_id")["n"]
    remove_cnt = con.execute(
        f"""SELECT client_id, count(*) AS n FROM clean_remove_from_cart
            WHERE client_id IN (SELECT client_id FROM cur_pop)
              AND timestamp >= '{w60_start}' AND timestamp < '{w60_end}' GROUP BY client_id"""
    ).fetchdf().set_index("client_id")["n"]
    add_cnt_full = add_cnt.reindex(feat.index)
    removal_ratio = remove_cnt.reindex(feat.index).fillna(0) / add_cnt_full
    feat = feat.join(removal_ratio.rename("h6_removal_ratio"))

    feat["reference_date"] = d
    all_feature_frames.append(feat.reset_index())
    print(d, "핵심 변수 재생성 완료, 행 수:", len(feat))

features_all = pd.concat(all_feature_frames, ignore_index=True)
outcome = con.execute("SELECT client_id, reference_date, outcome FROM training_snapshot").fetchdf()
features_all = features_all.merge(outcome, on=["client_id", "reference_date"], how="left")
con.register("features_all_df", features_all)
con.execute("CREATE OR REPLACE TABLE training_features AS SELECT * FROM features_all_df")
print("training_features 덮어씀(속도봇 제외), 크기:", features_all.shape)


# ---------- 핵심 변수 IV/판정 재계산 (3단계와 동일 방식, 간략판: 핵심 변수만) ----------
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


def bin_variable(series, na_label="결측", zero_threshold=0.3, n_qbins=10, min_bin_n=None):
    s = series.copy()
    is_na = s.isna()
    labels = pd.Series(index=s.index, dtype=object)
    labels[is_na] = na_label
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
        mapping = greedy_merge(counts, min_bin_n or len(s) * 0.05)
        merged = qcodes.map(mapping)
        for i in range(merged.max() + 1 if len(merged) else 0):
            lbl = f"Q{i+1}"
            labels[rest_mask & (merged == i).reindex(labels.index, fill_value=False)] = lbl
            bin_order.append(lbl)
    return labels, bin_order


def woe_iv_table(labels, outcome):
    tmp = pd.DataFrame({"bin": labels, "outcome": outcome})
    grp = tmp.groupby("bin")["outcome"].agg(n="count", good="sum")
    grp["bad"] = grp["n"] - grp["good"]
    grp["good_adj"], grp["bad_adj"] = grp["good"] + 0.5, grp["bad"] + 0.5
    tg, tb = grp["good_adj"].sum(), grp["bad_adj"].sum()
    grp["good_dist"], grp["bad_dist"] = grp["good_adj"] / tg, grp["bad_adj"] / tb
    grp["woe"] = np.log(grp["good_dist"] / grp["bad_dist"])
    iv = ((grp["good_dist"] - grp["bad_dist"]) * grp["woe"]).sum()
    grp["purchase_rate"] = grp["good"] / grp["n"]
    return grp, float(iv)


CORE_DIRECTIONS = {
    "h1_days_since_last_activity": "lower_better", "h2_pending_items": "higher_better",
    "h3_purchase_count": "higher_better", "h4_real_search_count": "higher_better",
    "h5_activity_growth_ratio": "higher_better", "h6_removal_ratio": "lower_better",
}
orig_iv = {"h1_days_since_last_activity": 0.5546, "h2_pending_items": 0.4044,
           "h3_purchase_count": 1.6325, "h4_real_search_count": 0.4473,
           "h5_activity_growth_ratio": 0.7359, "h6_removal_ratio": 1.3601}
orig_verdict = {"h1_days_since_last_activity": "채택", "h2_pending_items": "채택",
                 "h3_purchase_count": "채택", "h4_real_search_count": "채택",
                 "h5_activity_growth_ratio": "채택", "h6_removal_ratio": "기각"}

verdict_compare = {}
for col, direction in CORE_DIRECTIONS.items():
    na_label = "이전활동없음" if col.startswith("h5_") else "결측"
    labels, bin_order = bin_variable(features_all[col], na_label=na_label)
    grp, iv = woe_iv_table(labels, features_all["outcome"])
    ordered = [b for b in bin_order if b in grp.index]
    if len(ordered) >= 2:
        low_end, high_end = (ordered[0], ordered[-1]) if direction == "higher_better" else (ordered[-1], ordered[0])
        p_high, p_low = grp.loc[high_end, "purchase_rate"], grp.loc[low_end, "purchase_rate"]
        n_high, n_low = grp.loc[high_end, "n"], grp.loc[low_end, "n"]
        rate_ok = p_high > p_low
        if p_high > 0 and p_low > 0:
            se = np.sqrt((1 - p_high) / (n_high * p_high) + (1 - p_low) / (n_low * p_low))
            ratio = p_high / p_low
            ci_lo = ratio * np.exp(-1.96 * se)
            ci_ok = ci_lo > 1
        else:
            ci_ok = False
        ranks = list(range(1, len(ordered) + 1))
        rates = grp.loc[ordered, "purchase_rate"].values
        rx, ry = pd.Series(ranks).rank(), pd.Series(rates).rank()
        spearman = rx.corr(ry) if rx.nunique() > 1 and ry.nunique() > 1 else np.nan
        expected_sign = 1 if direction == "higher_better" else -1
        spearman_ok = (not np.isnan(spearman)) and (np.sign(spearman) == expected_sign)
    else:
        rate_ok = ci_ok = spearman_ok = False
    new_verdict = "채택" if (iv >= 0.02 and spearman_ok and rate_ok and ci_ok) else "기각"
    verdict_compare[col] = {
        "iv_orig": orig_iv[col], "iv_new": round(iv, 4),
        "verdict_orig": orig_verdict[col], "verdict_new": new_verdict,
        "changed": new_verdict != orig_verdict[col],
    }
    print(col, verdict_compare[col])

results["p1_hypothesis_verdict_compare"] = verdict_compare

with open("docs/prechecks_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/prechecks_results.json (P1 재계산까지)")
print("P1 전체 완료")


def wilson_ci(successes, n, z=1.96):
    if n == 0:
        return (None, None)
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z**2 / (4 * n**2)) ** 0.5) / denom
    return (round(max(0, center - half), 6), round(min(1, center + half), 6))


# ========== P2. 방문만 하는 고객의 구매 비중 (학습 기준일만, 전체 모집단 기준) ==========
print("\n## P2. 방문만 하는 고객의 구매 비중 (학습 기준일만)")
p2_results = {}
for d in TRAINING_DATES:
    tag = d.replace("-", "")
    w60_start, w60_end = shift(d, -60), shift(d, 0)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE has_other AS
        SELECT DISTINCT client_id FROM clean_add_to_cart WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}'
        UNION SELECT DISTINCT client_id FROM clean_remove_from_cart WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}'
        UNION SELECT DISTINCT client_id FROM clean_product_buy WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}'
        UNION SELECT DISTINCT client_id FROM clean_search_query_real WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}'
    """)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE visit_only AS
        SELECT p.client_id FROM pop_{tag} p
        JOIN (SELECT DISTINCT client_id FROM clean_page_visit
              WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}') v ON p.client_id = v.client_id
        WHERE p.client_id NOT IN (SELECT client_id FROM has_other)
    """)
    n_pop = con.execute(f"SELECT count(*) FROM pop_{tag}").fetchone()[0]
    n_visit_only = con.execute("SELECT count(*) FROM visit_only").fetchone()[0]
    n_visit_only_purchasers = con.execute(
        f"""SELECT count(*) FROM visit_only v
            JOIN outcome_{tag} o ON v.client_id = o.client_id WHERE o.outcome = 1"""
    ).fetchone()[0]
    n_total_purchasers = con.execute(f"SELECT count(*) FROM outcome_{tag} WHERE outcome = 1").fetchone()[0]

    share_pop = n_visit_only / n_pop
    purchase_rate_vo = n_visit_only_purchasers / n_visit_only
    share_of_purchasers = n_visit_only_purchasers / n_total_purchasers

    p2_results[d] = {
        "n_population": n_pop, "n_visit_only": n_visit_only,
        "share_of_population_pct": round(share_pop * 100, 3),
        "share_of_population_ci95": [round(c * 100, 3) if c is not None else None
                                      for c in wilson_ci(n_visit_only, n_pop)],
        "purchase_rate_pct": round(purchase_rate_vo * 100, 4),
        "purchase_rate_ci95": [round(c * 100, 4) if c is not None else None
                                for c in wilson_ci(n_visit_only_purchasers, n_visit_only)],
        "n_total_purchasers": n_total_purchasers, "n_visit_only_purchasers": n_visit_only_purchasers,
        "share_of_all_purchasers_pct": round(share_of_purchasers * 100, 3),
        "share_of_all_purchasers_ci95": [round(c * 100, 3) if c is not None else None
                                          for c in wilson_ci(n_visit_only_purchasers, n_total_purchasers)],
    }
    print(d, p2_results[d])

results["p2"] = p2_results
with open("docs/prechecks_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/prechecks_results.json (P2까지)")

# ========== P3. H6 원인 확인 (학습 기준일만) ==========
print("\n## P3. H6 원인 확인")

# P3-1. 담기 건수 통제한 비교 (학습 스냅샷 표본 500,000행 재사용, add_count 새로 계산)
print("### P3-1. 담기 건수 통제 비교")
add_remove_frames = []
for d in TRAINING_DATES:
    tag = d.replace("-", "")
    w60_start, w60_end = shift(d, -60), shift(d, 0)
    pop_ids = con.execute(f"SELECT client_id FROM training_snapshot WHERE reference_date = '{d}'").fetchdf()
    con.register("cur_pop_df", pop_ids)
    con.execute("CREATE OR REPLACE TEMP TABLE cur_pop AS SELECT * FROM cur_pop_df")
    add_cnt = con.execute(
        f"""SELECT client_id, count(*) AS n_add FROM clean_add_to_cart
            WHERE client_id IN (SELECT client_id FROM cur_pop)
              AND timestamp >= '{w60_start}' AND timestamp < '{w60_end}' GROUP BY client_id"""
    ).fetchdf()
    remove_cnt = con.execute(
        f"""SELECT client_id, count(*) AS n_remove FROM clean_remove_from_cart
            WHERE client_id IN (SELECT client_id FROM cur_pop)
              AND timestamp >= '{w60_start}' AND timestamp < '{w60_end}' GROUP BY client_id"""
    ).fetchdf()
    outcome_d = con.execute(
        f"SELECT client_id, outcome FROM training_snapshot WHERE reference_date = '{d}'"
    ).fetchdf()
    merged = add_cnt.merge(remove_cnt, on="client_id", how="left").merge(outcome_d, on="client_id", how="inner")
    merged["n_remove"] = merged["n_remove"].fillna(0)
    merged["removal_ratio"] = merged["n_remove"] / merged["n_add"]
    merged["reference_date"] = d
    add_remove_frames.append(merged)

p3_df = pd.concat(add_remove_frames, ignore_index=True)
print("담기>=1건 표본 전체 행 수(5개 기준일 합):", len(p3_df))


def add_bucket(n):
    if n == 1:
        return "1건"
    if n <= 3:
        return "2~3건"
    if n <= 9:
        return "4~9건"
    return "10건+"


def removal_group(r):
    if r == 0:
        return "0"
    if r <= 0.5:
        return "0초과~0.5"
    return "0.5초과"


p3_df["add_bucket"] = p3_df["n_add"].apply(add_bucket)
p3_df["removal_group"] = p3_df["removal_ratio"].apply(removal_group)

p3_cells = []
for ab in ["1건", "2~3건", "4~9건", "10건+"]:
    for rg in ["0", "0초과~0.5", "0.5초과"]:
        sub = p3_df[(p3_df["add_bucket"] == ab) & (p3_df["removal_group"] == rg)]
        n, good = len(sub), int(sub["outcome"].sum())
        rate = good / n if n else None
        ci = wilson_ci(good, n) if n else (None, None)
        p3_cells.append({"담기구간": ab, "제거비율그룹": rg, "n": n, "구매자": good,
                          "구매율": round(rate, 5) if rate is not None else None,
                          "ci_low": ci[0], "ci_high": ci[1]})
p3_cell_df = pd.DataFrame(p3_cells)
print(p3_cell_df.to_string(index=False))
results["p3_controlled_comparison"] = p3_cell_df.to_dict(orient="records")

# 구간 안에서 "제거 많을수록 구매율 높음" 유지 여부 확인
monotonic_check = {}
for ab in ["1건", "2~3건", "4~9건", "10건+"]:
    rates = p3_cell_df[p3_cell_df["담기구간"] == ab].set_index("제거비율그룹")["구매율"]
    ordered = [rates.get("0"), rates.get("0초과~0.5"), rates.get("0.5초과")]
    if all(r is not None for r in ordered):
        monotonic_check[ab] = ordered[0] <= ordered[1] <= ordered[2]
    else:
        monotonic_check[ab] = None
print("구간 내 '제거 많을수록 구매율 높음' 유지 여부:", monotonic_check)
results["p3_monotonic_within_bucket"] = monotonic_check

with open("docs/prechecks_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)

# P3-2. 결제 전 정리 패턴: 제거 후 24시간 내 구매 비율 (학습 기준일, 정제 계층 전체 모집단 기준)
print("\n### P3-2. 결제 전 정리 패턴 (제거 후 24시간 내 구매)")
p3_2 = {}
total_removes, total_matched = 0, 0
for d in TRAINING_DATES:
    tag = d.replace("-", "")
    w60_start, w60_end = shift(d, -60), shift(d, 0)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE removes_{tag} AS
        SELECT r.client_id, r.timestamp AS remove_ts, row_number() OVER () AS rid
        FROM clean_remove_from_cart r JOIN pop_{tag} p ON r.client_id = p.client_id
        WHERE r.timestamp >= '{w60_start}' AND r.timestamp < '{w60_end}'
    """)
    n_removes = con.execute(f"SELECT count(*) FROM removes_{tag}").fetchone()[0]
    n_matched = con.execute(f"""
        SELECT count(DISTINCT rem.rid) FROM removes_{tag} rem
        JOIN clean_product_buy b ON b.client_id = rem.client_id
        WHERE b.timestamp > rem.remove_ts
          AND strptime(b.timestamp,'%Y-%m-%d %H:%M:%S')
              <= strptime(rem.remove_ts,'%Y-%m-%d %H:%M:%S') + INTERVAL 24 HOUR
    """).fetchone()[0]
    rate = n_matched / n_removes if n_removes else None
    p3_2[d] = {"n_removes": n_removes, "n_matched_24h": n_matched,
               "rate": round(rate, 5) if rate is not None else None,
               "ci95": [c for c in wilson_ci(n_matched, n_removes)]}
    total_removes += n_removes
    total_matched += n_matched
    print(d, p3_2[d])
    con.execute(f"DROP TABLE removes_{tag}")

p3_2["전체(5개 기준일 합)"] = {
    "n_removes": total_removes, "n_matched_24h": total_matched,
    "rate": round(total_matched / total_removes, 5),
    "ci95": [c for c in wilson_ci(total_matched, total_removes)],
}
print("전체:", p3_2["전체(5개 기준일 합)"])
results["p3_pre_checkout_tidy"] = p3_2

with open("docs/prechecks_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("\nwrote docs/prechecks_results.json (최종)")
con.close()
print("P1~P3 전체 완료")

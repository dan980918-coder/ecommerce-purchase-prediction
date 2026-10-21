"""H1~H6 변수 생성 (학습 기준일 5개, 표본 스냅샷 기준).

모든 변수는 기준일 이전 정보만 쓴다. 기간을 따로 적지 않은 변수는 60일 신호 기간이다.
해당 행동이 없으면 NULL, 다만 "횟수"가 정의상 0이 맞는 경우는 0을 쓴다(변수별로 명시).
동시 타임스탬프 2차 정렬 기준(00_analysis_rules.md 5번): timestamp DESC, 이어서
이벤트 종류 우선순위(buy>remove>add)로 정렬 — H2 보류상품 판정에서 사용.
"""
import json
import os

import duckdb
import pandas as pd

os.makedirs("docs", exist_ok=True)

DB_PATH = "data/v2.duckdb"
con = duckdb.connect(DB_PATH)
con.execute("SET threads=4")
con.execute("SET memory_limit='5GB'")
con.execute("SET preserve_insertion_order=false")

TRAINING_DATES = ["2022-08-22", "2022-09-05", "2022-09-19", "2022-10-03", "2022-10-17"]
ALL_EVENT_TABLES = ["product_buy", "add_to_cart", "remove_from_cart", "page_visit", "search_query"]


def shift(d, days):
    return (pd.Timestamp(d) + pd.Timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def events_union_sql(start, end, tables=ALL_EVENT_TABLES):
    parts = [
        f"SELECT client_id, timestamp FROM clean_{t} WHERE timestamp >= '{start}' AND timestamp < '{end}'"
        for t in tables
    ]
    return " UNION ALL ".join(parts)


all_feature_frames = []

for d in TRAINING_DATES:
    print(f"\n===== 기준일 {d} =====")
    w60_start, w60_end = shift(d, -60), shift(d, 0)
    w30_start = shift(d, -30)
    w14_start = shift(d, -14)
    w7_start = shift(d, -7)
    prior46_start, prior46_end = shift(d, -60), shift(d, -14)

    pop = con.execute(
        f"SELECT client_id FROM training_snapshot WHERE reference_date = '{d}'"
    ).fetchdf()
    con.register("cur_pop_df", pop)
    con.execute("CREATE OR REPLACE TEMP TABLE cur_pop AS SELECT * FROM cur_pop_df")
    n_pop = len(pop)
    print("표본 인원:", n_pop)

    feat = pop.set_index("client_id")

    # ---------- H1: 최근 활동 ----------
    last_activity = con.execute(
        f"""SELECT p.client_id, max(u.timestamp) AS last_ts
            FROM cur_pop p LEFT JOIN ({events_union_sql(w60_start, w60_end)}) u ON p.client_id = u.client_id
            GROUP BY p.client_id"""
    ).fetchdf()
    last_activity["h1_days_since_last_activity"] = (
        pd.Timestamp(d) - pd.to_datetime(last_activity["last_ts"], format="%Y-%m-%d %H:%M:%S")
    ).dt.total_seconds() / 86400
    feat = feat.join(last_activity.set_index("client_id")[["h1_days_since_last_activity"]])

    last_visit = con.execute(
        f"""SELECT p.client_id, max(v.timestamp) AS last_ts FROM cur_pop p
            LEFT JOIN (SELECT client_id, timestamp FROM clean_page_visit
                       WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}') v
            ON p.client_id = v.client_id GROUP BY p.client_id"""
    ).fetchdf()
    last_visit["h1_days_since_last_visit"] = (
        pd.Timestamp(d) - pd.to_datetime(last_visit["last_ts"], format="%Y-%m-%d %H:%M:%S")
    ).dt.total_seconds() / 86400
    feat = feat.join(last_visit.set_index("client_id")[["h1_days_since_last_visit"]])

    last_cart = con.execute(
        f"""SELECT p.client_id, max(c.timestamp) AS last_ts FROM cur_pop p
            LEFT JOIN (SELECT client_id, timestamp FROM clean_add_to_cart
                       WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}') c
            ON p.client_id = c.client_id GROUP BY p.client_id"""
    ).fetchdf()
    last_cart["h1_days_since_last_cart_add"] = (
        pd.Timestamp(d) - pd.to_datetime(last_cart["last_ts"], format="%Y-%m-%d %H:%M:%S")
    ).dt.total_seconds() / 86400
    feat = feat.join(last_cart.set_index("client_id")[["h1_days_since_last_cart_add"]])

    active_days_30 = con.execute(
        f"""SELECT p.client_id, count(DISTINCT u.day) AS n FROM cur_pop p
            LEFT JOIN (
              SELECT client_id, CAST(strptime(timestamp,'%Y-%m-%d %H:%M:%S') AS DATE) AS day
              FROM ({events_union_sql(w30_start, w60_end)}) raw30
            ) u ON p.client_id = u.client_id
            GROUP BY p.client_id"""
    ).fetchdf()
    feat = feat.join(active_days_30.set_index("client_id")[["n"]].rename(columns={"n": "h1_active_days_last30"}))
    feat["h1_active_days_last30"] = feat["h1_active_days_last30"].fillna(0)

    # ---------- H2: 보류 상품 ----------
    pending_union = f"""
        SELECT client_id, sku, timestamp, 'add' AS kind
          FROM clean_add_to_cart WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}'
        UNION ALL
        SELECT client_id, sku, timestamp, 'remove' AS kind
          FROM clean_remove_from_cart WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}'
        UNION ALL
        SELECT client_id, sku, timestamp, 'buy' AS kind
          FROM clean_product_buy WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}'
    """
    # 상품별 마지막 행동이 담기면 보류. 같은 시각이면 구매 > 제거 > 담기 순으로 마지막으로 봄
    pending = con.execute(
        f"""WITH ev AS ({pending_union}),
             ranked AS (
               SELECT *, row_number() OVER (
                 PARTITION BY client_id, sku ORDER BY timestamp DESC,
                          CASE kind WHEN 'buy' THEN 1 WHEN 'remove' THEN 2 ELSE 3 END
               ) AS rn
               FROM ev
             )
             SELECT client_id, sku, timestamp AS add_ts
             FROM ranked WHERE rn = 1 AND kind = 'add'"""
    ).fetchdf()
    pending_count = pending.groupby("client_id").size().rename("h2_pending_items")
    feat = feat.join(pending_count)
    feat["h2_pending_items"] = feat["h2_pending_items"].fillna(0)
    feat["h2_has_pending"] = (feat["h2_pending_items"] > 0).astype(int)

    pending["add_ts_dt"] = pd.to_datetime(pending["add_ts"], format="%Y-%m-%d %H:%M:%S")
    recent_pending = pending[pending["add_ts_dt"] >= pd.Timestamp(w7_start)]
    recent_pending_count = recent_pending.groupby("client_id").size().rename("h2_pending_items_last7")
    feat = feat.join(recent_pending_count)
    feat["h2_pending_items_last7"] = feat["h2_pending_items_last7"].fillna(0)

    # ---------- H3: 과거 구매 ----------
    buys = con.execute(
        f"""SELECT p.client_id, count(b.timestamp) AS n_buys,
                   max(b.timestamp) AS last_buy_ts, count(DISTINCT b.sku) AS n_skus
            FROM cur_pop p
            LEFT JOIN (SELECT client_id, timestamp, sku FROM clean_product_buy
                       WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}') b
            ON p.client_id = b.client_id
            GROUP BY p.client_id"""
    ).fetchdf()
    buys["h3_purchase_count"] = buys["n_buys"].fillna(0)
    buys["h3_days_since_last_purchase"] = (
        pd.Timestamp(d) - pd.to_datetime(buys["last_buy_ts"], format="%Y-%m-%d %H:%M:%S")
    ).dt.total_seconds() / 86400
    buys["h3_unique_skus_bought"] = buys["n_skus"].fillna(0)
    feat = feat.join(buys.set_index("client_id")[
        ["h3_purchase_count", "h3_days_since_last_purchase", "h3_unique_skus_bought"]
    ])

    # ---------- H4: 실제 검색 ----------
    searches = con.execute(
        f"""SELECT p.client_id, count(s.timestamp) AS n_real, count(DISTINCT s.query) AS n_distinct_q
            FROM cur_pop p
            LEFT JOIN (SELECT client_id, timestamp, query FROM clean_search_query_real
                       WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}') s
            ON p.client_id = s.client_id GROUP BY p.client_id"""
    ).fetchdf()
    searches["h4_real_search_count"] = searches["n_real"].fillna(0)
    searches["h4_unique_queries"] = searches["n_distinct_q"].fillna(0)
    feat = feat.join(searches.set_index("client_id")[["h4_real_search_count", "h4_unique_queries"]])

    search_last7 = con.execute(
        f"""SELECT DISTINCT client_id FROM clean_search_query_real
            WHERE timestamp >= '{w7_start}' AND timestamp < '{w60_end}'"""
    ).fetchdf()
    feat["h4_real_search_last7"] = feat.index.isin(search_last7["client_id"]).astype(int)

    default_flag = con.execute(
        f"""SELECT DISTINCT client_id FROM clean_search_query_default
            WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}'"""
    ).fetchdf()
    feat["ref_default_search_flag"] = feat.index.isin(default_flag["client_id"]).astype(int)

    # ---------- H5: 활동 증가율 ----------
    recent14_cnt = con.execute(
        f"""SELECT p.client_id, count(u.timestamp) AS n,
                   count(DISTINCT CAST(strptime(u.timestamp,'%Y-%m-%d %H:%M:%S') AS DATE)) AS days
            FROM cur_pop p LEFT JOIN ({events_union_sql(w14_start, w60_end)}) u
            ON p.client_id = u.client_id GROUP BY p.client_id"""
    ).fetchdf()
    prior46_cnt = con.execute(
        f"""SELECT p.client_id, count(u.timestamp) AS n,
                   count(DISTINCT CAST(strptime(u.timestamp,'%Y-%m-%d %H:%M:%S') AS DATE)) AS days
            FROM cur_pop p LEFT JOIN ({events_union_sql(prior46_start, prior46_end)}) u
            ON p.client_id = u.client_id GROUP BY p.client_id"""
    ).fetchdf()
    r14 = recent14_cnt.set_index("client_id")
    p46 = prior46_cnt.set_index("client_id")
    recent14_avg = r14["n"].fillna(0) / 14
    prior46_avg = p46["n"].fillna(0) / 46
    no_prior = prior46_avg == 0
    ratio = recent14_avg / prior46_avg
    ratio[no_prior] = float("nan")
    feat = feat.join(ratio.rename("h5_activity_growth_ratio"))
    feat = feat.join(no_prior.rename("h5_no_prior_activity"))

    recent14_days_avg = r14["days"].fillna(0) / 14
    prior46_days_avg = p46["days"].fillna(0) / 46
    no_prior_days = prior46_days_avg == 0
    days_ratio = recent14_days_avg / prior46_days_avg
    days_ratio[no_prior_days] = float("nan")
    feat = feat.join(days_ratio.rename("h5_active_days_growth_ratio"))

    # ---------- H6: 장바구니 제거 비율 ----------
    add_cnt = con.execute(
        f"""SELECT client_id, count(*) AS n FROM clean_add_to_cart
            WHERE client_id IN (SELECT client_id FROM cur_pop)
              AND timestamp >= '{w60_start}' AND timestamp < '{w60_end}'
            GROUP BY client_id"""
    ).fetchdf().set_index("client_id")["n"]
    remove_cnt = con.execute(
        f"""SELECT client_id, count(*) AS n FROM clean_remove_from_cart
            WHERE client_id IN (SELECT client_id FROM cur_pop)
              AND timestamp >= '{w60_start}' AND timestamp < '{w60_end}'
            GROUP BY client_id"""
    ).fetchdf().set_index("client_id")["n"]
    add_cnt_full = add_cnt.reindex(feat.index)
    remove_cnt_full = remove_cnt.reindex(feat.index).fillna(0)
    removal_ratio = remove_cnt_full / add_cnt_full  # add_cnt_full가 NaN이면 결과도 NaN
    feat = feat.join(removal_ratio.rename("h6_removal_ratio"))

    remove_last7 = con.execute(
        f"""SELECT DISTINCT client_id FROM clean_remove_from_cart
            WHERE client_id IN (SELECT client_id FROM cur_pop)
              AND timestamp >= '{w7_start}' AND timestamp < '{w60_end}'"""
    ).fetchdf()
    feat["h6_removal_last7"] = feat.index.isin(remove_last7["client_id"]).astype(int)

    feat["reference_date"] = d
    feat = feat.reset_index()
    all_feature_frames.append(feat)
    print("변수 생성 완료, 컬럼 수:", feat.shape[1])

features_all = pd.concat(all_feature_frames, ignore_index=True)
outcome = con.execute("SELECT client_id, reference_date, outcome FROM training_snapshot").fetchdf()
features_all = features_all.merge(outcome, on=["client_id", "reference_date"], how="left")
print("\n전체 피처 테이블 크기:", features_all.shape)

con.register("features_all_df", features_all)
con.execute("CREATE OR REPLACE TABLE training_features AS SELECT * FROM features_all_df")
print("training_features 테이블 저장 완료")

summary = {
    "n_rows": len(features_all),
    "columns": list(features_all.columns),
    "null_rate_pct": {c: round(float(features_all[c].isna().mean() * 100), 3) for c in features_all.columns},
}
with open("docs/features_summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/features_summary.json")
con.close()

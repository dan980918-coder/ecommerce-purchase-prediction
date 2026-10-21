"""H1~H6 전체(핵심+보조) 변수 + 참고/플래그 변수를 한 번에 만드는 공용 함수.

14_models.py(학습셋, 검증 전체모집단)와 15_final_evaluation.py(최종평가 전체모집단)가
공통으로 쓴다. 동시 타임스탬프 2차 정렬(timestamp DESC, buy>remove>add)은
07_features.md·00_analysis_rules.md 5번과 동일하다.
"""
import pandas as pd


def shift(d, days):
    return (pd.Timestamp(d) + pd.Timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def events_union_sql(start, end, tables=("product_buy", "add_to_cart", "remove_from_cart",
                                           "page_visit", "search_query")):
    return " UNION ALL ".join(
        f"SELECT client_id, timestamp FROM clean_{t} WHERE timestamp >= '{start}' AND timestamp < '{end}'"
        for t in tables
    )


def build_features(con, population_df, reference_date, pop_table_name="cur_pop_feat"):
    """population_df: client_id 컬럼 하나짜리 DataFrame. 반환: client_id를 포함한 피처 DataFrame."""
    d = reference_date
    w60_start, w60_end = shift(d, -60), shift(d, 0)
    w30_start = shift(d, -30)
    w14_start, w7_start = shift(d, -14), shift(d, -7)
    prior46_start, prior46_end = shift(d, -60), shift(d, -14)

    con.register(f"{pop_table_name}_df", population_df[["client_id"]])
    con.execute(f"CREATE OR REPLACE TEMP TABLE {pop_table_name} AS SELECT * FROM {pop_table_name}_df")
    feat = population_df[["client_id"]].drop_duplicates().set_index("client_id")

    # H1
    last_activity = con.execute(
        f"""SELECT p.client_id, max(u.timestamp) AS last_ts FROM {pop_table_name} p
            LEFT JOIN ({events_union_sql(w60_start, w60_end)}) u ON p.client_id = u.client_id
            GROUP BY p.client_id"""
    ).fetchdf()
    last_activity["h1_days_since_last_activity"] = (
        pd.Timestamp(d) - pd.to_datetime(last_activity["last_ts"], format="%Y-%m-%d %H:%M:%S")
    ).dt.total_seconds() / 86400
    feat = feat.join(last_activity.set_index("client_id")[["h1_days_since_last_activity"]])

    last_visit = con.execute(
        f"""SELECT p.client_id, max(v.timestamp) AS last_ts FROM {pop_table_name} p
            LEFT JOIN (SELECT client_id, timestamp FROM clean_page_visit
                       WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}') v
            ON p.client_id = v.client_id GROUP BY p.client_id"""
    ).fetchdf()
    last_visit["h1_days_since_last_visit"] = (
        pd.Timestamp(d) - pd.to_datetime(last_visit["last_ts"], format="%Y-%m-%d %H:%M:%S")
    ).dt.total_seconds() / 86400
    feat = feat.join(last_visit.set_index("client_id")[["h1_days_since_last_visit"]])

    last_cart = con.execute(
        f"""SELECT p.client_id, max(c.timestamp) AS last_ts, count(c.timestamp) AS n_add FROM {pop_table_name} p
            LEFT JOIN (SELECT client_id, timestamp FROM clean_add_to_cart
                       WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}') c
            ON p.client_id = c.client_id GROUP BY p.client_id"""
    ).fetchdf()
    last_cart["h1_days_since_last_cart_add"] = (
        pd.Timestamp(d) - pd.to_datetime(last_cart["last_ts"], format="%Y-%m-%d %H:%M:%S")
    ).dt.total_seconds() / 86400
    feat = feat.join(last_cart.set_index("client_id")[["h1_days_since_last_cart_add", "n_add"]])
    feat["n_add"] = feat["n_add"].fillna(0)

    active_days_30 = con.execute(
        f"""SELECT p.client_id, count(DISTINCT u.day) AS n FROM {pop_table_name} p
            LEFT JOIN (
              SELECT client_id, CAST(strptime(timestamp,'%Y-%m-%d %H:%M:%S') AS DATE) AS day
              FROM ({events_union_sql(w30_start, w60_end)}) raw30
            ) u ON p.client_id = u.client_id GROUP BY p.client_id"""
    ).fetchdf()
    feat = feat.join(active_days_30.set_index("client_id")[["n"]].rename(
        columns={"n": "h1_active_days_last30"}))
    feat["h1_active_days_last30"] = feat["h1_active_days_last30"].fillna(0)

    # H2
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
             ranked AS (SELECT *, row_number() OVER (
                 PARTITION BY client_id, sku ORDER BY timestamp DESC,
                          CASE kind WHEN 'buy' THEN 1 WHEN 'remove' THEN 2 ELSE 3 END) AS rn FROM ev)
             SELECT client_id, sku, timestamp AS add_ts FROM ranked WHERE rn = 1 AND kind = 'add'"""
    ).fetchdf()
    pending_count = pending.groupby("client_id").size().rename("h2_pending_items")
    feat = feat.join(pending_count)
    feat["h2_pending_items"] = feat["h2_pending_items"].fillna(0)
    feat["h2_has_pending"] = (feat["h2_pending_items"] > 0).astype(int)
    pending["add_ts_dt"] = pd.to_datetime(pending["add_ts"], format="%Y-%m-%d %H:%M:%S")
    recent_pending_count = pending[pending["add_ts_dt"] >= pd.Timestamp(w7_start)].groupby(
        "client_id").size().rename("h2_pending_items_last7")
    feat = feat.join(recent_pending_count)
    feat["h2_pending_items_last7"] = feat["h2_pending_items_last7"].fillna(0)

    # H3
    buys = con.execute(
        f"""SELECT p.client_id, count(b.timestamp) AS n_buys, max(b.timestamp) AS last_buy_ts,
                   count(DISTINCT b.sku) AS n_skus
            FROM {pop_table_name} p
            LEFT JOIN (SELECT client_id, timestamp, sku FROM clean_product_buy
                       WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}') b
            ON p.client_id = b.client_id GROUP BY p.client_id"""
    ).fetchdf()
    buys["h3_purchase_count"] = buys["n_buys"].fillna(0)
    buys["h3_days_since_last_purchase"] = (
        pd.Timestamp(d) - pd.to_datetime(buys["last_buy_ts"], format="%Y-%m-%d %H:%M:%S")
    ).dt.total_seconds() / 86400
    buys["h3_unique_skus_bought"] = buys["n_skus"].fillna(0)
    feat = feat.join(buys.set_index("client_id")[
        ["h3_purchase_count", "h3_days_since_last_purchase", "h3_unique_skus_bought"]])

    # H4
    searches = con.execute(
        f"""SELECT p.client_id, count(s.timestamp) AS n_real, count(DISTINCT s.query) AS n_distinct_q
            FROM {pop_table_name} p
            LEFT JOIN (SELECT client_id, timestamp, query FROM clean_search_query_real
                       WHERE timestamp >= '{w60_start}' AND timestamp < '{w60_end}') s
            ON p.client_id = s.client_id GROUP BY p.client_id"""
    ).fetchdf()
    searches["h4_real_search_count"] = searches["n_real"].fillna(0)
    searches["h4_unique_queries"] = searches["n_distinct_q"].fillna(0)
    feat = feat.join(searches.set_index("client_id")[["h4_real_search_count", "h4_unique_queries"]])

    search_last7 = con.execute(
        f"""SELECT DISTINCT client_id FROM clean_search_query_real
            WHERE client_id IN (SELECT client_id FROM {pop_table_name})
              AND timestamp >= '{w7_start}' AND timestamp < '{w60_end}'"""
    ).fetchdf()
    feat["h4_real_search_last7"] = feat.index.isin(search_last7["client_id"]).astype(int)

    default_flag = con.execute(
        f"""SELECT DISTINCT client_id FROM clean_search_query_default
            WHERE client_id IN (SELECT client_id FROM {pop_table_name})
              AND timestamp >= '{w60_start}' AND timestamp < '{w60_end}'"""
    ).fetchdf()
    feat["ref_default_search_flag"] = feat.index.isin(default_flag["client_id"]).astype(int)

    # H5
    recent14_cnt = con.execute(
        f"""SELECT p.client_id, count(u.timestamp) AS n,
                   count(DISTINCT CAST(strptime(u.timestamp,'%Y-%m-%d %H:%M:%S') AS DATE)) AS days
            FROM {pop_table_name} p LEFT JOIN ({events_union_sql(w14_start, w60_end)}) u
            ON p.client_id = u.client_id GROUP BY p.client_id"""
    ).fetchdf()
    prior46_cnt = con.execute(
        f"""SELECT p.client_id, count(u.timestamp) AS n,
                   count(DISTINCT CAST(strptime(u.timestamp,'%Y-%m-%d %H:%M:%S') AS DATE)) AS days
            FROM {pop_table_name} p LEFT JOIN ({events_union_sql(prior46_start, prior46_end)}) u
            ON p.client_id = u.client_id GROUP BY p.client_id"""
    ).fetchdf()
    r14 = recent14_cnt.set_index("client_id")
    p46 = prior46_cnt.set_index("client_id")
    recent14_avg = r14["n"].reindex(feat.index).fillna(0) / 14
    prior46_avg = p46["n"].reindex(feat.index).fillna(0) / 46
    no_prior = prior46_avg == 0
    ratio = recent14_avg / prior46_avg
    ratio[no_prior] = float("nan")
    feat = feat.join(ratio.rename("h5_activity_growth_ratio"))
    feat = feat.join(no_prior.rename("h5_no_prior_activity"))

    recent14_days_avg = r14["days"].reindex(feat.index).fillna(0) / 14
    prior46_days_avg = p46["days"].reindex(feat.index).fillna(0) / 46
    no_prior_days = prior46_days_avg == 0
    days_ratio = recent14_days_avg / prior46_days_avg
    days_ratio[no_prior_days] = float("nan")
    feat = feat.join(days_ratio.rename("h5_active_days_growth_ratio"))

    # H6
    remove_cnt = con.execute(
        f"""SELECT client_id, count(*) AS n FROM clean_remove_from_cart
            WHERE client_id IN (SELECT client_id FROM {pop_table_name})
              AND timestamp >= '{w60_start}' AND timestamp < '{w60_end}' GROUP BY client_id"""
    ).fetchdf().set_index("client_id")["n"]
    remove_cnt_full = remove_cnt.reindex(feat.index).fillna(0)
    add_cnt_full = feat["n_add"].replace(0, float("nan"))
    feat["h6_removal_ratio"] = remove_cnt_full / add_cnt_full
    remove_last7 = con.execute(
        f"""SELECT DISTINCT client_id FROM clean_remove_from_cart
            WHERE client_id IN (SELECT client_id FROM {pop_table_name})
              AND timestamp >= '{w7_start}' AND timestamp < '{w60_end}'"""
    ).fetchdf()
    feat["h6_removal_last7"] = feat.index.isin(remove_last7["client_id"]).astype(int)
    feat["n_remove"] = remove_cnt_full

    # 참고 플래그: 방문 외 행동(담기·제거·구매·실제 검색 중 하나라도) 있음
    feat["ref_other_than_browsing"] = (
        (feat["n_add"] > 0) | (feat["n_remove"] > 0)
        | (feat["h3_purchase_count"] > 0) | (feat["h4_real_search_count"] > 0)
    ).astype(int)

    feat = feat.drop(columns=["n_add", "n_remove"])
    feat["reference_date"] = d
    return feat.reset_index()


CORE_AUX_COLS = [
    "h1_days_since_last_activity", "h1_days_since_last_visit", "h1_days_since_last_cart_add",
    "h1_active_days_last30",
    "h2_pending_items", "h2_has_pending", "h2_pending_items_last7",
    "h3_purchase_count", "h3_days_since_last_purchase", "h3_unique_skus_bought",
    "h4_real_search_count", "h4_unique_queries", "h4_real_search_last7",
    "h5_activity_growth_ratio", "h5_active_days_growth_ratio",
    "h6_removal_ratio", "h6_removal_last7",
]
FLAG_COLS = ["ref_default_search_flag", "ref_other_than_browsing"]
COUNT_LIKE_COLS = [  # log1p 대상(음이 아닌 횟수/일수성 변수)
    "h1_active_days_last30", "h2_pending_items", "h2_pending_items_last7",
    "h3_purchase_count", "h3_unique_skus_bought", "h4_real_search_count", "h4_unique_queries",
]

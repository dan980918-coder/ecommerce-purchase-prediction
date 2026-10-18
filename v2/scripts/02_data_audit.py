"""원데이터 점검 (2단계): 테이블 기본 정보, 시간 정보, 키/연결, 고객 커버리지, 데이터 품질.

주의: 비율/전환율 등 "결과" 계산은 하지 않는다. 기본 통계와 커버리지(등장 여부)만 본다.
이 머신은 물리 메모리가 8GB로 작아, DuckDB 작업은 한 번에 하나만 실행하고
threads/memory_limit을 보수적으로 설정한다.
"""
import json
import os

import duckdb

os.makedirs("docs", exist_ok=True)
os.makedirs("data/processed", exist_ok=True)

con = duckdb.connect()
con.execute("SET threads=4")
con.execute("SET memory_limit='5GB'")
con.execute("SET preserve_insertion_order=false")

RAW = "data/raw"
EVENT_TABLES = ["product_buy", "add_to_cart", "remove_from_cart", "page_visit", "search_query"]
ALL_TABLES = EVENT_TABLES + ["product_properties"]
SKU_TABLES = ["product_buy", "add_to_cart", "remove_from_cart"]

results = {}


def p(path):
    return f"{RAW}/{path}.parquet"


# ---------- 2-1. 테이블 기본 정보 ----------
print("## 2-1. 테이블 기본 정보")
basic = {}
specs = {
    "product_buy": ["client_id", "timestamp", "sku"],
    "add_to_cart": ["client_id", "timestamp", "sku"],
    "remove_from_cart": ["client_id", "timestamp", "sku"],
    "page_visit": ["client_id", "timestamp", "url"],
    "search_query": ["client_id", "timestamp", "query"],
    "product_properties": ["sku", "category", "price", "name"],
}
for t, cols in specs.items():
    n = con.execute(f"SELECT count(*) FROM read_parquet('{p(t)}')").fetchone()[0]
    dtypes = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{p(t)}')").fetchdf()
    sel = ", ".join([f"count(*)-count({c}) AS null_{c}" for c in cols])
    nulls = con.execute(f"SELECT {sel} FROM read_parquet('{p(t)}')").fetchone()
    n_client = None
    if "client_id" in cols:
        n_client = con.execute(
            f"SELECT count(DISTINCT client_id) FROM read_parquet('{p(t)}')"
        ).fetchone()[0]
    basic[t] = {
        "n_rows": n,
        "dtypes": dict(zip(dtypes["column_name"], dtypes["column_type"].astype(str))),
        "null_counts": dict(zip(cols, nulls)),
        "n_distinct_client_id": n_client,
    }
    print(t, basic[t])
results["basic"] = basic

# ---------- 2-2. 시간 정보 ----------
print("\n## 2-2. 시간 정보")
time_info = {}
for t in EVENT_TABLES:
    mn, mx, maxlen, minlen = con.execute(
        f"""SELECT min(timestamp), max(timestamp), max(length(timestamp)), min(length(timestamp))
            FROM read_parquet('{p(t)}')"""
    ).fetchone()
    not_mult5 = con.execute(
        f"""SELECT sum(CASE WHEN CAST(substr(timestamp,-2,2) AS INT) % 5 != 0 THEN 1 ELSE 0 END)
            FROM read_parquet('{p(t)}')"""
    ).fetchone()[0]
    time_info[t] = {
        "min_ts": mn, "max_ts": mx, "str_len": [minlen, maxlen],
        "not_multiple_of_5s": not_mult5,
    }
    # 일별 추이 -> CSV (그림용)
    con.execute(
        f"""COPY (
              SELECT date_trunc('day', strptime(timestamp,'%Y-%m-%d %H:%M:%S')) AS day, count(*) AS n
              FROM read_parquet('{p(t)}') GROUP BY day ORDER BY day
            ) TO 'data/processed/daily_{t}.csv' (HEADER, DELIMITER ',')"""
    )
    print(t, time_info[t])
results["time_info"] = time_info

# ---------- 2-3. 키와 연결 ----------
print("\n## 2-3. 키와 연결")
sku_coverage = {}
for t in SKU_TABLES:
    row = con.execute(
        f"""WITH ev AS (SELECT DISTINCT sku FROM read_parquet('{p(t)}')),
                 pp AS (SELECT DISTINCT sku FROM read_parquet('{p("product_properties")}'))
            SELECT (SELECT count(*) FROM ev) AS distinct_sku_in_event,
                   (SELECT count(*) FROM ev WHERE sku IN (SELECT sku FROM pp)) AS event_sku_found_in_pp,
                   (SELECT count(*) FROM pp) AS distinct_sku_in_pp,
                   (SELECT count(*) FROM pp WHERE sku IN (SELECT sku FROM ev)) AS pp_sku_found_in_event"""
    ).fetchone()
    row_level = con.execute(
        f"""SELECT count(*) AS total_rows,
                   sum(CASE WHEN sku IN (SELECT sku FROM read_parquet('{p("product_properties")}'))
                            THEN 1 ELSE 0 END) AS rows_with_pp
            FROM read_parquet('{p(t)}')"""
    ).fetchone()
    sku_coverage[t] = {
        "distinct_sku_in_event": row[0], "event_sku_found_in_pp": row[1],
        "distinct_sku_in_pp": row[2], "pp_sku_found_in_event": row[3],
        "total_rows": row_level[0], "rows_with_pp": row_level[1],
    }
    print(t, sku_coverage[t])
results["sku_coverage"] = sku_coverage

url_sku = con.execute(
    f"""SELECT (SELECT count(DISTINCT url) FROM read_parquet('{p("page_visit")}')) AS distinct_url,
               (SELECT min(url) FROM read_parquet('{p("page_visit")}')) AS min_url,
               (SELECT max(url) FROM read_parquet('{p("page_visit")}')) AS max_url,
               (SELECT min(sku) FROM read_parquet('{p("product_properties")}')) AS min_sku,
               (SELECT max(sku) FROM read_parquet('{p("product_properties")}')) AS max_sku"""
).fetchone()
results["url_vs_sku_idspace"] = dict(zip(
    ["distinct_url", "min_url", "max_url", "min_sku", "max_sku"], url_sku))
print("url vs sku id-space:", results["url_vs_sku_idspace"])

sq = con.execute(
    f"""SELECT count(*), count(DISTINCT query), min(length(query)), max(length(query)), avg(length(query))
        FROM read_parquet('{p("search_query")}')"""
).fetchone()
results["search_query_form"] = dict(zip(
    ["n", "n_distinct", "minlen", "maxlen", "avglen"], sq))
print("search_query form:", results["search_query_form"])

pp_form = con.execute(
    f"""SELECT count(*) n, count(DISTINCT category) distinct_cat, min(category), max(category),
               count(DISTINCT price) distinct_price, min(price), max(price), avg(price)
        FROM read_parquet('{p("product_properties")}')"""
).fetchone()
results["product_properties_form"] = dict(zip(
    ["n", "distinct_category", "min_category", "max_category",
     "distinct_price", "min_price", "max_price", "avg_price"], pp_form))
print("product_properties form:", results["product_properties_form"])

# ---------- 2-4. 고객 커버리지 (등장 여부만, 비율 계산 금지) ----------
print("\n## 2-4. 고객 커버리지")
for name, t in [("c_buy", "product_buy"), ("c_cart", "add_to_cart"), ("c_remove", "remove_from_cart"),
                 ("c_visit", "page_visit"), ("c_search", "search_query")]:
    con.execute(f"CREATE TEMP TABLE {name} AS SELECT DISTINCT client_id FROM read_parquet('{p(t)}')")

con.execute(
    """CREATE TEMP TABLE all_ids AS
       SELECT client_id FROM c_buy UNION SELECT client_id FROM c_cart
       UNION SELECT client_id FROM c_remove UNION SELECT client_id FROM c_visit
       UNION SELECT client_id FROM c_search"""
)
total_clients = con.execute("SELECT count(*) FROM all_ids").fetchone()[0]

combo_df = con.execute(
    """SELECT (b.client_id IS NOT NULL) AS has_buy, (c.client_id IS NOT NULL) AS has_cart,
              (r.client_id IS NOT NULL) AS has_remove, (v.client_id IS NOT NULL) AS has_visit,
              (s.client_id IS NOT NULL) AS has_search, count(*) AS n_clients
       FROM all_ids a
       LEFT JOIN c_buy b ON a.client_id=b.client_id
       LEFT JOIN c_cart c ON a.client_id=c.client_id
       LEFT JOIN c_remove r ON a.client_id=r.client_id
       LEFT JOIN c_visit v ON a.client_id=v.client_id
       LEFT JOIN c_search s ON a.client_id=s.client_id
       GROUP BY 1,2,3,4,5 ORDER BY n_clients DESC"""
).fetchdf()
combo_df["pct_of_total"] = (combo_df["n_clients"] / total_clients * 100).round(3)
combo_df.to_csv("data/processed/client_coverage_32combo.csv", index=False)
results["client_coverage"] = {
    "total_distinct_clients_any_table": total_clients,
    "per_table_distinct_clients": {
        "product_buy": con.execute("SELECT count(*) FROM c_buy").fetchone()[0],
        "add_to_cart": con.execute("SELECT count(*) FROM c_cart").fetchone()[0],
        "remove_from_cart": con.execute("SELECT count(*) FROM c_remove").fetchone()[0],
        "page_visit": con.execute("SELECT count(*) FROM c_visit").fetchone()[0],
        "search_query": con.execute("SELECT count(*) FROM c_search").fetchone()[0],
    },
    "top10_combos": combo_df.head(10).to_dict(orient="records"),
}
print("total distinct clients:", total_clients)
print(combo_df.head(10).to_string())

# 고객당 이벤트 수 분포
event_dist = {}
for t in EVENT_TABLES:
    r = con.execute(
        f"""SELECT median(cnt), quantile_cont(cnt,0.9), quantile_cont(cnt,0.99), max(cnt), avg(cnt)
            FROM (SELECT client_id, count(*) AS cnt FROM read_parquet('{p(t)}') GROUP BY client_id)"""
    ).fetchone()
    event_dist[t] = dict(zip(["median", "p90", "p99", "max", "mean"], r))
    print(t, "per-client event dist:", event_dist[t])
results["events_per_client"] = event_dist

# ---------- 2-5. 데이터 품질 ----------
print("\n## 2-5. 데이터 품질")
dup = {}
for t, cols in specs.items():
    colstr = ", ".join(cols)
    r = con.execute(
        f"""SELECT sum(c-1) AS dup_excess_rows, sum(CASE WHEN c>1 THEN 1 ELSE 0 END) AS dup_groups,
                   count(*) AS total_groups
            FROM (SELECT {colstr}, count(*) c FROM read_parquet('{p(t)}') GROUP BY {colstr}) x"""
    ).fetchone()
    dup[t] = dict(zip(["dup_excess_rows", "dup_groups", "total_groups"], r))
    print(t, "duplicates:", dup[t])
results["exact_duplicates"] = dup

burst = {}
target_col = {"product_buy": "sku", "add_to_cart": "sku", "remove_from_cart": "sku", "search_query": "query"}
for t, tgt in target_col.items():
    r = con.execute(
        f"""WITH tt AS (
              SELECT client_id, {tgt}, strptime(timestamp,'%Y-%m-%d %H:%M:%S') AS ts
              FROM read_parquet('{p(t)}')
            ), lagged AS (
              SELECT client_id, {tgt}, ts, ts - lag(ts) OVER (PARTITION BY client_id, {tgt} ORDER BY ts) AS diff
              FROM tt
            )
            SELECT sum(CASE WHEN diff = INTERVAL 0 SECOND THEN 1 ELSE 0 END),
                   sum(CASE WHEN diff > INTERVAL 0 SECOND AND diff <= INTERVAL 1 SECOND THEN 1 ELSE 0 END),
                   sum(CASE WHEN diff > INTERVAL 0 SECOND AND diff <= INTERVAL 5 SECOND THEN 1 ELSE 0 END),
                   sum(CASE WHEN diff > INTERVAL 0 SECOND AND diff <= INTERVAL 30 SECOND THEN 1 ELSE 0 END),
                   count(*)
            FROM lagged"""
    ).fetchone()
    burst[t] = dict(zip(["exact_same_ts_same_target", "within_1s", "within_5s", "within_30s", "total_rows"], r))
    print(t, "burst:", burst[t])
# page_visit은 메모리 제약으로 분리 실행 (동일 로직)
r = con.execute(
    f"""WITH tt AS (
          SELECT client_id, url, strptime(timestamp,'%Y-%m-%d %H:%M:%S') AS ts
          FROM read_parquet('{p("page_visit")}')
        ), lagged AS (
          SELECT client_id, url, ts, ts - lag(ts) OVER (PARTITION BY client_id, url ORDER BY ts) AS diff
          FROM tt
        )
        SELECT sum(CASE WHEN diff = INTERVAL 0 SECOND THEN 1 ELSE 0 END),
               sum(CASE WHEN diff > INTERVAL 0 SECOND AND diff <= INTERVAL 1 SECOND THEN 1 ELSE 0 END),
               sum(CASE WHEN diff > INTERVAL 0 SECOND AND diff <= INTERVAL 5 SECOND THEN 1 ELSE 0 END),
               sum(CASE WHEN diff > INTERVAL 0 SECOND AND diff <= INTERVAL 30 SECOND THEN 1 ELSE 0 END),
               count(*)
        FROM lagged"""
).fetchone()
burst["page_visit"] = dict(zip(["exact_same_ts_same_target", "within_1s", "within_5s", "within_30s", "total_rows"], r))
print("page_visit", "burst:", burst["page_visit"])
results["burst_repeats"] = burst

same_ts_any_target = {}
for t in target_col:
    r = con.execute(
        f"""SELECT sum(CASE WHEN c>1 THEN c ELSE 0 END), sum(CASE WHEN c>1 THEN 1 ELSE 0 END),
                   count(*), max(c)
            FROM (SELECT client_id, timestamp, count(*) c FROM read_parquet('{p(t)}')
                  GROUP BY client_id, timestamp) x"""
    ).fetchone()
    same_ts_any_target[t] = dict(zip(
        ["rows_in_collision_groups", "collision_groups", "total_groups", "max_rows_same_ts"], r))
    print(t, "same-ts(any target):", same_ts_any_target[t])
r = con.execute(
    f"""SELECT sum(CASE WHEN c>1 THEN c ELSE 0 END), sum(CASE WHEN c>1 THEN 1 ELSE 0 END),
               count(*), max(c)
        FROM (SELECT client_id, timestamp, count(*) c FROM read_parquet('{p("page_visit")}')
              GROUP BY client_id, timestamp) x"""
).fetchone()
same_ts_any_target["page_visit"] = dict(zip(
    ["rows_in_collision_groups", "collision_groups", "total_groups", "max_rows_same_ts"], r))
print("page_visit", "same-ts(any target):", same_ts_any_target["page_visit"])
results["same_timestamp_any_target"] = same_ts_any_target

# 구매 단위: 같은 client+timestamp의 distinct sku 수 분포 (바스켓 proxy)
basket = con.execute(
    f"""SELECT basket_size, count(*) AS n_baskets
        FROM (SELECT client_id, timestamp, count(DISTINCT sku) AS basket_size
              FROM read_parquet('{p("product_buy")}') GROUP BY client_id, timestamp) x
        GROUP BY basket_size ORDER BY basket_size"""
).fetchdf()
basket.to_csv("data/processed/product_buy_basket_size_dist.csv", index=False)
results["basket_size_dist_top20"] = basket.head(20).to_dict(orient="records")
results["basket_size_max"] = int(basket["basket_size"].max())
results["basket_n_over_20"] = int(basket.loc[basket["basket_size"] > 20, "n_baskets"].sum())
results["basket_total"] = int(basket["n_baskets"].sum())
print("basket size max:", results["basket_size_max"], "n_baskets:", results["basket_total"])

# 이상값: 음수/범위 확인 + 미래 시각
ranges = {}
check_cols = {
    "product_buy": ["client_id", "sku"], "add_to_cart": ["client_id", "sku"],
    "remove_from_cart": ["client_id", "sku"], "page_visit": ["client_id", "url"],
    "search_query": ["client_id"], "product_properties": ["sku", "category", "price"],
}
for t, cols in check_cols.items():
    sel = ", ".join([f"min({c}) AS min_{c}, max({c}) AS max_{c}" for c in cols])
    r = con.execute(f"SELECT {sel} FROM read_parquet('{p(t)}')").fetchone()
    cols_out = []
    for c in cols:
        cols_out += [f"min_{c}", f"max_{c}"]
    ranges[t] = dict(zip(cols_out, r))
results["value_ranges"] = ranges
print("value ranges:", ranges)

future = {}
for t in EVENT_TABLES:
    r = con.execute(
        f"""SELECT sum(CASE WHEN strptime(timestamp,'%Y-%m-%d %H:%M:%S') > now() THEN 1 ELSE 0 END)
            FROM read_parquet('{p(t)}')"""
    ).fetchone()[0]
    future[t] = r
results["future_timestamp_rows"] = future
print("future timestamp rows:", future)

with open("docs/audit_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("\nwrote docs/audit_results.json")

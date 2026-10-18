"""A. 완전 중복 행 정밀 확인: 오류 vs 수량 vs 시간 반올림의 산물.

처리 방침(중복 제거 등)은 결정하지 않는다. 관찰과 세 가지 설명에 대한 근거만 정리한다.
"""
import json
import os
import sys

import duckdb
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from _pseudonym import pseudonymize  # noqa: E402

os.makedirs("docs", exist_ok=True)

con = duckdb.connect()
con.execute("SET threads=4")
con.execute("SET memory_limit='5GB'")
con.execute("SET preserve_insertion_order=false")

RAW = "data/raw"
TARGET_COL = {
    "product_buy": "sku", "add_to_cart": "sku", "remove_from_cart": "sku",
    "page_visit": "url", "search_query": "query",
}


def p(t):
    return f"{RAW}/{t}.parquet"


results = {}

# ---------- A-1. 중복 배수 분포 ----------
print("## A-1. 중복 배수 분포")
mult_dist = {}
for t, tgt in TARGET_COL.items():
    df = con.execute(
        f"""WITH grp AS (
              SELECT client_id, timestamp, {tgt}, count(*) AS c
              FROM read_parquet('{p(t)}') GROUP BY client_id, timestamp, {tgt}
            )
            SELECT CASE WHEN c=1 THEN '1(무중복)' WHEN c=2 THEN '2'
                        WHEN c=3 THEN '3' WHEN c=4 THEN '4'
                        WHEN c BETWEEN 5 AND 9 THEN '5-9' ELSE '10+' END AS bucket,
                   count(*) AS n_groups, sum(c) AS n_rows
            FROM grp GROUP BY bucket"""
    ).fetchdf()
    order = ["1(무중복)", "2", "3", "4", "5-9", "10+"]
    df["bucket"] = pd.Categorical(df["bucket"], categories=order, ordered=True)
    df = df.sort_values("bucket")
    mult_dist[t] = df.to_dict(orient="records")
    print(t)
    print(df.to_string(index=False))
results["multiplicity_distribution"] = mult_dist

# ---------- product_buy 중복 그룹 무작위 15개 예시 ----------
print("\n## product_buy 중복 그룹 무작위 15개 예시")
con.execute("SELECT setseed(0.4242)")
sample = con.execute(
    """WITH grp AS (
         SELECT client_id, timestamp, sku, count(*) AS c
         FROM read_parquet('data/raw/product_buy.parquet')
         GROUP BY client_id, timestamp, sku
       )
       SELECT client_id, timestamp, sku, c FROM grp WHERE c > 1
       ORDER BY random() LIMIT 15"""
).fetchdf()

examples = []
for _, row in sample.iterrows():
    cid, ts, sku, c = int(row["client_id"]), row["timestamp"], int(row["sku"]), int(row["c"])
    pseudo = pseudonymize([cid])[0]
    # 해당 고객+sku의 product_buy/add_to_cart/remove_from_cart 전체 이벤트를 시간순으로 붙임
    ctx = con.execute(
        f"""SELECT 'product_buy' AS table_name, timestamp FROM read_parquet('{p("product_buy")}')
              WHERE client_id = {cid} AND sku = {sku}
            UNION ALL
            SELECT 'add_to_cart', timestamp FROM read_parquet('{p("add_to_cart")}')
              WHERE client_id = {cid} AND sku = {sku}
            UNION ALL
            SELECT 'remove_from_cart', timestamp FROM read_parquet('{p("remove_from_cart")}')
              WHERE client_id = {cid} AND sku = {sku}
            ORDER BY timestamp"""
    ).fetchdf()
    examples.append({
        "고객": pseudo, "sku": sku, "중복_timestamp": ts, "반복_횟수": c,
        "전후_이벤트": ctx.to_dict(orient="records"),
    })
    print(pseudo, "sku=", sku, "ts=", ts, "반복=", c)
    print(ctx.to_string(index=False))
    print()
results["product_buy_dup_examples"] = examples

# ---------- A-2-1. 5초 배수 여부별 중복 비율 ----------
print("\n## A-2-1. 5초 배수 여부별 중복 비율")
mult5 = {}
for t, tgt in TARGET_COL.items():
    df = con.execute(
        f"""WITH grp AS (
              SELECT client_id, timestamp, {tgt}, count(*) AS c
              FROM read_parquet('{p(t)}') GROUP BY client_id, timestamp, {tgt}
            )
            SELECT CASE WHEN CAST(substr(timestamp,-2,2) AS INT) % 5 = 0 THEN 1 ELSE 0 END AS is_mult5,
                   sum(CASE WHEN c>1 THEN c ELSE 0 END) AS dup_rows,
                   sum(c) AS total_rows,
                   sum(CASE WHEN c>1 THEN 1 ELSE 0 END) AS dup_groups,
                   count(*) AS total_groups
            FROM grp GROUP BY is_mult5 ORDER BY is_mult5"""
    ).fetchdf()
    df["dup_row_rate_pct"] = (df["dup_rows"] / df["total_rows"] * 100).round(3)
    mult5[t] = df.to_dict(orient="records")
    print(t)
    print(df.to_string(index=False))
results["dup_rate_by_5s_multiple"] = mult5

# ---------- A-2-2. 수량 설명 검증 ----------
print("\n## A-2-2. 수량 설명 검증 (product_buy)")

# (a) 구매 직전 1시간 내 같은 sku 장바구니 담기 건수 vs 구매 중복 배수 교차표
cart_vs_mult = con.execute(
    f"""WITH dupgrp AS (
          SELECT client_id, timestamp, sku, count(*) AS c,
                 strptime(timestamp,'%Y-%m-%d %H:%M:%S') AS pts
          FROM read_parquet('{p("product_buy")}')
          GROUP BY client_id, timestamp, sku HAVING count(*) > 1
        ),
        cart_cnt AS (
          SELECT d.client_id, d.sku, d.pts, d.c, count(a.timestamp) AS cart_cnt_1h
          FROM dupgrp d
          LEFT JOIN read_parquet('{p("add_to_cart")}') a
            ON a.client_id = d.client_id AND a.sku = d.sku
           AND strptime(a.timestamp,'%Y-%m-%d %H:%M:%S') <= d.pts
           AND strptime(a.timestamp,'%Y-%m-%d %H:%M:%S') >= d.pts - INTERVAL 1 HOUR
          GROUP BY d.client_id, d.sku, d.pts, d.c
        )
        SELECT CASE WHEN c=2 THEN '2' WHEN c=3 THEN '3' WHEN c=4 THEN '4' ELSE '5+' END AS mult_bucket,
               CASE WHEN cart_cnt_1h=0 THEN '0' WHEN cart_cnt_1h=1 THEN '1'
                    WHEN cart_cnt_1h=2 THEN '2' WHEN cart_cnt_1h=3 THEN '3' ELSE '4+' END AS cart_bucket,
               count(*) AS n_groups
        FROM cart_cnt GROUP BY mult_bucket, cart_bucket ORDER BY mult_bucket, cart_bucket"""
).fetchdf()
print(cart_vs_mult.to_string(index=False))
results["quantity_cart_crosstab"] = cart_vs_mult.to_dict(orient="records")

# (b) 중복/비중복 구매 그룹의 가격 구간 분포 비교
price_cmp = con.execute(
    f"""WITH grp AS (
          SELECT client_id, timestamp, sku, count(*) AS c
          FROM read_parquet('{p("product_buy")}') GROUP BY client_id, timestamp, sku
        ), joined AS (
          SELECT g.c, pp.price FROM grp g JOIN read_parquet('{p("product_properties")}') pp
            ON g.sku = pp.sku
        )
        SELECT (CASE WHEN c>1 THEN '중복' ELSE '비중복' END) AS dup_flag,
               CAST(price/10 AS INT)*10 AS price_decile,
               count(*) AS n_groups
        FROM joined GROUP BY dup_flag, price_decile ORDER BY dup_flag, price_decile"""
).fetchdf()
print(price_cmp.to_string(index=False))
results["quantity_price_decile_comparison"] = price_cmp.to_dict(orient="records")

# ---------- A-2-3. 로깅 오류 설명 검증 ----------
print("\n## A-2-3. 로깅 오류 설명 검증 (일별/시간대별 중복 비율, 테이블 간 동시 발생)")
daily_dup = {}
hourly_dup = {}
for t, tgt in TARGET_COL.items():
    df_day = con.execute(
        f"""WITH grp AS (
              SELECT client_id, timestamp, {tgt}, count(*) AS c
              FROM read_parquet('{p(t)}') GROUP BY client_id, timestamp, {tgt}
            )
            SELECT date_trunc('day', strptime(timestamp,'%Y-%m-%d %H:%M:%S')) AS day,
                   sum(CASE WHEN c>1 THEN c ELSE 0 END) AS dup_rows, sum(c) AS total_rows
            FROM grp GROUP BY day ORDER BY day"""
    ).fetchdf()
    df_day["dup_rate_pct"] = (df_day["dup_rows"] / df_day["total_rows"] * 100).round(3)
    df_day.to_csv(f"data/processed/dup_rate_daily_{t}.csv", index=False)
    daily_dup[t] = {"min": float(df_day["dup_rate_pct"].min()), "max": float(df_day["dup_rate_pct"].max()),
                     "median": float(df_day["dup_rate_pct"].median())}

    df_hour = con.execute(
        f"""WITH grp AS (
              SELECT client_id, timestamp, {tgt}, count(*) AS c
              FROM read_parquet('{p(t)}') GROUP BY client_id, timestamp, {tgt}
            )
            SELECT CAST(strftime(strptime(timestamp,'%Y-%m-%d %H:%M:%S'), '%H') AS INT) AS hour,
                   sum(CASE WHEN c>1 THEN c ELSE 0 END) AS dup_rows, sum(c) AS total_rows
            FROM grp GROUP BY hour ORDER BY hour"""
    ).fetchdf()
    df_hour["dup_rate_pct"] = (df_hour["dup_rows"] / df_hour["total_rows"] * 100).round(3)
    df_hour.to_csv(f"data/processed/dup_rate_hourly_{t}.csv", index=False)
    hourly_dup[t] = {"min": float(df_hour["dup_rate_pct"].min()), "max": float(df_hour["dup_rate_pct"].max())}
    print(t, "daily dup rate range:", daily_dup[t], "| hourly dup rate range:", hourly_dup[t])
results["daily_dup_rate_summary"] = daily_dup
results["hourly_dup_rate_summary"] = hourly_dup

# 테이블 간 동시 발생: product_buy의 중복 (client_id,timestamp)가 다른 테이블에서도 중복으로 나타나는지
dup_ts_tables = {}
for t, tgt in TARGET_COL.items():
    con.execute(f"""CREATE TEMP TABLE dup_ts_{t} AS
        SELECT DISTINCT client_id, timestamp FROM (
          SELECT client_id, timestamp, {tgt}, count(*) AS c
          FROM read_parquet('{p(t)}') GROUP BY client_id, timestamp, {tgt}
        ) WHERE c > 1""")
cross = {}
pb_total = con.execute("SELECT count(*) FROM dup_ts_product_buy").fetchone()[0]
for t in ["add_to_cart", "remove_from_cart", "search_query", "page_visit"]:
    overlap = con.execute(
        f"""SELECT count(*) FROM dup_ts_product_buy p
            WHERE EXISTS (SELECT 1 FROM dup_ts_{t} o
                          WHERE o.client_id = p.client_id AND o.timestamp = p.timestamp)"""
    ).fetchone()[0]
    cross[t] = {"overlap_with_product_buy_dup_ts": overlap, "product_buy_dup_ts_total": pb_total}
    print("product_buy 중복 시각과", t, "중복 시각 겹침:", overlap, "/", pb_total)
results["cross_table_same_time_duplicates"] = cross

# ---------- A-3. 처리 선택지별 이벤트 수 ----------
print("\n## A-3. 처리 선택지별 이벤트 수")
with open("docs/audit_results.json", encoding="utf-8") as f:
    audit = json.load(f)
options = {}
for t in TARGET_COL:
    n_rows = audit["basic"][t]["n_rows"]
    n_groups = audit["exact_duplicates"][t]["total_groups"]
    options[t] = {
        "옵션1_그대로": n_rows,
        "옵션2_완전중복_1건으로_합침": n_groups,
        "옵션3_수량으로_해석_행수(quantity_field_보존)": n_groups if t == "product_buy" else None,
    }
    print(t, options[t])
results["processing_options_row_counts"] = options

with open("docs/duplicates_results_part1.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("\nwrote docs/duplicates_results_part1.json")

# ---------- 그림: 일별 중복 비율 추이 (5개 테이블) ----------
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "AppleGothic"
plt.rcParams["axes.unicode_minus"] = False

fig, axes = plt.subplots(len(TARGET_COL), 1, figsize=(11, 3 * len(TARGET_COL)), sharex=True)
for ax, t in zip(axes, TARGET_COL):
    df = pd.read_csv(f"data/processed/dup_rate_daily_{t}.csv", parse_dates=["day"])
    ax.plot(df["day"], df["dup_rate_pct"], linewidth=1)
    ax.set_title(f"{t} 일별 완전중복 비율(%)")
    ax.set_ylabel("중복 비율(%)")
    ax.grid(alpha=0.3)
axes[-1].set_xlabel("날짜")
fig.suptitle("테이블별 일별 완전중복 행 비율 추이", y=1.0, fontsize=13)
fig.tight_layout(rect=[0, 0, 1, 0.98])
fig.savefig("docs/figures/daily_duplicate_rate.png", dpi=150)
print("saved docs/figures/daily_duplicate_rate.png")

# ---------- 월 경계 패턴: 일자(day-of-month) vs 중복 비율 상관관계 ----------
print("\n## 월 경계 패턴 (day-of-month vs 중복 비율 상관관계, 마지막 부분일 제외)")
monthly_corr = {}
for t in TARGET_COL:
    df = pd.read_csv(f"data/processed/dup_rate_daily_{t}.csv", parse_dates=["day"])
    df["dom"] = df["day"].dt.day
    df = df[df["day"] < "2022-12-08"]
    corr = df.groupby(df["day"].dt.to_period("M")).apply(
        lambda g: g["dom"].corr(g["dup_rate_pct"])
    )
    monthly_corr[t] = {str(k): (None if pd.isna(v) else round(float(v), 3)) for k, v in corr.items()}
    print(t, monthly_corr[t])
results["day_of_month_vs_dup_rate_correlation"] = monthly_corr

with open("docs/duplicates_results_part1.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("updated docs/duplicates_results_part1.json with monthly pattern")

"""B. 검색어 최빈값(search_query.query)의 정체 확인. 결론은 내리지 않고 해석 후보별 근거만 정리한다."""
import json
import os

import duckdb
import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

os.makedirs("docs", exist_ok=True)
os.makedirs("data/processed", exist_ok=True)

con = duckdb.connect()
con.execute("SET threads=4")
con.execute("SET memory_limit='5GB'")
con.execute("SET preserve_insertion_order=false")

SQ = "data/raw/search_query.parquet"
results = {}

# ---------- 최빈값 실제 문자열 ----------
top_value, top_count = con.execute(
    f"""SELECT query, count(*) AS n FROM read_parquet('{SQ}')
        GROUP BY query ORDER BY n DESC LIMIT 1"""
).fetchone()
total_rows = con.execute(f"SELECT count(*) FROM read_parquet('{SQ}')").fetchone()[0]
print("최빈값:", top_value)
print("건수:", top_count, "/", total_rows, f"({top_count/total_rows*100:.2f}%)")
results["top_value"] = {"value": top_value, "count": top_count, "total_rows": total_rows,
                         "share_pct": round(top_count / total_rows * 100, 3)}

# ---------- 상위 20개 쿼리 값 ----------
top20 = con.execute(
    f"""SELECT query, count(*) AS n, count(DISTINCT client_id) AS n_clients
        FROM read_parquet('{SQ}') GROUP BY query ORDER BY n DESC LIMIT 20"""
).fetchdf()
top20["share_pct"] = (top20["n"] / total_rows * 100).round(3)
print(top20.to_string(index=False))
results["top20_queries"] = top20.to_dict(orient="records")
top20.to_csv("data/processed/search_top20_queries.csv", index=False)

# ---------- 최빈값 사용 양상 ----------
print("\n## 최빈값 사용 양상")
n_clients_top = con.execute(
    f"SELECT count(DISTINCT client_id) FROM read_parquet('{SQ}') WHERE query = ?", [top_value]
).fetchone()[0]
print("최빈값을 쓴 고유 고객 수:", n_clients_top)

# 고객별 자신의 전체 검색 중 최빈값 비중 분포
share_dist = con.execute(
    f"""WITH per_client AS (
          SELECT client_id, count(*) AS total_n,
                 sum(CASE WHEN query = ? THEN 1 ELSE 0 END) AS top_n
          FROM read_parquet('{SQ}') GROUP BY client_id
        )
        SELECT median(top_n * 1.0 / total_n) AS median_share,
               quantile_cont(top_n * 1.0 / total_n, 0.9) AS p90_share,
               sum(CASE WHEN top_n = total_n THEN 1 ELSE 0 END) AS n_clients_all_top,
               count(*) AS n_clients_with_top
        FROM per_client WHERE top_n > 0""",
    [top_value],
).fetchone()
print("최빈값 쓴 고객 중 '자신의 검색 전부가 최빈값'인 고객 수:", share_dist[2], "/", share_dist[3])
print("고객별 자기 검색 중 최빈값 비중: 중앙값=", share_dist[0], "p90=", share_dist[1])
results["usage_by_client"] = {
    "n_clients_used_top_value": n_clients_top,
    "median_share_within_own_searches": share_dist[0],
    "p90_share_within_own_searches": share_dist[1],
    "n_clients_all_searches_are_top_value": share_dist[2],
    "n_clients_with_top_value_at_least_once": share_dist[3],
}

# 일별/시간대별 분포 (전체 검색 대비)
daily = con.execute(
    f"""SELECT date_trunc('day', strptime(timestamp,'%Y-%m-%d %H:%M:%S')) AS day,
               sum(CASE WHEN query = ? THEN 1 ELSE 0 END) AS top_n, count(*) AS total_n
        FROM read_parquet('{SQ}') GROUP BY day ORDER BY day""",
    [top_value],
).fetchdf()
daily["share_pct"] = (daily["top_n"] / daily["total_n"] * 100).round(3)
daily.to_csv("data/processed/search_top_value_daily.csv", index=False)

hourly = con.execute(
    f"""SELECT CAST(strftime(strptime(timestamp,'%Y-%m-%d %H:%M:%S'), '%H') AS INT) AS hour,
               sum(CASE WHEN query = ? THEN 1 ELSE 0 END) AS top_n, count(*) AS total_n
        FROM read_parquet('{SQ}') GROUP BY hour ORDER BY hour""",
    [top_value],
).fetchdf()
hourly["share_pct"] = (hourly["top_n"] / hourly["total_n"] * 100).round(3)
hourly.to_csv("data/processed/search_top_value_hourly.csv", index=False)
print("일별 최빈값 비중 범위:", daily["share_pct"].min(), "~", daily["share_pct"].max())
print("시간대별 최빈값 비중 범위:", hourly["share_pct"].min(), "~", hourly["share_pct"].max())
results["daily_share_range_pct"] = [float(daily["share_pct"].min()), float(daily["share_pct"].max())]
results["hourly_share_range_pct"] = [float(hourly["share_pct"].min()), float(hourly["share_pct"].max())]

# 완전 중복(동일 client+동일 timestamp+최빈값) 및 30초 이내 반복 비율
dup_and_burst = con.execute(
    f"""WITH tv AS (
          SELECT client_id, strptime(timestamp,'%Y-%m-%d %H:%M:%S') AS ts
          FROM read_parquet('{SQ}') WHERE query = ?
        ), lagged AS (
          SELECT client_id, ts, ts - lag(ts) OVER (PARTITION BY client_id ORDER BY ts) AS diff
          FROM tv
        )
        SELECT count(*) AS total_top_rows,
               sum(CASE WHEN diff = INTERVAL 0 SECOND THEN 1 ELSE 0 END) AS exact_same_ts,
               sum(CASE WHEN diff > INTERVAL 0 SECOND AND diff <= INTERVAL 30 SECOND THEN 1 ELSE 0 END) AS within_30s
        FROM lagged""",
    [top_value],
).fetchone()
print("최빈값 행 중 동일시각 반복:", dup_and_burst[1], "/", dup_and_burst[0],
      "| 30초 이내 반복:", dup_and_burst[2], "/", dup_and_burst[0])
results["top_value_dup_and_burst"] = {
    "total_top_rows": dup_and_burst[0], "exact_same_ts": dup_and_burst[1], "within_30s": dup_and_burst[2],
}

# 고객 검색 순서에서 최빈값이 몇 번째에 나오는지
seq = con.execute(
    f"""WITH ranked AS (
          SELECT client_id, query,
                 row_number() OVER (PARTITION BY client_id ORDER BY timestamp) AS rn,
                 count(*) OVER (PARTITION BY client_id) AS total_n
          FROM read_parquet('{SQ}')
        )
        SELECT rn, total_n FROM ranked WHERE query = ?""",
    [top_value],
).fetchdf()
seq["rel_pos"] = (seq["rn"] - 1) / seq["total_n"].clip(lower=1)
n_first = int((seq["rn"] == 1).sum())
n_total_occurrences = len(seq)
print("최빈값이 고객의 '첫 검색'으로 나온 횟수:", n_first, "/", n_total_occurrences,
      f"({n_first/n_total_occurrences*100:.2f}%)")
print("상대적 위치(0=첫 검색,1=마지막) 분포 요약:")
print(seq["rel_pos"].describe())
results["sequence_position"] = {
    "n_first_search": n_first,
    "n_total_occurrences": n_total_occurrences,
    "first_search_share_pct": round(n_first / n_total_occurrences * 100, 3),
    "rel_pos_median": float(seq["rel_pos"].median()),
    "rel_pos_mean": float(seq["rel_pos"].mean()),
}
seq[["rn", "total_n", "rel_pos"]].to_csv("data/processed/search_top_value_sequence_position.csv", index=False)

with open("docs/search_top_value_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("\nwrote docs/search_top_value_results.json")

# ---------- 그림 ----------
plt.rcParams["font.family"] = "AppleGothic"
plt.rcParams["axes.unicode_minus"] = False

fig, axes = plt.subplots(3, 1, figsize=(11, 10))
daily["day"] = pd.to_datetime(daily["day"])
axes[0].plot(daily["day"], daily["share_pct"], linewidth=1)
axes[0].set_title("검색어 최빈값이 전체 검색에서 차지하는 비중(%) — 일별")
axes[0].set_ylabel("비중(%)")
axes[0].grid(alpha=0.3)

axes[1].bar(hourly["hour"], hourly["share_pct"])
axes[1].set_title("검색어 최빈값 비중(%) — 시간대별(0~23시)")
axes[1].set_xlabel("시(hour)")
axes[1].set_ylabel("비중(%)")
axes[1].grid(alpha=0.3)

axes[2].hist(seq["rel_pos"], bins=20)
axes[2].set_title("최빈값이 등장한 상대적 위치 분포 (0=고객의 첫 검색, 1=마지막 검색)")
axes[2].set_xlabel("상대적 위치")
axes[2].set_ylabel("빈도")
axes[2].grid(alpha=0.3)

fig.tight_layout()
fig.savefig("docs/figures/search_top_value_patterns.png", dpi=150)
print("saved docs/figures/search_top_value_patterns.png")

"""검색어 최빈값의 정체 구분: 빈 검색 / 행사 키워드 / 광고 링크 사전 채움.

00_analysis_rules.md의 원칙을 따른다(구매 관련 비율 계산 안 함, 5초 미만 순서 분석 안 함,
관측 기간 경계 유의). 처리 방침은 정하지 않고 세 해석에 대한 지지/반대 근거만 정리한다.
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
os.makedirs("data/processed", exist_ok=True)

con = duckdb.connect()
con.execute("SET threads=4")
con.execute("SET memory_limit='5GB'")
con.execute("SET preserve_insertion_order=false")

SQ = "data/raw/search_query.parquet"
PV = "data/raw/page_visit.parquet"
TOP_VALUE = "[203 242 203 203 203 203 203  59  59 203 203 203 203 203 203 240]"
TOP_VEC = np.array([203, 242, 203, 203, 203, 203, 203, 59, 59, 203, 203, 203, 203, 203, 203, 240], dtype=np.int16)

results = {}

# ---------- 1. 유사 코드 탐색 (해밍거리 1~3) ----------
print("## 1. 유사 코드 탐색")
distinct_q = con.execute(
    f"SELECT query, count(*) AS n FROM read_parquet('{SQ}') GROUP BY query"
).fetchdf()
print("전체 고유 쿼리 수:", len(distinct_q))


def parse_vec(s):
    inner = s.strip("[]")
    return np.array(inner.split(), dtype=np.int16)


vecs = np.stack(distinct_q["query"].map(parse_vec).values)
dist = (vecs != TOP_VEC).sum(axis=1)
distinct_q["hamming_dist"] = dist

similar = distinct_q[(distinct_q["hamming_dist"] >= 1) & (distinct_q["hamming_dist"] <= 3)].copy()
print("해밍거리 1~3인 유사 코드 수(고유값 기준):", len(similar))
print("해밍거리별 고유 코드 수:", similar["hamming_dist"].value_counts().sort_index().to_dict())
print("유사 코드들의 총 등장 행 수:", int(similar["n"].sum()))
results["similar_codes_summary"] = {
    "n_distinct_similar_codes": int(len(similar)),
    "by_distance": {str(k): int(v) for k, v in similar["hamming_dist"].value_counts().sort_index().items()},
    "total_rows_similar_codes": int(similar["n"].sum()),
}
similar.drop(columns=["query"]).assign(query=similar["query"]).to_csv(
    "data/processed/search_similar_codes.csv", index=False
)

# 유사 코드 리스트를 조인에 쓰기 위해 DuckDB에 직접 등록
similar_reg = similar[["query", "hamming_dist"]].copy()
con.register("similar_codes", similar_reg)

# 유사 코드 그룹의 일별 건수 (거리 1 그룹과 2~3 그룹 분리)
daily_similar = con.execute(
    f"""WITH sq AS (
          SELECT s.hamming_dist, date_trunc('day', strptime(t.timestamp,'%Y-%m-%d %H:%M:%S')) AS day
          FROM read_parquet('{SQ}') t JOIN similar_codes s ON t.query = s.query
        )
        SELECT day, CASE WHEN hamming_dist = 1 THEN 'dist1' ELSE 'dist2_3' END AS grp, count(*) AS n
        FROM sq GROUP BY day, grp ORDER BY day"""
).fetchdf()
daily_similar_pivot = daily_similar.pivot(index="day", columns="grp", values="n").fillna(0)
daily_similar_pivot.to_csv("data/processed/search_similar_codes_daily.csv")
print(daily_similar_pivot.head(3).to_string())
print(daily_similar_pivot.loc["2022-07-20":"2022-08-05"].to_string() if len(daily_similar_pivot) else "no rows")

with open("docs/search_identity_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/search_identity_results.json (중간 저장)")

# ---------- 2. 추이 모양: 최빈값 일별 건수 vs 전체 page_visit 일별 건수 ----------
print("\n## 2. 추이 모양 비교")
top_daily = pd.read_csv("data/processed/search_top_value_daily.csv", parse_dates=["day"])
pv_daily = pd.read_csv("data/processed/daily_page_visit.csv", parse_dates=["day"])
merged = top_daily[["day", "top_n"]].merge(pv_daily.rename(columns={"n": "page_visit_n"}), on="day", how="inner")
merged = merged[merged["day"] < "2022-12-08"]  # 부분일 제외 (00_analysis_rules.md)
corr = merged["top_n"].corr(merged["page_visit_n"])
print("최빈값 일별 건수 vs page_visit 일별 건수 상관계수(전체 기간):", round(corr, 3))
# 급등 이후(2022-07-28~) 구간만 상관
after = merged[merged["day"] >= "2022-07-28"]
corr_after = after["top_n"].corr(after["page_visit_n"])
print("급등 이후(07-28~) 구간 상관계수:", round(corr_after, 3))
results["trend_correlation"] = {"full_period": round(float(corr), 3), "after_jump": round(float(corr_after), 3)}

plt.rcParams["font.family"] = "AppleGothic"
plt.rcParams["axes.unicode_minus"] = False

fig, ax1 = plt.subplots(figsize=(12, 5))
ax1.plot(merged["day"], merged["top_n"], color="tab:orange", label="검색어 최빈값 일별 건수")
ax1.set_ylabel("최빈값 일별 건수", color="tab:orange")
ax1.tick_params(axis="y", labelcolor="tab:orange")
ax2 = ax1.twinx()
ax2.plot(merged["day"], merged["page_visit_n"], color="tab:blue", alpha=0.6, label="page_visit 일별 건수")
ax2.set_ylabel("page_visit 일별 건수", color="tab:blue")
ax2.tick_params(axis="y", labelcolor="tab:blue")
ax1.axvline(pd.Timestamp("2022-07-28"), color="red", linestyle="--", linewidth=1, alpha=0.7)
ax1.set_title("검색어 최빈값 일별 건수 vs page_visit 일별 건수 (빨간 점선=2022-07-28)")
ax1.set_xlabel("날짜")
fig.tight_layout()
fig.savefig("docs/figures/search_top_value_vs_pagevisit.png", dpi=150)
print("saved docs/figures/search_top_value_vs_pagevisit.png")

with open("docs/search_identity_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)

# ---------- 3. 반복 사용 ----------
print("\n## 3. 반복 사용 분포")
per_client = con.execute(
    f"""SELECT client_id, count(*) AS n FROM read_parquet('{SQ}')
        WHERE query = '{TOP_VALUE}' GROUP BY client_id"""
).fetchdf()
usage_dist = {
    "median": float(per_client["n"].median()), "p90": float(per_client["n"].quantile(0.9)),
    "p99": float(per_client["n"].quantile(0.99)), "max": int(per_client["n"].max()),
    "n_clients": int(len(per_client)),
}
print("고객당 최빈값 사용 횟수 분포:", usage_dist)
results["per_client_usage_count"] = usage_dist

same_day = con.execute(
    f"""SELECT client_id, date_trunc('day', strptime(timestamp,'%Y-%m-%d %H:%M:%S')) AS day, count(*) AS n
        FROM read_parquet('{SQ}') WHERE query = '{TOP_VALUE}'
        GROUP BY client_id, day"""
).fetchdf()
same_day_dist = {
    "median": float(same_day["n"].median()), "p90": float(same_day["n"].quantile(0.9)),
    "p99": float(same_day["n"].quantile(0.99)), "max": int(same_day["n"].max()),
    "n_client_days": int(len(same_day)),
    "n_client_days_with_1": int((same_day["n"] == 1).sum()),
    "n_client_days_with_2plus": int((same_day["n"] >= 2).sum()),
}
print("같은 날 내 반복 횟수 분포:", same_day_dist)
results["same_day_repeat_count"] = same_day_dist

with open("docs/search_identity_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)

# ---------- 4. 시작 시각: 2022-07-27~29 시간대별 건수 ----------
print("\n## 4. 시작 시각 (2022-07-27~29 시간별)")
hourly_window = con.execute(
    f"""SELECT date_trunc('hour', strptime(timestamp,'%Y-%m-%d %H:%M:%S')) AS hour_bucket,
               sum(CASE WHEN query = '{TOP_VALUE}' THEN 1 ELSE 0 END) AS top_n, count(*) AS total_n
        FROM read_parquet('{SQ}')
        WHERE timestamp >= '2022-07-27 00:00:00' AND timestamp < '2022-07-30 00:00:00'
        GROUP BY hour_bucket ORDER BY hour_bucket"""
).fetchdf()
hourly_window.to_csv("data/processed/search_top_value_hourly_window_0727_0729.csv", index=False)
print(hourly_window.to_string())
# 급변 시각: 직전 시간 대비 top_n 증가폭이 가장 큰 시점
hourly_window["diff"] = hourly_window["top_n"].diff()
jump_row = hourly_window.loc[hourly_window["diff"].idxmax()]
print("가장 큰 증가가 발생한 시간:", jump_row["hour_bucket"], "증가폭:", jump_row["diff"])
results["jump_hour"] = {"hour_bucket": str(jump_row["hour_bucket"]), "jump_size": float(jump_row["diff"])}

with open("docs/search_identity_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("\nwrote docs/search_identity_results.json (최종)")

"""봇 의심 고객 표시: 2단계 교차 극단 1,183명 후보 중 3개 신호로 재판정.

계산 범위: 2022-11-22 이전 데이터만, 구매 테이블은 쓰지 않는다(결과 정보 혼입 방지).
판정 기준은 고정이며 결과를 보고 바꾸지 않는다.
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

DB_PATH = "data/v2.duckdb"
con = duckdb.connect(DB_PATH)
con.execute("SET threads=4")
con.execute("SET memory_limit='5GB'")
con.execute("SET preserve_insertion_order=false")

CUTOFF = "2022-11-22 00:00:00"
RAW = "data/raw"
TABLES = ["product_buy", "add_to_cart", "remove_from_cart", "page_visit", "search_query"]
results = {}

# ---------- 1,183명 교차 극단 후보 재도출 ----------
# 후보 집합 자체는 2단계(07_abnormal_clients.py)에서 원본(raw) 데이터 기준으로 정의한 것을
# 그대로 쓴다(지침: "후보: 2단계에서 정의한 교차 극단 고객 1,183명" — 고정된 입력).
# 정제 계층으로 다시 구하면 중복 제거로 p99.9 문턱이 바뀌어 1,219명이 나와 수가 달라진다.
# 새 신호(1~3) 계산에는 지침대로 정제 계층을 쓴다.
print("## 교차 극단 후보 재도출 (원본 데이터, 2단계와 동일 방법)")
extreme_sets = {}
for t in TABLES:
    cnt = con.execute(
        f"SELECT client_id, count(*) AS n FROM read_parquet('{RAW}/{t}.parquet') GROUP BY client_id"
    ).fetchdf()
    p999 = cnt["n"].quantile(0.999)
    extreme_sets[t] = set(cnt.loc[cnt["n"] > p999, "client_id"].tolist())
    print(t, "p99.9=", p999, "n_extreme=", len(extreme_sets[t]))

all_extreme = set()
for s in extreme_sets.values():
    all_extreme |= s
overlap = {}
candidate_ids = []
for cid in all_extreme:
    n_tables = sum(1 for t in TABLES if cid in extreme_sets[t])
    overlap[n_tables] = overlap.get(n_tables, 0) + 1
    if n_tables >= 3:
        candidate_ids.append(cid)
print("교차 극단(3개 이상 테이블) 후보 수:", len(candidate_ids))
print("겹침 분포:", overlap)
results["candidate_overlap_distribution"] = overlap
results["n_candidates"] = len(candidate_ids)

candidate_df = pd.DataFrame({"client_id": candidate_ids})
con.register("bot_candidates", candidate_df)

# ---------- 신호 계산 (2022-11-22 이전, 구매 테이블 제외) ----------
print("\n## 신호 계산 (pre-2022-11-22, 구매 테이블 제외)")
id_list_sql = ",".join(str(c) for c in candidate_ids)

frames = []
for t in ["add_to_cart", "remove_from_cart", "page_visit", "search_query"]:
    df = con.execute(
        f"""SELECT client_id, timestamp FROM clean_{t}
            WHERE client_id IN ({id_list_sql}) AND timestamp < '{CUTOFF}'"""
    ).fetchdf()
    frames.append(df)
combined = pd.concat(frames, ignore_index=True)
combined["ts"] = pd.to_datetime(combined["timestamp"], format="%Y-%m-%d %H:%M:%S")
print("결합 이벤트(구매 제외) 행 수:", len(combined))

# 신호1: 속도 — 어느 1분이든 60건 이상
minute_counts = combined.groupby(["client_id", combined["ts"].dt.floor("min")]).size()
max_per_min = minute_counts.groupby("client_id").max()
signal1_clients = set(max_per_min[max_per_min >= 60].index)
print("신호1(속도) 해당 고객 수:", len(signal1_clients))

# 신호2: 수면 없음 — 하루 18시간대 이상 활동한 날이 3일 이상
hour_per_day = combined.groupby(["client_id", combined["ts"].dt.date])["ts"].apply(lambda s: s.dt.hour.nunique())
days_over_18 = (hour_per_day >= 18).groupby(level=0).sum()
signal2_clients = set(days_over_18[days_over_18 >= 3].index)
print("신호2(수면없음) 해당 고객 수:", len(signal2_clients))

# 신호3: 기계적 반복 — add_to_cart 20건 이상이면서 직전과 같은 sku 비율 80% 이상
atc = con.execute(
    f"""SELECT client_id, timestamp, sku FROM clean_add_to_cart
        WHERE client_id IN ({id_list_sql}) AND timestamp < '{CUTOFF}'
        ORDER BY client_id, timestamp, sku"""
).fetchdf()
atc["ts"] = pd.to_datetime(atc["timestamp"], format="%Y-%m-%d %H:%M:%S")
atc = atc.sort_values(["client_id", "ts", "sku"])
atc["prev_sku"] = atc.groupby("client_id")["sku"].shift(1)
atc["is_repeat"] = atc["sku"] == atc["prev_sku"]
atc_stats = atc.groupby("client_id").agg(n_adds=("sku", "size"), repeat_rate=("is_repeat", "mean"))
signal3_clients = set(atc_stats[(atc_stats["n_adds"] >= 20) & (atc_stats["repeat_rate"] >= 0.8)].index)
print("신호3(기계적반복) 해당 고객 수:", len(signal3_clients))

results["signal_counts"] = {
    "속도": len(signal1_clients), "수면없음": len(signal2_clients), "기계적반복": len(signal3_clients),
}

# ---------- 판정: 3개 중 2개 이상 ----------
signal_count_per_client = {}
for cid in candidate_ids:
    n_signals = (cid in signal1_clients) + (cid in signal2_clients) + (cid in signal3_clients)
    signal_count_per_client[cid] = n_signals

bot_clients = [cid for cid, n in signal_count_per_client.items() if n >= 2]
print("\n최종 봇 의심 제외 인원(2개 이상 신호):", len(bot_clients))
results["n_bot_excluded"] = len(bot_clients)

dist = pd.Series(signal_count_per_client).value_counts().sort_index()
print("신호 개수별 고객 수 분포:", dist.to_dict())
results["signal_count_distribution"] = {str(k): int(v) for k, v in dist.items()}

# 봇 명단 저장 (내부용, git 제외 폴더)
pd.DataFrame({"client_id": list(signal_count_per_client.keys()),
              "n_signals": list(signal_count_per_client.values())}).assign(
    is_bot=lambda d: d["client_id"].isin(bot_clients)
).to_csv("data/bot_flags.csv", index=False)

con.execute("CREATE OR REPLACE TABLE bot_clients (client_id BIGINT)")
if bot_clients:
    con.executemany("INSERT INTO bot_clients VALUES (?)", [(int(c),) for c in bot_clients])
print("bot_clients 테이블 저장 완료 (DuckDB), 행 수:", len(bot_clients))

with open("docs/bot_flags_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/bot_flags_results.json")

# ---------- 그림: 1,183명의 신호 개수 히스토그램 ----------
plt.rcParams["font.family"] = "AppleGothic"
plt.rcParams["axes.unicode_minus"] = False
fig, ax = plt.subplots(figsize=(7, 5))
counts = [signal_count_per_client[c] for c in candidate_ids]
bins = np.arange(-0.5, 4.5, 1)
ax.hist(counts, bins=bins, rwidth=0.6, color="steelblue")
ax.axvline(1.5, color="red", linestyle="--", label="판정 기준(2개 이상 = 봇 의심)")
ax.set_xticks([0, 1, 2, 3])
ax.set_xlabel("해당하는 신호 개수(0~3)")
ax.set_ylabel("고객 수")
ax.set_title(f"교차 극단 후보 {len(candidate_ids)}명의 봇 의심 신호 개수 분포")
ax.legend()
fig.tight_layout()
fig.savefig("docs/figures/bot_signal_distribution.png", dpi=150)
print("saved docs/figures/bot_signal_distribution.png")

con.close()

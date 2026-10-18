"""C. 비정상 고객(봇 의심 등) 정밀 확인. 제외 여부는 결정하지 않고 패턴 근거와 영향만 정리한다."""
import json
import os
import sys

import duckdb
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from _pseudonym import pseudonymize  # noqa: E402

os.makedirs("docs", exist_ok=True)
os.makedirs("data/processed", exist_ok=True)

con = duckdb.connect()
con.execute("SET threads=4")
con.execute("SET memory_limit='5GB'")
con.execute("SET preserve_insertion_order=false")

RAW = "data/raw"
TABLES = ["product_buy", "add_to_cart", "remove_from_cart", "page_visit", "search_query"]
TARGET_COL = {"product_buy": "sku", "add_to_cart": "sku", "remove_from_cart": "sku",
              "page_visit": "url", "search_query": "query"}


def p(t):
    return f"{RAW}/{t}.parquet"


results = {}
cnt_df_by_table = {}

# ---------- C-1. 규모 ----------
print("## C-1. 극단 고객 규모")
extreme_sets = {}
concentration = {}
for t in TABLES:
    cnt_df = con.execute(
        f"SELECT client_id, count(*) AS n FROM read_parquet('{p(t)}') GROUP BY client_id"
    ).fetchdf()
    cnt_df_by_table[t] = cnt_df
    p99 = cnt_df["n"].quantile(0.99)
    p999 = cnt_df["n"].quantile(0.999)
    over_p999 = cnt_df[cnt_df["n"] > p999]
    over_10x_p99 = cnt_df[cnt_df["n"] > p99 * 10]
    extreme_sets[t] = {
        "over_p999": set(over_p999["client_id"].tolist()),
        "over_10x_p99": set(over_10x_p99["client_id"].tolist()),
    }
    total_events = cnt_df["n"].sum()
    cnt_sorted = cnt_df.sort_values("n", ascending=False)
    n_clients = len(cnt_sorted)
    top_shares = {}
    for pct, label in [(0.0001, "top0.01pct"), (0.001, "top0.1pct"), (0.01, "top1pct")]:
        k = max(1, int(round(n_clients * pct)))
        top_shares[label] = {
            "n_clients": k,
            "event_share_pct": round(cnt_sorted["n"].iloc[:k].sum() / total_events * 100, 3),
        }
    concentration[t] = top_shares
    results.setdefault("extreme_counts", {})[t] = {
        "p99": float(p99), "p999": float(p999),
        "n_over_p999": len(over_p999), "n_over_10x_p99": len(over_10x_p99),
        "total_clients": n_clients,
    }
    print(t, "p99=", p99, "p99.9=", p999, "n>p99.9=", len(over_p999), "n>10x p99=", len(over_10x_p99))
    print("  concentration:", top_shares)
results["event_concentration"] = concentration

# 겹침: over_p999 기준으로 여러 테이블에서 동시에 극단인 고객 수
all_extreme_p999 = set()
for t in TABLES:
    all_extreme_p999 |= extreme_sets[t]["over_p999"]
overlap_count = {}
for cid in all_extreme_p999:
    n_tables = sum(1 for t in TABLES if cid in extreme_sets[t]["over_p999"])
    overlap_count[n_tables] = overlap_count.get(n_tables, 0) + 1
print("p99.9 초과 고객이 몇 개 테이블에서 동시에 극단인지 분포:", overlap_count)
results["extreme_overlap_across_tables"] = overlap_count

with open("docs/abnormal_clients_part1.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/abnormal_clients_part1.json (중간 저장)")

# ---------- C-2. 패턴 (page_visit 상위 20명 + 다른 테이블 각 상위 5명) ----------
print("\n## C-2. 패턴 분석 대상 고객 선정")
selected = []  # (client_id, source_table)
top20_pv = cnt_df_by_table["page_visit"].sort_values("n", ascending=False).head(20)
for cid in top20_pv["client_id"]:
    selected.append((int(cid), "page_visit"))
for t in ["product_buy", "add_to_cart", "remove_from_cart", "search_query"]:
    top5 = cnt_df_by_table[t].sort_values("n", ascending=False).head(5)
    for cid in top5["client_id"]:
        selected.append((int(cid), t))
print("선정된 (고객,소속테이블) 수:", len(selected))

all_client_ids = sorted(set(cid for cid, _ in selected))
pseudo_map = dict(zip(all_client_ids, pseudonymize(all_client_ids)))

# 각 테이블에서 선정 고객들의 전체 이벤트를 한 번에 추출 (클라이언트별 반복 스캔 방지)
id_list_sql = ",".join(str(c) for c in all_client_ids)
events_by_table = {}
for t in TABLES:
    tgt = TARGET_COL[t]
    df = con.execute(
        f"""SELECT client_id, timestamp, {tgt} AS target
            FROM read_parquet('{p(t)}') WHERE client_id IN ({id_list_sql})"""
    ).fetchdf()
    df["ts"] = pd.to_datetime(df["timestamp"], format="%Y-%m-%d %H:%M:%S")
    events_by_table[t] = df
    print(t, "추출된 행 수:", len(df))

presence = {t: set(events_by_table[t]["client_id"].unique()) for t in TABLES}

rows = []
for cid, src_table in selected:
    df = events_by_table[src_table]
    sub = df[df["client_id"] == cid].sort_values("ts")
    total_events = len(sub)
    active_days = sub["ts"].dt.date.nunique()
    avg_per_active_day = total_events / active_days if active_days else None

    minute_counts = sub.groupby(sub["ts"].dt.floor("min")).size()
    hour_counts_abs = sub.groupby(sub["ts"].dt.floor("h")).size()
    max_per_min = int(minute_counts.max()) if len(minute_counts) else 0
    max_per_hour = int(hour_counts_abs.max()) if len(hour_counts_abs) else 0

    gaps = sub["ts"].diff().dt.total_seconds().dropna()
    gap_median = float(gaps.median()) if len(gaps) else None
    gap_cv = float(gaps.std() / gaps.mean()) if len(gaps) and gaps.mean() > 0 else None

    repeat_rate = float((sub["target"] == sub["target"].shift(1)).mean()) if total_events > 1 else None
    distinct_targets = sub["target"].nunique()

    hour_of_day = sub["ts"].dt.hour
    share_0_6 = float(((hour_of_day >= 0) & (hour_of_day < 6)).mean())
    n_distinct_hours_active = hour_of_day.nunique()

    rows.append({
        "고객": pseudo_map[cid], "소속테이블": src_table,
        "총이벤트수": total_events, "활동일수": active_days,
        "활동일평균이벤트수": round(avg_per_active_day, 2) if avg_per_active_day else None,
        "1분최대이벤트": max_per_min, "1시간최대이벤트": max_per_hour,
        "간격중앙값(초)": gap_median, "간격변동계수": round(gap_cv, 3) if gap_cv is not None else None,
        "직전동일대상반복률": round(repeat_rate, 3) if repeat_rate is not None else None,
        "고유대상수": int(distinct_targets),
        "새벽0_6시비중": round(share_0_6, 3),
        "활동시간대수(0_23)": int(n_distinct_hours_active),
        "product_buy등장": cid in presence["product_buy"],
        "add_to_cart등장": cid in presence["add_to_cart"],
        "remove_from_cart등장": cid in presence["remove_from_cart"],
        "page_visit등장": cid in presence["page_visit"],
        "search_query등장": cid in presence["search_query"],
    })

pattern_df = pd.DataFrame(rows)
pattern_df.to_csv("data/processed/abnormal_clients_pattern.csv", index=False)
print(pattern_df.to_string(index=False))
results["pattern_table"] = pattern_df.to_dict(orient="records")

# ---------- C-3. 그림 ----------
plt.rcParams["font.family"] = "AppleGothic"
plt.rcParams["axes.unicode_minus"] = False

# 활동 타임라인: 상위 3명(총 이벤트 수 기준) 시간대 x 날짜 히트맵
top3 = pattern_df.sort_values("총이벤트수", ascending=False).head(3)
fig, axes = plt.subplots(1, 3, figsize=(18, 5))
for ax, (_, row) in zip(axes, top3.iterrows()):
    src = row["소속테이블"]
    pseudo = row["고객"]
    cid = [c for c, pn in pseudo_map.items() if pn == pseudo][0]
    sub = events_by_table[src]
    sub = sub[sub["client_id"] == cid].copy()
    sub["date"] = sub["ts"].dt.date
    sub["hour"] = sub["ts"].dt.hour
    pivot = sub.groupby(["date", "hour"]).size().unstack(fill_value=0)
    im = ax.imshow(pivot.values, aspect="auto", cmap="viridis")
    ax.set_title(f"{pseudo} ({src})\n활동 시간대 x 날짜")
    ax.set_xlabel("시(hour)")
    ax.set_ylabel("날짜 인덱스")
    fig.colorbar(im, ax=ax, label="이벤트 수")
fig.tight_layout()
fig.savefig("docs/figures/top3_activity_heatmap.png", dpi=150)
print("saved docs/figures/top3_activity_heatmap.png")

# 패턴 비교: 상위 고객(page_visit) vs 일반 고객(중앙값 근처 1,000명) 이벤트 간격 분포
pv_cnt = cnt_df_by_table["page_visit"]
median_n = pv_cnt["n"].median()
near_median = pv_cnt[(pv_cnt["n"] >= median_n - 1) & (pv_cnt["n"] <= median_n + 1)]
sample_ids = near_median["client_id"].sample(n=min(1000, len(near_median)), random_state=42).tolist()
sample_id_sql = ",".join(str(int(c)) for c in sample_ids)
normal_events = con.execute(
    f"""SELECT client_id, timestamp FROM read_parquet('{p("page_visit")}')
        WHERE client_id IN ({sample_id_sql})"""
).fetchdf()
normal_events["ts"] = pd.to_datetime(normal_events["timestamp"], format="%Y-%m-%d %H:%M:%S")
normal_gaps = normal_events.sort_values(["client_id", "ts"]).groupby("client_id")["ts"].diff().dt.total_seconds().dropna()

top_pv_events = events_by_table["page_visit"]
top_gaps = top_pv_events.sort_values(["client_id", "ts"]).groupby("client_id")["ts"].diff().dt.total_seconds().dropna()

fig, ax = plt.subplots(figsize=(9, 5))
bins = np.logspace(0, 7, 50)
ax.hist(normal_gaps.clip(lower=1), bins=bins, density=True, alpha=0.5, label=f"일반 고객 표본(n={len(sample_ids)}, 중앙값 근처)")
ax.hist(top_gaps.clip(lower=1), bins=bins, density=True, alpha=0.5, label="page_visit 상위 20명")
ax.set_xscale("log")
ax.set_xlabel("연속 이벤트 간격(초, 로그축)")
ax.set_ylabel("밀도")
ax.set_title("이벤트 간격 분포 비교: page_visit 상위 고객 vs 일반 고객 표본")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig("docs/figures/gap_distribution_comparison.png", dpi=150)
print("saved docs/figures/gap_distribution_comparison.png")

results["normal_sample_gap_median_sec"] = float(normal_gaps.median())
results["top_clients_gap_median_sec"] = float(top_gaps.median())

with open("docs/abnormal_clients_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("\nwrote docs/abnormal_clients_results.json")

"""스냅샷 설계: 기준일별 모집단과(학습 기준일만) 결과 라벨.

검증(11-07)·최종평가(11-23) 기준일은 모집단 인원만 계산하고 구매 결과는
절대 계산/저장하지 않는다(00_analysis_rules.md 7번).
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
VALIDATION_DATE = "2022-11-07"
FINAL_DATE = "2022-11-23"
ALL_DATES = TRAINING_DATES + [VALIDATION_DATE, FINAL_DATE]

EVENT_TABLES = ["clean_product_buy", "clean_add_to_cart", "clean_remove_from_cart",
                 "clean_page_visit", "clean_search_query"]

SAMPLE_TARGET_PER_DATE = 100_000  # 표본 상한(기준): 처리 가능한 규모로 제한, 학습 기준일에만 적용
SEED = 42

results = {"population": {}, "training_outcome": {}}


def shift_days(date_str, days):
    return (pd.Timestamp(date_str) + pd.Timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


# ---------- 모집단: 기준일 직전 30일 활동 고객, 봇 제외 ----------
print("## 모집단 계산 (전체 7개 기준일)")
for d in ALL_DATES:
    win_start = shift_days(d, -30)
    win_end = shift_days(d, 0)
    union_sql = " UNION ALL ".join(
        f"SELECT client_id FROM {t} WHERE timestamp >= '{win_start}' AND timestamp < '{win_end}'"
        for t in EVENT_TABLES
    )
    con.execute(f"""
        CREATE OR REPLACE TABLE pop_{d.replace('-', '')} AS
        SELECT DISTINCT client_id FROM ({union_sql}) u
        WHERE client_id NOT IN (SELECT client_id FROM bot_clients)
    """)
    n = con.execute(f"SELECT count(*) FROM pop_{d.replace('-', '')}").fetchone()[0]
    results["population"][d] = n
    print(d, "모집단 인원:", n)

with open("docs/snapshot_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/snapshot_results.json (중간 저장)")

# ---------- 학습 기준일: 결과 라벨 + 표본 ----------
print("\n## 학습 기준일 결과 라벨 (구매 14일 이내)")
training_frames = []
for d in TRAINING_DATES:
    tag = d.replace("-", "")
    out_start = shift_days(d, 0)
    out_end = shift_days(d, 14)
    con.execute(f"""
        CREATE OR REPLACE TABLE outcome_{tag} AS
        SELECT p.client_id,
               CASE WHEN b.client_id IS NOT NULL THEN 1 ELSE 0 END AS outcome
        FROM pop_{tag} p
        LEFT JOIN (
            SELECT DISTINCT client_id FROM clean_product_buy
            WHERE timestamp >= '{out_start}' AND timestamp < '{out_end}'
        ) b ON p.client_id = b.client_id
    """)
    df = con.execute(f"SELECT client_id, outcome FROM outcome_{tag}").fetchdf()
    n = len(df)
    n_pos = int(df["outcome"].sum())
    rate = n_pos / n
    results["training_outcome"][d] = {"n_population": n, "n_purchasers": n_pos, "purchase_rate": round(rate, 5)}
    print(d, "모집단:", n, "구매자:", n_pos, "구매율:", round(rate * 100, 3), "%")

    # 표본: 전체가 기준 이하면 그대로, 넘으면 구매여부 층화 무작위 표본(seed=42)
    if n > SAMPLE_TARGET_PER_DATE:
        frac = SAMPLE_TARGET_PER_DATE / n
        sampled = df.groupby("outcome", group_keys=False).apply(
            lambda g: g.sample(frac=frac, random_state=SEED)
        )
        results["training_outcome"][d]["sampled"] = True
        results["training_outcome"][d]["sample_size"] = len(sampled)
        results["training_outcome"][d]["sample_method"] = "구매여부 층화 무작위 표본, seed=42"
    else:
        sampled = df
        results["training_outcome"][d]["sampled"] = False
        results["training_outcome"][d]["sample_size"] = len(sampled)

    sampled = sampled.copy()
    sampled["reference_date"] = d
    training_frames.append(sampled)
    print("  표본 크기:", len(sampled), "(샘플링 여부:", results["training_outcome"][d]["sampled"], ")")

training_snapshot = pd.concat(training_frames, ignore_index=True)
print("\n학습 스냅샷 전체 행 수:", len(training_snapshot),
      "(같은 고객이 여러 기준일에 중복 등장할 수 있음)")
print("고유 고객 수:", training_snapshot["client_id"].nunique())
results["training_snapshot_total_rows"] = len(training_snapshot)
results["training_snapshot_unique_clients"] = int(training_snapshot["client_id"].nunique())

con.register("training_snapshot_df", training_snapshot)
con.execute("CREATE OR REPLACE TABLE training_snapshot AS SELECT * FROM training_snapshot_df")
print("training_snapshot 테이블 저장 완료")

with open("docs/snapshot_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/snapshot_results.json (최종)")
con.close()

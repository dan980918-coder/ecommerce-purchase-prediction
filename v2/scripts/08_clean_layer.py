"""정제 계층 구축: 완전 중복 제거 + 검색 기본값 분리.

이후 모든 스크립트(09~12)는 v2/data/v2.duckdb의 clean_* 테이블/뷰만 쓴다.
v2/data/는 git 제외 대상이라 이 DB 파일은 커밋되지 않는다.
"""
import json
import os

import duckdb

os.makedirs("docs", exist_ok=True)
os.makedirs("data", exist_ok=True)

DB_PATH = "data/v2.duckdb"
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)  # 재실행 시 처음부터 다시 만든다(재현성)

con = duckdb.connect(DB_PATH)
con.execute("SET threads=4")
con.execute("SET memory_limit='5GB'")
con.execute("SET preserve_insertion_order=false")

RAW = "data/raw"
EVENT_TABLES = ["product_buy", "add_to_cart", "remove_from_cart", "page_visit", "search_query"]
TOP_VALUE = "[203 242 203 203 203 203 203  59  59 203 203 203 203 203 203 240]"

results = {}

# ---------- 1. 완전 중복 제거 ----------
print("## 1. 완전 중복 제거")
for t in EVENT_TABLES:
    before = con.execute(f"SELECT count(*) FROM read_parquet('{RAW}/{t}.parquet')").fetchone()[0]
    con.execute(f"CREATE OR REPLACE TABLE clean_{t} AS SELECT DISTINCT * FROM read_parquet('{RAW}/{t}.parquet')")
    after = con.execute(f"SELECT count(*) FROM clean_{t}").fetchone()[0]
    results[t] = {"before": before, "after": after, "removed": before - after,
                  "removed_pct": round((before - after) / before * 100, 3)}
    print(t, results[t])

# product_properties는 중복이 없었음(1단계에서 확인) — 원본 그대로 사용, 복제하지 않음
con.execute(f"CREATE OR REPLACE VIEW clean_product_properties AS SELECT * FROM read_parquet('{RAW}/product_properties.parquet')")

# ---------- 2. 검색 기본값 분리 ----------
print("\n## 2. 검색 기본값 분리")
con.execute(
    f"CREATE OR REPLACE VIEW clean_search_query_real AS "
    f"SELECT * FROM clean_search_query WHERE query <> '{TOP_VALUE}'"
)
con.execute(
    f"CREATE OR REPLACE VIEW clean_search_query_default AS "
    f"SELECT * FROM clean_search_query WHERE query = '{TOP_VALUE}'"
)
n_default = con.execute("SELECT count(*) FROM clean_search_query_default").fetchone()[0]
n_real = con.execute("SELECT count(*) FROM clean_search_query_real").fetchone()[0]
n_total_clean_search = con.execute("SELECT count(*) FROM clean_search_query").fetchone()[0]
print("검색 기본값 행 수:", n_default, "/ 실제 검색 행 수:", n_real, "/ 정제 후 전체:", n_total_clean_search)
results["search_default_split"] = {"default_rows": n_default, "real_rows": n_real, "total_clean": n_total_clean_search}

with open("docs/cleaning_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("\nwrote docs/cleaning_results.json")
con.close()
print("saved data/v2.duckdb")

"""모든 테이블의 모든 컬럼에 대한 카탈로그 생성: 자료형/결측률/고유값 수/대표 분포."""
import json

import duckdb

con = duckdb.connect()
con.execute("SET threads=4")
con.execute("SET memory_limit='5GB'")
con.execute("SET preserve_insertion_order=false")

TABLES = {
    "product_buy": ["client_id", "timestamp", "sku"],
    "add_to_cart": ["client_id", "timestamp", "sku"],
    "remove_from_cart": ["client_id", "timestamp", "sku"],
    "page_visit": ["client_id", "timestamp", "url"],
    "search_query": ["client_id", "timestamp", "query"],
    "product_properties": ["sku", "category", "price", "name"],
}

catalog = {}
for table, cols in TABLES.items():
    path = f"data/raw/{table}.parquet"
    n_total = con.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()[0]
    dtypes = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchdf()
    catalog[table] = {"n_rows": n_total, "columns": {}}
    for col in cols:
        dtype = dtypes.loc[dtypes["column_name"] == col, "column_type"].iloc[0]
        n_null = con.execute(
            f"SELECT count(*) - count({col}) FROM read_parquet('{path}')"
        ).fetchone()[0]
        n_distinct = con.execute(
            f"SELECT count(DISTINCT {col}) FROM read_parquet('{path}')"
        ).fetchone()[0]
        if col == "timestamp":
            top = con.execute(
                f"""SELECT min({col}) AS v, max({col}) AS v2 FROM read_parquet('{path}')"""
            ).fetchdf()
            sample_repr = f"min={top['v'][0]}, max={top['v2'][0]} (YYYY-MM-DD HH:MM:SS 문자열)"
        elif col in ("query", "name"):
            top = con.execute(
                f"""SELECT {col}, count(*) c FROM read_parquet('{path}')
                    GROUP BY {col} ORDER BY c DESC LIMIT 3"""
            ).fetchdf()
            sample_repr = "상위 반복값: " + "; ".join(
                f"{r[col][:40]}... (n={r['c']})" for _, r in top.iterrows()
            )
        else:
            top = con.execute(
                f"""SELECT {col}, count(*) c FROM read_parquet('{path}')
                    GROUP BY {col} ORDER BY c DESC LIMIT 5"""
            ).fetchdf()
            stats = con.execute(
                f"SELECT min({col}), max({col}), avg({col}) FROM read_parquet('{path}')"
            ).fetchone()
            sample_repr = (
                f"min={stats[0]}, max={stats[1]}, avg={stats[2]:.2f}; "
                f"최빈값 top5: {top[col].tolist()} (counts={top['c'].tolist()})"
            )
        catalog[table]["columns"][col] = {
            "dtype": str(dtype),
            "n_null": int(n_null),
            "null_rate_pct": round(n_null / n_total * 100, 4) if n_total else None,
            "n_distinct": int(n_distinct),
            "n_distinct_rate_pct": round(n_distinct / n_total * 100, 4) if n_total else None,
            "repr": sample_repr,
        }
        print(table, col, "done")

with open("docs/variable_catalog_raw.json", "w", encoding="utf-8") as f:
    json.dump(catalog, f, ensure_ascii=False, indent=2)
print("wrote docs/variable_catalog_raw.json")

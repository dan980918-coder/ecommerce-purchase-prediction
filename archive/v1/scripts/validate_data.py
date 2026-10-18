"""Phase 1 - 8.2 파일 구조 검사.

DuckDB lazy scan으로 각 Parquet 파일의 스키마, 행/열 수, 결측값,
고유값, PK 후보, 중복 행 수를 검사한다. 전체 데이터를 Pandas로
메모리에 올리지 않는다.
"""

import csv
import json
from pathlib import Path

import duckdb

RAW_DIR = Path("data/raw/synerise_dataset")
REPORT_DIR = Path("reports")
FILES = [
    "product_buy.parquet",
    "add_to_cart.parquet",
    "remove_from_cart.parquet",
    "page_visit.parquet",
    "search_query.parquet",
    "product_properties.parquet",
]

PK_CANDIDATES = {
    "product_buy.parquet": ["client_id", "timestamp", "sku"],
    "add_to_cart.parquet": ["client_id", "timestamp", "sku"],
    "remove_from_cart.parquet": ["client_id", "timestamp", "sku"],
    "page_visit.parquet": ["client_id", "timestamp", "url"],
    "search_query.parquet": ["client_id", "timestamp"],
    "product_properties.parquet": ["sku"],
}


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


def main() -> None:
    con = duckdb.connect()
    dictionary_rows = []
    summary_rows = []

    for fname in FILES:
        path = RAW_DIR / fname
        file_size = path.stat().st_size
        rel = con.sql(f"SELECT * FROM read_parquet('{path.as_posix()}')")

        row_count = con.sql(f"SELECT COUNT(*) FROM read_parquet('{path.as_posix()}')").fetchone()[0]
        schema = con.sql(f"DESCRIBE SELECT * FROM read_parquet('{path.as_posix()}')").fetchall()
        col_count = len(schema)

        print(f"\n{'=' * 80}\n{fname}\n{'=' * 80}")
        print(f"file_size = {human_size(file_size)} ({file_size} bytes)")
        print(f"row_count = {row_count:,}")
        print(f"col_count = {col_count}")
        print("columns:")
        for col_name, col_type, *_ in schema:
            print(f"  - {col_name}: {col_type}")

        # 첫 5행 / 마지막 5행
        first5 = con.sql(f"SELECT * FROM read_parquet('{path.as_posix()}') LIMIT 5").df()
        print("\n[first 5 rows]")
        print(first5.to_string(index=False))

        # 마지막 5행: rowid 기반 접근이 없으므로 전체 행수 - 5 offset 사용
        offset = max(row_count - 5, 0)
        last5 = con.sql(
            f"SELECT * FROM read_parquet('{path.as_posix()}') LIMIT 5 OFFSET {offset}"
        ).df()
        print("\n[last 5 rows]")
        print(last5.to_string(index=False))

        # 결측값, 고유값
        col_names = [c[0] for c in schema]
        null_exprs = ", ".join(
            f"SUM(CASE WHEN \"{c}\" IS NULL THEN 1 ELSE 0 END) AS null_{i}"
            for i, c in enumerate(col_names)
        )
        distinct_exprs = ", ".join(
            f"COUNT(DISTINCT \"{c}\") AS distinct_{i}" for i, c in enumerate(col_names)
        )
        null_res = con.sql(
            f"SELECT {null_exprs} FROM read_parquet('{path.as_posix()}')"
        ).fetchone()
        distinct_res = con.sql(
            f"SELECT {distinct_exprs} FROM read_parquet('{path.as_posix()}')"
        ).fetchone()

        print("\n[null / distinct counts]")
        col_stats = []
        for i, c in enumerate(col_names):
            nulls = null_res[i]
            distinct = distinct_res[i]
            print(f"  - {c}: nulls={nulls:,} ({nulls / row_count:.4%}), distinct={distinct:,}")
            col_stats.append(
                {
                    "file": fname,
                    "column": c,
                    "dtype": str(schema[i][1]),
                    "null_count": nulls,
                    "null_pct": round(nulls / row_count, 6) if row_count else None,
                    "distinct_count": distinct,
                }
            )
        dictionary_rows.extend(col_stats)

        # 중복 행 수 (전체 컬럼 기준)
        col_list = ", ".join(f'"{c}"' for c in col_names)
        dup_count = con.sql(
            f"""
            SELECT COUNT(*) FROM (
                SELECT {col_list}, COUNT(*) AS cnt
                FROM read_parquet('{path.as_posix()}')
                GROUP BY {col_list}
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]

        # PK 후보 중복 검사
        pk_cols = PK_CANDIDATES.get(fname, col_names)
        pk_col_list = ", ".join(f'"{c}"' for c in pk_cols if c in col_names)
        pk_distinct = con.sql(
            f"SELECT COUNT(DISTINCT ({pk_col_list})) FROM read_parquet('{path.as_posix()}')"
        ).fetchone()[0]

        print(f"\n[duplicate full rows] {dup_count:,}")
        print(f"[PK candidate {pk_cols}] distinct_combo={pk_distinct:,} / row_count={row_count:,} -> unique={pk_distinct == row_count}")

        summary_rows.append(
            {
                "file": fname,
                "file_size_bytes": file_size,
                "file_size_human": human_size(file_size),
                "row_count": row_count,
                "col_count": col_count,
                "columns": json.dumps(col_names, ensure_ascii=False),
                "duplicate_full_rows": dup_count,
                "pk_candidate": json.dumps(pk_cols, ensure_ascii=False),
                "pk_candidate_distinct_combo": pk_distinct,
                "pk_candidate_is_unique": pk_distinct == row_count,
            }
        )

    REPORT_DIR.mkdir(exist_ok=True)

    with open(REPORT_DIR / "phase1_event_summary.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    with open(REPORT_DIR / "phase1_data_dictionary.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(dictionary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(dictionary_rows)

    print(f"\n\nSaved: {REPORT_DIR / 'phase1_event_summary.csv'}")
    print(f"Saved: {REPORT_DIR / 'phase1_data_dictionary.csv'}")


if __name__ == "__main__":
    main()

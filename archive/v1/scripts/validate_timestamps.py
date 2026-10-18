"""Phase 1 - 8.3 타임스탬프 검증.

이벤트 테이블(timestamp 컬럼 존재)에 대해 TRY_CAST로 파싱 오류를 먼저 확인하고,
MIN/MAX/행수/고유 client 수, 기준일(2023-08-05) 이후 비율을 계산한다.
"""

import csv
from pathlib import Path

import duckdb

RAW_DIR = Path("data/raw/synerise_dataset")
REPORT_DIR = Path("reports")
CUTOFF = "2023-08-05 00:00:00"
TODAY = "2026-08-05"

EVENT_FILES = [
    "product_buy.parquet",
    "add_to_cart.parquet",
    "remove_from_cart.parquet",
    "page_visit.parquet",
    "search_query.parquet",
]


def main() -> None:
    con = duckdb.connect()
    rows = []

    for fname in EVENT_FILES:
        path = (RAW_DIR / fname).as_posix()
        event_type = fname.replace(".parquet", "")

        row_count = con.sql(f"SELECT COUNT(*) FROM read_parquet('{path}')").fetchone()[0]

        parse_fail = con.sql(
            f"""
            SELECT COUNT(*) FROM read_parquet('{path}')
            WHERE TRY_CAST(timestamp AS TIMESTAMP) IS NULL
            """
        ).fetchone()[0]

        stats = con.sql(
            f"""
            SELECT
                MIN(TRY_CAST(timestamp AS TIMESTAMP)) AS min_ts,
                MAX(TRY_CAST(timestamp AS TIMESTAMP)) AS max_ts,
                COUNT(DISTINCT client_id) AS unique_clients,
                SUM(CASE WHEN TRY_CAST(timestamp AS TIMESTAMP) >= TIMESTAMP '{CUTOFF}' THEN 1 ELSE 0 END) AS rows_after_cutoff
            FROM read_parquet('{path}')
            """
        ).fetchone()

        min_ts, max_ts, unique_clients, rows_after_cutoff = stats
        pct_after_cutoff = rows_after_cutoff / row_count * 100 if row_count else 0
        observation_days = (max_ts - min_ts).days if (min_ts and max_ts) else None

        print(f"\n{event_type}")
        print(f"  row_count           = {row_count:,}")
        print(f"  parse_fail_count    = {parse_fail:,}")
        print(f"  min_timestamp       = {min_ts}")
        print(f"  max_timestamp       = {max_ts}")
        print(f"  observation_days    = {observation_days}")
        print(f"  unique_clients      = {unique_clients:,}")
        print(f"  rows_after_cutoff   = {rows_after_cutoff:,} ({pct_after_cutoff:.4f}%)")
        print(f"  cutoff              = {CUTOFF} (recent-3-years threshold; today={TODAY})")

        rows.append(
            {
                "event_type": event_type,
                "row_count": row_count,
                "parse_fail_count": parse_fail,
                "min_timestamp": min_ts,
                "max_timestamp": max_ts,
                "observation_days": observation_days,
                "unique_clients": unique_clients,
                "rows_after_cutoff": rows_after_cutoff,
                "pct_after_cutoff": round(pct_after_cutoff, 6),
                "cutoff_date": CUTOFF,
            }
        )

    REPORT_DIR.mkdir(exist_ok=True)
    with open(REPORT_DIR / "phase1_timestamp_summary.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nSaved: {REPORT_DIR / 'phase1_timestamp_summary.csv'}")


if __name__ == "__main__":
    main()

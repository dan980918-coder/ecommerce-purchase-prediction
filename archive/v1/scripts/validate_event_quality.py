"""Phase 1 - 8.6 이벤트 품질 검사.

중복/결측/타임스탬프 파싱 오류는 8.2, 8.3에서 이미 확인했으므로 여기서는
다음을 새로 계산한다:
  - 고객별 이벤트 수 분포 및 상위 이상치 고객
  - 동일 고객(+상품)의 짧은 시간(5초 이내) 반복 이벤트(버스트) 수
  - 고객별 전체 이벤트 통합 기준 첫/마지막 행동, 관찰일 수
  - 이벤트 타입별 일별 이벤트량 분포 및 특이 날짜
"""

import csv
from pathlib import Path

import duckdb

RAW_DIR = Path("data/raw/synerise_dataset")
REPORT_DIR = Path("reports")

EVENT_TABLES = {
    "product_buy": ("product_buy.parquet", "sku"),
    "add_to_cart": ("add_to_cart.parquet", "sku"),
    "remove_from_cart": ("remove_from_cart.parquet", "sku"),
    "page_visit": ("page_visit.parquet", "url"),
    "search_query": ("search_query.parquet", None),
}

BURST_SECONDS = 5


def p(fname: str) -> str:
    return (RAW_DIR / fname).as_posix()


def main() -> None:
    con = duckdb.connect()
    con.sql("PRAGMA memory_limit='6GB'")

    outlier_rows = []
    burst_rows = []
    daily_rows = []

    print("=" * 80)
    print("A. 고객별 이벤트 수 분포 및 이상치")
    print("=" * 80)
    for name, (fname, _) in EVENT_TABLES.items():
        path = p(fname)
        stats = con.sql(
            f"""
            WITH per_client AS (
                SELECT client_id, COUNT(*) AS n
                FROM read_parquet('{path}')
                GROUP BY client_id
            )
            SELECT
                MIN(n), MAX(n),
                approx_quantile(n, 0.5) AS p50,
                approx_quantile(n, 0.9) AS p90,
                approx_quantile(n, 0.95) AS p95,
                approx_quantile(n, 0.99) AS p99,
                approx_quantile(n, 0.999) AS p999,
                AVG(n) AS mean_n
            FROM per_client
            """
        ).fetchone()
        min_n, max_n, p50, p90, p95, p99, p999, mean_n = stats
        print(f"\n{name}: min={min_n}, mean={mean_n:.2f}, p50={p50}, p90={p90}, p95={p95}, p99={p99}, p99.9={p999}, max={max_n:,}")

        top5 = con.sql(
            f"""
            SELECT client_id, COUNT(*) AS n
            FROM read_parquet('{path}')
            GROUP BY client_id
            ORDER BY n DESC
            LIMIT 5
            """
        ).fetchall()
        print(f"  상위 5개 고객: {top5}")

        outlier_rows.append(
            {
                "event_type": name,
                "min_events_per_client": min_n,
                "mean_events_per_client": round(mean_n, 4),
                "p50": p50,
                "p90": p90,
                "p95": p95,
                "p99": p99,
                "p999": p999,
                "max_events_per_client": max_n,
                "top5_client_id_count": str(top5),
            }
        )

    print("\n" + "=" * 80)
    print(f"B. 짧은 시간({BURST_SECONDS}초 이내) 반복 이벤트 (버스트)")
    print("=" * 80)
    for name, (fname, item_col) in EVENT_TABLES.items():
        path = p(fname)
        partition_cols = "client_id" if item_col is None else f"client_id, {item_col}"
        burst_count = con.sql(
            f"""
            WITH ordered AS (
                SELECT
                    client_id,
                    {item_col + ',' if item_col else ''}
                    TRY_CAST(timestamp AS TIMESTAMP) AS ts,
                    LAG(TRY_CAST(timestamp AS TIMESTAMP)) OVER (
                        PARTITION BY {partition_cols} ORDER BY TRY_CAST(timestamp AS TIMESTAMP)
                    ) AS prev_ts
                FROM read_parquet('{path}')
            )
            SELECT COUNT(*) FROM ordered
            WHERE prev_ts IS NOT NULL
              AND date_diff('second', prev_ts, ts) BETWEEN 0 AND {BURST_SECONDS}
            """
        ).fetchone()[0]
        total = con.sql(f"SELECT COUNT(*) FROM read_parquet('{path}')").fetchone()[0]
        pct = burst_count / total * 100 if total else 0
        print(f"{name}: {burst_count:,} / {total:,} 행 ({pct:.4f}%)이 동일 {partition_cols} 기준 {BURST_SECONDS}초 이내 반복")
        burst_rows.append(
            {
                "event_type": name,
                "partition_key": partition_cols,
                "burst_event_count": burst_count,
                "total_rows": total,
                "burst_pct": round(pct, 6),
            }
        )

    print("\n" + "=" * 80)
    print("C. 고객별 전체 이벤트 통합 기준 첫/마지막 행동, 관찰일 수")
    print("=" * 80)
    union_sql = " UNION ALL ".join(
        f"SELECT client_id, TRY_CAST(timestamp AS TIMESTAMP) AS ts FROM read_parquet('{p(fname)}')"
        for name, (fname, _) in EVENT_TABLES.items()
    )
    obs = con.sql(
        f"""
        WITH all_events AS ({union_sql}),
        per_client AS (
            SELECT
                client_id,
                MIN(ts) AS first_ts,
                MAX(ts) AS last_ts,
                COUNT(DISTINCT CAST(ts AS DATE)) AS n_active_days
            FROM all_events
            GROUP BY client_id
        )
        SELECT
            MIN(first_ts), MAX(first_ts),
            MIN(last_ts), MAX(last_ts),
            approx_quantile(n_active_days, 0.5) AS median_active_days,
            AVG(n_active_days) AS mean_active_days,
            MAX(n_active_days) AS max_active_days,
            COUNT(*) AS n_clients
        FROM per_client
        """
    ).fetchone()
    print(f"고객별 첫 행동일 범위: {obs[0]} ~ {obs[1]}")
    print(f"고객별 마지막 행동일 범위: {obs[2]} ~ {obs[3]}")
    print(f"고객별 관찰(활동)일 수: median={obs[4]}, mean={obs[5]:.2f}, max={obs[6]}")
    print(f"전체 고객 수: {obs[7]:,}")

    observation_summary = {
        "first_ts_min": str(obs[0]),
        "first_ts_max": str(obs[1]),
        "last_ts_min": str(obs[2]),
        "last_ts_max": str(obs[3]),
        "median_active_days": obs[4],
        "mean_active_days": round(obs[5], 4),
        "max_active_days": obs[6],
        "n_clients": obs[7],
    }

    print("\n" + "=" * 80)
    print("D. 이벤트 타입별 일별 이벤트량 (급증/급감 날짜)")
    print("=" * 80)
    for name, (fname, _) in EVENT_TABLES.items():
        path = p(fname)
        daily = con.sql(
            f"""
            SELECT CAST(TRY_CAST(timestamp AS TIMESTAMP) AS DATE) AS d, COUNT(*) AS n
            FROM read_parquet('{path}')
            GROUP BY d
            ORDER BY d
            """
        ).df()
        n_days = len(daily)
        mean_n = daily["n"].mean()
        std_n = daily["n"].std()
        max_row = daily.loc[daily["n"].idxmax()]
        min_row = daily.loc[daily["n"].idxmin()]
        print(f"\n{name}: 관측일수={n_days}, 일평균={mean_n:.1f}, 표준편차={std_n:.1f}")
        print(f"  최고 일자: {max_row['d']} ({max_row['n']:,}건)")
        print(f"  최저 일자: {min_row['d']} ({min_row['n']:,}건)")

        daily_rows.append(
            {
                "event_type": name,
                "n_observed_days": n_days,
                "mean_daily_count": round(mean_n, 2),
                "std_daily_count": round(std_n, 2),
                "max_day": str(max_row["d"]),
                "max_day_count": int(max_row["n"]),
                "min_day": str(min_row["d"]),
                "min_day_count": int(min_row["n"]),
            }
        )

    REPORT_DIR.mkdir(exist_ok=True)
    with open(REPORT_DIR / "phase1_data_quality.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["section", "data"])
        writer.writerow(["A_client_event_count_distribution", ""])
        w = csv.DictWriter(f, fieldnames=list(outlier_rows[0].keys()))
        w.writeheader()
        w.writerows(outlier_rows)

        writer.writerow([])
        writer.writerow(["B_burst_events", ""])
        w = csv.DictWriter(f, fieldnames=list(burst_rows[0].keys()))
        w.writeheader()
        w.writerows(burst_rows)

        writer.writerow([])
        writer.writerow(["C_observation_summary", ""])
        w = csv.DictWriter(f, fieldnames=list(observation_summary.keys()))
        w.writeheader()
        w.writerow(observation_summary)

        writer.writerow([])
        writer.writerow(["D_daily_volume", ""])
        w = csv.DictWriter(f, fieldnames=list(daily_rows[0].keys()))
        w.writeheader()
        w.writerows(daily_rows)

    print(f"\nSaved: {REPORT_DIR / 'phase1_data_quality.csv'}")


if __name__ == "__main__":
    main()

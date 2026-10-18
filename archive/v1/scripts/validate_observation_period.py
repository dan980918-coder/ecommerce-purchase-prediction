"""Phase 1 - 8.10 관찰기간과 검열(censoring) 문제 검토."""

import csv
from pathlib import Path

import duckdb

RAW_DIR = Path("data/raw/synerise_dataset")
REPORT_DIR = Path("reports")

EVENT_FILES = [
    "product_buy.parquet",
    "add_to_cart.parquet",
    "remove_from_cart.parquet",
    "page_visit.parquet",
    "search_query.parquet",
]

LEFT_CENSOR_DAYS = 7   # 관측 시작 후 N일 이내 첫 등장 -> 좌측 검열 후보 (기본값)
RIGHT_CENSOR_DAYS = 14  # 관측 종료 전 N일 이내 첫 등장 -> 우측 검열/신규 후보 (기본값)


def p(fname: str) -> str:
    return (RAW_DIR / fname).as_posix()


def main() -> None:
    con = duckdb.connect()
    con.sql("PRAGMA memory_limit='6GB'")
    out = {}

    union_sql = " UNION ALL ".join(
        f"SELECT client_id, TRY_CAST(timestamp AS TIMESTAMP) AS ts FROM read_parquet('{p(f)}')"
        for f in EVENT_FILES
    )
    con.sql(f"CREATE OR REPLACE TEMP VIEW all_events AS {union_sql}")
    con.sql(
        """
        CREATE OR REPLACE TEMP VIEW per_client AS
        SELECT client_id, MIN(ts) AS first_ts, MAX(ts) AS last_ts,
               date_diff('day', MIN(ts), MAX(ts)) AS obs_days
        FROM all_events GROUP BY client_id
        """
    )

    window_min, window_max = con.sql("SELECT MIN(ts), MAX(ts) FROM all_events").fetchone()
    print(f"전체 관측 기간: {window_min} ~ {window_max}")
    out["window_min_ts"] = str(window_min)
    out["window_max_ts"] = str(window_max)

    n_clients = con.sql("SELECT COUNT(*) FROM per_client").fetchone()[0]
    print(f"전체 고객 수: {n_clients:,}")
    out["n_clients"] = n_clients

    print("\n" + "=" * 80)
    print("A. 고객별 관찰기간(일) 분포")
    print("=" * 80)
    dist = con.sql(
        """
        SELECT MIN(obs_days), AVG(obs_days), approx_quantile(obs_days,0.5),
               approx_quantile(obs_days,0.9), approx_quantile(obs_days,0.95), MAX(obs_days)
        FROM per_client
        """
    ).fetchone()
    print(f"min={dist[0]}, mean={dist[1]:.2f}, median={dist[2]}, p90={dist[3]}, p95={dist[4]}, max={dist[5]}")
    out.update(
        {
            "obs_days_min": dist[0],
            "obs_days_mean": round(dist[1], 4),
            "obs_days_median": dist[2],
            "obs_days_p90": dist[3],
            "obs_days_p95": dist[4],
            "obs_days_max": dist[5],
        }
    )

    single_day = con.sql("SELECT COUNT(*) FROM per_client WHERE obs_days = 0").fetchone()[0]
    print(f"관찰기간 0일(하루만 활동): {single_day:,} ({single_day/n_clients*100:.2f}%)")
    out["obs_days_zero_count"] = single_day
    out["obs_days_zero_pct"] = round(single_day / n_clients * 100, 4)

    print("\n" + "=" * 80)
    print(f"B. 좌측 검열(left-censoring) 후보 — 관측 시작 {LEFT_CENSOR_DAYS}일 이내 첫 등장")
    print("=" * 80)
    left_censor = con.sql(
        f"""
        SELECT COUNT(*) FROM per_client
        WHERE first_ts < TIMESTAMP '{window_min}' + INTERVAL '{LEFT_CENSOR_DAYS} days'
        """
    ).fetchone()[0]
    pct_left = left_censor / n_clients * 100
    print(f"좌측 검열 후보(이미 활동 중이었을 가능성, '진짜 첫 방문'을 알 수 없음): {left_censor:,} ({pct_left:.2f}%)")
    out["left_censor_window_days"] = LEFT_CENSOR_DAYS
    out["left_censor_candidates"] = left_censor
    out["left_censor_pct"] = round(pct_left, 4)

    print("\n" + "=" * 80)
    print(f"C. 우측 검열(right-censoring) 후보 — 관측 종료 {RIGHT_CENSOR_DAYS}일 이내 첫 등장")
    print("=" * 80)
    right_censor = con.sql(
        f"""
        SELECT COUNT(*) FROM per_client
        WHERE first_ts >= TIMESTAMP '{window_max}' - INTERVAL '{RIGHT_CENSOR_DAYS} days'
        """
    ).fetchone()[0]
    pct_right = right_censor / n_clients * 100
    print(f"우측 검열 후보(관측 종료 직전 첫 등장, 이후 반복행동 관측 불가): {right_censor:,} ({pct_right:.2f}%)")
    out["right_censor_window_days"] = RIGHT_CENSOR_DAYS
    out["right_censor_candidates"] = right_censor
    out["right_censor_pct"] = round(pct_right, 4)

    print("\n" + "=" * 80)
    print("D. 구매 고객 대상 검열 문제 (첫 관측 구매 != 진짜 첫 구매)")
    print("=" * 80)
    buy_path = p("product_buy.parquet")
    con.sql(
        f"""
        CREATE OR REPLACE TEMP VIEW buyer_first_last AS
        SELECT client_id, MIN(TRY_CAST(timestamp AS TIMESTAMP)) AS first_buy,
               MAX(TRY_CAST(timestamp AS TIMESTAMP)) AS last_buy
        FROM read_parquet('{buy_path}') GROUP BY client_id
        """
    )
    n_buyers = con.sql("SELECT COUNT(*) FROM buyer_first_last").fetchone()[0]

    buyers_first_day = con.sql(
        f"""
        SELECT COUNT(*) FROM buyer_first_last
        WHERE first_buy < TIMESTAMP '{window_min}' + INTERVAL '{LEFT_CENSOR_DAYS} days'
        """
    ).fetchone()[0]
    buyers_last_window = con.sql(
        f"""
        SELECT COUNT(*) FROM buyer_first_last
        WHERE last_buy >= TIMESTAMP '{window_max}' - INTERVAL '{RIGHT_CENSOR_DAYS} days'
        """
    ).fetchone()[0]

    pct_buyers_first_day = buyers_first_day / n_buyers * 100
    pct_buyers_last_window = buyers_last_window / n_buyers * 100
    print(f"구매 고객 중 관측 시작 {LEFT_CENSOR_DAYS}일 이내 첫 구매(=이미 기존 고객이었을 가능성): {buyers_first_day:,} ({pct_buyers_first_day:.2f}%)")
    print(f"구매 고객 중 관측 종료 {RIGHT_CENSOR_DAYS}일 이내 마지막 구매(=이후 재구매 여부를 알 수 없음): {buyers_last_window:,} ({pct_buyers_last_window:.2f}%)")

    out.update(
        {
            "n_buyers": n_buyers,
            "buyers_first_purchase_in_left_window": buyers_first_day,
            "buyers_first_purchase_in_left_window_pct": round(pct_buyers_first_day, 4),
            "buyers_last_purchase_in_right_window": buyers_last_window,
            "buyers_last_purchase_in_right_window_pct": round(pct_buyers_last_window, 4),
        }
    )

    REPORT_DIR.mkdir(exist_ok=True)
    with open(REPORT_DIR / "phase1_observation_period.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        for k, v in out.items():
            writer.writerow([k, v])

    print(f"\nSaved: {REPORT_DIR / 'phase1_observation_period.csv'}")


if __name__ == "__main__":
    main()

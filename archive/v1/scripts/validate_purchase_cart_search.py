"""Phase 1 - 8.7 구매행동 / 8.8 장바구니 행동 / 8.9 페이지방문·검색 검사."""

import csv
from pathlib import Path

import duckdb

RAW_DIR = Path("data/raw/synerise_dataset")
REPORT_DIR = Path("reports")


def p(fname: str) -> str:
    return (RAW_DIR / fname).as_posix()


def main() -> None:
    con = duckdb.connect()
    con.sql("PRAGMA memory_limit='6GB'")
    out = {}

    buy = f"read_parquet('{p('product_buy.parquet')}')"
    cart = f"read_parquet('{p('add_to_cart.parquet')}')"
    remove = f"read_parquet('{p('remove_from_cart.parquet')}')"
    visit = f"read_parquet('{p('page_visit.parquet')}')"
    search = f"read_parquet('{p('search_query.parquet')}')"
    props = f"read_parquet('{p('product_properties.parquet')}')"

    print("=" * 80)
    print("8.7 구매행동 검사")
    print("=" * 80)

    buyer_count = con.sql(f"SELECT COUNT(DISTINCT client_id) FROM {buy}").fetchone()[0]
    print(f"구매 고객 수: {buyer_count:,}")
    out["8.7_buyer_count"] = buyer_count

    per_cust = con.sql(
        f"""
        WITH b AS (
            SELECT client_id, TRY_CAST(timestamp AS TIMESTAMP) AS ts, sku
            FROM {buy}
        ),
        joined AS (
            SELECT b.client_id, b.ts, b.sku, pr.category
            FROM b LEFT JOIN {props} pr ON b.sku = pr.sku
        ),
        agg AS (
            SELECT
                client_id,
                COUNT(*) AS n_purchases,
                COUNT(DISTINCT CAST(ts AS DATE)) AS n_purchase_days,
                COUNT(DISTINCT sku) AS n_unique_skus,
                COUNT(DISTINCT category) AS n_categories,
                MIN(ts) AS first_purchase,
                MAX(ts) AS last_purchase
            FROM joined
            GROUP BY client_id
        )
        SELECT
            AVG(n_purchases), approx_quantile(n_purchases,0.5),
            AVG(n_purchase_days), approx_quantile(n_purchase_days,0.5),
            AVG(n_unique_skus), approx_quantile(n_unique_skus,0.5),
            AVG(n_categories), approx_quantile(n_categories,0.5),
            SUM(CASE WHEN n_purchase_days = 1 THEN 1 ELSE 0 END),
            SUM(CASE WHEN n_purchase_days >= 2 THEN 1 ELSE 0 END),
            SUM(CASE WHEN n_purchase_days >= 3 THEN 1 ELSE 0 END),
            COUNT(*)
        FROM agg
        """
    ).fetchone()

    (mean_n, med_n, mean_days, med_days, mean_skus, med_skus, mean_cat, med_cat,
     one_day, two_plus, three_plus, n_total) = per_cust

    print(f"고객당 구매 이벤트 수: mean={mean_n:.2f}, median={med_n}")
    print(f"고객당 고유 구매일 수: mean={mean_days:.2f}, median={med_days}")
    print(f"고객당 고유 구매 상품 수: mean={mean_skus:.2f}, median={med_skus}")
    print(f"고객당 구매 카테고리 수: mean={mean_cat:.2f}, median={med_cat}")
    print(f"\n[정의: '구매 회차' = 고유 구매일(day) 수 기준. 동일 날짜 복수 구매는 1회로 간주]")
    print(f"구매일 1일(=1회) 고객: {one_day:,} ({one_day/n_total*100:.2f}%)")
    print(f"구매일 2일 이상(=2회+) 고객: {two_plus:,} ({two_plus/n_total*100:.2f}%)")
    print(f"구매일 3일 이상(=3회+) 고객: {three_plus:,} ({three_plus/n_total*100:.2f}%)")
    print(f"반복구매 가능한 고객 수(=구매일 2일 이상과 동일 정의 사용): {two_plus:,}")

    out.update(
        {
            "8.7_mean_purchases_per_customer": round(mean_n, 4),
            "8.7_median_purchases_per_customer": med_n,
            "8.7_mean_purchase_days_per_customer": round(mean_days, 4),
            "8.7_median_purchase_days_per_customer": med_days,
            "8.7_mean_unique_skus_per_customer": round(mean_skus, 4),
            "8.7_median_unique_skus_per_customer": med_skus,
            "8.7_mean_categories_per_customer": round(mean_cat, 4),
            "8.7_median_categories_per_customer": med_cat,
            "8.7_pct_1_purchase_day": round(one_day / n_total * 100, 4),
            "8.7_pct_2plus_purchase_days": round(two_plus / n_total * 100, 4),
            "8.7_pct_3plus_purchase_days": round(three_plus / n_total * 100, 4),
            "8.7_repeat_capable_customers": two_plus,
        }
    )

    # 관찰 종료 직전 구매 고객 비율 (기본값: 마지막 14일 창 사용, 확정된 이탈기준 아님)
    window_days = 14
    end_ts = con.sql(f"SELECT MAX(TRY_CAST(timestamp AS TIMESTAMP)) FROM {buy}").fetchone()[0]
    recent_buyers = con.sql(
        f"""
        SELECT COUNT(DISTINCT client_id) FROM {buy}
        WHERE TRY_CAST(timestamp AS TIMESTAMP) >= TIMESTAMP '{end_ts}' - INTERVAL '{window_days} days'
        """
    ).fetchone()[0]
    pct_recent = recent_buyers / buyer_count * 100
    print(f"\n관찰 종료 직전 {window_days}일 내 구매 고객: {recent_buyers:,} / {buyer_count:,} ({pct_recent:.2f}%) [참고용 기본 window, 공식 이탈 기준 아님]")
    out["8.7_recent_window_days"] = window_days
    out["8.7_pct_buyers_in_recent_window"] = round(pct_recent, 4)

    # 구매 간격 (이벤트 레벨, 연속 구매 사이 일수)
    gaps = con.sql(
        f"""
        WITH b AS (
            SELECT client_id, TRY_CAST(timestamp AS TIMESTAMP) AS ts
            FROM {buy}
        ),
        ordered AS (
            SELECT client_id, ts,
                   LAG(ts) OVER (PARTITION BY client_id ORDER BY ts) AS prev_ts
            FROM b
        ),
        gap_days AS (
            SELECT client_id, date_diff('second', prev_ts, ts) / 86400.0 AS gap
            FROM ordered WHERE prev_ts IS NOT NULL AND ts != prev_ts
        )
        SELECT
            AVG(gap), approx_quantile(gap,0.5),
            approx_quantile(gap,0.25), approx_quantile(gap,0.75),
            approx_quantile(gap,0.90), approx_quantile(gap,0.95)
        FROM gap_days
        """
    ).fetchone()
    print(f"\n구매 간격(일, 이벤트 레벨): mean={gaps[0]:.2f}, median={gaps[1]:.2f}, p25={gaps[2]:.2f}, p75={gaps[3]:.2f}, p90={gaps[4]:.2f}, p95={gaps[5]:.2f}")
    out.update(
        {
            "8.7_gap_mean_days": round(gaps[0], 4),
            "8.7_gap_median_days": round(gaps[1], 4),
            "8.7_gap_p25_days": round(gaps[2], 4),
            "8.7_gap_p75_days": round(gaps[3], 4),
            "8.7_gap_p90_days": round(gaps[4], 4),
            "8.7_gap_p95_days": round(gaps[5], 4),
        }
    )

    print("\n" + "=" * 80)
    print("8.8 장바구니 행동 검사")
    print("=" * 80)

    add_stats = con.sql(
        f"""
        WITH per AS (SELECT client_id, COUNT(*) AS n FROM {cart} GROUP BY client_id)
        SELECT AVG(n), approx_quantile(n,0.5) FROM per
        """
    ).fetchone()
    remove_stats = con.sql(
        f"""
        WITH per AS (SELECT client_id, COUNT(*) AS n FROM {remove} GROUP BY client_id)
        SELECT AVG(n), approx_quantile(n,0.5) FROM per
        """
    ).fetchone()
    print(f"고객별 장바구니 추가 횟수: mean={add_stats[0]:.2f}, median={add_stats[1]}")
    print(f"고객별 장바구니 제거 횟수: mean={remove_stats[0]:.2f}, median={remove_stats[1]}")
    out["8.8_mean_add_per_customer"] = round(add_stats[0], 4)
    out["8.8_median_add_per_customer"] = add_stats[1]
    out["8.8_mean_remove_per_customer"] = round(remove_stats[0], 4)
    out["8.8_median_remove_per_customer"] = remove_stats[1]

    top_add = con.sql(
        f"SELECT sku, COUNT(*) AS n FROM {cart} GROUP BY sku ORDER BY n DESC LIMIT 10"
    ).fetchall()
    top_remove = con.sql(
        f"SELECT sku, COUNT(*) AS n FROM {remove} GROUP BY sku ORDER BY n DESC LIMIT 10"
    ).fetchall()
    print(f"상품별 추가 횟수 상위 10: {top_add}")
    print(f"상품별 제거 횟수 상위 10: {top_remove}")

    # 추가 후 동일 상품 구매 가능성 및 소요 시간
    add_to_buy = con.sql(
        f"""
        WITH a AS (
            SELECT client_id, sku, MIN(TRY_CAST(timestamp AS TIMESTAMP)) AS add_ts
            FROM {cart} GROUP BY client_id, sku
        ),
        b AS (
            SELECT client_id, sku, MIN(TRY_CAST(timestamp AS TIMESTAMP)) AS buy_ts
            FROM {buy} GROUP BY client_id, sku
        ),
        matched AS (
            SELECT a.client_id, a.sku, a.add_ts, b.buy_ts,
                   date_diff('second', a.add_ts, b.buy_ts) / 3600.0 AS hours_to_buy
            FROM a JOIN b ON a.client_id = b.client_id AND a.sku = b.sku
            WHERE b.buy_ts >= a.add_ts
        )
        SELECT COUNT(*), AVG(hours_to_buy), approx_quantile(hours_to_buy,0.5),
               approx_quantile(hours_to_buy,0.9)
        FROM matched
        """
    ).fetchone()
    total_add_pairs = con.sql(f"SELECT COUNT(DISTINCT (client_id, sku)) FROM {cart}").fetchone()[0]
    matched_cnt, mean_hrs, med_hrs, p90_hrs = add_to_buy
    match_rate = matched_cnt / total_add_pairs * 100
    print(f"\n추가 후 동일 상품 구매 전환: {matched_cnt:,} / {total_add_pairs:,} (client_id,sku) 쌍 ({match_rate:.2f}%)")
    print(f"추가→구매 소요시간(시간 단위): mean={mean_hrs:.2f}, median={med_hrs:.2f}, p90={p90_hrs:.2f}")
    out.update(
        {
            "8.8_add_to_buy_matched_pairs": matched_cnt,
            "8.8_add_to_buy_total_pairs": total_add_pairs,
            "8.8_add_to_buy_conversion_pct": round(match_rate, 4),
            "8.8_add_to_buy_mean_hours": round(mean_hrs, 4),
            "8.8_add_to_buy_median_hours": round(med_hrs, 4),
            "8.8_add_to_buy_p90_hours": round(p90_hrs, 4),
        }
    )

    # 제거 후 구매한 사례
    remove_to_buy = con.sql(
        f"""
        WITH r AS (
            SELECT client_id, sku, MIN(TRY_CAST(timestamp AS TIMESTAMP)) AS remove_ts
            FROM {remove} GROUP BY client_id, sku
        ),
        b AS (
            SELECT client_id, sku, MIN(TRY_CAST(timestamp AS TIMESTAMP)) AS buy_ts
            FROM {buy} GROUP BY client_id, sku
        )
        SELECT COUNT(*) FROM r JOIN b ON r.client_id = b.client_id AND r.sku = b.sku
        WHERE b.buy_ts >= r.remove_ts
        """
    ).fetchone()[0]
    total_remove_pairs = con.sql(f"SELECT COUNT(DISTINCT (client_id, sku)) FROM {remove}").fetchone()[0]
    print(f"\n제거 후 구매한 사례: {remove_to_buy:,} / {total_remove_pairs:,} (client_id,sku) 쌍 ({remove_to_buy/total_remove_pairs*100:.2f}%)")
    out["8.8_remove_then_buy_pairs"] = remove_to_buy
    out["8.8_remove_total_pairs"] = total_remove_pairs
    out["8.8_remove_then_buy_pct"] = round(remove_to_buy / total_remove_pairs * 100, 4)

    print("\n" + "=" * 80)
    print("8.9 페이지 방문과 검색 검사")
    print("=" * 80)

    # 구매 전 방문/검색량 vs 비구매 고객
    buyer_first_purchase = con.sql(
        f"""
        CREATE OR REPLACE TEMP VIEW first_purchase AS
        SELECT client_id, MIN(TRY_CAST(timestamp AS TIMESTAMP)) AS first_ts
        FROM {buy} GROUP BY client_id
        """
    )
    pre_purchase_visits = con.sql(
        f"""
        WITH v AS (
            SELECT v.client_id, COUNT(*) AS n
            FROM {visit} v JOIN first_purchase fp ON v.client_id = fp.client_id
            WHERE TRY_CAST(v.timestamp AS TIMESTAMP) < fp.first_ts
            GROUP BY v.client_id
        )
        SELECT AVG(n), approx_quantile(n,0.5), COUNT(*) FROM v
        """
    ).fetchone()
    pre_purchase_search = con.sql(
        f"""
        WITH s AS (
            SELECT s.client_id, COUNT(*) AS n
            FROM {search} s JOIN first_purchase fp ON s.client_id = fp.client_id
            WHERE TRY_CAST(s.timestamp AS TIMESTAMP) < fp.first_ts
            GROUP BY s.client_id
        )
        SELECT AVG(n), approx_quantile(n,0.5), COUNT(*) FROM s
        """
    ).fetchone()

    nonbuyer_visits = con.sql(
        f"""
        WITH v AS (
            SELECT v.client_id, COUNT(*) AS n
            FROM {visit} v
            WHERE NOT EXISTS (SELECT 1 FROM first_purchase fp WHERE fp.client_id = v.client_id)
            GROUP BY v.client_id
        )
        SELECT AVG(n), approx_quantile(n,0.5), COUNT(*) FROM v
        """
    ).fetchone()
    nonbuyer_search = con.sql(
        f"""
        WITH s AS (
            SELECT s.client_id, COUNT(*) AS n
            FROM {search} s
            WHERE NOT EXISTS (SELECT 1 FROM first_purchase fp WHERE fp.client_id = s.client_id)
            GROUP BY s.client_id
        )
        SELECT AVG(n), approx_quantile(n,0.5), COUNT(*) FROM s
        """
    ).fetchone()

    print(f"구매 고객의 '첫 구매 이전' page_visit: mean={pre_purchase_visits[0]:.2f}, median={pre_purchase_visits[1]}, n={pre_purchase_visits[2]:,}")
    print(f"구매 고객의 '첫 구매 이전' search_query: mean={pre_purchase_search[0]:.2f}, median={pre_purchase_search[1]}, n={pre_purchase_search[2]:,}")
    print(f"비구매 고객의 전체 page_visit: mean={nonbuyer_visits[0]:.2f}, median={nonbuyer_visits[1]}, n={nonbuyer_visits[2]:,}")
    print(f"비구매 고객의 전체 search_query: mean={nonbuyer_search[0]:.2f}, median={nonbuyer_search[1]}, n={nonbuyer_search[2]:,}")

    out.update(
        {
            "8.9_buyer_pre_purchase_visit_mean": round(pre_purchase_visits[0], 4),
            "8.9_buyer_pre_purchase_visit_median": pre_purchase_visits[1],
            "8.9_buyer_pre_purchase_search_mean": round(pre_purchase_search[0], 4),
            "8.9_buyer_pre_purchase_search_median": pre_purchase_search[1],
            "8.9_nonbuyer_visit_mean": round(nonbuyer_visits[0], 4),
            "8.9_nonbuyer_visit_median": nonbuyer_visits[1],
            "8.9_nonbuyer_search_mean": round(nonbuyer_search[0], 4),
            "8.9_nonbuyer_search_median": nonbuyer_search[1],
        }
    )

    REPORT_DIR.mkdir(exist_ok=True)
    with open(REPORT_DIR / "phase1_behavior_summary.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        for k, v in out.items():
            writer.writerow([k, v])

    with open(REPORT_DIR / "phase1_top_cart_items.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "sku", "add_count", "sku_remove", "remove_count"])
        for i in range(10):
            add_sku, add_n = top_add[i] if i < len(top_add) else (None, None)
            rem_sku, rem_n = top_remove[i] if i < len(top_remove) else (None, None)
            writer.writerow([i + 1, add_sku, add_n, rem_sku, rem_n])

    print(f"\nSaved: {REPORT_DIR / 'phase1_behavior_summary.csv'}")
    print(f"Saved: {REPORT_DIR / 'phase1_top_cart_items.csv'}")


if __name__ == "__main__":
    main()

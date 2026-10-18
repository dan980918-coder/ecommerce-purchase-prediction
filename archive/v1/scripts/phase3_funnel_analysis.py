"""Phase 3 - 고객 단위 퍼널 분석 (PROJECT_GUIDELINES.md 13번).

reports/phase3_funnel_analysis.md의 모든 수치를 재현하는 스크립트.
작성 당시(2026-08-06) 즉석 쿼리로만 계산하고 스크립트를 남기지 않아 재현이
안 되는 상태였고, 2026-08-08 사용자 요청으로 뒤늦게 스크립트화했다.

Phase 1 8.9에서 page_visit.url이 sku와 연결되지 않는 것을 확인했으므로
상품 단위 퍼널은 계산하지 않고, mart_customer_360 기준 고객 단위 탐색
퍼널만 다룬다.
"""

from pathlib import Path

import duckdb
import pandas as pd
import yaml

CONFIG_PATH = Path("config/paths.yaml")


def get_connection() -> duckdb.DuckDBPyConnection:
    with open(CONFIG_PATH) as f:
        paths = yaml.safe_load(f)
    return duckdb.connect(str(paths["database_path"]), read_only=True)


def funnel_reach(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """단계별 도달률: 전체 -> 탐색 -> 탐색+장바구니 -> 탐색+장바구니+구매."""
    row = con.sql(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN n_page_visit > 0 OR n_search_query > 0 THEN 1 ELSE 0 END) AS explore,
            SUM(CASE WHEN (n_page_visit > 0 OR n_search_query > 0) AND has_cart_activity THEN 1 ELSE 0 END) AS explore_to_cart,
            SUM(CASE WHEN (n_page_visit > 0 OR n_search_query > 0) AND has_cart_activity AND is_buyer THEN 1 ELSE 0 END) AS explore_to_cart_to_buy
        FROM mart_customer_360
        """
    ).fetchone()
    total, explore, explore_to_cart, explore_to_cart_to_buy = row

    return pd.DataFrame(
        [
            {"stage": "전체 고객", "n_customers": total, "pct_of_total": 100.0, "pct_of_prev_stage": None},
            {"stage": "탐색", "n_customers": explore, "pct_of_total": explore / total * 100, "pct_of_prev_stage": None},
            {
                "stage": "탐색 → 장바구니 추가",
                "n_customers": explore_to_cart,
                "pct_of_total": explore_to_cart / total * 100,
                "pct_of_prev_stage": explore_to_cart / explore * 100,
            },
            {
                "stage": "탐색 → 장바구니 → 구매",
                "n_customers": explore_to_cart_to_buy,
                "pct_of_total": explore_to_cart_to_buy / total * 100,
                "pct_of_prev_stage": explore_to_cart_to_buy / explore_to_cart * 100,
            },
        ]
    )


def buyer_path_breakdown(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """구매자 909,210명의 실제 경로 분해: (탐색 O/X) x (장바구니 O/X) x (구매 여부)."""
    df = con.sql(
        """
        SELECT
            CASE WHEN n_page_visit > 0 OR n_search_query > 0 THEN 'O' ELSE 'X' END AS has_explore,
            CASE WHEN has_cart_activity THEN 'O' ELSE 'X' END AS has_cart,
            is_buyer,
            COUNT(*) AS n_customers
        FROM mart_customer_360
        GROUP BY 1, 2, 3
        ORDER BY is_buyer DESC, has_explore DESC, has_cart DESC
        """
    ).df()
    n_buyers = df.loc[df["is_buyer"], "n_customers"].sum()
    df["pct_of_buyers"] = df.apply(
        lambda r: r["n_customers"] / n_buyers * 100 if r["is_buyer"] else None, axis=1
    )
    return df


def repeat_vs_single_buyer(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """1회 구매자 vs 반복구매자(구매일 2일 이상) 인원."""
    return con.sql(
        """
        SELECT
            CASE WHEN n_purchase_days = 1 THEN '1회 구매(구매일 1일)' ELSE '반복구매(구매일 2일+)' END AS group_name,
            COUNT(*) AS n_customers
        FROM mart_customer_360
        WHERE is_buyer
        GROUP BY 1
        ORDER BY 1
        """
    ).df()


def main() -> None:
    con = get_connection()

    print("=== 1. 단계별 도달률 ===")
    reach = funnel_reach(con)
    print(reach.to_string(index=False))

    print("\n=== 2. 구매자 경로 분해 (909,210명) ===")
    breakdown = buyer_path_breakdown(con)
    print(breakdown.to_string(index=False))

    print("\n=== 3. 1회 구매자 vs 반복구매자 ===")
    repeat_vs_single = repeat_vs_single_buyer(con)
    print(repeat_vs_single.to_string(index=False))

    out_dir = Path("reports/tables")
    out_dir.mkdir(parents=True, exist_ok=True)
    reach.to_csv(out_dir / "phase3_funnel_reach.csv", index=False)
    breakdown.to_csv(out_dir / "phase3_funnel_buyer_path_breakdown.csv", index=False)
    repeat_vs_single.to_csv(out_dir / "phase3_funnel_repeat_vs_single.csv", index=False)
    print(f"\n저장 완료: {out_dir}/phase3_funnel_*.csv")


if __name__ == "__main__":
    main()

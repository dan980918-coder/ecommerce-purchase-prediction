"""Phase 1 - 8.4 고객 ID 연결성 검사.

5개 이벤트 테이블 간 client_id 교집합/합집합, 이벤트 타입 보유 수 분포를 계산한다.
"""

import csv
from pathlib import Path

import duckdb

RAW_DIR = Path("data/raw/synerise_dataset")
REPORT_DIR = Path("reports")

EVENT_TABLES = {
    "product_buy": "product_buy.parquet",
    "add_to_cart": "add_to_cart.parquet",
    "remove_from_cart": "remove_from_cart.parquet",
    "page_visit": "page_visit.parquet",
    "search_query": "search_query.parquet",
}


def p(fname: str) -> str:
    return (RAW_DIR / fname).as_posix()


def main() -> None:
    con = duckdb.connect()

    # 각 이벤트별 고유 client_id를 임시 뷰로 등록
    for name, fname in EVENT_TABLES.items():
        con.sql(
            f"CREATE OR REPLACE TEMP VIEW clients_{name} AS "
            f"SELECT DISTINCT client_id FROM read_parquet('{p(fname)}')"
        )

    print("=" * 80)
    print("이벤트별 고유 고객 수")
    print("=" * 80)
    single_counts = {}
    rows_single = []
    for name in EVENT_TABLES:
        cnt = con.sql(f"SELECT COUNT(*) FROM clients_{name}").fetchone()[0]
        single_counts[name] = cnt
        print(f"  {name}: {cnt:,}")
        rows_single.append({"metric": f"unique_clients_{name}", "value": cnt})

    # 전체 합집합 (5개 이벤트 어느 하나라도 있는 고객)
    union_sql = " UNION ".join(f"SELECT client_id FROM clients_{n}" for n in EVENT_TABLES)
    total_union = con.sql(f"SELECT COUNT(*) FROM ({union_sql})").fetchone()[0]
    print(f"\n전체 고유 고객 (5개 이벤트 합집합): {total_union:,}")
    rows_single.append({"metric": "total_unique_clients_union", "value": total_union})

    print("\n" + "=" * 80)
    print("주요 교집합")
    print("=" * 80)

    pairwise = {
        "buy_and_cart": ("product_buy", "add_to_cart"),
        "buy_and_search": ("product_buy", "search_query"),
        "buy_and_pagevisit": ("product_buy", "page_visit"),
        "cart_and_remove": ("add_to_cart", "remove_from_cart"),
    }
    for label, (a, b) in pairwise.items():
        cnt = con.sql(
            f"SELECT COUNT(*) FROM clients_{a} a JOIN clients_{b} b USING (client_id)"
        ).fetchone()[0]
        print(f"  {label} ({a} ∩ {b}): {cnt:,}")
        rows_single.append({"metric": f"intersect_{label}", "value": cnt})

    # 5개 이벤트 모두 보유
    join_sql = " JOIN ".join(f"clients_{n}" for n in EVENT_TABLES)
    using_sql = " USING (client_id) JOIN ".join(list(EVENT_TABLES.keys()))
    all5_sql = (
        "SELECT COUNT(*) FROM clients_product_buy "
        "JOIN clients_add_to_cart USING (client_id) "
        "JOIN clients_remove_from_cart USING (client_id) "
        "JOIN clients_page_visit USING (client_id) "
        "JOIN clients_search_query USING (client_id)"
    )
    all5 = con.sql(all5_sql).fetchone()[0]
    print(f"\n5개 이벤트 모두 보유: {all5:,}")
    rows_single.append({"metric": "clients_with_all_5_events", "value": all5})

    print("\n" + "=" * 80)
    print("고객별 이벤트 타입 보유 수 분포")
    print("=" * 80)

    per_client_union = (
        " UNION ALL ".join(
            f"SELECT client_id, '{n}' AS event_type FROM clients_{n}" for n in EVENT_TABLES
        )
    )
    dist = con.sql(
        f"""
        WITH per_client AS (
            SELECT client_id, COUNT(DISTINCT event_type) AS n_event_types
            FROM ({per_client_union})
            GROUP BY client_id
        )
        SELECT n_event_types, COUNT(*) AS n_clients
        FROM per_client
        GROUP BY n_event_types
        ORDER BY n_event_types
        """
    ).fetchall()

    rows_dist = []
    for n_types, n_clients in dist:
        pct = n_clients / total_union * 100
        print(f"  이벤트 타입 {n_types}개 보유: {n_clients:,}명 ({pct:.2f}%)")
        rows_dist.append({"n_event_types": n_types, "n_clients": n_clients, "pct": round(pct, 4)})

    only_one = con.sql(
        f"""
        WITH per_client AS (
            SELECT client_id, COUNT(DISTINCT event_type) AS n_event_types
            FROM ({per_client_union})
            GROUP BY client_id
        )
        SELECT COUNT(*) FROM per_client WHERE n_event_types = 1
        """
    ).fetchone()[0]
    print(f"\n하나의 이벤트만 가진 고객: {only_one:,}")
    rows_single.append({"metric": "clients_with_only_1_event_type", "value": only_one})

    REPORT_DIR.mkdir(exist_ok=True)
    with open(REPORT_DIR / "phase1_customer_overlap.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "value"])
        writer.writeheader()
        writer.writerows(rows_single)

    with open(REPORT_DIR / "phase1_customer_event_type_distribution.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["n_event_types", "n_clients", "pct"])
        writer.writeheader()
        writer.writerows(rows_dist)

    print(f"\nSaved: {REPORT_DIR / 'phase1_customer_overlap.csv'}")
    print(f"Saved: {REPORT_DIR / 'phase1_customer_event_type_distribution.csv'}")


if __name__ == "__main__":
    main()

"""Phase 1 - 8.5 상품 ID 연결성 검사."""

import csv
from pathlib import Path

import duckdb

RAW_DIR = Path("data/raw/synerise_dataset")
REPORT_DIR = Path("reports")


def p(fname: str) -> str:
    return (RAW_DIR / fname).as_posix()


def main() -> None:
    con = duckdb.connect()
    rows = []

    buy_skus = con.sql(
        f"SELECT COUNT(DISTINCT sku) FROM read_parquet('{p('product_buy.parquet')}')"
    ).fetchone()[0]
    cart_skus = con.sql(
        f"SELECT COUNT(DISTINCT sku) FROM read_parquet('{p('add_to_cart.parquet')}')"
    ).fetchone()[0]
    remove_skus = con.sql(
        f"SELECT COUNT(DISTINCT sku) FROM read_parquet('{p('remove_from_cart.parquet')}')"
    ).fetchone()[0]
    prop_skus = con.sql(
        f"SELECT COUNT(DISTINCT sku) FROM read_parquet('{p('product_properties.parquet')}')"
    ).fetchone()[0]
    prop_rows = con.sql(
        f"SELECT COUNT(*) FROM read_parquet('{p('product_properties.parquet')}')"
    ).fetchone()[0]

    print(f"구매 상품 수 (distinct sku, product_buy): {buy_skus:,}")
    print(f"장바구니 상품 수 (distinct sku, add_to_cart): {cart_skus:,}")
    print(f"장바구니 제거 상품 수 (distinct sku, remove_from_cart): {remove_skus:,}")
    print(f"상품 속성 테이블 상품 수 (distinct sku, product_properties): {prop_skus:,}")
    print(f"상품 속성 테이블 행 수: {prop_rows:,} (distinct sku와 같으면 sku당 1행)")

    rows.extend(
        [
            {"metric": "distinct_sku_product_buy", "value": buy_skus},
            {"metric": "distinct_sku_add_to_cart", "value": cart_skus},
            {"metric": "distinct_sku_remove_from_cart", "value": remove_skus},
            {"metric": "distinct_sku_product_properties", "value": prop_skus},
            {"metric": "row_count_product_properties", "value": prop_rows},
        ]
    )

    # 매칭률
    buy_matched = con.sql(
        f"""
        SELECT COUNT(DISTINCT b.sku)
        FROM (SELECT DISTINCT sku FROM read_parquet('{p('product_buy.parquet')}')) b
        JOIN (SELECT DISTINCT sku FROM read_parquet('{p('product_properties.parquet')}')) pr
          ON b.sku = pr.sku
        """
    ).fetchone()[0]
    cart_matched = con.sql(
        f"""
        SELECT COUNT(DISTINCT c.sku)
        FROM (SELECT DISTINCT sku FROM read_parquet('{p('add_to_cart.parquet')}')) c
        JOIN (SELECT DISTINCT sku FROM read_parquet('{p('product_properties.parquet')}')) pr
          ON c.sku = pr.sku
        """
    ).fetchone()[0]

    buy_match_rate = buy_matched / buy_skus * 100 if buy_skus else 0
    cart_match_rate = cart_matched / cart_skus * 100 if cart_skus else 0

    print(f"\n구매 상품 ↔ 속성 테이블 매칭: {buy_matched:,} / {buy_skus:,} ({buy_match_rate:.2f}%)")
    print(f"장바구니 상품 ↔ 속성 테이블 매칭: {cart_matched:,} / {cart_skus:,} ({cart_match_rate:.2f}%)")

    rows.extend(
        [
            {"metric": "buy_sku_matched_to_properties", "value": buy_matched},
            {"metric": "buy_sku_match_rate_pct", "value": round(buy_match_rate, 4)},
            {"metric": "cart_sku_matched_to_properties", "value": cart_matched},
            {"metric": "cart_sku_match_rate_pct", "value": round(cart_match_rate, 4)},
        ]
    )

    # 결측률 (product_properties)
    null_stats = con.sql(
        f"""
        SELECT
            SUM(CASE WHEN category IS NULL THEN 1 ELSE 0 END) AS null_category,
            SUM(CASE WHEN price IS NULL THEN 1 ELSE 0 END) AS null_price,
            SUM(CASE WHEN name IS NULL THEN 1 ELSE 0 END) AS null_name
        FROM read_parquet('{p('product_properties.parquet')}')
        """
    ).fetchone()
    null_category, null_price, null_name = null_stats
    print(f"\ncategory 결측: {null_category:,} ({null_category / prop_rows:.4%})")
    print(f"price 결측: {null_price:,} ({null_price / prop_rows:.4%})")
    print(f"name 결측: {null_name:,} ({null_name / prop_rows:.4%})")

    rows.extend(
        [
            {"metric": "null_category_count", "value": null_category},
            {"metric": "null_category_pct", "value": round(null_category / prop_rows * 100, 6)},
            {"metric": "null_price_count", "value": null_price},
            {"metric": "null_price_pct", "value": round(null_price / prop_rows * 100, 6)},
            {"metric": "null_name_count", "value": null_name},
            {"metric": "null_name_pct", "value": round(null_name / prop_rows * 100, 6)},
        ]
    )

    # 중복 상품 속성: 한 sku에 여러 행(=여러 속성값 조합)이 존재하는지
    dup_sku = con.sql(
        f"""
        SELECT COUNT(*) FROM (
            SELECT sku, COUNT(*) AS cnt
            FROM read_parquet('{p('product_properties.parquet')}')
            GROUP BY sku
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    print(f"\n중복 sku (2개 이상 행을 가진 상품): {dup_sku:,}")
    rows.append({"metric": "sku_with_multiple_rows", "value": dup_sku})

    # 한 sku에 서로 다른 category/price 값이 존재하는지 (혹시 dup_sku > 0인 경우 확인용)
    if dup_sku > 0:
        conflicting = con.sql(
            f"""
            SELECT COUNT(*) FROM (
                SELECT sku
                FROM read_parquet('{p('product_properties.parquet')}')
                GROUP BY sku
                HAVING COUNT(DISTINCT category) > 1 OR COUNT(DISTINCT price) > 1
            )
            """
        ).fetchone()[0]
        print(f"동일 sku 내 category/price 값이 서로 다른 경우: {conflicting:,}")
        rows.append({"metric": "sku_with_conflicting_category_or_price", "value": conflicting})

    # 가격이 실제 금액이 아니라 구간/순위형인지 참고용 확인
    price_range = con.sql(
        f"SELECT MIN(price), MAX(price), COUNT(DISTINCT price) FROM read_parquet('{p('product_properties.parquet')}')"
    ).fetchone()
    print(f"\nprice 값 범위: min={price_range[0]}, max={price_range[1]}, distinct={price_range[2]:,} (구간/순위형 추정)")
    rows.extend(
        [
            {"metric": "price_min", "value": price_range[0]},
            {"metric": "price_max", "value": price_range[1]},
            {"metric": "price_distinct_count", "value": price_range[2]},
        ]
    )

    REPORT_DIR.mkdir(exist_ok=True)
    with open(REPORT_DIR / "phase1_product_match.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "value"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nSaved: {REPORT_DIR / 'phase1_product_match.csv'}")


if __name__ == "__main__":
    main()

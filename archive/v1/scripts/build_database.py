"""Phase 2 - sql/staging 아래 SQL 파일을 실행해 DuckDB 데이터베이스에 staging 뷰를 만든다.

PROJECT_GUIDELINES.md 32번 디렉터리 구조의 `data/processed/crm.duckdb`를 사용한다.
staging 레이어는 VIEW로 생성해 원본 Parquet을 lazy하게 참조한다
(전체를 메모리에 올리지 않는다는 Phase 1 원칙 유지).
"""

from pathlib import Path

import duckdb
import yaml

CONFIG_PATH = Path("config/paths.yaml")

# int_customer_category_repurchase_by_snapshot은 이름이 알파벳순으로
# int_customer_observation_period/int_customer_purchase_history보다 앞에 와
# 의존성이 깨진다 (2026-08-08 추가, Model A/B 카테고리 재구매율 feature 근거
# 테이블). intermediate 레이어도 명시적 순서를 지정한다.
INTERMEDIATE_BUILD_ORDER = [
    "int_customer_observation_period.sql",
    "int_customer_purchase_gap.sql",
    "int_customer_purchase_history.sql",
    "int_customer_cart_behavior.sql",
    "int_customer_daily_activity.sql",
    "int_customer_category_behavior.sql",
    "int_customer_category_repurchase_by_snapshot.sql",
    "int_customer_category_repurchase_avg_by_snapshot.sql",
]

# 순수 알파벳 순서로는 의존성이 깨지는 파일이 있어(mart_churn_target,
# mart_purchase_propensity가 mart_customer_snapshot을 참조) 마트 레이어만
# 명시적 순서를 지정한다. 목록에 없는 파일은 이 뒤에 알파벳 순으로 이어붙인다.
MART_BUILD_ORDER = [
    "mart_customer_360.sql",
    "mart_customer_cohort.sql",
    "mart_customer_daily.sql",
    "mart_customer_lifecycle.sql",
    "mart_customer_retention.sql",
    "mart_customer_segment.sql",
    "mart_customer_snapshot.sql",
    "mart_customer_weekly.sql",
    "mart_churn_target.sql",
    "mart_purchase_propensity.sql",
]


def ordered_sql_files(layer_dir: Path, explicit_order: list[str] | None = None) -> list[Path]:
    all_files = sorted(layer_dir.glob("*.sql"))
    if not explicit_order:
        return all_files
    by_name = {f.name: f for f in all_files}
    ordered = [by_name.pop(name) for name in explicit_order if name in by_name]
    ordered.extend(sorted(by_name.values()))
    return ordered


def main() -> None:
    with open(CONFIG_PATH) as f:
        paths = yaml.safe_load(f)

    db_path = Path(paths["database_path"])
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path))

    # macros는 staging 뷰가 참조하므로(예: is_burst_repeat) staging보다
    # 먼저 생성돼야 한다. 알파벳순 glob에 맡기지 않고 레이어 자체를
    # staging 앞에 두어 순서를 보장한다.
    layer_dirs = [
        ("macros", Path(paths["sql_macros_dir"])),
        ("staging", Path(paths["sql_staging_dir"])),
        ("intermediate", Path(paths["sql_intermediate_dir"])),
        ("marts", Path(paths["sql_marts_dir"])),
    ]

    for layer_name, layer_dir in layer_dirs:
        if layer_name == "marts":
            explicit_order = MART_BUILD_ORDER
        elif layer_name == "intermediate":
            explicit_order = INTERMEDIATE_BUILD_ORDER
        else:
            explicit_order = None
        sql_files = ordered_sql_files(layer_dir, explicit_order)
        if not sql_files:
            continue
        print(f"\n=== {layer_name} 레이어 ===")
        for sql_file in sql_files:
            print(f"실행: {sql_file}")
            con.sql(sql_file.read_text())

    print("\n생성된 테이블/뷰:")
    objects = con.sql(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_name LIKE 'stg_%' OR table_name LIKE 'int_%' OR table_name LIKE 'mart_%' "
        "ORDER BY table_name"
    ).fetchall()
    for (name,) in objects:
        cnt = con.sql(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  - {name}: {cnt:,} rows")

    con.close()
    print(f"\nDatabase: {db_path}")


if __name__ == "__main__":
    main()

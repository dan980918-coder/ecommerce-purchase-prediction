"""Phase 2 staging 레이어 데이터 품질 테스트.

Phase 1에서 확인한 수치(reports/phase1_*.csv)와 staging 뷰 결과를 대조해
데이터 손실이나 왜곡이 없는지 확인한다.
"""

from pathlib import Path

import duckdb
import pytest
import yaml

CONFIG_PATH = Path("config/paths.yaml")


@pytest.fixture(scope="module")
def con():
    with open(CONFIG_PATH) as f:
        paths = yaml.safe_load(f)
    connection = duckdb.connect(str(paths["database_path"]), read_only=True)
    yield connection
    connection.close()


# Phase 1 8.2에서 확인한 원본 행 수 (reports/phase1_event_summary.csv)
EXPECTED_ROW_COUNTS = {
    "stg_product_buy": 2_318_502,
    "stg_add_to_cart": 7_541_117,
    "stg_remove_from_cart": 2_688_894,
    "stg_page_visit": 199_451_980,
    "stg_search_query": 13_223_769,
    "stg_product_properties": 1_534_050,
}

# Phase 1 8.6에서 확인한 버스트(5초 이내 반복) 비율 (reports/phase1_data_quality.csv)
EXPECTED_BURST_PCT = {
    "stg_product_buy": 16.4396,
    "stg_add_to_cart": 4.7168,
    "stg_remove_from_cart": 10.3020,
    "stg_page_visit": 16.6049,
    "stg_search_query": 13.0281,
}


@pytest.mark.parametrize("view_name,expected", EXPECTED_ROW_COUNTS.items())
def test_staging_row_count_matches_raw(con, view_name, expected):
    actual = con.sql(f"SELECT COUNT(*) FROM {view_name}").fetchone()[0]
    assert actual == expected, f"{view_name}: staging 행 수({actual})가 원본({expected})과 다름 — 데이터 손실/중복 의심"


@pytest.mark.parametrize("view_name,expected_pct", EXPECTED_BURST_PCT.items())
def test_burst_flag_pct_matches_phase1(con, view_name, expected_pct):
    total, burst = con.sql(
        f"SELECT COUNT(*), SUM(CASE WHEN is_burst_repeat_5s THEN 1 ELSE 0 END) FROM {view_name}"
    ).fetchone()
    actual_pct = burst / total * 100
    assert actual_pct == pytest.approx(expected_pct, abs=0.01), (
        f"{view_name}: 버스트 비율({actual_pct:.4f}%)이 Phase 1 결과({expected_pct}%)와 다름"
    )


@pytest.mark.parametrize(
    "view_name,cols",
    [
        ("stg_product_buy", ["client_id", "event_ts", "sku"]),
        ("stg_add_to_cart", ["client_id", "event_ts", "sku"]),
        ("stg_remove_from_cart", ["client_id", "event_ts", "sku"]),
        ("stg_page_visit", ["client_id", "event_ts", "url"]),
        ("stg_search_query", ["client_id", "event_ts", "query"]),
    ],
)
def test_no_nulls_in_key_columns(con, view_name, cols):
    for col in cols:
        n_null = con.sql(f"SELECT COUNT(*) FROM {view_name} WHERE {col} IS NULL").fetchone()[0]
        assert n_null == 0, f"{view_name}.{col}: NULL {n_null}건 발견 (Phase 1에서는 0건이었음)"


def test_timestamp_cast_no_parse_failures(con):
    for view_name in ["stg_product_buy", "stg_add_to_cart", "stg_remove_from_cart", "stg_page_visit", "stg_search_query"]:
        n_fail = con.sql(f"SELECT COUNT(*) FROM {view_name} WHERE event_ts IS NULL").fetchone()[0]
        assert n_fail == 0, f"{view_name}: event_ts 캐스팅 실패 {n_fail}건 (TRY_CAST가 NULL 반환)"


def test_product_properties_sku_is_unique_pk(con):
    total = con.sql("SELECT COUNT(*) FROM stg_product_properties").fetchone()[0]
    distinct_sku = con.sql("SELECT COUNT(DISTINCT sku) FROM stg_product_properties").fetchone()[0]
    assert total == distinct_sku, "stg_product_properties: sku가 PK로 유일하지 않음"


def test_product_properties_price_bucket_range(con):
    min_p, max_p = con.sql("SELECT MIN(price_bucket), MAX(price_bucket) FROM stg_product_properties").fetchone()
    assert min_p == 0 and max_p == 99, (
        f"price_bucket 범위가 Phase 1에서 확인한 0~99와 다름 (min={min_p}, max={max_p}) — "
        "실제 금액으로 오인되지 않도록 재확인 필요"
    )

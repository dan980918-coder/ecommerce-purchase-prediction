"""Phase 2 mart 레이어(의존성 없는 5개) 데이터 품질 테스트."""

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


@pytest.mark.parametrize(
    "table,pk_cols",
    [
        ("mart_customer_360", ["client_id"]),
        ("mart_customer_daily", ["client_id", "activity_date"]),
        ("mart_customer_weekly", ["client_id", "week_start"]),
        ("mart_customer_cohort", ["client_id"]),
        ("mart_customer_retention", ["cohort_week"]),
    ],
)
def test_pk_uniqueness(con, table, pk_cols):
    cols = ", ".join(pk_cols)
    total = con.sql(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    distinct = con.sql(f"SELECT COUNT(*) FROM (SELECT DISTINCT {cols} FROM {table})").fetchone()[0]
    assert total == distinct, f"{table}: PK({cols}) 유일하지 않음"


def test_mart_customer_360_row_count_matches_total_clients(con):
    n = con.sql("SELECT COUNT(*) FROM mart_customer_360").fetchone()[0]
    assert n == 22_298_361


def test_mart_customer_360_buyer_flag_matches_phase1(con):
    n = con.sql("SELECT COUNT(*) FROM mart_customer_360 WHERE is_buyer").fetchone()[0]
    assert n == 909_210


def test_mart_customer_360_cart_flag_matches_phase1(con):
    n = con.sql("SELECT COUNT(*) FROM mart_customer_360 WHERE has_cart_activity").fetchone()[0]
    assert n == 2_359_888


def test_mart_customer_360_repeat_capable_matches_phase1(con):
    n = con.sql("SELECT COUNT(*) FROM mart_customer_360 WHERE is_repeat_capable").fetchone()[0]
    assert n == 210_633


def test_mart_customer_cohort_row_count_matches_buyer_count(con):
    n = con.sql("SELECT COUNT(*) FROM mart_customer_cohort").fetchone()[0]
    assert n == 909_210


def test_mart_customer_retention_rates_between_0_and_1(con):
    row = con.sql(
        """
        SELECT MIN(repurchase_7d_rate), MAX(repurchase_7d_rate),
               MIN(repurchase_14d_rate), MAX(repurchase_14d_rate),
               MIN(repurchase_28d_rate), MAX(repurchase_28d_rate)
        FROM mart_customer_retention
        """
    ).fetchone()
    for v in row:
        assert 0.0 <= v <= 1.0, f"재구매율이 0~1 범위를 벗어남: {row}"


def test_mart_customer_retention_censoring_flags_present_near_window_end(con):
    # 관측 종료(2022-12-08)에 가장 가까운 코호트는 반드시 검열 플래그가 TRUE여야 함
    last_cohort = con.sql(
        "SELECT is_7d_window_censored, is_14d_window_censored, is_28d_window_censored "
        "FROM mart_customer_retention ORDER BY cohort_week DESC LIMIT 1"
    ).fetchone()
    assert all(last_cohort), f"마지막 코호트의 검열 플래그가 모두 TRUE가 아님: {last_cohort}"


def test_mart_customer_weekly_events_match_daily(con):
    daily_total = con.sql("SELECT SUM(n_events_total) FROM mart_customer_daily").fetchone()[0]
    weekly_total = con.sql("SELECT SUM(n_events_total) FROM mart_customer_weekly").fetchone()[0]
    assert daily_total == weekly_total, "주간 롤업 합계가 일별 합계와 다름 — 집계 누락 의심"

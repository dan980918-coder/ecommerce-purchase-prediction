"""Phase 4 mart_customer_lifecycle 데이터 품질 테스트."""

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


def test_pk_uniqueness(con):
    total = con.sql("SELECT COUNT(*) FROM mart_customer_lifecycle").fetchone()[0]
    distinct = con.sql("SELECT COUNT(DISTINCT client_id) FROM mart_customer_lifecycle").fetchone()[0]
    assert total == distinct == 22_298_361


def test_no_unclassified_customers(con):
    n = con.sql("SELECT COUNT(*) FROM mart_customer_lifecycle WHERE lifecycle_stage = '기타'").fetchone()[0]
    assert n == 0, f"미분류('기타') 고객 {n}명 발견 — 상태 분류 로직에 누락된 케이스가 있음"


def test_no_null_lifecycle_stage(con):
    n = con.sql("SELECT COUNT(*) FROM mart_customer_lifecycle WHERE lifecycle_stage IS NULL").fetchone()[0]
    assert n == 0


def test_buyer_states_sum_to_buyer_count(con):
    buyer_states = ["첫_관측_구매_고객", "복귀_고객", "활성_구매_고객", "구매_감소_고객", "구매_비활성_위험_고객", "비활성_고객"]
    placeholders = ", ".join(f"'{s}'" for s in buyer_states)
    n = con.sql(f"SELECT COUNT(*) FROM mart_customer_lifecycle WHERE lifecycle_stage IN ({placeholders})").fetchone()[0]
    assert n == 909_210, f"구매 관련 상태 합계 불일치: {n} (기대 909,210)"


def test_non_buyer_states_sum_to_non_buyer_count(con):
    n = con.sql(
        "SELECT COUNT(*) FROM mart_customer_lifecycle WHERE lifecycle_stage IN ('탐색_고객', '장바구니_고객')"
    ).fetchone()[0]
    assert n == 22_298_361 - 909_210, f"비구매 상태 합계 불일치: {n}"


def test_days_since_last_purchase_non_negative_for_buyers(con):
    n = con.sql(
        "SELECT COUNT(*) FROM mart_customer_lifecycle WHERE is_buyer AND days_since_last_purchase < 0"
    ).fetchone()[0]
    assert n == 0, f"음수 recency {n}건 — 시간 정렬 오류 의심"

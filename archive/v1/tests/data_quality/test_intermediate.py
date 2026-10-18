"""Phase 2 intermediate 레이어 데이터 품질 테스트.

Grain/PK 유일성과 Phase 1 검증 수치와의 교차검증(cross-check)을 확인한다.
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


# --- Grain/PK 유일성 ---

@pytest.mark.parametrize(
    "table,pk_cols",
    [
        ("int_customer_purchase_gap", ["client_id"]),
        ("int_customer_observation_period", ["client_id"]),
        ("int_customer_cart_behavior", ["client_id"]),
        ("int_customer_category_behavior", ["client_id", "category"]),
        ("int_customer_daily_activity", ["client_id", "activity_date"]),
    ],
)
def test_pk_uniqueness(con, table, pk_cols):
    cols = ", ".join(pk_cols)
    total = con.sql(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    distinct = con.sql(f"SELECT COUNT(*) FROM (SELECT DISTINCT {cols} FROM {table})").fetchone()[0]
    assert total == distinct, f"{table}: PK({cols})가 유일하지 않음 (전체 {total}, 고유 {distinct})"


# --- Phase 1 수치와 교차검증 (reports/phase1_*.csv 근거) ---

def test_purchase_gap_row_count_matches_buyer_count(con):
    n = con.sql("SELECT COUNT(*) FROM int_customer_purchase_gap").fetchone()[0]
    assert n == 909_210, f"구매 고객 수 불일치: {n} (Phase 1: 909,210)"


def test_purchase_history_row_count_matches_raw(con):
    n = con.sql("SELECT COUNT(*) FROM int_customer_purchase_history").fetchone()[0]
    assert n == 2_318_502, f"purchase_history 행 수 불일치: {n} (원본 product_buy: 2,318,502)"


def test_observation_period_row_count_matches_total_clients(con):
    n = con.sql("SELECT COUNT(*) FROM int_customer_observation_period").fetchone()[0]
    assert n == 22_298_361, f"전체 고객 수 불일치: {n} (Phase 1 8.4: 22,298,361)"


def test_cart_behavior_row_count_matches_union(con):
    # 8.4: add_to_cart 고객 2,333,463 + remove_from_cart 고객 694,391 - 교집합 667,966
    n = con.sql("SELECT COUNT(*) FROM int_customer_cart_behavior").fetchone()[0]
    expected = 2_333_463 + 694_391 - 667_966
    assert n == expected, f"cart_behavior 고객 수 불일치: {n} (기대값 {expected})"


def test_purchase_gap_pooled_mean_matches_phase1(con):
    # int_customer_purchase_history의 occasion-level days_since_prev_purchase_occasion을
    # 풀링(pooled)해서 평균/중앙값을 냈을 때 Phase 1 8.7 결과(mean=22.9463, median=9.4827)와
    # 같아야 함. 동일 client_id+event_ts(같은 결제의 여러 줄)는 distinct 처리 후
    # occasion 단위로 계산되므로, 여기서도 distinct해서 풀링해야 중복 카운트를 피한다.
    # median()(정확 계산)을 사용한다 — approx_quantile은 근사 스케치 알고리즘이라
    # 동일 데이터에서도 실행마다 9~10 사이로 결과가 흔들려(비결정적) 테스트가
    # 간헐적으로 실패했다. 이 쿼리 규모에서는 정확 median도 성능 문제가 없다.
    mean_gap, median_gap = con.sql(
        """
        SELECT AVG(days_since_prev_purchase_occasion), median(days_since_prev_purchase_occasion)
        FROM (
            SELECT DISTINCT client_id, event_ts, days_since_prev_purchase_occasion
            FROM int_customer_purchase_history
        )
        WHERE days_since_prev_purchase_occasion IS NOT NULL
        """
    ).fetchone()
    assert mean_gap == pytest.approx(22.9463, abs=0.01), f"pooled mean gap 불일치: {mean_gap}"
    assert median_gap == pytest.approx(9.4827, abs=0.5), f"pooled median gap 불일치: {median_gap}"




def test_daily_activity_total_events_matches_raw_sum(con):
    total = con.sql(
        "SELECT SUM(n_events_total) FROM int_customer_daily_activity"
    ).fetchone()[0]
    # Phase 1: product_buy 2,318,502 + add_to_cart 7,541,117 + remove_from_cart 2,688,894
    #        + page_visit 199,451,980 + search_query 13,223,769
    expected = 2_318_502 + 7_541_117 + 2_688_894 + 199_451_980 + 13_223_769
    assert total == expected, f"일별 활동 합계가 원본 이벤트 총합과 다름: {total} (기대값 {expected})"


def test_category_behavior_no_null_category(con):
    n_null = con.sql(
        "SELECT COUNT(*) FROM int_customer_category_behavior WHERE category IS NULL"
    ).fetchone()[0]
    assert n_null == 0, (
        f"category NULL {n_null}건 — Phase 1 8.5에서 구매↔속성 매칭률 100%였는데 "
        "intermediate 레이어에서 매칭 깨짐 의심"
    )


def test_no_future_leakage_in_purchase_history(con):
    # 미래 정보 누수 방지: days_since_prev_purchase_occasion은 항상 0 이상이어야 함
    # (LAG가 항상 과거 시점을 가리키므로 event_ts 정렬이 깨지지 않았는지 확인)
    n_negative = con.sql(
        "SELECT COUNT(*) FROM int_customer_purchase_history WHERE days_since_prev_purchase_occasion < 0"
    ).fetchone()[0]
    assert n_negative == 0, f"음수 구매 간격 {n_negative}건 발견 — 시간 정렬 오류 의심"

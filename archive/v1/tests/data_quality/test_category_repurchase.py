"""카테고리별 재구매율 feature 데이터 품질 테스트 (2026-08-08 추가).

PROJECT_GUIDELINES.md 9번 "미래 정보 누수 방지 테스트를 작성한다" 적용 대상.
int_customer_category_repurchase_by_snapshot이 snapshot_date마다 그 시점
이전 데이터로만 재계산됐는지, 최소 표본 기준이 실제로 지켜졌는지,
mart_customer_snapshot/mart_purchase_propensity의 avg_category_repurchase_rate가
합리적 범위인지 검증한다.
"""

from pathlib import Path

import duckdb
import pytest
import yaml

CONFIG_PATH = Path("config/paths.yaml")
MIN_SAMPLE = 100


@pytest.fixture(scope="module")
def con():
    with open(CONFIG_PATH) as f:
        paths = yaml.safe_load(f)
    connection = duckdb.connect(str(paths["database_path"]), read_only=True)
    yield connection
    connection.close()


def test_min_sample_threshold_enforced(con):
    n = con.sql(
        f"SELECT COUNT(*) FROM int_customer_category_repurchase_by_snapshot WHERE n_customers < {MIN_SAMPLE}"
    ).fetchone()[0]
    assert n == 0, f"최소 표본 기준({MIN_SAMPLE}명) 미달 행이 {n}건 존재 — HAVING 필터 누락 의심"


def test_repurchase_rate_between_0_and_1(con):
    row = con.sql(
        "SELECT MIN(repurchase_rate), MAX(repurchase_rate) FROM int_customer_category_repurchase_by_snapshot"
    ).fetchone()
    assert 0 <= row[0] and row[1] <= 1


def test_repurchase_customers_not_exceed_total(con):
    n = con.sql(
        "SELECT COUNT(*) FROM int_customer_category_repurchase_by_snapshot "
        "WHERE n_repurchase_customers > n_customers"
    ).fetchone()[0]
    assert n == 0


def test_category_customer_count_non_decreasing_over_snapshots(con):
    """미래 누수 방지 간접 검증: snapshot_date가 늦을수록(누적 이력이 더 길수록)
    같은 카테고리의 n_customers는 절대 줄어들 수 없어야 한다 — event_ts <
    snapshot_date 조건이 실제로 매 snapshot마다 다시 적용됐는지 확인."""
    violations = con.sql(
        """
        WITH ordered AS (
            SELECT
                category, snapshot_date, n_customers,
                LAG(n_customers) OVER (PARTITION BY category ORDER BY snapshot_date) AS prev_n
            FROM int_customer_category_repurchase_by_snapshot
        )
        SELECT COUNT(*) FROM ordered WHERE prev_n IS NOT NULL AND n_customers < prev_n
        """
    ).fetchone()[0]
    assert violations == 0, (
        f"{violations}개 (category, snapshot_date) 조합에서 n_customers가 이전 snapshot보다 감소함 — "
        "누적 이력이 아니라 특정 시점 데이터만 반영됐거나 미래 데이터가 섞였을 가능성"
    )


def test_avg_category_repurchase_rate_range_in_snapshot(con):
    row = con.sql(
        "SELECT MIN(avg_category_repurchase_rate), MAX(avg_category_repurchase_rate) "
        "FROM mart_customer_snapshot WHERE avg_category_repurchase_rate IS NOT NULL"
    ).fetchone()
    assert 0 <= row[0] and row[1] <= 1


def test_avg_category_repurchase_rate_range_in_propensity(con):
    row = con.sql(
        "SELECT MIN(avg_category_repurchase_rate), MAX(avg_category_repurchase_rate) "
        "FROM mart_purchase_propensity WHERE avg_category_repurchase_rate IS NOT NULL"
    ).fetchone()
    assert 0 <= row[0] and row[1] <= 1


def test_no_purchase_history_implies_null_in_propensity(con):
    # 구매 이력이 없는 후보 고객은 카테고리 자체가 없으므로 반드시 NULL이어야 함
    n = con.sql(
        "SELECT COUNT(*) FROM mart_purchase_propensity "
        "WHERE NOT has_purchase_history AND avg_category_repurchase_rate IS NOT NULL"
    ).fetchone()[0]
    assert n == 0


def test_row_counts_unchanged_by_feature_addition(con):
    # avg_category_repurchase_rate 추가가 LEFT JOIN 중복으로 행을 늘리지 않았는지 확인.
    # n_propensity 기대값은 2026-08-08 search_first 통일(mart_purchase_propensity.sql)로
    # 22,277,058 -> 21,119,640으로 갱신됨(모집단 조건 변경 — docs/methodology.md 참고,
    # LEFT JOIN 중복 문제와는 무관).
    n_snapshot = con.sql("SELECT COUNT(*) FROM mart_customer_snapshot").fetchone()[0]
    n_churn = con.sql("SELECT COUNT(*) FROM mart_churn_target").fetchone()[0]
    n_propensity = con.sql("SELECT COUNT(*) FROM mart_purchase_propensity").fetchone()[0]
    assert n_snapshot == 4_196_385
    assert n_churn == 4_196_385
    assert n_propensity == 21_119_640

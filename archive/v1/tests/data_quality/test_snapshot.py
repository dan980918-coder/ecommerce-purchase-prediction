"""Phase 5 mart_customer_snapshot 데이터 품질 테스트.

PROJECT_GUIDELINES.md 31번 "Snapshot Feature·Label 분리" 테스트 항목 구현.
docs/methodology.md 2026-08-05 "우측 검열 고객 처리 방침" 결정에서 약속한
안전장치(snapshot_date + label_window <= 관측 종료일)를 여기서 검증한다.
"""

from pathlib import Path

import duckdb
import pytest
import yaml

CONFIG_PATH = Path("config/paths.yaml")
LABEL_WINDOW_DAYS = 28  # 두 라벨 중 더 엄격한 쪽 (14일은 자동으로 안전)


@pytest.fixture(scope="module")
def con():
    with open(CONFIG_PATH) as f:
        paths = yaml.safe_load(f)
    connection = duckdb.connect(str(paths["database_path"]), read_only=True)
    yield connection
    connection.close()


def test_pk_uniqueness(con):
    total = con.sql("SELECT COUNT(*) FROM mart_customer_snapshot").fetchone()[0]
    distinct = con.sql(
        "SELECT COUNT(*) FROM (SELECT DISTINCT client_id, snapshot_date FROM mart_customer_snapshot)"
    ).fetchone()[0]
    assert total == distinct


def test_no_negative_or_null_recency(con):
    n = con.sql(
        "SELECT COUNT(*) FROM mart_customer_snapshot "
        "WHERE days_since_last_purchase IS NULL OR days_since_last_purchase < 0"
    ).fetchone()[0]
    assert n == 0, f"recency 결측/음수 {n}건 — feature leakage 또는 조인 오류 의심"


def test_no_label_window_censoring(con):
    """안전장치: 모든 snapshot_date에 대해 라벨 계산 구간이 실제 관측 범위를
    벗어나지 않아야 한다 (docs/methodology.md 2026-08-05 결정 사항)."""
    window_max = con.sql(
        "SELECT MAX(last_event_ts) FROM int_customer_observation_period"
    ).fetchone()[0]
    violating = con.sql(
        f"""
        SELECT COUNT(DISTINCT snapshot_date) FROM mart_customer_snapshot
        WHERE snapshot_date + INTERVAL {LABEL_WINDOW_DAYS} DAY > TIMESTAMP '{window_max}'
        """
    ).fetchone()[0]
    assert violating == 0, (
        f"{violating}개 snapshot_date의 라벨 기간이 관측 종료일({window_max})을 벗어남 — "
        "우측 검열 방지 설계가 깨짐"
    )


def test_feature_window_no_future_leakage(con):
    # 이전 로직에서 사용한 event_ts < snapshot_date 조건이 지켜졌는지 간접 검증:
    # n_purchases_7d <= n_purchases_14d <= n_purchases_28d <= n_purchase_occasions_so_far
    n_violation = con.sql(
        """
        SELECT COUNT(*) FROM mart_customer_snapshot
        WHERE NOT (n_purchases_7d <= n_purchases_14d
                   AND n_purchases_14d <= n_purchases_28d
                   AND n_purchases_28d <= n_purchase_occasions_so_far)
        """
    ).fetchone()[0]
    assert n_violation == 0, f"구매 feature 단조성 위반 {n_violation}건 — 집계 오류 의심"


def test_label_rates_between_0_and_1(con):
    row = con.sql(
        "SELECT MIN(label_purchase_14d), MAX(label_purchase_14d), "
        "MIN(label_purchase_28d), MAX(label_purchase_28d) FROM mart_customer_snapshot"
    ).fetchone()
    assert all(v in (0, 1) for v in row)


def test_label_28d_consistent_with_inactive_flag(con):
    n = con.sql(
        "SELECT COUNT(*) FROM mart_customer_snapshot "
        "WHERE (label_purchase_28d = 0) != label_inactive_28d"
    ).fetchone()[0]
    assert n == 0


def test_row_count_matches_expected_spine(con):
    n = con.sql("SELECT COUNT(*) FROM mart_customer_snapshot").fetchone()[0]
    assert n == 4_196_385


def test_9_snapshot_dates(con):
    n = con.sql("SELECT COUNT(DISTINCT snapshot_date) FROM mart_customer_snapshot").fetchone()[0]
    assert n == 9

"""Phase 5 mart_churn_target, mart_purchase_propensity 데이터 품질 테스트."""

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


# --- mart_churn_target ---

def test_churn_target_matches_snapshot_row_count(con):
    n = con.sql("SELECT COUNT(*) FROM mart_churn_target").fetchone()[0]
    assert n == 4_196_385


def test_churn_target_pk_uniqueness(con):
    total = con.sql("SELECT COUNT(*) FROM mart_churn_target").fetchone()[0]
    distinct = con.sql(
        "SELECT COUNT(*) FROM (SELECT DISTINCT client_id, snapshot_date FROM mart_churn_target)"
    ).fetchone()[0]
    assert total == distinct


def test_churn_target_consistent_with_snapshot_labels(con):
    n_mismatch = con.sql(
        """
        SELECT COUNT(*) FROM mart_churn_target t
        JOIN mart_customer_snapshot s
          ON t.client_id = s.client_id AND t.snapshot_date = s.snapshot_date
        WHERE t.churn_14d != s.label_inactive_14d OR t.churn_28d != s.label_inactive_28d
        """
    ).fetchone()[0]
    assert n_mismatch == 0


# --- mart_purchase_propensity ---

def test_propensity_pk_uniqueness(con):
    total = con.sql("SELECT COUNT(*) FROM mart_purchase_propensity").fetchone()[0]
    distinct = con.sql(
        "SELECT COUNT(*) FROM (SELECT DISTINCT client_id, snapshot_date FROM mart_purchase_propensity)"
    ).fetchone()[0]
    assert total == distinct


def test_propensity_includes_non_buyers(con):
    # Model B는 churn_target(구매 이력자만)보다 넓은 모집단이어야 함 —
    # 그렇지 않으면 churn 라벨의 단순 반전에 불과해 별도 모델 의미가 없음
    n_no_history = con.sql(
        "SELECT COUNT(*) FROM mart_purchase_propensity WHERE NOT has_purchase_history"
    ).fetchone()[0]
    assert n_no_history > 0, "구매 이력 없는 고객이 전혀 포함되지 않음 — Model B 모집단이 Model A와 동일해짐"


def test_propensity_recency_consistency(con):
    n = con.sql(
        """
        SELECT COUNT(*) FROM mart_purchase_propensity
        WHERE (has_purchase_history AND days_since_last_purchase IS NULL)
           OR (NOT has_purchase_history AND days_since_last_purchase IS NOT NULL)
           OR (days_since_last_purchase < 0)
        """
    ).fetchone()[0]
    assert n == 0


def test_propensity_no_label_window_censoring(con):
    window_max = con.sql(
        "SELECT MAX(last_event_ts) FROM int_customer_observation_period"
    ).fetchone()[0]
    violating = con.sql(
        f"""
        SELECT COUNT(DISTINCT snapshot_date) FROM mart_purchase_propensity
        WHERE snapshot_date + INTERVAL 28 DAY > TIMESTAMP '{window_max}'
        """
    ).fetchone()[0]
    assert violating == 0


def test_propensity_label_rates_between_0_and_1(con):
    row = con.sql(
        "SELECT MIN(will_purchase_14d), MAX(will_purchase_14d), "
        "MIN(will_purchase_28d), MAX(will_purchase_28d) FROM mart_purchase_propensity"
    ).fetchone()
    assert all(v in (0, 1) for v in row)


def test_propensity_broader_population_than_churn_target(con):
    n_prop = con.sql("SELECT COUNT(*) FROM mart_purchase_propensity").fetchone()[0]
    n_churn = con.sql("SELECT COUNT(*) FROM mart_churn_target").fetchone()[0]
    assert n_prop > n_churn

"""Phase 7 mart_targeting_simulation 데이터 품질 테스트."""

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


def test_row_count(con):
    n = con.sql("SELECT COUNT(*) FROM mart_targeting_simulation").fetchone()[0]
    assert n == 72


def test_contact_rate_and_recall_selected_customers_match_pct(con):
    n = con.sql(
        """
        SELECT COUNT(*) FROM mart_targeting_simulation
        WHERE policy NOT LIKE '모델_vs%'
          AND ABS(n_selected * 1.0 / n_total * 100 - contact_rate_pct) > 0.01
        """
    ).fetchone()[0]
    assert n == 0, "선정 인원 비율이 접촉 비율과 일치하지 않음"


def test_model_recall_gte_random_recall(con):
    # 모델 정책의 recall이 동일 접촉 비율의 무작위 정책보다 항상 높아야 함
    n = con.sql(
        """
        WITH model AS (
            SELECT model, label, contact_rate_pct, recall
            FROM mart_targeting_simulation WHERE policy = '모델_LightGBM'
        ),
        rand AS (
            SELECT model, label, contact_rate_pct, recall
            FROM mart_targeting_simulation WHERE policy = '무작위'
        )
        SELECT COUNT(*) FROM model m
        JOIN rand r USING (model, label, contact_rate_pct)
        WHERE m.recall <= r.recall
        """
    ).fetchone()[0]
    assert n == 0, "모델의 recall이 무작위보다 낮거나 같은 경우 발견"


def test_contact_reduction_non_negative_for_propensity(con):
    n = con.sql(
        """
        SELECT COUNT(*) FROM mart_targeting_simulation
        WHERE model = 'Model_B_propensity' AND policy LIKE '모델_vs%'
          AND contact_reduction_pct < 0
        """
    ).fetchone()[0]
    assert n == 0, "Model B에서 모델이 규칙보다 비효율적인(음수 절감률) 사례 발견"


def test_four_contact_rates_present(con):
    rates = con.sql("SELECT DISTINCT contact_rate_pct FROM mart_targeting_simulation ORDER BY 1").df()
    assert list(rates["contact_rate_pct"]) == [5, 10, 20, 30]

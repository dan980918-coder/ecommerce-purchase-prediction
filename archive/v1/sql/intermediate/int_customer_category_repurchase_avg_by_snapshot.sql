-- Grain: 1 row = 1 고객 x 1 snapshot_date (snapshot_date 이전 구매 이력이 있는 고객만)
-- Primary Key: (client_id, snapshot_date)
--
-- 목적: 고객 단위 feature "이 고객이 구매한 카테고리들의 평균 재구매율"을
-- mart_customer_snapshot(Model A)과 mart_purchase_propensity(Model B) 양쪽이
-- 동일 정의로 재사용하기 위한 lookup. 원래 각 mart 파일 안에 인라인 CTE로
-- 넣었으나, mart_purchase_propensity.sql의 기존 무거운 조인
-- (activity_before, 46.9M행 int_customer_daily_activity 기반)과 한 쿼리
-- 플랜 안에서 합쳐지면서 8GB 메모리 환경에서 OOM이 발생해 별도 테이블로
-- 분리했다 — 계산을 한 번만 하고 양쪽 mart는 가벼운 LEFT JOIN만 하면 되므로
-- 중복 계산도 줄어드는 부수 효과가 있다.
--
-- 미래 정보 누수 방지: int_customer_category_repurchase_by_snapshot 자체가
-- snapshot_date별로 그 시점 이전 데이터로만 계산되므로, 여기서도 고객의
-- snapshot_date 이전 구매 occasion만 사용한다.
--
-- 입력: int_customer_purchase_history, stg_product_properties,
--       int_customer_category_repurchase_by_snapshot, int_customer_observation_period
-- 출력: mart_customer_snapshot, mart_purchase_propensity
CREATE OR REPLACE TABLE int_customer_category_repurchase_avg_by_snapshot AS
WITH bounds AS (
    SELECT MAX(last_event_ts) AS window_max, MIN(first_event_ts) AS window_min
    FROM int_customer_observation_period
),
snapshot_dates AS (
    SELECT CAST(gs AS DATE) AS snapshot_date
    FROM bounds, generate_series(
        CAST(window_min AS DATE) + INTERVAL 28 DAY,
        CAST(window_max AS DATE) - INTERVAL 28 DAY,
        INTERVAL 14 DAY
    ) AS t(gs)
),
cat_occasions AS (
    SELECT DISTINCT h.client_id, pp.category, h.event_ts
    FROM int_customer_purchase_history h
    JOIN stg_product_properties pp ON h.sku = pp.sku
),
client_categories AS (
    SELECT DISTINCT sd.snapshot_date, co.client_id, co.category
    FROM snapshot_dates sd
    JOIN cat_occasions co ON co.event_ts < sd.snapshot_date
)
SELECT
    cc.snapshot_date,
    cc.client_id,
    AVG(cr.repurchase_rate) AS avg_category_repurchase_rate
FROM client_categories cc
LEFT JOIN int_customer_category_repurchase_by_snapshot cr
    ON cc.snapshot_date = cr.snapshot_date AND cc.category = cr.category
GROUP BY cc.snapshot_date, cc.client_id;

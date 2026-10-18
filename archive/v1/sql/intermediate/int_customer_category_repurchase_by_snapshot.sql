-- Grain: 1 row = 1 snapshot_date x 1 category (해당 시점 기준 표본 100명 이상인 카테고리만)
-- Primary Key: (snapshot_date, category)
--
-- 목적: Phase 6 Model A/B feature "고객이 구매한 카테고리들의 평균 재구매율"의
-- 근거 테이블. 카테고리별 재구매율 검증(reports/phase3_funnel_analysis.md
-- 정정, reports/adhoc_category_repurchase_rate_n100plus.csv)에서 카테고리 간
-- 재구매율 차이가 실제로 유의미함을 확인해(z=95.9, 55.5 등) feature로 승격했다.
--
-- 미래 정보 누수 방지(PROJECT_GUIDELINES.md 12번): 카테고리 재구매율을 전체 기간
-- 통합으로 한 번만 계산하지 않고, snapshot_date마다 그 시점 이전(event_ts <
-- snapshot_date) 구매 occasion만으로 다시 계산한다. 그렇지 않으면 특정
-- 고객의 미래(snapshot_date 이후) 재구매가 그 고객 자신의 feature 값에
-- 스며드는 문제가 생긴다.
--
-- 최소 표본 기준: snapshot_date 시점까지 해당 카테고리 구매 고객이 100명
-- 미만이면 제외한다(adhoc 분석 근거: p~0.2 기준 95% CI 오차범위 약 ±8%p로
-- 통상 허용 가능한 하한선). 제외된 카테고리는 고객 feature 계산 시
-- LEFT JOIN으로 인해 해당 카테고리 기여분만 NULL 처리되고, 나머지 카테고리로
-- 평균이 계산된다(AVG는 NULL을 무시).
--
-- 셀프 포함 편향: 카테고리 통계에 그 고객 자신의 과거 occasion도 포함되지만,
-- 최소 표본이 100명이므로 한 고객의 기여는 통계치를 최대 1%p만 흔든다 —
-- leave-one-out까지는 하지 않는 합리적 기본값 처리(docs/decisions_pending_review.md).
--
-- 입력: int_customer_purchase_history, stg_product_properties, int_customer_observation_period
-- 출력: mart_customer_snapshot, mart_purchase_propensity
CREATE OR REPLACE TABLE int_customer_category_repurchase_by_snapshot AS
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
client_cat_occasion_count AS (
    SELECT
        sd.snapshot_date,
        co.client_id,
        co.category,
        COUNT(DISTINCT co.event_ts) AS n_occasions_before_snapshot
    FROM snapshot_dates sd
    JOIN cat_occasions co ON co.event_ts < sd.snapshot_date
    GROUP BY sd.snapshot_date, co.client_id, co.category
)
SELECT
    snapshot_date,
    category,
    COUNT(*) AS n_customers,
    SUM(CASE WHEN n_occasions_before_snapshot >= 2 THEN 1 ELSE 0 END) AS n_repurchase_customers,
    AVG(CASE WHEN n_occasions_before_snapshot >= 2 THEN 1.0 ELSE 0.0 END) AS repurchase_rate
FROM client_cat_occasion_count
GROUP BY snapshot_date, category
HAVING COUNT(*) >= 100;

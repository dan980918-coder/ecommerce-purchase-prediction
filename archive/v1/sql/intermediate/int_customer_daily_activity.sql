-- Grain: 1 row = 1 고객 x 1 활동일(activity_date)
-- Primary Key: (client_id, activity_date)
-- 입력: stg_product_buy, stg_add_to_cart, stg_remove_from_cart, stg_page_visit, stg_search_query
-- 출력: Phase 3(활동 리텐션), Phase 5(feature 계산의 일별 롤업 기반)
CREATE OR REPLACE TABLE int_customer_daily_activity AS
WITH unioned AS (
    SELECT client_id, CAST(event_ts AS DATE) AS activity_date, 'page_visit' AS event_type FROM stg_page_visit
    UNION ALL
    SELECT client_id, CAST(event_ts AS DATE), 'search_query' FROM stg_search_query
    UNION ALL
    SELECT client_id, CAST(event_ts AS DATE), 'add_to_cart' FROM stg_add_to_cart
    UNION ALL
    SELECT client_id, CAST(event_ts AS DATE), 'remove_from_cart' FROM stg_remove_from_cart
    UNION ALL
    SELECT client_id, CAST(event_ts AS DATE), 'product_buy' FROM stg_product_buy
)
SELECT
    client_id,
    activity_date,
    SUM(CASE WHEN event_type = 'page_visit' THEN 1 ELSE 0 END) AS n_page_visit,
    SUM(CASE WHEN event_type = 'search_query' THEN 1 ELSE 0 END) AS n_search_query,
    SUM(CASE WHEN event_type = 'add_to_cart' THEN 1 ELSE 0 END) AS n_add_to_cart,
    SUM(CASE WHEN event_type = 'remove_from_cart' THEN 1 ELSE 0 END) AS n_remove_from_cart,
    SUM(CASE WHEN event_type = 'product_buy' THEN 1 ELSE 0 END) AS n_product_buy,
    COUNT(*) AS n_events_total,
    COUNT(DISTINCT event_type) AS n_event_types_active
FROM unioned
GROUP BY client_id, activity_date;

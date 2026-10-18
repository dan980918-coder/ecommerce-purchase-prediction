-- Grain: 1 row = 1 고객 x 1 활동주(week_start, 월요일 기준)
-- Primary Key: (client_id, week_start)
-- 목적: 주 단위 활동 롤업 (Phase 3 코호트·리텐션의 "주차" 계산 기준 단위)
-- 입력: int_customer_daily_activity
-- 출력: Phase 3(코호트/리텐션), Phase 5 feature
CREATE OR REPLACE TABLE mart_customer_weekly AS
SELECT
    client_id,
    date_trunc('week', activity_date) AS week_start,
    SUM(n_page_visit) AS n_page_visit,
    SUM(n_search_query) AS n_search_query,
    SUM(n_add_to_cart) AS n_add_to_cart,
    SUM(n_remove_from_cart) AS n_remove_from_cart,
    SUM(n_product_buy) AS n_product_buy,
    SUM(n_events_total) AS n_events_total,
    COUNT(DISTINCT activity_date) AS n_active_days_in_week
FROM int_customer_daily_activity
GROUP BY client_id, date_trunc('week', activity_date);

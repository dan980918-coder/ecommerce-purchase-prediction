-- Grain: 1 row = 1 고객 (5개 이벤트 중 하나라도 있는 전체 고객)
-- Primary Key: client_id
-- 목적: 고객별 전체 활동 요약 (라이프사이클/세그먼트 등 판단 기준에 의존하지 않는
--   순수 집계 지표만 포함). Phase 4 이후 lifecycle/segment 컬럼이 여기에
--   추가될 예정이나, 그 전까지는 이 마트가 최종본이 아니라 "확정 가능한 부분"만
--   담은 중간 산출물임을 문서에 명시한다.
-- 입력: int_customer_observation_period, int_customer_purchase_gap,
--       int_customer_cart_behavior, stg_page_visit, stg_search_query
-- 출력: Phase 4(lifecycle/segment 컬럼 추가), Phase 7 대시보드 Overview 페이지
CREATE OR REPLACE TABLE mart_customer_360 AS
WITH visit_summary AS (
    SELECT client_id, COUNT(*) AS n_page_visit, MIN(event_ts) AS first_visit_ts, MAX(event_ts) AS last_visit_ts
    FROM stg_page_visit GROUP BY client_id
),
search_summary AS (
    SELECT client_id, COUNT(*) AS n_search_query
    FROM stg_search_query GROUP BY client_id
)
SELECT
    op.client_id,
    op.first_event_ts,
    op.last_event_ts,
    op.observation_days,
    op.n_active_days,
    op.is_left_censor_candidate,
    op.is_right_censor_candidate,
    COALESCE(v.n_page_visit, 0) AS n_page_visit,
    COALESCE(s.n_search_query, 0) AS n_search_query,
    COALESCE(cb.n_add, 0) AS n_add_to_cart,
    COALESCE(cb.n_remove, 0) AS n_remove_from_cart,
    COALESCE(pg.n_purchases, 0) AS n_purchases,
    COALESCE(pg.n_purchase_days, 0) AS n_purchase_days,
    pg.first_purchase_ts,
    pg.last_purchase_ts,
    pg.avg_purchase_gap_days,
    (pg.client_id IS NOT NULL) AS is_buyer,
    (cb.client_id IS NOT NULL) AS has_cart_activity,
    COALESCE(pg.n_purchase_days >= 2, FALSE) AS is_repeat_capable
FROM int_customer_observation_period op
LEFT JOIN visit_summary v ON op.client_id = v.client_id
LEFT JOIN search_summary s ON op.client_id = s.client_id
LEFT JOIN int_customer_cart_behavior cb ON op.client_id = cb.client_id
LEFT JOIN int_customer_purchase_gap pg ON op.client_id = pg.client_id;

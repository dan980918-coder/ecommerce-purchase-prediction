-- Grain: 1 row = 1 cohort_week (첫 관측 구매 주차)
-- Primary Key: cohort_week
-- 목적: 코호트별 7/14/28일 재구매율 (PROJECT_GUIDELINES.md 14번에 이미 고정된 지표).
--
-- 주의(우측 검열): 관측 종료일에 가까운 cohort_week는 N일 재구매 관측 창
-- 자체가 실제 데이터 범위를 벗어난다 (예: 관측 종료 10일 전에 첫 구매한
-- 코호트는 28일 재구매 여부를 절대 알 수 없음). 이를 숨기지 않고
-- is_7d/14d/28d_window_censored 플래그로 명시한다 (합리적 기본값 처리 —
-- docs/decisions_pending_review.md에 기록). 이 플래그가 TRUE인 코호트의
-- 재구매율은 과소추정된 값이므로 Phase 3 해석 시 별도 표시가 필요하다.
--
-- 입력: mart_customer_cohort, int_customer_purchase_history, int_customer_category_behavior
-- 출력: Phase 3 코호트·리텐션 분석, Phase 7 대시보드
CREATE OR REPLACE TABLE mart_customer_retention AS
WITH occasions AS (
    SELECT DISTINCT client_id, event_ts FROM int_customer_purchase_history
),
window_bounds AS (
    SELECT MAX(last_event_ts) AS window_max FROM int_customer_observation_period
),
repurchase_flags AS (
    SELECT
        c.client_id,
        c.cohort_week,
        c.n_purchase_days,
        MAX(CASE WHEN o.event_ts > c.first_purchase_ts
                  AND o.event_ts <= c.first_purchase_ts + INTERVAL '7 days'
             THEN 1 ELSE 0 END) AS repurchase_7d,
        MAX(CASE WHEN o.event_ts > c.first_purchase_ts
                  AND o.event_ts <= c.first_purchase_ts + INTERVAL '14 days'
             THEN 1 ELSE 0 END) AS repurchase_14d,
        MAX(CASE WHEN o.event_ts > c.first_purchase_ts
                  AND o.event_ts <= c.first_purchase_ts + INTERVAL '28 days'
             THEN 1 ELSE 0 END) AS repurchase_28d
    FROM mart_customer_cohort c
    LEFT JOIN occasions o ON c.client_id = o.client_id
    GROUP BY c.client_id, c.cohort_week, c.n_purchase_days
),
category_div AS (
    SELECT client_id, COUNT(DISTINCT category) AS n_categories
    FROM int_customer_category_behavior
    GROUP BY client_id
)
SELECT
    rf.cohort_week,
    COUNT(*) AS n_customers_in_cohort,
    AVG(rf.repurchase_7d) AS repurchase_7d_rate,
    AVG(rf.repurchase_14d) AS repurchase_14d_rate,
    AVG(rf.repurchase_28d) AS repurchase_28d_rate,
    AVG(rf.n_purchase_days) AS avg_purchase_days,
    AVG(cd.n_categories) AS avg_category_diversity,
    (rf.cohort_week + INTERVAL '7 days') > wb.window_max AS is_7d_window_censored,
    (rf.cohort_week + INTERVAL '14 days') > wb.window_max AS is_14d_window_censored,
    (rf.cohort_week + INTERVAL '28 days') > wb.window_max AS is_28d_window_censored
FROM repurchase_flags rf
LEFT JOIN category_div cd ON rf.client_id = cd.client_id
CROSS JOIN window_bounds wb
GROUP BY rf.cohort_week, wb.window_max
ORDER BY rf.cohort_week;

-- Grain: 1 row = 1 구매 고객 (첫 관측 구매가 있는 고객만, 909,210행)
-- Primary Key: client_id
-- 목적: "첫 관측 구매 주차" 코호트 배정 (PROJECT_GUIDELINES.md 14번 — 가입일이 없어
--   이 정의를 고정 기준으로 사용. 새로운 판단 아님).
-- 입력: int_customer_purchase_gap
-- 출력: mart_customer_retention, Phase 3 코호트 분석
CREATE OR REPLACE TABLE mart_customer_cohort AS
SELECT
    client_id,
    first_purchase_ts,
    date_trunc('week', first_purchase_ts) AS cohort_week,
    n_purchases,
    n_purchase_days,
    avg_purchase_gap_days
FROM int_customer_purchase_gap;

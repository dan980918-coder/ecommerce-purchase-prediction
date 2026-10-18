-- Grain: 1 row = 1 고객 x 1 활동일
-- Primary Key: (client_id, activity_date)
-- 목적: int_customer_daily_activity를 그대로 마트로 승격 (Phase 5 feature 계산의
--   기본 시계열 단위). 현재는 intermediate와 동일하지만, 향후 라이프사이클
--   상태 등 파생 컬럼이 필요해지면 이 마트에서 확장한다.
-- 입력: int_customer_daily_activity
-- 출력: Phase 5 feature, Phase 7 대시보드
CREATE OR REPLACE TABLE mart_customer_daily AS
SELECT * FROM int_customer_daily_activity;

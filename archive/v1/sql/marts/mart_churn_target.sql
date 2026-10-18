-- Grain: 1 row = 1 고객 x 1 snapshot_date (mart_customer_snapshot과 동일 그레인/모집단)
-- Primary Key: (client_id, snapshot_date)
--
-- PROJECT_GUIDELINES.md 18번 Model A("구매 비활성 위험", 과거 구매 이력이 있는 고객 대상)의
-- 타겟 테이블. mart_customer_snapshot은 범용 feature+label 저장소이고, 이
-- 테이블은 Model A 학습에 바로 쓸 수 있도록 타겟 컬럼명을 명확히 하고
-- (label_inactive_* -> churn_*) 불필요한 컬럼을 정리한 "모델링 준비" 뷰다.
--
-- 입력: mart_customer_snapshot
-- 출력: Phase 6 모델 A 학습/평가
CREATE OR REPLACE TABLE mart_churn_target AS
SELECT
    snapshot_date,
    client_id,
    last_purchase_ts,
    days_since_last_purchase,
    n_purchase_occasions_so_far,
    n_purchase_days_so_far,
    avg_purchase_gap_days_so_far,
    n_purchases_7d,
    n_purchases_14d,
    n_purchases_28d,
    n_categories_so_far,
    avg_category_repurchase_rate,
    n_page_visit_28d,
    n_search_query_28d,
    n_add_to_cart_28d,
    n_remove_from_cart_28d,
    label_inactive_14d AS churn_14d,
    label_inactive_28d AS churn_28d
FROM mart_customer_snapshot;

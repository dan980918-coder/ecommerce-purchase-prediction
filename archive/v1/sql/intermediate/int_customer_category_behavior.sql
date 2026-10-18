-- Grain: 1 row = 1 고객 x 1 카테고리 (해당 고객이 그 카테고리에서 구매한 이력이 있는 조합만)
-- Primary Key: (client_id, category)
-- Foreign Key: category -> stg_product_properties.category
-- 입력: stg_product_buy, stg_product_properties (구매↔속성 매칭률 100% — Phase 1 8.5)
-- 출력: Phase 3(카테고리별 퍼널), Phase 5(카테고리 다양성 feature) 참조 예정
CREATE OR REPLACE TABLE int_customer_category_behavior AS
SELECT
    b.client_id,
    p.category,
    COUNT(*) AS n_purchases,
    COUNT(DISTINCT b.sku) AS n_distinct_sku,
    MIN(b.event_ts) AS first_purchase_ts,
    MAX(b.event_ts) AS last_purchase_ts
FROM stg_product_buy b
JOIN stg_product_properties p ON b.sku = p.sku
GROUP BY b.client_id, p.category;

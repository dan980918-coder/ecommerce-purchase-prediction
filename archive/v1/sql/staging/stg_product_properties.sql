-- Grain: 1 row = 1 sku (dimension table, sku is a valid PK — Phase 1 8.5 확인)
-- Source: data/raw/synerise_dataset/product_properties.parquet
-- 공식 문서상 컬럼명은 `embedding`이지만 실제 파일 컬럼명은 `name` (Phase 1 8.2 발견).
-- price는 실제 금액이 아닌 0~99 구간값 — 매출로 해석하지 않음 (Phase 1 8.5).
CREATE OR REPLACE VIEW stg_product_properties AS
SELECT
    sku,
    category,
    price AS price_bucket,
    name AS name_embedding
FROM read_parquet('data/raw/synerise_dataset/product_properties.parquet');

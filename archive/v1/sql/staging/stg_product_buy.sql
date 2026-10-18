-- Grain: 1 row = 1 product_buy event (client_id, event_ts, sku)
-- Source: data/raw/synerise_dataset/product_buy.parquet
-- timestamp(VARCHAR) -> event_ts(TIMESTAMP) 캐스팅.
-- is_burst_repeat_5s: 동일 (client_id, sku)가 직전 이벤트와 5초 이내 반복되면 TRUE.
--   원본 행은 삭제하지 않고 플래그만 추가 (Phase 1 8.6 결정, docs/decisions_pending_review.md 참고).
CREATE OR REPLACE VIEW stg_product_buy AS
WITH casted AS (
    SELECT
        client_id,
        TRY_CAST(timestamp AS TIMESTAMP) AS event_ts,
        sku
    FROM read_parquet('data/raw/synerise_dataset/product_buy.parquet')
)
SELECT
    client_id,
    event_ts,
    sku,
    is_burst_repeat(
        event_ts,
        LAG(event_ts) OVER (PARTITION BY client_id, sku ORDER BY event_ts)
    ) AS is_burst_repeat_5s
FROM casted;

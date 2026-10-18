-- Grain: 1 row = 1 add_to_cart event (client_id, event_ts, sku)
-- Source: data/raw/synerise_dataset/add_to_cart.parquet
-- is_burst_repeat_5s: 동일 (client_id, sku) 5초 이내 반복 플래그 (원본 보존, 비파괴적).
CREATE OR REPLACE VIEW stg_add_to_cart AS
WITH casted AS (
    SELECT
        client_id,
        TRY_CAST(timestamp AS TIMESTAMP) AS event_ts,
        sku
    FROM read_parquet('data/raw/synerise_dataset/add_to_cart.parquet')
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

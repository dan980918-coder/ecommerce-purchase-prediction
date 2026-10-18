-- Grain: 1 row = 1 page_visit event (client_id, event_ts, url)
-- Source: data/raw/synerise_dataset/page_visit.parquet
-- url은 상품(sku)과 연결되는 키가 아님 (Phase 1 8.9, docs/methodology.md 참고) — 고객 단위 탐색 지표로만 사용.
-- is_burst_repeat_5s: 동일 (client_id, url) 5초 이내 반복 플래그 (원본 보존, 비파괴적).
CREATE OR REPLACE VIEW stg_page_visit AS
WITH casted AS (
    SELECT
        client_id,
        TRY_CAST(timestamp AS TIMESTAMP) AS event_ts,
        url
    FROM read_parquet('data/raw/synerise_dataset/page_visit.parquet')
)
SELECT
    client_id,
    event_ts,
    url,
    is_burst_repeat(
        event_ts,
        LAG(event_ts) OVER (PARTITION BY client_id, url ORDER BY event_ts)
    ) AS is_burst_repeat_5s
FROM casted;

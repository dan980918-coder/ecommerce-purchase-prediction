-- Grain: 1 row = 1 search_query event (client_id, event_ts, query)
-- Source: data/raw/synerise_dataset/search_query.parquet
-- query는 16차원 양자화 임베딩 문자열이며 해석 가능한 원문 텍스트가 아님 (Phase 1 8.2).
-- item 단위 키가 없어 is_burst_repeat_5s는 client_id 기준으로만 계산 (Phase 1 8.6과 동일 정의).
CREATE OR REPLACE VIEW stg_search_query AS
WITH casted AS (
    SELECT
        client_id,
        TRY_CAST(timestamp AS TIMESTAMP) AS event_ts,
        query
    FROM read_parquet('data/raw/synerise_dataset/search_query.parquet')
)
SELECT
    client_id,
    event_ts,
    query,
    is_burst_repeat(
        event_ts,
        LAG(event_ts) OVER (PARTITION BY client_id ORDER BY event_ts)
    ) AS is_burst_repeat_5s
FROM casted;

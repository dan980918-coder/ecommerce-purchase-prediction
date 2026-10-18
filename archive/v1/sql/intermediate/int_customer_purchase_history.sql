-- Grain: 1 row = 1 product_buy 이벤트 (stg_product_buy와 1:1, client_id 기준 enrichment 추가)
-- Primary Key: 없음 (원본 이벤트가 유일하지 않음 — Phase 1 8.2)
-- Foreign Key: client_id, sku
--
-- 주의: 한 번의 결제(order)에 여러 상품이 담기면 client_id+timestamp가 완전히
-- 동일한 여러 행으로 기록된다(동일 타임스탬프 재등장 비율 63.72% 확인,
-- intermediate 레이어 검증 중 발견). 따라서 "구매 순번/간격"은
-- 원본 행 단위가 아니라 DISTINCT (client_id, event_ts) = "구매 occasion" 단위로
-- 계산해야 한다 (Phase 1 8.7 검증 스크립트와 동일 정의 — ts=prev_ts 쌍은 간격
-- 계산에서 제외). 원본 행 단위 순번이 필요하면 별도로 raw_row_seq를 쓴다.
--
-- 입력: stg_product_buy
-- 출력: int_customer_purchase_gap, Phase 5 feature 계산에서 참조 예정
CREATE OR REPLACE TABLE int_customer_purchase_history AS
WITH occasion AS (
    SELECT DISTINCT client_id, event_ts
    FROM stg_product_buy
),
occasion_seq AS (
    SELECT
        client_id,
        event_ts,
        ROW_NUMBER() OVER (PARTITION BY client_id ORDER BY event_ts) AS purchase_occasion_seq,
        date_diff(
            'day',
            LAG(event_ts) OVER (PARTITION BY client_id ORDER BY event_ts),
            event_ts
        ) AS days_since_prev_purchase_occasion
    FROM occasion
)
SELECT
    b.client_id,
    b.event_ts,
    b.sku,
    b.is_burst_repeat_5s,
    ROW_NUMBER() OVER (PARTITION BY b.client_id ORDER BY b.event_ts, b.sku) AS raw_row_seq,
    o.purchase_occasion_seq,
    o.days_since_prev_purchase_occasion,
    o.purchase_occasion_seq = 1 AS is_first_observed_purchase
FROM stg_product_buy b
JOIN occasion_seq o ON b.client_id = o.client_id AND b.event_ts = o.event_ts;

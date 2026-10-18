-- Grain: 1 row = 1 고객 (구매 고객 전체)
-- Primary Key: client_id
--
-- n_purchases는 원본 이벤트(행) 수 그대로 유지한다 (Phase 1 8.7 "고객당 구매
-- 이벤트 수" mean=2.55와 동일 정의). 반면 구매 간격(gap) 통계는 동일 결제 내
-- 여러 줄(동일 client_id+event_ts)을 하나의 "구매 occasion"으로 묶은 뒤
-- occasion 간 간격으로 계산한다 — 동일 타임스탬프 재등장 비율이 63.72%에
-- 달해, 이를 묶지 않으면 간격이 0으로 왜곡된다 (int_customer_purchase_history
-- 주석 참고, Phase 1 8.7 검증 스크립트와 동일 정의로 맞춤).
--
-- 입력: stg_product_buy (독립적으로 재계산 — 빌드 순서와 무관하게 항상 재현 가능)
-- 출력: Phase 3(구매간격 분포), Phase 5(feature) 참조 예정
CREATE OR REPLACE TABLE int_customer_purchase_gap AS
WITH occasion_gaps AS (
    SELECT
        client_id,
        event_ts,
        date_diff(
            'day',
            LAG(event_ts) OVER (PARTITION BY client_id ORDER BY event_ts),
            event_ts
        ) AS gap_days
    FROM (SELECT DISTINCT client_id, event_ts FROM stg_product_buy)
),
gap_summary AS (
    SELECT
        client_id,
        AVG(gap_days) AS avg_purchase_gap_days,
        STDDEV(gap_days) AS stddev_purchase_gap_days,
        MIN(gap_days) AS min_purchase_gap_days,
        MAX(gap_days) AS max_purchase_gap_days
    FROM occasion_gaps
    GROUP BY client_id
),
raw_summary AS (
    SELECT
        client_id,
        COUNT(*) AS n_purchases,
        COUNT(DISTINCT CAST(event_ts AS DATE)) AS n_purchase_days,
        MIN(event_ts) AS first_purchase_ts,
        MAX(event_ts) AS last_purchase_ts
    FROM stg_product_buy
    GROUP BY client_id
)
SELECT
    r.client_id,
    r.n_purchases,
    r.n_purchase_days,
    r.first_purchase_ts,
    r.last_purchase_ts,
    g.avg_purchase_gap_days,
    g.stddev_purchase_gap_days,
    g.min_purchase_gap_days,
    g.max_purchase_gap_days
FROM raw_summary r
LEFT JOIN gap_summary g ON r.client_id = g.client_id;

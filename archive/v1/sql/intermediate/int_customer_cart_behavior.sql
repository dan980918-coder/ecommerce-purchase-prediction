-- Grain: 1 row = 1 고객 (add_to_cart 또는 remove_from_cart 중 하나라도 있는 고객)
-- Primary Key: client_id
--
-- median_seconds_add_to_remove: 고객별 (add_ts, 그 이후
-- 첫 remove_ts) 쌍의 간격 중앙값. 전체 분포를 로그스케일 히스토그램으로
-- 보면 뚜렷한 이봉(bimodal) 형태다 — 짧은 쪽 봉우리(수 분)와 긴 쪽 봉우리
-- (수일~수주) 사이 계곡(valley)이 약 15,399~26,068초(4.3~7.2시간) 구간에
-- 있어, 그 중간값인 6시간(21,600초)을 fast/slow 경계로 채택했다(사전에
-- 정한 임의 기준이 아니라 실측 분포의 골짜기 — Phase 1/3에서 k 선택에
-- 쓴 Kneedle 엘보우와 같은 원리). add에 매칭되는 remove가 전혀 없는 고객은
-- NULL(장바구니에 담아두고 명시적으로 빼지 않은 경우 — 오히려 가장 많은
-- 케이스, mart_customer_segment.sql에서 no_removal_recorded로 분류).
--
-- 입력: stg_add_to_cart, stg_remove_from_cart, stg_product_buy
-- 출력: Phase 3(장바구니 이탈 분석), Phase 4(장바구니_이탈형 하위분류), Phase 5(feature) 참조 예정
CREATE OR REPLACE TABLE int_customer_cart_behavior AS
WITH add_summary AS (
    SELECT
        client_id,
        COUNT(*) AS n_add,
        COUNT(DISTINCT sku) AS n_add_distinct_sku,
        MIN(event_ts) AS first_add_ts,
        MAX(event_ts) AS last_add_ts
    FROM stg_add_to_cart
    GROUP BY client_id
),
remove_summary AS (
    SELECT
        client_id,
        COUNT(*) AS n_remove,
        COUNT(DISTINCT sku) AS n_remove_distinct_sku,
        MIN(event_ts) AS first_remove_ts,
        MAX(event_ts) AS last_remove_ts
    FROM stg_remove_from_cart
    GROUP BY client_id
),
add_first AS (
    SELECT client_id, sku, MIN(event_ts) AS add_ts FROM stg_add_to_cart GROUP BY client_id, sku
),
buy_first AS (
    SELECT client_id, sku, MIN(event_ts) AS buy_ts FROM stg_product_buy GROUP BY client_id, sku
),
conv AS (
    SELECT
        a.client_id,
        COUNT(*) AS n_add_to_buy_pairs,
        AVG(date_diff('second', a.add_ts, b.buy_ts) / 3600.0) AS avg_hours_add_to_buy
    FROM add_first a
    JOIN buy_first b ON a.client_id = b.client_id AND a.sku = b.sku
    WHERE b.buy_ts >= a.add_ts
    GROUP BY a.client_id
),
remove_after_add AS (
    SELECT a.client_id, a.sku, a.add_ts, MIN(r.event_ts) AS remove_ts
    FROM add_first a
    JOIN stg_remove_from_cart r ON a.client_id = r.client_id AND a.sku = r.sku AND r.event_ts >= a.add_ts
    GROUP BY a.client_id, a.sku, a.add_ts
),
removal_gap AS (
    SELECT client_id, MEDIAN(date_diff('second', add_ts, remove_ts)) AS median_seconds_add_to_remove
    FROM remove_after_add
    GROUP BY client_id
)
SELECT
    COALESCE(a.client_id, r.client_id) AS client_id,
    COALESCE(a.n_add, 0) AS n_add,
    COALESCE(a.n_add_distinct_sku, 0) AS n_add_distinct_sku,
    a.first_add_ts,
    a.last_add_ts,
    COALESCE(r.n_remove, 0) AS n_remove,
    COALESCE(r.n_remove_distinct_sku, 0) AS n_remove_distinct_sku,
    r.first_remove_ts,
    r.last_remove_ts,
    COALESCE(c.n_add_to_buy_pairs, 0) AS n_add_to_buy_pairs,
    c.avg_hours_add_to_buy,
    rg.median_seconds_add_to_remove
FROM add_summary a
FULL OUTER JOIN remove_summary r ON a.client_id = r.client_id
LEFT JOIN conv c ON COALESCE(a.client_id, r.client_id) = c.client_id
LEFT JOIN removal_gap rg ON COALESCE(a.client_id, r.client_id) = rg.client_id;

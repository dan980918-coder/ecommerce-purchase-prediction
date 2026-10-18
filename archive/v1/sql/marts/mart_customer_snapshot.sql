-- Grain: 1 row = 1 고객 x 1 snapshot_date
-- Primary Key: (client_id, snapshot_date)
--
-- Feature Window: snapshot_date 이전 28일 (PROJECT_GUIDELINES.md 12번 예시값 채택)
-- Label Window: snapshot_date 이후 14일 AND 28일 둘 다 계산 (PROJECT_GUIDELINES.md 18번이
--   14일 기준과 함께 28일 기준도 비교 대상으로 언급했으므로 하나를 고르지 않고 둘 다 생성)
--
-- snapshot_date 유효 범위 (우측 검열 원천 차단 — docs/methodology.md의
-- "우측 검열 고객 처리 방침" 결정 적용):
--   snapshot_date >= 관측시작일 + 28일 (feature window 전체 확보)
--   snapshot_date <= 관측종료일 - 28일 (두 라벨 중 더 엄격한 28일 기준으로
--     맞춤 — 14일 라벨은 자동으로 안전 범위에 포함됨)
-- snapshot_date 간격은 14일(라벨 윈도우 길이와 동일) — 인접 스냅샷의 라벨
-- 기간이 겹치지 않도록 하기 위함. 결과: 9개 snapshot_date
-- (2022-07-21 ~ 2022-11-10).
--
-- 모집단: PROJECT_GUIDELINES.md 18번 Model A("과거 구매 이력이 있는 고객")에 맞춰
-- snapshot_date 이전에 구매 이력이 1건 이상 있는 고객만 포함. Model B(활동
-- 고객 전체 대상 구매성향)용 스냅샷은 모집단이 훨씬 커서 별도 테이블로
-- 분리하는 것이 합리적이라 판단해 이번 빌드에서는 제외함(추후 필요 시
-- mart_activity_snapshot 등으로 별도 구축).
--
-- avg_category_repurchase_rate: 고객이 snapshot_date 이전에
-- 구매한 카테고리들의 재구매율(int_customer_category_repurchase_avg_by_snapshot,
-- snapshot_date마다 그 시점 이전 데이터로만 재계산 — 미래 누수 없음) 평균.
-- 원래 이 mart 안에 인라인 CTE로 계산했으나, 이 파일의 기존 무거운 조인과
-- 한 쿼리 플랜에 합쳐지며 OOM이 발생해(8GB 환경) 별도 intermediate 테이블로
-- 분리하고 여기서는 가벼운 LEFT JOIN만 한다. 표본 100명 미만 카테고리는
-- 근거 테이블에서 이미 제외돼 있어, 고객이 그런 카테고리에서만 구매했다면
-- NULL(정보 없음)이 된다 — 0으로 대체하지 않음(0은 "확실히 재구매 안 함"이라는
-- 잘못된 의미가 되므로).
--
-- 입력: stg_product_buy, stg_add_to_cart, stg_remove_from_cart, stg_page_visit,
--       stg_search_query, stg_product_properties, int_customer_category_repurchase_avg_by_snapshot
-- 출력: mart_churn_target, mart_purchase_propensity, Phase 6 모델링
CREATE OR REPLACE TABLE mart_customer_snapshot AS
WITH bounds AS (
    SELECT MAX(last_event_ts) AS window_max, MIN(first_event_ts) AS window_min
    FROM int_customer_observation_period
),
snapshot_dates AS (
    SELECT CAST(gs AS DATE) AS snapshot_date
    FROM bounds, generate_series(
        CAST(window_min AS DATE) + INTERVAL 28 DAY,
        CAST(window_max AS DATE) - INTERVAL 28 DAY,
        INTERVAL 14 DAY
    ) AS t(gs)
),
buyer_ids AS (
    SELECT DISTINCT client_id FROM stg_product_buy
),
-- 이벤트 테이블을 구매 이력 고객으로 먼저 필터링 (page_visit 199M행 등 대형
-- 테이블에 대한 이후 range join 비용을 낮추기 위함)
buyer_buy AS (
    SELECT b.client_id, p.event_ts, p.sku
    FROM stg_product_buy p JOIN buyer_ids b ON p.client_id = b.client_id
),
buyer_cart_add AS (
    SELECT b.client_id, c.event_ts
    FROM stg_add_to_cart c JOIN buyer_ids b ON c.client_id = b.client_id
),
buyer_cart_remove AS (
    SELECT b.client_id, r.event_ts
    FROM stg_remove_from_cart r JOIN buyer_ids b ON r.client_id = b.client_id
),
buyer_visit AS (
    SELECT b.client_id, v.event_ts
    FROM stg_page_visit v JOIN buyer_ids b ON v.client_id = b.client_id
),
buyer_search AS (
    SELECT b.client_id, s.event_ts
    FROM stg_search_query s JOIN buyer_ids b ON s.client_id = b.client_id
),
purchase_occasions AS (
    SELECT DISTINCT client_id, event_ts FROM buyer_buy
),
spine AS (
    SELECT DISTINCT sd.snapshot_date, po.client_id
    FROM snapshot_dates sd
    JOIN purchase_occasions po ON po.event_ts < sd.snapshot_date
),
-- 구매 관련 feature: occasion 단위(동일 결제 내 여러 상품 중복 방지,
-- int_customer_purchase_history와 동일 원칙 — docs/data_dictionary.md 참고)
purchase_calc AS (
    SELECT
        s.snapshot_date,
        s.client_id,
        po.event_ts,
        date_diff(
            'day',
            LAG(po.event_ts) OVER (PARTITION BY s.snapshot_date, s.client_id ORDER BY po.event_ts),
            po.event_ts
        ) AS gap_days
    FROM spine s
    JOIN purchase_occasions po ON s.client_id = po.client_id AND po.event_ts < s.snapshot_date
),
purchase_features AS (
    SELECT
        snapshot_date,
        client_id,
        MAX(event_ts) AS last_purchase_ts,
        COUNT(*) AS n_purchase_occasions_so_far,
        COUNT(DISTINCT CAST(event_ts AS DATE)) AS n_purchase_days_so_far,
        AVG(gap_days) AS avg_purchase_gap_days_so_far,
        SUM(CASE WHEN event_ts >= snapshot_date - INTERVAL 7 DAY THEN 1 ELSE 0 END) AS n_purchases_7d,
        SUM(CASE WHEN event_ts >= snapshot_date - INTERVAL 14 DAY THEN 1 ELSE 0 END) AS n_purchases_14d,
        SUM(CASE WHEN event_ts >= snapshot_date - INTERVAL 28 DAY THEN 1 ELSE 0 END) AS n_purchases_28d
    FROM purchase_calc
    GROUP BY snapshot_date, client_id
),
category_features AS (
    SELECT s.snapshot_date, s.client_id, COUNT(DISTINCT pp.category) AS n_categories_so_far
    FROM spine s
    JOIN buyer_buy bb ON s.client_id = bb.client_id AND bb.event_ts < s.snapshot_date
    JOIN stg_product_properties pp ON bb.sku = pp.sku
    GROUP BY s.snapshot_date, s.client_id
),
visit_features AS (
    SELECT s.snapshot_date, s.client_id, COUNT(*) AS n_page_visit_28d
    FROM spine s
    JOIN buyer_visit v ON s.client_id = v.client_id
        AND v.event_ts >= s.snapshot_date - INTERVAL 28 DAY AND v.event_ts < s.snapshot_date
    GROUP BY s.snapshot_date, s.client_id
),
search_features AS (
    SELECT s.snapshot_date, s.client_id, COUNT(*) AS n_search_query_28d
    FROM spine s
    JOIN buyer_search sq ON s.client_id = sq.client_id
        AND sq.event_ts >= s.snapshot_date - INTERVAL 28 DAY AND sq.event_ts < s.snapshot_date
    GROUP BY s.snapshot_date, s.client_id
),
cart_add_features AS (
    SELECT s.snapshot_date, s.client_id, COUNT(*) AS n_add_to_cart_28d
    FROM spine s
    JOIN buyer_cart_add c ON s.client_id = c.client_id
        AND c.event_ts >= s.snapshot_date - INTERVAL 28 DAY AND c.event_ts < s.snapshot_date
    GROUP BY s.snapshot_date, s.client_id
),
cart_remove_features AS (
    SELECT s.snapshot_date, s.client_id, COUNT(*) AS n_remove_from_cart_28d
    FROM spine s
    JOIN buyer_cart_remove r ON s.client_id = r.client_id
        AND r.event_ts >= s.snapshot_date - INTERVAL 28 DAY AND r.event_ts < s.snapshot_date
    GROUP BY s.snapshot_date, s.client_id
),
-- 라벨: snapshot_date 이후 14일/28일 이내 구매 발생 여부
label_features AS (
    SELECT
        s.snapshot_date,
        s.client_id,
        MAX(CASE WHEN po.event_ts > s.snapshot_date
                  AND po.event_ts <= s.snapshot_date + INTERVAL 14 DAY
             THEN 1 ELSE 0 END) AS label_purchase_14d,
        MAX(CASE WHEN po.event_ts > s.snapshot_date
                  AND po.event_ts <= s.snapshot_date + INTERVAL 28 DAY
             THEN 1 ELSE 0 END) AS label_purchase_28d
    FROM spine s
    LEFT JOIN purchase_occasions po ON s.client_id = po.client_id
    GROUP BY s.snapshot_date, s.client_id
)
SELECT
    s.snapshot_date,
    s.client_id,
    pf.last_purchase_ts,
    date_diff('day', pf.last_purchase_ts, s.snapshot_date) AS days_since_last_purchase,
    pf.n_purchase_occasions_so_far,
    pf.n_purchase_days_so_far,
    pf.avg_purchase_gap_days_so_far,
    pf.n_purchases_7d,
    pf.n_purchases_14d,
    pf.n_purchases_28d,
    COALESCE(cf.n_categories_so_far, 0) AS n_categories_so_far,
    car.avg_category_repurchase_rate,
    COALESCE(vf.n_page_visit_28d, 0) AS n_page_visit_28d,
    COALESCE(sf.n_search_query_28d, 0) AS n_search_query_28d,
    COALESCE(caf.n_add_to_cart_28d, 0) AS n_add_to_cart_28d,
    COALESCE(crf.n_remove_from_cart_28d, 0) AS n_remove_from_cart_28d,
    lf.label_purchase_14d,
    lf.label_purchase_28d,
    (lf.label_purchase_14d = 0) AS label_inactive_14d,
    (lf.label_purchase_28d = 0) AS label_inactive_28d
FROM spine s
JOIN purchase_features pf ON s.snapshot_date = pf.snapshot_date AND s.client_id = pf.client_id
LEFT JOIN category_features cf ON s.snapshot_date = cf.snapshot_date AND s.client_id = cf.client_id
LEFT JOIN visit_features vf ON s.snapshot_date = vf.snapshot_date AND s.client_id = vf.client_id
LEFT JOIN search_features sf ON s.snapshot_date = sf.snapshot_date AND s.client_id = sf.client_id
LEFT JOIN cart_add_features caf ON s.snapshot_date = caf.snapshot_date AND s.client_id = caf.client_id
LEFT JOIN cart_remove_features crf ON s.snapshot_date = crf.snapshot_date AND s.client_id = crf.client_id
LEFT JOIN int_customer_category_repurchase_avg_by_snapshot car
    ON s.snapshot_date = car.snapshot_date AND s.client_id = car.client_id
JOIN label_features lf ON s.snapshot_date = lf.snapshot_date AND s.client_id = lf.client_id;

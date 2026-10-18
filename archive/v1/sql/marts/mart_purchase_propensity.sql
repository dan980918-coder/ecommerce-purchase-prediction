-- Grain: 1 row = 1 고객 x 1 snapshot_date
-- Primary Key: (client_id, snapshot_date)
--
-- PROJECT_GUIDELINES.md 19번 Model B("향후 구매 가능성", "활동 고객" 대상)의 타겟
-- 테이블. mart_churn_target(구매 이력 있는 고객만 대상)과 달리, 아직 한 번도
-- 구매하지 않았지만 구매 가능성이 있는 고객(예: 방문/검색이 활발한 탐색
-- 고객)까지 포함한다 — 그렇지 않으면 이 라벨이 churn 라벨의 단순 반전에
-- 불과해져 별도 모델을 만들 이유가 없어진다.
--
-- 모집단 정의("활동 고객"의 데이터 기반 해석): snapshot_date 이전 누적
-- 기준으로 (a) 방문 10회 이상 (Phase 4 세그먼트에서 이미 사용한 p90 기준과
-- 동일선상) 또는 (b) search_first(검색이 방문보다 먼저 발생, 아래
-- 설명) 또는 (c) 장바구니 추가 이력 또는 (d) 구매 이력. 순수
-- 1~2회성 방문자(전체의 76.89%, 저관여_탐색형)는 제외 — 전환 가능성이
-- 사실상 0에 가까운 트래픽을 propensity 모델링에 포함하지 않는 것은
-- 실무에서도 흔한 관행이며, 계산 비용도 크게 줄인다.
--
-- (b) search_first 조건 (docs/methodology.md 참고): 원래는
-- "검색 1회 이상"이었으나, mart_customer_segment.sql의 구매_직전_탐색형
-- 분류에서 이미 이 기준이 저의도(search_only, 실제 전환율 7.75%)와
-- 고의도(search_first, 44.02%) 신호를 구분 못 한다는 게 확인돼 교체됐다.
-- 이 mart는 그 교체를 반영받지 못한 채 남아있었던 것을 뒤늦게 통일한다.
-- 미래 누수 방지를 위해 "검색이 방문보다 먼저"라는 사실은 snapshot_date
-- 이전에 두 이벤트(첫 검색, 첫 방문)가 이미 관측된 경우에만 인정한다
-- (아래 population CTE의 cf.first_search_ts < ab.snapshot_date 등 조건).
--
-- 효율성: 원본 199M행 page_visit을 다시 스캔하지 않고, 이미 만들어진
-- int_customer_daily_activity(46.9M행, client x date 집계)를 재사용한다.
-- 다만 search_first 판정에는 날짜가 아닌 정확한 이벤트 순서가 필요해
-- (같은 날 검색과 방문이 모두 있으면 daily 집계로는 순서를 알 수 없음)
-- 이 부분만 stg_search_query/stg_page_visit 원본을 별도로 스캔한다.
--
-- avg_category_repurchase_rate: mart_customer_snapshot과
-- 동일한 lookup(int_customer_category_repurchase_avg_by_snapshot)을 재사용.
-- 구매 이력이 없는 후보 고객(방문/검색/장바구니만 있는 경우)은 정의상
-- NULL — "정보 없음"과 "재구매 안 함(0)"을 구분해야 하므로 0으로 대체하지 않음.
--
-- 입력: mart_customer_360, int_customer_daily_activity, int_customer_purchase_history,
--       stg_search_query, stg_page_visit, int_customer_category_repurchase_avg_by_snapshot
-- 출력: Phase 6 모델 B 학습/평가
--
-- 구현 노트: 이 파일은 세 단계로 나뉜다(전부 8GB 환경 OOM 회피 목적 —
-- 무거운 계산을 하나의 쿼리 플랜에 몰아넣지 않고 단계별로 디스크에
-- materialize).
--   0단계: candidate_ids + search_first 판정에 필요한 first_search_ts/
--          first_visit_ts를 먼저 계산해 작은 TEMP 테이블로 고정
--   1단계: 기존 activity_before/purchase_before/population 로직(0단계
--          결과를 가볍게 JOIN)
--   2단계: avg_category_repurchase_rate LEFT JOIN
CREATE OR REPLACE TEMP TABLE tmp_candidate_ids AS
WITH first_search_all AS (
    SELECT client_id, MIN(event_ts) AS first_search_ts FROM stg_search_query GROUP BY client_id
),
first_visit_all AS (
    SELECT client_id, MIN(event_ts) AS first_visit_ts FROM stg_page_visit GROUP BY client_id
)
SELECT
    m.client_id,
    fs.first_search_ts,
    fv.first_visit_ts
FROM mart_customer_360 m
LEFT JOIN first_search_all fs ON m.client_id = fs.client_id
LEFT JOIN first_visit_all fv ON m.client_id = fv.client_id
WHERE m.n_page_visit >= 10
   OR (fs.first_search_ts IS NOT NULL AND fv.first_visit_ts IS NOT NULL AND fs.first_search_ts < fv.first_visit_ts)
   OR m.has_cart_activity
   OR m.is_buyer;

CREATE OR REPLACE TABLE mart_purchase_propensity_base AS
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
candidate_ids AS (
    -- 전체 관측기간 기준 상한 후보 — 이후 snapshot_date별로 더 좁혀짐
    SELECT client_id FROM tmp_candidate_ids
),
cand_daily AS (
    SELECT d.*
    FROM int_customer_daily_activity d
    JOIN candidate_ids c ON d.client_id = c.client_id
),
cand_purchase_occasions AS (
    SELECT DISTINCT h.client_id, h.event_ts
    FROM int_customer_purchase_history h
    JOIN candidate_ids c ON h.client_id = c.client_id
),
activity_before AS (
    SELECT
        sd.snapshot_date,
        d.client_id,
        SUM(d.n_page_visit) AS cum_visits,
        SUM(d.n_add_to_cart) AS cum_cart_add,
        SUM(CASE WHEN d.activity_date >= sd.snapshot_date - INTERVAL 28 DAY
                 THEN d.n_page_visit ELSE 0 END) AS n_page_visit_28d,
        SUM(CASE WHEN d.activity_date >= sd.snapshot_date - INTERVAL 28 DAY
                 THEN d.n_search_query ELSE 0 END) AS n_search_query_28d,
        SUM(CASE WHEN d.activity_date >= sd.snapshot_date - INTERVAL 28 DAY
                 THEN d.n_add_to_cart ELSE 0 END) AS n_add_to_cart_28d,
        SUM(CASE WHEN d.activity_date >= sd.snapshot_date - INTERVAL 28 DAY
                 THEN d.n_remove_from_cart ELSE 0 END) AS n_remove_from_cart_28d
    FROM snapshot_dates sd
    JOIN cand_daily d ON d.activity_date < sd.snapshot_date
    GROUP BY sd.snapshot_date, d.client_id
),
purchase_before AS (
    SELECT
        sd.snapshot_date,
        po.client_id,
        MAX(po.event_ts) AS last_purchase_ts,
        COUNT(*) AS n_purchase_occasions_so_far
    FROM snapshot_dates sd
    JOIN cand_purchase_occasions po ON po.event_ts < sd.snapshot_date
    GROUP BY sd.snapshot_date, po.client_id
),
population AS (
    SELECT ab.snapshot_date, ab.client_id
    FROM activity_before ab
    JOIN tmp_candidate_ids cf ON ab.client_id = cf.client_id
    WHERE ab.cum_visits >= 10
       OR (cf.first_search_ts IS NOT NULL AND cf.first_visit_ts IS NOT NULL
           AND cf.first_search_ts < ab.snapshot_date AND cf.first_visit_ts < ab.snapshot_date
           AND cf.first_search_ts < cf.first_visit_ts)
       OR ab.cum_cart_add > 0
    UNION
    SELECT snapshot_date, client_id FROM purchase_before
),
label_calc AS (
    SELECT
        p.snapshot_date,
        p.client_id,
        MAX(CASE WHEN po.event_ts > p.snapshot_date
                  AND po.event_ts <= p.snapshot_date + INTERVAL 14 DAY
             THEN 1 ELSE 0 END) AS will_purchase_14d,
        MAX(CASE WHEN po.event_ts > p.snapshot_date
                  AND po.event_ts <= p.snapshot_date + INTERVAL 28 DAY
             THEN 1 ELSE 0 END) AS will_purchase_28d
    FROM population p
    LEFT JOIN cand_purchase_occasions po ON p.client_id = po.client_id
    GROUP BY p.snapshot_date, p.client_id
)
SELECT
    p.snapshot_date,
    p.client_id,
    (pb.client_id IS NOT NULL) AS has_purchase_history,
    pb.last_purchase_ts,
    CASE WHEN pb.last_purchase_ts IS NOT NULL
         THEN date_diff('day', pb.last_purchase_ts, p.snapshot_date) END AS days_since_last_purchase,
    COALESCE(pb.n_purchase_occasions_so_far, 0) AS n_purchase_occasions_so_far,
    COALESCE(ab.n_page_visit_28d, 0) AS n_page_visit_28d,
    COALESCE(ab.n_search_query_28d, 0) AS n_search_query_28d,
    COALESCE(ab.n_add_to_cart_28d, 0) AS n_add_to_cart_28d,
    COALESCE(ab.n_remove_from_cart_28d, 0) AS n_remove_from_cart_28d,
    lc.will_purchase_14d,
    lc.will_purchase_28d
FROM population p
LEFT JOIN purchase_before pb ON p.snapshot_date = pb.snapshot_date AND p.client_id = pb.client_id
LEFT JOIN activity_before ab ON p.snapshot_date = ab.snapshot_date AND p.client_id = ab.client_id
JOIN label_calc lc ON p.snapshot_date = lc.snapshot_date AND p.client_id = lc.client_id;

CREATE OR REPLACE TABLE mart_purchase_propensity AS
SELECT
    base.* EXCLUDE (will_purchase_14d, will_purchase_28d),
    car.avg_category_repurchase_rate,
    base.will_purchase_14d,
    base.will_purchase_28d
FROM mart_purchase_propensity_base base
LEFT JOIN int_customer_category_repurchase_avg_by_snapshot car
    ON base.snapshot_date = car.snapshot_date AND base.client_id = car.client_id;

DROP TABLE mart_purchase_propensity_base;
DROP TABLE tmp_candidate_ids;

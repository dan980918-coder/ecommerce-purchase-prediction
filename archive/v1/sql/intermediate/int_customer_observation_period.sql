-- Grain: 1 row = 1 고객 (전체 22,298,361명 — 5개 이벤트 통합 기준)
-- Primary Key: client_id
-- 입력: stg_product_buy, stg_add_to_cart, stg_remove_from_cart, stg_page_visit, stg_search_query
-- 출력: Phase 5 스냅샷 설계에서 좌/우측 검열 판단 참고용으로 사용
-- 좌측 검열 창(7일)·우측 검열 창(14일)은 Phase 1 8.10에서 진단용으로 이미 사용한
-- 값과 동일하게 유지 (docs/decisions_pending_review.md 참고, 새로운 판단 아님).
-- 참고: 우측 검열 문제 자체는 Phase 5 mart_customer_snapshot 설계 단계에서
-- snapshot_date를 관측 종료일 - label window 이전으로 제한하는 방식으로
-- 원천 차단하기로 이미 결정됨 (docs/methodology.md의 "우측 검열 고객 처리
-- 방침" 결정 참고). 이 테이블의
-- is_right_censor_candidate 플래그는 그 결정을 대체하지 않는 진단/참고용 컬럼.
CREATE OR REPLACE TABLE int_customer_observation_period AS
WITH all_events AS (
    SELECT client_id, event_ts FROM stg_product_buy
    UNION ALL SELECT client_id, event_ts FROM stg_add_to_cart
    UNION ALL SELECT client_id, event_ts FROM stg_remove_from_cart
    UNION ALL SELECT client_id, event_ts FROM stg_page_visit
    UNION ALL SELECT client_id, event_ts FROM stg_search_query
),
bounds AS (
    SELECT MIN(event_ts) AS window_min, MAX(event_ts) AS window_max FROM all_events
)
SELECT
    e.client_id,
    MIN(e.event_ts) AS first_event_ts,
    MAX(e.event_ts) AS last_event_ts,
    date_diff('day', MIN(e.event_ts), MAX(e.event_ts)) AS observation_days,
    COUNT(DISTINCT CAST(e.event_ts AS DATE)) AS n_active_days,
    MIN(e.event_ts) < (SELECT window_min FROM bounds) + INTERVAL '7 days' AS is_left_censor_candidate,
    MIN(e.event_ts) >= (SELECT window_max FROM bounds) - INTERVAL '14 days' AS is_right_censor_candidate
FROM all_events e
GROUP BY e.client_id;

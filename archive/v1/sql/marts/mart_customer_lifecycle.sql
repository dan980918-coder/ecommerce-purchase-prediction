-- Grain: 1 row = 1 고객 (전체 22,298,361명)
-- Primary Key: client_id
--
-- 라이프사이클 상태는 관측 종료 시점(reference_ts = 전체 데이터의 MAX
-- timestamp, 2022-12-08)을 기준으로 한 단면(snapshot) 분류다. Phase 5에서
-- 시점별(snapshot_date별) feature가 필요해지면 이 로직을 reference_ts 대신
-- 임의의 snapshot_date로 파라미터화해 재사용한다.
--
-- 임계값 근거 (PROJECT_GUIDELINES.md 16번 "기준은 임의로 결정하지 않는다" 원칙에 따라
-- 데이터 기반으로 도출, docs/methodology.md 참고):
--   - 14일 = 구매 간격 중앙값(9.48일, Phase 1 8.7) x 1.5  (업계 통상 "조기 경고" 배수)
--   - 28일 = 구매 간격 중앙값 x 3                          (업계 통상 "고위험" 배수)
--   - 60일 = 구매 간격 p90(68.05일, Phase 1 8.7)을 반올림  ("정상 구매 패턴 밖" 경계)
-- PROJECT_GUIDELINES.md 18번이 14일 기준과 함께 28일 기준도 비교 대상으로 이미
-- 언급했는데, 실제 median 기반 배수 계산 결과와 정확히 일치해 이 값들을 그대로 채택함.
--
-- PROJECT_GUIDELINES.md 16번 후보 9개 중 "반복구매 고객"과 "활성 구매 고객"은 상호
-- 배타적으로 만들기 어려워(둘 다 "최근 정상 구매 중"이라는 동일 개념) 하나의
-- 상태(활성_구매_고객)로 통합. n_purchase_days 컬럼은 남겨둬 필요시 재분리 가능.
--
-- 입력: mart_customer_360, int_customer_observation_period, int_customer_purchase_history
-- 출력: Phase 4 세그먼트 설계, Phase 7 대시보드 Lifecycle 페이지
CREATE OR REPLACE TABLE mart_customer_lifecycle AS
WITH bounds AS (
    SELECT MAX(last_event_ts) AS reference_ts FROM int_customer_observation_period
),
last_gap AS (
    -- 고객별 "가장 최근 구매 occasion 직전의 간격" — 복귀 고객 판정에 사용
    SELECT client_id, days_since_prev_purchase_occasion AS gap_before_last_purchase
    FROM (
        SELECT
            client_id,
            days_since_prev_purchase_occasion,
            ROW_NUMBER() OVER (PARTITION BY client_id ORDER BY purchase_occasion_seq DESC) AS rn
        FROM int_customer_purchase_history
    )
    WHERE rn = 1
),
base AS (
    SELECT
        m.client_id,
        m.is_buyer,
        m.has_cart_activity,
        m.n_page_visit,
        m.n_search_query,
        m.n_purchase_days,
        m.last_purchase_ts,
        date_diff('day', m.last_purchase_ts, b.reference_ts) AS days_since_last_purchase,
        lg.gap_before_last_purchase
    FROM mart_customer_360 m
    CROSS JOIN bounds b
    LEFT JOIN last_gap lg ON m.client_id = lg.client_id
)
SELECT
    client_id,
    is_buyer,
    n_purchase_days,
    days_since_last_purchase,
    gap_before_last_purchase,
    CASE
        WHEN is_buyer AND days_since_last_purchase <= 14 AND n_purchase_days = 1
            THEN '첫_관측_구매_고객'
        WHEN is_buyer AND days_since_last_purchase <= 14 AND n_purchase_days >= 2
             AND gap_before_last_purchase > 28
            THEN '복귀_고객'
        WHEN is_buyer AND days_since_last_purchase <= 14 AND n_purchase_days >= 2
            THEN '활성_구매_고객'
        WHEN is_buyer AND days_since_last_purchase BETWEEN 15 AND 28
            THEN '구매_감소_고객'
        WHEN is_buyer AND days_since_last_purchase BETWEEN 29 AND 60
            THEN '구매_비활성_위험_고객'
        WHEN is_buyer AND days_since_last_purchase > 60
            THEN '비활성_고객'
        WHEN NOT is_buyer AND has_cart_activity
            THEN '장바구니_고객'
        WHEN NOT is_buyer AND (n_page_visit > 0 OR n_search_query > 0)
            THEN '탐색_고객'
        ELSE '기타'
    END AS lifecycle_stage
FROM base;

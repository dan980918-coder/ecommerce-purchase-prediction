-- Grain: 1 row = 1 고객 (전체 22,298,361명)
-- Primary Key: client_id
--
-- PROJECT_GUIDELINES.md 17번 "규칙 기반 세그먼트를 먼저 만든다" 원칙에 따라 규칙 기반으로
-- 구축. mart_customer_lifecycle의 8개 상태와 대부분 1:1 대응하되, '탐색_고객'
-- (전체의 87.97%로 지나치게 큼)은 PROJECT_GUIDELINES.md 17번이 요구하는 "구매 직전
-- 탐색형" vs "저관여 탐색형"으로, '장바구니_고객'은 아래 설명대로
-- '장바구니_이탈형'/'장바구니_보류형'으로 각각 세분화한다 — 결과 세그먼트는
-- 총 9개(PROJECT_GUIDELINES.md 17번 원문은 8개 후보를 예시했으나, 이 갱신은 사용자
-- 승인 하에 이루어짐).
--
-- 세분화 기준 (데이터 기반 — docs/methodology.md 참고):
-- 탐색_고객 중 n_page_visit >= 10(해당 그룹의 p90, 전환율 변곡점은 아니지만
-- 상위 10% cut + 과접촉 방지라는 실무적 근거는 유효) 이거나 검색을 방문보다
-- 먼저 한 경우(search_first: 검색과 방문을 모두 했고 첫 검색이 첫 방문보다
-- 이른 경우)를 "구매 직전 탐색형"(고관여/고의도)으로 본다.
--
-- 기존에는 n_search_query > 0(검색 1회 이상)만으로 판단했으나, 검색만 하고
-- 방문은 전혀 없는 고객(search_only)의 실제 전환율은 7.75%로 낮은 반면,
-- 검색 후 방문까지 이어진 고객(search_first)은 44.02%로 매우 높아 — 이
-- 둘을 하나의 조건으로 묶으면 저의도 고객까지 고관여로 잘못 분류하게 된다.
-- search_first는 "검색으로 명확한 니즈를 표현한 뒤 실제 상품 탐색(방문)까지
-- 이어간" 행동이라 구매 직전 신호로 보기에 더 타당하다.
--
-- '구매_비활성_위험_고객'과 '비활성_고객'은 세그먼트 레벨에서는
-- '구매_비활성형' 하나로 합친다 — recency의 세밀한 구분은 이미 lifecycle에
-- 남아있어 세그먼트 레벨에서 또 나눌 필요가 없다(대시보드 Segment
-- Explorer는 세그먼트를, Lifecycle 페이지는 lifecycle을 보여주는 방식으로
-- 역할 분리). 이 병합 자체는 아래 장바구니_고객 분리와 별개 판단이다.
--
-- 장바구니_고객 분리 (참고용 컬럼 추가에서 세그먼트 분리로 확대. 근거:
-- docs/methodology.md 참고):
-- 처음에는 cart_removal_subtype 참고용 컬럼만 추가했으나(no_removal_recorded/
-- fast_removal/slow_removal), no_removal_recorded가 이 그룹의 79.38%(명시적
-- 제거 이벤트가 전혀 없음 — 로깅 누락이 아니라 실측 확인: 96.5%가 remove
-- 이벤트 자체가 없고, 시간도 충분했음에도(중앙값 76일 여유) 방치된 경우)로
-- 압도적 다수를 차지해, "장바구니 이탈형"이라는 이름과 "이탈 회수(Cart
-- Recovery)" CRM 목적이 이 다수에게는 맞지 않는다고 판단해 세그먼트 자체를
-- 분리했다:
--   - 장바구니_이탈형: 담은 뒤 명시적으로 제거함(fast_removal + slow_removal,
--     20.62%) — 실제 "거부" 신호가 있는 고객
--   - 장바구니_보류형(신설): 제거 이벤트 없이 담긴 채로 있음(no_removal_recorded,
--     79.38%) — 아직 결정을 안 내린 고객, CRM 목적도 "회수"가 아니라
--     "완결 유도(체크아웃 리마인더)"로 달라야 함
-- cart_removal_subtype 컬럼은 그대로 유지 — 장바구니_이탈형 내부에서
-- fast/slow 구분은 여전히 유의미하고(관여도·CRM 액션이 다름), 장바구니_보류형은
-- 정의상 항상 'no_removal_recorded'다. 다른 7개 세그먼트에는 NULL.
--
-- 입력: mart_customer_lifecycle, mart_customer_360, stg_search_query, stg_page_visit,
--       int_customer_cart_behavior
-- 출력: Phase 7 대시보드 Segment Explorer
-- 참고: mart_customer_segment는 Phase 6 모델 feature나 baseline rule로
-- 쓰이지 않는다 — src/models/baselines.py의 모든 baseline 함수는
-- days_since_last_purchase 등 원시 컬럼만 사용하고 이 마트를 참조하지 않는다.
CREATE OR REPLACE TABLE mart_customer_segment AS
WITH first_search AS (
    SELECT client_id, MIN(event_ts) AS first_search_ts
    FROM stg_search_query
    GROUP BY client_id
),
first_visit AS (
    -- mart_customer_360은 first_visit_ts를 출력 컬럼으로 노출하지 않아 여기서 별도 집계
    SELECT client_id, MIN(event_ts) AS first_visit_ts
    FROM stg_page_visit
    GROUP BY client_id
),
subtype_base AS (
    SELECT
        l.client_id,
        l.lifecycle_stage,
        m.n_page_visit,
        fs.first_search_ts,
        fv.first_visit_ts,
        CASE
            WHEN l.lifecycle_stage != '장바구니_고객' THEN NULL
            WHEN cb.median_seconds_add_to_remove IS NULL THEN 'no_removal_recorded'
            WHEN cb.median_seconds_add_to_remove <= 21600 THEN 'fast_removal'
            ELSE 'slow_removal'
        END AS cart_removal_subtype
    FROM mart_customer_lifecycle l
    JOIN mart_customer_360 m ON l.client_id = m.client_id
    LEFT JOIN first_search fs ON l.client_id = fs.client_id
    LEFT JOIN first_visit fv ON l.client_id = fv.client_id
    LEFT JOIN int_customer_cart_behavior cb ON l.client_id = cb.client_id
)
SELECT
    client_id,
    lifecycle_stage,
    CASE
        WHEN lifecycle_stage = '탐색_고객'
             AND (
                 n_page_visit >= 10
                 OR (first_search_ts IS NOT NULL
                     AND first_visit_ts IS NOT NULL
                     AND first_search_ts < first_visit_ts)
             )
            THEN '구매_직전_탐색형'
        WHEN lifecycle_stage = '탐색_고객'
            THEN '저관여_탐색형'
        WHEN lifecycle_stage = '장바구니_고객' AND cart_removal_subtype = 'no_removal_recorded'
            THEN '장바구니_보류형'
        WHEN lifecycle_stage = '장바구니_고객'
            THEN '장바구니_이탈형'
        WHEN lifecycle_stage = '첫_관측_구매_고객'
            THEN '첫_관측_구매_고관여형'
        WHEN lifecycle_stage = '활성_구매_고객'
            THEN '안정적_반복구매형'
        WHEN lifecycle_stage = '구매_감소_고객'
            THEN '반복구매_감소형'
        WHEN lifecycle_stage IN ('구매_비활성_위험_고객', '비활성_고객')
            THEN '구매_비활성형'
        WHEN lifecycle_stage = '복귀_고객'
            THEN '복귀형'
        ELSE '기타'
    END AS segment,
    cart_removal_subtype
FROM subtype_base;

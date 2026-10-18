-- is_burst_repeat(event_ts, prev_event_ts): 같은 키(client_id + 아이템 등)를
-- 가진 두 이벤트가 5초 이내 간격으로 반복됐는지 판정한다.
--
-- "5초"라는 burst 임계값은 이 파일 한 곳에서만 정의된다. sql/staging의
-- stg_add_to_cart/stg_remove_from_cart/stg_product_buy/stg_page_visit/
-- stg_search_query 5개 파일은 전부 이 매크로를 호출할 뿐 임계값을 직접
-- 갖고 있지 않다 — 기준을 바꾸려면 이 파일만 수정하면 된다. 각 파일의
-- LAG(event_ts) OVER (PARTITION BY ...) 절(어떤 컬럼을 "같은 아이템"으로
-- 볼지)은 파일마다 달라 매크로로 통합하지 않고 각 staging 파일에 그대로
-- 남긴다.
CREATE OR REPLACE MACRO is_burst_repeat(event_ts, prev_event_ts) AS
    COALESCE(date_diff('second', prev_event_ts, event_ts) BETWEEN 0 AND 5, FALSE);

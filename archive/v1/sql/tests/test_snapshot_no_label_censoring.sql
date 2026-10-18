-- PROJECT_GUIDELINES.md 31번 "Snapshot Feature·Label 분리" 테스트
-- docs/methodology.md의 "우측 검열 고객 처리 방침" 결정에 대한 안전장치.
-- 이 쿼리는 위반 행을 반환한다 — 결과가 0행이면 통과.
-- (자동화된 assert는 tests/data_quality/test_snapshot.py::test_no_label_window_censoring 참고)

SELECT DISTINCT snapshot_date
FROM mart_customer_snapshot
WHERE snapshot_date + INTERVAL 28 DAY > (
    SELECT MAX(last_event_ts) FROM int_customer_observation_period
);

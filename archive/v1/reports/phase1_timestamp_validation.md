# Phase 1 - 8.3 타임스탬프 검증

검증 스크립트: `scripts/validate_timestamps.py`
방법: DuckDB `TRY_CAST(timestamp AS TIMESTAMP)` — VARCHAR로 저장된 timestamp 컬럼을
파싱 오류 여부까지 함께 확인 후 MIN/MAX/기준일 이후 비율 계산.

## 결과

| event_type | row_count | parse_fail | min_timestamp | max_timestamp | 관측기간(일) | unique_clients | rows_after_2023-08-05 | 비율 |
|---|---:|---:|---|---|---:|---:|---:|---:|
| product_buy | 2,318,502 | 0 | 2022-06-23 00:12:15 | 2022-12-08 00:09:15 | 167 | 909,210 | 0 | 0.0000% |
| add_to_cart | 7,541,117 | 0 | 2022-06-23 00:10:20 | 2022-12-08 00:09:55 | 167 | 2,333,463 | 0 | 0.0000% |
| remove_from_cart | 2,688,894 | 0 | 2022-06-23 00:12:25 | 2022-12-08 00:09:40 | 167 | 694,391 | 0 | 0.0000% |
| page_visit | 199,451,980 | 0 | 2022-06-23 00:10:00 | 2022-12-08 00:09:59 | 167 | 21,993,998 | 0 | 0.0000% |
| search_query | 13,223,769 | 0 | 2022-06-23 00:10:00 | 2022-12-08 00:09:55 | 167 | 1,629,447 | 0 | 0.0000% |

전체 원본 데이터: **2022-06-23 \~ 2022-12-08 (167일, 약 6개월)** — 공식 페이지의
"6개월간 기록" 설명과 정확히 일치. timestamp 파싱 오류 0건 (VARCHAR지만 전량 정상 형식).

## 최근 3년(2023-08-05 이후) 기준 충족 여부

**5개 테이블 전부, 0.0000% 충족 — 전량 미달.** 기준일(2026-08-05) 대비 최신 이벤트도
약 3년 8개월 전 데이터다.

## 정책 결정

PROJECT_GUIDELINES.md 원 규칙상 이는 10번 "Phase 1 중단 조건"("타임스탬프가 최근성 기준을 크게
벗어남")에 해당해 중단 대상이었으나, 사용자와 협의하여 하드 컷오프 중단 규칙을
"데이터 시점 투명 명시" 방식으로 전환하고 Phase 1을 계속 진행하기로 결정했다.

- 관련 한계 기록: [`docs/limitations.md`](../docs/limitations.md) (1번 항목)
- PROJECT_GUIDELINES.md 10번("Phase 1 중단 조건") 섹션에 인라인 갱신 반영

## 생성 파일

- `reports/phase1_timestamp_validation.md` (본 문서)
- `reports/phase1_timestamp_summary.csv`
- `scripts/validate_timestamps.py`

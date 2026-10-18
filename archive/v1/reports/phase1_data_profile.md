# Phase 1 데이터 프로파일 (종합)

8.1\~8.10 전체 검증 결과를 종합한 문서입니다. 각 항목의 세부 근거는 개별
보고서(`reports/phase1_*.md`, `reports/phase1_*.csv`)를 참조하세요.

## 1. 데이터 출처

- 공식 페이지: https://recsys.synerise.com/data-set
- 공식 코드 저장소: https://github.com/Synerise/recsys2025 (코드: MIT License)
- 라이선스(데이터): CC BY-NC 4.0 — "Universal Behavioral Modeling Dataset © 2025 by Synerise SA is licensed under Creative Commons Attribution-NonCommercial 4.0 International." (원문 확인, `reports/phase1_download_log.md`)
- 다운로드 방식: 로그인/등록 불필요, 직접 링크
- 다운로드 파일: `synerise_dataset.tar.gz` (원본, ≈1.92GB, sha256 `e90b8fded8bc7a87b8c51ced7d5eead75f6deb09852ea701f5f22934e78b66e7`)
- 데이터 성격: 실제 온라인 리테일 서비스의 익명화 고객 행동 로그 (6개월)

## 2. 파일 목록 및 규모

| 파일 | 크기 | 행 수 | 열 수 |
|---|---:|---:|---:|
| product_buy.parquet | 30.05 MB | 2,318,502 | 3 |
| add_to_cart.parquet | 100.54 MB | 7,541,117 | 3 |
| remove_from_cart.parquet | 34.84 MB | 2,688,894 | 3 |
| page_visit.parquet | 1.87 GB | 199,451,980 | 3 |
| search_query.parquet | 335.74 MB | 13,223,769 | 3 |
| product_properties.parquet | 64.24 MB | 1,534,050 | 4 |

전체 이벤트 행 수: 226,758,312행 (product_buy+add_to_cart+remove_from_cart+page_visit+search_query 합계)

## 3. 컬럼 설명

| 파일 | 컬럼 | 타입 | 비고 |
|---|---|---|---|
| product_buy / add_to_cart / remove_from_cart | client_id, timestamp, sku | BIGINT, VARCHAR, BIGINT | timestamp는 문자열이나 파싱 오류 0건 |
| page_visit | client_id, timestamp, url | BIGINT, VARCHAR, BIGINT | url은 익명 숫자 ID, 상품과 연결 불가 |
| search_query | client_id, timestamp, query | BIGINT, VARCHAR, VARCHAR | query는 16차원 양자화 정수 배열(임베딩), 원문 텍스트 아님 (공식 문서는 20차원이라 했으나 실측 16차원) |
| product_properties | sku, category, price, name | BIGINT, BIGINT, BIGINT, VARCHAR | price는 0\~99 구간값(실제 금액 아님), name은 16차원 임베딩(공식 문서상 컬럼명은 `embedding`) |

## 4. 타임스탬프 범위

전체 관측 기간: **2022-06-23 00:10:00 \~ 2022-12-08 00:09:59** (167일, 약 6개월)
— 5개 이벤트 테이블 전부 동일 범위. 2023-08-05 이후 데이터는 **0.0000%**
(전량 미충족). 하드 컷오프 대신 "데이터 시점 투명 명시" 방식으로 프로젝트를
진행하기로 결정함(PROJECT_GUIDELINES.md 10번 섹션(Phase 1 중단 조건)의
타임스탬프 관련 정책 참고).

## 5. 고객 수

| 구분 | 고객 수 |
|---|---:|
| 전체 고유 고객 (5개 이벤트 합집합) | 22,298,361 |
| 구매 고객 | 909,210 |
| 장바구니 추가 고객 | 2,333,463 |
| 장바구니 제거 고객 | 694,391 |
| 페이지 방문 고객 | 21,993,998 |
| 검색 고객 | 1,629,447 |
| 5개 이벤트 모두 보유 | 194,997 (0.87%) |
| 이벤트 타입 1개만 보유 | 19,090,856 (85.62%) |

## 6. 상품 수 및 매칭

| 구분 | 값 |
|---|---:|
| 구매 상품(sku) 수 | 639,126 |
| 장바구니 상품(sku) 수 | 1,444,160 |
| 상품 속성 테이블 상품 수 | 1,534,050 |
| 구매↔속성 매칭률 | 100.00% |
| 장바구니↔속성 매칭률 | 100.00% |

## 7. 결측과 중복

- 결측값: 전 파일·전 컬럼 **0건**
- 완전 중복 행: product_buy 364,491 / add_to_cart 121,309 / remove_from_cart 119,656 / page_visit 17,320,847(8.7%) / search_query 612,891
- 5초 이내 동일 고객·상품 반복(버스트): product_buy 16.44%, page_visit 16.60%, search_query 13.03%, add_to_cart 4.72%, remove_from_cart 10.30%
- 처리 방침: 원본 보존 + Phase 2에서 비파괴적 플래그 컬럼으로 반영 예정 (`docs/decisions_pending_review.md`)

## 8. 고객별 관찰기간

- 관찰기간(첫\~마지막 행동) median **0일**, 66.33%가 하루만 활동
- 좌측 검열 후보(관측 시작 7일 이내 첫 등장): 전체 5.54%, 구매자 4.45%
- 우측 검열 후보(관측 종료 14일 이내 첫 등장): 전체 8.17%, 구매자 15.18%(138,041명)
- → "첫 관측 고객/첫 관측 구매/관찰기간 내 행동가치" 표현 원칙 적용 필수

## 9. 구매 분포

- 구매 1일(=1회) 76.83%, 2일 이상(=2회+) 23.17%, 3일 이상(=3회+) 8.88%
- 구매 간격: median 9.48일 (p25 0.89일, p75 32.82일, p90 68.05일, p95 92.47일)
- 고객당 평균 구매 이벤트 2.55건, 평균 고유 구매 상품 2.00개, 평균 구매 카테고리 1.70개

## 10. 장바구니 분포

- 추가→구매 전환율 20.27% (median 소요시간 0.12시간 ≈ 7분)
- 제거 후에도 구매한 사례 9.71%
- 상위 추가/제거 상품이 거의 동일 상품군으로 겹침 (`reports/phase1_top_cart_items.csv`)

## 11. 이벤트 간 연결성

- client_id는 이벤트 간 정상 연결 (교집합 존재, 8.4)
- sku는 구매·장바구니·속성 테이블 간 100% 매칭 (8.5)
- **url(page_visit)은 sku와 연결 불가** → 상품 단위 퍼널 구조적으로 불가능, 고객 단위 퍼널만 가능 (`docs/methodology.md`)
- 세션 ID 없음 — 세션화 기준(30분/60분/일단위) 미확정, Phase 2에서 실제 이벤트 간격 분포로 재검토 예정

## 참조 문서

- `reports/phase1_download_log.md` (8.1)
- `reports/phase1_file_structure.md`, `phase1_event_summary.csv`, `phase1_data_dictionary.csv` (8.2)
- `reports/phase1_timestamp_validation.md`, `phase1_timestamp_summary.csv` (8.3)
- `reports/phase1_customer_overlap.md`, `phase1_customer_overlap.csv`, `phase1_customer_event_type_distribution.csv` (8.4)
- `reports/phase1_product_match.md`, `phase1_product_match.csv` (8.5)
- `reports/phase1_event_quality.md`, `phase1_data_quality.csv`, `phase1_outlier_candidates.csv` (8.6)
- `reports/phase1_purchase_cart_search_behavior.md`, `phase1_behavior_summary.csv`, `phase1_top_cart_items.csv` (8.7\~8.9)
- `reports/phase1_observation_period.md`, `phase1_observation_period.csv` (8.10)
- `docs/methodology.md`, `docs/limitations.md`, `docs/decisions_pending_review.md`

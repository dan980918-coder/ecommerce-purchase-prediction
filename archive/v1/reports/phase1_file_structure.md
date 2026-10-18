# Phase 1 - 8.2 파일 구조 검사

검사 도구: DuckDB 1.5.5 (Python 3.13.5, `duckdb.read_parquet` lazy scan — 전체 데이터를 Pandas로 메모리에 올리지 않음)
검사 스크립트: `scripts/validate_data.py`
원본 데이터 경로: `data/raw/synerise_dataset/` (아카이브 `data/raw/synerise_dataset.tar.gz` 압축 해제본)

## 파일별 요약

| 파일 | 크기 | 행 수 | 열 수 | 컬럼 | 완전 중복 행 | PK 후보 | PK 유일성 |
|---|---:|---:|---:|---|---:|---|---|
| product_buy.parquet | 30.05 MB | 2,318,502 | 3 | client_id, timestamp, sku | 364,491 | (client_id, timestamp, sku) | **아니오** |
| add_to_cart.parquet | 100.54 MB | 7,541,117 | 3 | client_id, timestamp, sku | 121,309 | (client_id, timestamp, sku) | **아니오** |
| remove_from_cart.parquet | 34.84 MB | 2,688,894 | 3 | client_id, timestamp, sku | 119,656 | (client_id, timestamp, sku) | **아니오** |
| page_visit.parquet | 1.87 GB | 199,451,980 | 3 | client_id, timestamp, url | 17,320,847 | (client_id, timestamp, url) | **아니오** |
| search_query.parquet | 335.74 MB | 13,223,769 | 3 | client_id, timestamp, query | 612,891 | (client_id, timestamp) | **아니오** |
| product_properties.parquet | 64.24 MB | 1,534,050 | 4 | sku, category, price, name | 0 | (sku) | **예** |

전체 행 수: 226,758,312행 (product_properties 제외 이벤트 5종 합계)

## 컬럼 스키마 상세

### product_buy / add_to_cart / remove_from_cart (동일 스키마)
- `client_id`: BIGINT, 결측 0
- `timestamp`: **VARCHAR** (형식: `YYYY-MM-DD HH:mm:ss`) — 공식 문서상 timestamp이지만 실제 타입은 문자열. 8.3에서 파싱 검증 및 CAST 필요
- `sku`: BIGINT, 결측 0

### page_visit
- `client_id`: BIGINT, 결측 0
- `timestamp`: VARCHAR, 결측 0
- `url`: BIGINT (숫자 ID), 결측 0 — 공식 문서와 일치, 실제 URL 문자열 아님

### search_query
- `client_id`: BIGINT, 결측 0
- `timestamp`: VARCHAR, 결측 0
- `query`: VARCHAR, 결측 0 — 실제 값은 16차원 정수 배열의 문자열 표현 (product quantization 압축 임베딩). 공식 문서는 20차원이라고 했으나 실측 확인 결과 **16차원**임 (8.9에서 재확인 필요)

### product_properties
- `sku`: BIGINT, 결측 0, 고유값 1,534,050 (= 행 수, PK로 유효)
- `category`: BIGINT, 결측 0, 고유값 6,912
- `price`: BIGINT, 결측 0, 고유값 100 (가격 구간/버킷으로 추정 — 실제 금액 아님, PROJECT_GUIDELINES.md 8.5 원칙과 일치)
- `name`: VARCHAR, 결측 0 — 공식 문서상 컬럼명은 `embedding`이지만 실제 파일의 컬럼명은 **`name`**. 값은 16차원 정수 배열 문자열(상품명 임베딩으로 추정)

## 발견한 문제 / 예상과 다른 점

1. **모든 이벤트 테이블에서 완전 중복 행 존재.** 특히 `page_visit`은 199,451,980행 중 17,320,847행(8.7%)이 완전히 동일한 (client_id, timestamp, url) 조합입니다. 이게 실제 반복 행동(같은 시각 재조회)인지 로깅 중복인지는 8.6(이벤트 품질 검사)에서 추가로 판단이 필요합니다.
2. **timestamp 컬럼이 문자열(VARCHAR) 타입.** 실제 TIMESTAMP 타입이 아니라서 8.3에서 파싱 오류 여부를 먼저 확인해야 합니다.
3. **search_query의 `query` 임베딩 차원이 공식 문서(20차원)와 실측(16차원)이 다릅니다.**
4. **product_properties의 컬럼명이 공식 문서(`embedding`)와 실제 파일(`name`)이 다릅니다.** PROJECT_GUIDELINES.md 10번 중단 조건("주요 컬럼 설명이 공식 문서와 다름")에 해당할 수 있는 사안이라 별도로 보고합니다 — 다만 이건 컬럼명 표기 차이 수준이고 스키마 자체(4개 컬럼, 타입)는 문서와 일치하므로, 치명적 중단 사유는 아니라고 판단했으나 최종 판단은 사용자 확인이 필요합니다.
5. **(참고, 정식 검증은 8.3에서 진행)** 첫 5행/마지막 5행에 노출된 timestamp 값이 모두 **2022년**입니다 (예: `2022-07-07`, `2022-12-07`). PROJECT_GUIDELINES.md의 "최근 3년(2023-08-05 이후)" 기준과 충돌할 가능성이 있어 보이나, 이는 정렬되지 않은 상태의 첫/마지막 5행 샘플일 뿐이므로 전체 MIN/MAX는 8.3에서 별도로 정확히 계산하겠습니다.

## 인프라 이슈 (참고 기록)

- 최초 실행 시 `page_visit.parquet`(199M행)의 중복 행 GROUP BY 연산 중 디스크 공간 부족으로 실패 (`No space left on device`, 당시 여유 공간 5.5GB). 사용자가 디스크 공간을 확보(39GB)한 후 재실행하여 성공.
- 재실행 과정에서 압축 해제본 중 `page_visit.parquet`(1.87GB)이 사라져 있어(디스크 정리 과정에서 삭제된 것으로 추정), 원본 `.tar.gz`에서 해당 파일만 재추출 후 정상 완료.
- 시스템 Python은 3.13.5이며 PROJECT_GUIDELINES.md 명시 버전(3.12)과 다름 — 추후 가상환경 구성 시 확인 필요.

## 생성 파일

- `reports/phase1_file_structure.md` (본 문서)
- `reports/phase1_event_summary.csv` (파일별 요약 표)
- `reports/phase1_data_dictionary.csv` (컬럼별 결측/고유값 상세)
- `scripts/validate_data.py` (검사 스크립트, 재실행 가능)

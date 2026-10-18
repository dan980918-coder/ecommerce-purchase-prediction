# Phase 1 - 8.5 상품 ID 연결성 검사

검증 스크립트: `scripts/validate_product_match.py`

## 결과

| 항목 | 값 |
|---|---:|
| 구매 상품 수 (distinct sku, product_buy) | 639,126 |
| 장바구니 상품 수 (distinct sku, add_to_cart) | 1,444,160 |
| 장바구니 제거 상품 수 (distinct sku, remove_from_cart) | 824,536 |
| 상품 속성 테이블 상품 수 (distinct sku, product_properties) | 1,534,050 |
| 상품 속성 테이블 행 수 | 1,534,050 (= distinct sku, sku당 정확히 1행) |

## 매칭률

| 조합 | 매칭 | 매칭률 |
|---|---:|---:|
| 구매 상품 ↔ 속성 테이블 | 639,126 / 639,126 | **100.00%** |
| 장바구니 상품 ↔ 속성 테이블 | 1,444,160 / 1,444,160 | **100.00%** |

## 결측률 (product_properties)

| 컬럼 | 결측 수 | 결측률 |
|---|---:|---:|
| category | 0 | 0.0000% |
| price | 0 | 0.0000% |
| name (임베딩) | 0 | 0.0000% |

## 중복 및 값 범위

- 중복 sku(한 상품에 2개 이상 행): **0건** — `sku`가 product_properties에서 완전한 Primary Key로 유효함 (8.2 검사 결과와 일치)
- `price` 값 범위: min=0, max=99, distinct=100 → **실제 금액이 아니라 100개 구간(버킷) 값**으로 확인됨. PROJECT_GUIDELINES.md 8.5 원칙("가격은 실제 금액이 아니라 구간 또는 순위형 값일 수 있으므로 실제 매출로 해석하지 않는다")과 일치하므로, 이후 어떤 분석에서도 `price`를 실제 매출/금액으로 환산하지 않는다.

## 결론

- 구매·장바구니 상품이 속성 테이블과 **100% 매칭**되어, 카테고리·가격구간 기반 분석(카테고리별 퍼널, 가격대별 행동 등)이 구조적으로 가능함을 확인.
- 결측·중복 문제 없음. product_properties는 sku 기준 깨끗한 차원(dimension) 테이블.
- 8.2에서 발견했던 "컬럼명이 공식 문서(`embedding`)와 다르게 `name`으로 되어 있다"는 표기 차이 외에, 데이터 품질 자체에는 문제가 없음을 재확인.

## 생성 파일

- `reports/phase1_product_match.md` (본 문서)
- `reports/phase1_product_match.csv`
- `scripts/validate_product_match.py`

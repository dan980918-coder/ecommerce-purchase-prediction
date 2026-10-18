# Model Card — Model B: 향후 구매 가능성(Propensity) 예측

## 개요
- **목적**: 활동 고객(구매 이력 없는 고관여 탐색/장바구니 고객 포함)이 기준일 이후 14일/28일 내 구매할지 예측
- **모집단**: `mart_purchase_propensity` (snapshot_date 이전 누적 방문≥10 또는
  search_first(검색이 방문보다 먼저 — 2026-08-08 갱신, 이전 "검색≥1"은
  `mart_customer_segment.sql`이 이미 폐기한 저의도 기준이라 통일함) 또는
  장바구니/구매 이력)
- **최종 모델**: LightGBM (500 rounds, val AUC 기준 조기종료)
- **비교 대상**: 무작위, 전체평균, 최근성 규칙, 구매빈도 규칙, 방문검색 규칙, 로지스틱 회귀

## 데이터
- 학습/검증/테스트 기간: Model A와 동일한 snapshot_date 경계 사용(직접 비교 가능하도록)
- Feature Window: snapshot_date 이전 28일 / Label Window: 이후 14일 또는 28일

## Feature (8개, 2026-08-08 갱신 — avg_category_repurchase_rate 추가)
has_purchase_history, days_since_last_purchase, n_purchase_occasions_so_far,
**avg_category_repurchase_rate**, n_page_visit_28d, n_search_query_28d,
n_add_to_cart_28d, n_remove_from_cart_28d

## 성능 (test, LightGBM)

| 라벨 | AUC | PR-AUC | Lift@10% | 실제 양성률 |
|---|---:|---:|---:|---:|
| will_purchase_14d | 0.865 | 0.160 | 6.23 | 1.4% |
| will_purchase_28d | 0.858 | 0.242 | 5.95 | 2.6% |

avg_category_repurchase_rate의 feature importance는 8개 중 꼴찌(최상위
`has_purchase_history` 대비 1.7%) — 모집단 상당수가 구매 이력이 없어 이
feature 자체가 NULL이고, 이미 has_purchase_history 등 훨씬 강한 신호가
있기 때문으로 판단된다(Model A에서는 9/13위로 더 유효했음). 상세:
`docs/methodology.md`의 "`avg_category_repurchase_rate`를 Model A/B feature로
추가 + Phase 3 리포트 정정("계산 불가" → 실제 계산)" 항목.

## 한계 및 주의사항
- 모집단이 "활동 고객" 중 일부(방문 10회 이상/search_first/장바구니/구매
  이력)로 한정됨 — 완전 무작위 방문자(저관여_탐색형, 전체의 78.05%)는
  제외해 전환 가능성이 낮은 트래픽은 다루지 않음(`docs/data_dictionary.md`
  mart_purchase_propensity 항목)
- Model A와 Lift 수치를 직접 비교하면 안 됨(라벨 기저율이 달라 상한이
  다름) — `reports/phase6_modeling_results.md` "Lift 해석에 대한 일반적 교훈" 참고
- 실제 캠페인 전환율 개선은 검증되지 않음 (PROJECT_GUIDELINES.md 5번)

## 재현
`python3 scripts/train_model_b.py`

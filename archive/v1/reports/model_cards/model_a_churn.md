# Model Card — Model A: 구매 비활성(Churn) 위험 예측

## 개요
- **목적**: 과거 구매 이력이 있는 고객이 기준일(snapshot_date) 이후 14일/28일 동안 구매하지 않을지 예측
- **모집단**: `mart_churn_target` (구매 이력 있는 고객, snapshot_date 이전 구매 1회 이상)
- **최종 모델**: LightGBM (500 rounds, val AUC 기준 조기종료)
- **비교 대상**: 무작위, 전체평균, 최근성 규칙, 구매빈도 규칙, 라이프사이클 규칙, 로지스틱 회귀

## 데이터
- 학습 기간(snapshot_date): 2022-07-21 \~ 2022-09-29 (6개 스냅샷)
- 검증 기간: 2022-10-13 (1개 스냅샷)
- 테스트 기간: 2022-10-27, 2022-11-10 (2개 스냅샷)
- Feature Window: snapshot_date 이전 28일 / Label Window: 이후 14일 또는 28일

## Feature (13개, 2026-08-08 갱신 — avg_category_repurchase_rate 추가)
days_since_last_purchase, n_purchase_occasions_so_far, n_purchase_days_so_far,
avg_purchase_gap_days_so_far, n_purchases_7d/14d/28d, n_categories_so_far,
**avg_category_repurchase_rate**, n_page_visit_28d, n_search_query_28d,
n_add_to_cart_28d, n_remove_from_cart_28d

## 성능 (test, LightGBM)

| 라벨 | AUC | PR-AUC | Lift@10% | 실제 양성률 |
|---|---:|---:|---:|---:|
| churn_14d | 0.754 | 0.977 | 1.04 | 94.6% |
| churn_28d | 0.742 | 0.953 | 1.07 | 90.2% |

avg_category_repurchase_rate의 feature importance는 13개 중 9위(중간 정도
기여, 최상위 대비 4.9%) — 카테고리별 재구매율 차이(예: 특정 카테고리
28.59% vs 전체 평균 7.18%)가 실제 예측에 일부 기여함을 확인했다. 상세:
`docs/methodology.md`의 "`avg_category_repurchase_rate`를 Model A/B feature로
추가 + Phase 3 리포트 정정("계산 불가" → 실제 계산)" 항목.

## 한계 및 주의사항
- **이 모델은 Lift가 아니라 AUC로 평가하는 게 맞다.** 라벨 기저율이 90%+
  로 매우 높아(다수 클래스), Lift@K가 구조적으로 1.0\~1.1 범위에 묶여
  있다 — 이 지표만으로 "모델이 별 효과가 없다"고 오해하면 안 됨(AUC
  기준으로는 최선 규칙 대비 뚜렷한 개선, 0.754 vs 0.669). 실제로 라벨을
  60일로 늘려 검증해보니(2026-08-11, 동일 snapshot·split 통제 실험)
  양성률이 낮아질수록 Lift@10%는 올랐지만(1.038→1.105) AUC는 오히려
  떨어졌다(0.7433→0.7109) — Lift 개선이 모델 품질 개선을 의미하지
  않음을 직접 확인했다. 상세: `reports/phase6_modeling_results.md`,
  `docs/hypotheses.md` 8번
- 6개월 관측 스냅샷 기반이라 장기 이탈은 다루지 않음(`docs/limitations.md`)
- 실제 배포/캠페인 적용 시 성능은 검증되지 않음 — 과거 데이터 기반 대상
  선정 효율만 확인 (PROJECT_GUIDELINES.md 5번, 실제 이탈률 개선 주장 금지)

## 재현
`python3 scripts/train_model_a.py`

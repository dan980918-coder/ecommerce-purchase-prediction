# Phase 6 - 모델링 결과 (Model A: 구매 비활성 / Model B: 구매성향)

## 설계 결정 요약

| 항목 | 결정 | 근거 |
|---|---|---|
| 시간순 분할 | Train 6개 스냅샷(07-21\~09-29) / Val 1개(10-13) / Test 2개(10-27, 11-10) | 스냅샷이 9개뿐이라 val은 가볍게(트리 모델 조기종료용), test는 2개로 늘려 단일 시점 우연성을 줄임(PROJECT_GUIDELINES.md 21번 시간순 분할 원칙) |
| 기준선 | 무작위, 전체평균, 최근성 규칙, 구매빈도 규칙, (Model A만)라이프사이클 규칙, (Model B만)방문검색 규칙 | PROJECT_GUIDELINES.md 20번 — 복잡한 모델이 단순 규칙보다 나은지 반드시 비교 |
| 통계 모델 | 로지스틱 회귀 (StandardScaler + median 결측 대체) | PROJECT_GUIDELINES.md 20번 명시 |
| 트리 모델 | LightGBM (500 rounds, val 기준 조기종료) | PROJECT_GUIDELINES.md 선택 기술 스택, 결측치 자동 처리 가능해 feature engineering 부담 적음 |
| 평가 지표 | ROC-AUC, PR-AUC, LogLoss, Brier, Precision/Recall/Lift@5·10·20% | PROJECT_GUIDELINES.md 22번 |
| 클래스 균형 처리 | **적용 안 함**(class_weight/is_unbalance 미사용) | LogLoss/Brier(보정 확률 품질)를 함께 요구하는데, 인위적 재조정은 예측 확률의 보정을 깨뜨림. 순위 기반 지표(AUC 등)는 균형 조정 없이도 정상 작동 |

## Model A — 구매 비활성(churn) 예측

모집단: `mart_churn_target` (구매 이력 있는 고객, 4,196,385행)

**중요한 발견 — 라벨 기저율이 매우 높음(다수 클래스)**: `churn_14d` 실제 비율이
약 94.7%(val)/94.6%(test), `churn_28d`는 약 90.9%/90.2%다. 즉 "14일/28일
이내 미구매"가 이미 압도적 다수 결과이며, "이탈"이 예외가 아니라 기본값에
가깝다. 이는 PROJECT_GUIDELINES.md 원 라벨 정의(14일/28일 미구매=이탈) 자체가 짧은
구매 주기 이벤트의 자연스러운 결과다.

### 결과 (test)

| method | churn_14d AUC | churn_14d Lift@10% | churn_28d AUC | churn_28d Lift@10% |
|---|---:|---:|---:|---:|
| 무작위 | 0.503 | 1.00 | 0.501 | 1.00 |
| 전체_평균 | 0.500 | 1.00 | 0.500 | 1.00 |
| 최근성_규칙 | 0.669 | 1.03 | 0.655 | 1.05 |
| 구매빈도_규칙 | 0.638 | 1.02 | 0.623 | 1.03 |
| 라이프사이클_규칙 | 0.657 | 1.03 | 0.644 | 1.05 |
| 로지스틱_회귀 | 0.724 | 1.03 | 0.712 | 1.06 |
| **LightGBM** | **0.754** | **1.04** | **0.742** | **1.07** |

### 해석

- **AUC 기준으로는 PROJECT_GUIDELINES.md 20번 질문("복잡한 모델이 단순 규칙보다 나은가")에 명확히 "그렇다"** — LightGBM(0.754)이 최선의 규칙(최근성 규칙, 0.669)보다 뚜렷이 우수하고, 로지스틱 회귀(0.724)도 규칙보다 낫다.
- **하지만 Lift@10%는 전 방법에서 1.0\~1.07 사이로 미미하다.** 이는 모델 성능 문제가 아니라 **라벨의 구조적 한계**다 — 기저율이 이미 90%+ 이므로 Lift(선택 상위 10%의 정밀도 ÷ 전체 기저율)가 수학적으로 크게 오를 여지가 없다(이론적 상한이 1/기저율 ≈ 1.05\~1.10 수준). CRM 관점에서 "이탈 위험 상위 10%를 골라도 전체 대비 별로 특별하지 않다"는 뜻이며, 이 라벨 정의만으로는 **타겟팅 효율화의 실익이 제한적**임을 시사한다.
- Feature importance 1위는 `n_purchase_days_so_far`(누적 구매일 수) — 과거에 얼마나 자주 샀는지가 앞으로도 살지 예측하는 가장 강력한 신호였다. `days_since_last_purchase`(전형적 recency 신호)는 오히려 5위로, 단순 "최근성 규칙"만으로는 놓치는 정보가 많다는 뜻이다.
- **[2026-08-08 추가]** 카테고리별 재구매율(`avg_category_repurchase_rate`, Phase 3 리포트 정정 항목 참고)을 feature로 추가한 결과, 13개 feature 중 **9위**(gain 8,925 — 최상위 대비 4.9%, `n_purchase_occasions_so_far`와 비슷한 수준)를 차지했다. 상위 6개 feature(구매일수·방문·검색·구매간격·recency·카테고리 다양성)보다는 약하지만, 하위 4개(구매 7/14/28일 카운트, 장바구니 제거)보다는 뚜렷이 강한 신호다 — 완전히 무의미한 feature는 아니지만 핵심 동인도 아닌, 중간 수준의 보조 신호로 확인됐다. AUC 변화는 churn_14d 0.753→0.754, churn_28d 0.741→0.742로 미미하다(자세한 판단 근거는 `docs/methodology.md`의 "`avg_category_repurchase_rate`를 Model A/B feature로 추가 + Phase 3 리포트 정정("계산 불가" → 실제 계산)" 항목 참고).
- **[2026-08-11 검증 완료] "Model A는 Lift가 아니라 AUC로 평가하는 게 맞다."** 위 두 번째 불릿의 "기저율 상한" 설명이 이론적 추정에 그치지 않는지 직접 확인했다 — churn 라벨을 14/28일 대신 60일(생애주기 비활성 임계값)로 늘려, 동일한 4개 train/1개 val/1개 test snapshot(시기 차이라는 교란변수를 제거한 통제 실험)으로 재학습했다. 결과: 라벨 양성률이 낮아질수록(94.65%→90.77%→83.95%) Lift@10%는 예측대로 상승했지만(1.038→1.063→1.105), **AUC는 오히려 하락했다(0.7433→0.7312→0.7109)**. 즉 Lift가 오른 건 모델이 좋아져서가 아니라 라벨 구조가 바뀌어서였다 — Lift 개선이 모델 품질 개선을 의미하지 않는다는 함정을 실제로 재현한 것. 상세: `docs/hypotheses.md` 8번, `reports/adhoc_churn_60d_hypothesis_test.csv`, `reports/adhoc_churn_controlled_comparison.csv`.

## Model B — 향후 구매 가능성(propensity) 예측

모집단: `mart_purchase_propensity` (활동 고객 전체, 구매 이력 없는 고관여
탐색/장바구니 고객 포함, **21,119,640행** — 2026-08-08 search_first 통일로
22,277,058 → 21,119,640, `docs/methodology.md` 참고)

### 결과 (test)

| method | will_purchase_14d AUC | Lift@10% | will_purchase_28d AUC | Lift@10% |
|---|---:|---:|---:|---:|
| 무작위 | 0.499 | 1.00 | 0.499 | 0.99 |
| 전체_평균 | 0.500 | 1.18 | 0.500 | 1.17 |
| 최근성_규칙 | 0.804 | 5.55 | 0.800 | 5.31 |
| 구매빈도_규칙 | 0.803 | 5.21 | 0.801 | 5.05 |
| 방문검색_규칙 | 0.713 | 3.92 | 0.694 | 3.56 |
| 로지스틱_회귀 | 0.857 | 5.78 | 0.851 | 5.57 |
| **LightGBM** | **0.865** | **6.23** | **0.858** | **5.95** |

### 해석

- **Model A와 정반대로 Lift@10%가 5\~6배로 매우 유의미하다.** "14일 내 구매함"이 소수 클래스(약 1.4\~2.7%)이기 때문에 상위 10%를 잘 골라내면 전체 평균 대비 6배 이상 밀도 높은 구매 후보군을 만들 수 있다.
- LightGBM AUC(0.865)가 Model A(0.754)보다 훨씬 높다 — 모집단에 "한 번도 관여하지 않은" 극단과 "매우 활발한" 극단이 함께 있어 모델이 구분할 신호가 더 뚜렷하기 때문으로 보인다. Feature importance 1위는 `has_purchase_history`(과거 구매 이력 유무) — 구매 이력이 있다는 사실 자체가 가장 강력한 신호였다.
- **[2026-08-08 추가]** `avg_category_repurchase_rate`를 Model A와 동일하게 추가했으나, 여기서는 8개 feature 중 **꼴찌**(gain 10,136 — 최상위 대비 1.7%)에 그쳤다. Model B의 모집단은 구매 이력이 없는 후보까지 포함해 상당수가 이 feature 값을 아예 갖지 않고(NULL — 정의상 구매한 카테고리가 없음), 이미 `has_purchase_history`·`n_purchase_occasions_so_far`·`days_since_last_purchase`라는 압도적으로 강한 신호가 있어 카테고리 재구매율이 추가로 줄 수 있는 정보가 제한적이었다. "산 적 있는지"가 핵심 질문인 Model B보다 "이미 사본 사람들 사이의 차이"를 보는 Model A에서 이 feature가 더 유용하다는 뜻이다.
- **[2026-08-08 추가]** 모집단 정의를 search_first로 통일(저의도 search-only 고객 제외)한 뒤 재학습한 결과, AUC/Lift가 아주 미세하게 하락했다(will_purchase_14d AUC 0.867→0.865, Lift@10% 6.31→6.23). 저의도 고객을 제외해 "쉽게 구분되는 진짜 비활동 고객"이 줄어든 영향으로 추정되며, feature importance 순위는 그대로다. 목적이 AUC 최적화가 아니라 모집단 정의를 실제("활동 고객")에 맞게 정정하는 것이었으므로 이 정도 변화는 예상된 트레이드오프로 판단한다(`docs/methodology.md` 참고).
- **CRM 실무 시사점**: Model A(비활성 위험)는 "누구를 재활성화할지"에는 규칙 대비 개선이 제한적이지만, Model B(구매성향)는 "누구를 구매 유도 타겟으로 상위 10%만 고를지"에 훨씬 강력하다. 즉 이 데이터셋에서는 **재활성화보다 구매 유도(전환) 타겟팅이 모델 기반 접근의 이득이 훨씬 큰 영역**이라는 결론을 내릴 수 있다. Phase 7 CRM 타기팅 시뮬레이션에서 이 비대칭을 그대로 반영해야 한다.

## Lift 해석에 대한 일반적 교훈 (학습 포인트)

이번 결과는 "Lift@K가 낮다 = 모델이 나쁘다"로 오해하기 쉬운 흔한 함정을
보여준다. Lift는 항상 **라벨의 기저율에 상한이 묶여 있다** — 기저율이
90%인 이진 라벨에서는 아무리 좋은 모델도 Lift가 1.1을 넘기 어렵고,
기저율이 2%인 라벨에서는 좋은 모델이 Lift 6\~10배를 쉽게 낸다. 따라서
Lift@K로 서로 다른 라벨(Model A vs Model B)을 직접 비교하면 안 되고,
**같은 라벨 안에서 방법론 간(규칙 vs 모델) 비교에만** 써야 한다. 대신
서로 다른 라벨의 "모델이 규칙보다 얼마나 나은가"는 AUC/PR-AUC로 비교하는
것이 더 공정하다.

**[2026-08-11] 이론이 아니라 실제로 확인됨.** 위 설명이 정말 맞는지
Model A의 라벨 자체를 60일로 바꿔 직접 검증했다 — 라벨이 희소해질수록
Lift는 예측대로 올랐지만 AUC는 오히려 떨어졌다. 이 문서의 "라벨 기저율에
상한이 묶여 있다"는 주장은 더 이상 이론적 추정이 아니라 통제 실험으로
재현된 결과다. 상세: `docs/hypotheses.md` 8번.

## 생성 파일

- `reports/phase6_modeling_results.md` (본 문서)
- `reports/phase6_model_a_results.csv`, `reports/phase6_model_a_feature_importance.csv`
- `reports/phase6_model_b_results.csv`, `reports/phase6_model_b_feature_importance.csv`
- `src/models/metrics.py`, `src/models/baselines.py`
- `scripts/train_model_a.py`, `scripts/train_model_b.py`
- `sql/intermediate/int_customer_category_repurchase_by_snapshot.sql`,
  `sql/intermediate/int_customer_category_repurchase_avg_by_snapshot.sql`
  (2026-08-08 추가, `avg_category_repurchase_rate` feature 근거)
- `reports/figures/10_model_roc_lift_curves.png`

# Decisions Pending Review — 전처리/정제 잠정 결정 로그

---

## 버스트 이벤트 (5초 이내 동일 고객·상품 반복)

**이슈**: `scripts/validate_event_quality.py` 결과, 동일 (client_id, sku/url)
조합이 5초 이내에 반복 기록되는 비율이 product_buy 16.44%(381,152건),
add_to_cart 4.72%, remove_from_cart 10.30%, page_visit 16.60%(33,118,828건),
search_query(client_id 기준) 13.03%로 확인됨 (`reports/phase1_data_quality.csv`
섹션 B). 원인(더블클릭 재로깅 / 수량별 개별 로깅 / 실제 재구매)은 세션ID나
주문ID가 데이터에 없어 완전히 확정할 수 없음.

**검토한 선택지**
1. 최초 1건만 남기고 즉시 dedup
2. 원본 보존 + 별도 플래그 컬럼 추가(비파괴적)
3. 원인 조사 먼저 완료 후 결정

**선택한 기본값**: **2번 (원본 보존 + 플래그 컬럼)**

**근거**: 원인이 불확실한 상태에서 삭제(1번)는 되돌릴 수 없고, product_buy처럼
매출과 직결된 테이블에서 실제 유효 행동(예: 같은 상품 2개를 짧은 간격으로
개별 구매)을 지울 위험이 있다. 조사(3번)는 order_id/session_id 부재로 완전한
결론에 도달하기 어려워 시간 대비 확신도가 낮다. 플래그 추가는 가역적이고
저위험이며, 이후 Phase 2에서 언제든 "포함/제외" 두 버전을 다 만들어볼 수 있다.

**반영 위치**: Phase 2 SQL staging 레이어(`sql/staging/stg_product_buy.sql` 등)
설계 시 `is_burst_repeat_5s` (또는 유사) boolean 컬럼을 추가해 원본 행은
유지하되 플래그로 구분하는 방식으로 구현 예정. Phase 1에서는 정의만 기록하고
실제 스키마 변경은 하지 않음(원본 파일 미변경, `data/raw/`는 read-only 취급).

**상태**: 잠정 결정 — 재검토 필요 (Phase 2에서 실제 구현 시 재확인)

---

## 이상치 고객 (극단적 고빈도 client_id)

**이슈**: 고객별 이벤트 수 분포에서 극단적 long-tail 이상치 발견 (예:
page_visit p99.9=463인데 max=55,561, client_id OUTLIER_13). client_id `OUTLIER_07`,
`OUTLIER_06`, `OUTLIER_08`은 여러 이벤트 타입(add_to_cart, remove_from_cart,
search_query)에서 동시에 상위 이상치로 반복 등장 — 봇/크롤러 또는 비정상
파워유저 가능성 (`reports/phase1_event_quality.md` 섹션 A,
`reports/phase1_data_quality.csv`).

**검토한 선택지**
1. 8.7\~8.9까지 그대로 두고 지켜보기 (배제하지 않음)
2. 지금 바로 제외 기준(예: p99.9 초과) 설정
3. 배제하지 않되 별도 "이상치 후보 리스트"로 추적

**선택한 기본값**: **1번 + 3번 결합** — 배제하지 않고 원본 그대로 유지하며,
이번에 발견된 이상치 client_id 후보를 별도 CSV로 기록해 추적한다. 이후
8.7\~8.9 및 Phase 3\~6 보고서에서 평균 대신 중앙값/percentile 중심으로
서술한다.

**근거**: PROJECT_GUIDELINES.md 1\~4번 규칙(데이터 확인 전 기준 임의 확정 금지)에 따라
원인(봇인지 정상 고빈도 고객인지)을 모른 채 배제 기준(2번)부터 정하는 것은
성급하다. 반대로 아무 기록 없이 방치하면 나중에 이 고객들의 존재를 잊고
평균 기반 지표를 그대로 신뢰할 위험이 있어, 후보 리스트로 남겨 추적성을
확보한다.

**반영 위치**: `reports/phase1_outlier_candidates.csv` 생성 (아래 표 참고).
이후 Phase 4(세그먼트 설계)·Phase 5\~6(모델링 feature 처리)에서 이 목록을
참고해 클리핑/제외/별도 세그먼트 여부를 다시 판단한다.

| client_id | 등장 이벤트 타입(횟수) |
|---|---|
| OUTLIER_07 | add_to_cart(1,993), remove_from_cart(1,511), search_query(4,558) |
| OUTLIER_06 | add_to_cart(2,200), remove_from_cart(1,032) |
| OUTLIER_08 | add_to_cart(1,491), remove_from_cart(1,351) |
| OUTLIER_13 | page_visit(55,561) |
| OUTLIER_14 | page_visit(37,073) |
| OUTLIER_15 | page_visit(29,566) |
| OUTLIER_16 | page_visit(28,306) |
| OUTLIER_17 | page_visit(25,860) |
| OUTLIER_01 | product_buy(644) |
| OUTLIER_02 | product_buy(536) |
| OUTLIER_03 | product_buy(485) |
| OUTLIER_04 | product_buy(404) |
| OUTLIER_05 | product_buy(383) |
| OUTLIER_09 | add_to_cart(1,227) |
| OUTLIER_10 | add_to_cart(1,220) |
| OUTLIER_11 | remove_from_cart(858) |
| OUTLIER_12 | remove_from_cart(823) |
| OUTLIER_18 | search_query(3,245) |
| OUTLIER_19 | search_query(2,916) |
| OUTLIER_20 | search_query(2,824) |
| OUTLIER_21 | search_query(2,353) |

**상태**: 잠정 결정 — 재검토 필요 (Phase 4\~6에서 실제 처리 여부 재확인)

---

## "구매 1회/2회+/3회+" 정의: 이벤트 수 vs 고유 구매일 수

**이슈**: PROJECT_GUIDELINES.md 8.7은 "구매 1회 고객 비율", "구매 2회 이상 고객 비율" 등을
요구하지만, "1회"를 이벤트(행) 단위로 볼지 날짜(day) 단위로 볼지 명시하지
않음. 동일 날짜에 여러 상품을 한 번에 구매하면 이벤트는 여러 건이지만
실질적으로는 "한 번의 쇼핑"일 수 있음.

**검토한 선택지**
1. 이벤트(행) 수 기준 — 구현이 단순하지만 "한 번의 장바구니에 여러 상품"을
   여러 번의 구매로 과대 계산할 위험
2. 고유 구매일(day) 수 기준 — 같은 날 여러 건은 1회로 묶음
3. 세션 단위 — 세션 ID가 없어 데이터상 불가능(8.8에서 이미 확인)

**선택한 기본값**: **2번 (고유 구매일 수 기준)**

**근거**: 1번은 "한 번에 3개 상품을 담아 결제"한 경우를 3회 구매로 잘못
셀 수 있어 반복구매율을 과대평가한다. 3번은 세션 ID 부재로 데이터상
구현 불가능. 2번이 "구매 1회 vs 반복구매"라는 CRM 관점의 실제 의미에
가장 가깝고, 계산도 재현 가능하다.

**반영 위치**: `scripts/validate_purchase_cart_search.py`의 `n_purchase_days`
계산 로직. 결과: 구매 1일(1회) 76.83%, 2일 이상(2회+) 23.17%, 3일 이상(3회+)
8.88%. (`reports/phase1_purchase_cart_search_behavior.md`)

**상태**: 잠정 결정 — Phase 4(세그먼트)·Phase 5(모델링 레이블)에서 동일 정의를
유지할지 재확인 필요.

---

## "관찰 종료 직전 구매 고객 비율" 계산 창(window) 길이

**이슈**: PROJECT_GUIDELINES.md 8.7이 요구하는 "관찰 종료 직전 구매 고객 비율" 지표를
계산하려면 "직전"의 구체적 일수를 정해야 함. 이는 이탈/비활성 기준(14일 vs
28일)과 겹치는 영역이라 확정하면 안 되는 판단.

**검토한 선택지**
1. 14일 (PROJECT_GUIDELINES.md 18번 "모델 A"에서 공식 과제와 비교 가능한 기준으로 이미
   언급된 값)
2. 28일 (PROJECT_GUIDELINES.md가 함께 비교 대상으로 언급한 값)
3. 두 창 모두 계산

**선택한 기본값**: **1번 (14일)을 참고용으로만 사용, "공식 이탈 기준 아님"이라고
결과에 명시**

**근거**: Phase 1은 아직 이탈/비활성 기준을 확정하는 단계가 아니므로(PROJECT_GUIDELINES.md
규칙 3번), 두 값을 다 계산해 마치 둘 다 후보인 것처럼 보고하면 오히려 이 값이
이후 Phase 5\~6 결정에 앵커링(anchoring)될 위험이 있다. 대신 14일 하나만
참고용으로 계산하고 "공식 기준 아님"을 명시해, Phase 5\~6에서 실제 구매간격
분포(8.7에서 이미 확인한 median 9.48일, p90 68.05일)를 근거로 원점에서 다시
결정하도록 유도한다.

**반영 위치**: `scripts/validate_purchase_cart_search.py`의
`window_days = 14` 변수. 결과: 15.18%(138,041/909,210명)가 마지막 14일 내
구매. (`reports/phase1_purchase_cart_search_behavior.md`)

**상태**: 잠정 결정 — Phase 5\~6에서 실제 이탈/비활성 기준 확정 시 반드시
재검토 (PROJECT_GUIDELINES.md 규칙상 이 값 자체가 최종 기준이 될 수 없음).

---

## 좌측/우측 검열(censoring) 판정 창(window) 길이

**이슈**: PROJECT_GUIDELINES.md 8.10은 "데이터 시작 시점에 이미 활동 중인 고객", "데이터
종료 시점 직전 처음 등장한 고객"을 확인하라고 요구하지만, "시작/종료 시점"을
며칠로 볼지는 명시하지 않음.

**검토한 선택지**
1. 좌측 7일 / 우측 14일 (임의의 짧은 참고 창)
2. 좌측 30일 / 우측 30일 (더 넓은 창)
3. 전체 관측 기간(167일) 대비 비율(예: 상하위 5%)로 정의

**선택한 기본값**: **1번 (좌측 7일 / 우측 14일)**

**근거**: 이 지표의 목적은 "정확한 검열 인구 규모 확정"이 아니라 "검열 문제가
실재하며 무시할 수 없는 규모임을 보여주는 것"이다. 짧은 창(7일/14일)을
쓰면 오히려 검열 규모를 보수적으로(작게) 추정하게 되므로, 결과가 이미
유의미하다면(실제로 좌측 5.54%, 우측 8.17%, 구매자 기준 각각 4.45%/15.18%)
"과장되지 않은 최소 추정치"로서 설득력이 있다. 우측 14일은 8.7에서 이미 참고용
"관찰 종료 직전 구매 비율" 계산에 쓴 값과 통일해 두 보고서 간 수치를 상호
검증 가능하게 했다(둘 다 138,041명/15.18%로 일치 확인).

**반영 위치**: `scripts/validate_observation_period.py`의 `LEFT_CENSOR_DAYS=7`,
`RIGHT_CENSOR_DAYS=14`. 결과: `reports/phase1_observation_period.md`,
`reports/phase1_observation_period.csv`.

**상태**: ~~잠정 결정~~ → **결정 완료 (2026-08-05)**. Phase 5\~6에서의 실제
처리 방침은 아래 항목("우측 검열 고객 처리 방침")에서 확정됨. 이 항목의
7일/14일 창은 "검열 문제 존재 확인용" 진단 지표로서의 역할로 목적을
다했고, 실제 모델링 설계는 스냅샷 구조로 별도 해결됨.

---

## 우측 검열 고객 처리 방침 [결정 완료]

**이슈**: 위 8.10 항목에서 진단한 우측 검열 고객(구매자 기준 138,041명,
15.18%)을 Phase 5\~6 모델링에서 실제로 어떻게 처리할지. `reports/phase1_recommendation.md`
에 Phase 5 착수 전 반드시 해결해야 할 blocker로 검토함.

**검토한 선택지** (상세는 `docs/methodology.md`의 "프로젝트 주제 확정(A안) 및
우측 검열(right-censoring) 고객 처리 방침" 항목 참고)
1. 우측 검열 대상 고객을 학습/평가에서 개별적으로 제외
2. `snapshot_date`를 관측 종료일 − label window(14일) 이전으로만 선택해
   스냅샷 설계 자체에서 검열을 원천 차단
3. 생존분석(survival analysis)으로 검열을 명시적으로 모델링

**결정**: **2번 채택** + 안전장치로 1번의 "검열 여부 체크"를 PROJECT_GUIDELINES.md 31번
데이터 테스트(Snapshot Feature·Label 분리 검증)에 포함.

**근거 및 상세**: `docs/methodology.md`의 "프로젝트 주제 확정(A안) 및 우측
검열(right-censoring) 고객 처리 방침" 항목에 전문 기록. 요약 —
`mart_customer_snapshot`의 Feature/Label Window 구조(PROJECT_GUIDELINES.md 12번)를 그대로
활용해 `snapshot_date ≤ 2022-11-24`(=2022-12-08 − 14일)로 제한하면, 개별
고객 단위 검열 판정 로직 없이 구조적으로 문제가 해소됨. 안전장치로
`snapshot_date + 14일 ≤ MAX(관측 timestamp)`를 검증하는 pytest를
`sql/tests/`와 `tests/data_quality/`에 추가하기로 함.

**상태**: **결정 완료.** Phase 2 `mart_customer_snapshot` 설계 및 Phase 5
모델링 시 이 방침을 그대로 적용한다. 재검토가 필요해지면(예: label window
길이를 14일이 아닌 다른 값으로 바꾸는 경우) 이 항목을 다시 연다.

---

## 코호트별 재구매율의 우측 검열 처리

**이슈**: `mart_customer_retention`(코호트별 7/14/28일 재구매율)을 만드는 중,
관측 종료(2022-12-08)에 가까운 코호트(예: 2022-12-05주)는 28일 재구매 관측
창 자체가 실제 데이터 범위를 벗어난다는 걸 발견함. 이 상태로 재구매율을
그대로 노출하면 "최근 코호트일수록 재구매율이 낮아지는" 것처럼 보이는
착시가 생기는데, 실제로는 관측 부족일 뿐 진짜 하락이 아닐 수 있음. (실제로
빌드 결과 2022-11-14 이후 코호트부터 28일 재구매율이 눈에 띄게 낮아지는
패턴이 나타남 — `reports`에 기록된 실측치로 확인.)

**검토한 선택지**
1. 검열된 코호트를 아예 마트에서 제외
2. 그대로 노출하되 `is_7d/14d/28d_window_censored` 플래그 컬럼 추가
3. 검열되지 않은 값으로 보정(외삽) 시도

**선택한 기본값**: **2번 (플래그 컬럼 추가, 값은 그대로 노출)**

**근거**: 1번(제외)은 최근 코호트 데이터를 아예 숨겨 "최근 트렌드를 못 보는"
손실이 크다. 3번(보정)은 근거 없는 외삽이라 PROJECT_GUIDELINES.md "입력에 없는 숫자
생성 금지" 원칙과 충돌 위험이 있다. 2번은 우측 검열 고객 처리 방침(위 항목)과
동일한 철학 — 데이터를 숨기거나 조작하지 않고 "이 값은 불완전한 관측에 기반함"
을 명시적으로 드러낸다. Phase 3에서 코호트별 재구매율을 해석/시각화할 때 이
플래그가 TRUE인 코호트는 점선·주석 등으로 구분 표시하는 방식을 권장.

**반영 위치**: `sql/marts/mart_customer_retention.sql`의
`is_7d_window_censored`, `is_14d_window_censored`, `is_28d_window_censored`
컬럼. 실행 결과 2022-11-14주부터 28일 플래그가, 2022-11-28주부터 14일
플래그가, 2022-12-05주부터 7일 플래그까지 TRUE로 확인됨 (총 25개 코호트 중
마지막 4개 코호트가 영향받음).

**상태**: 결정 완료(기본값 적용). Phase 3에서 대시보드/보고서에 실제로
플래그를 반영해 표시하는지 재확인 필요.

---

(이후 항목은 아래에 시간순으로 계속 추가한다.)

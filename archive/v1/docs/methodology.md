# Methodology — 주요 결정 기록

---

## 상품 단위 퍼널 불가 확정 → 프로젝트 스코프를 "고객 단위 CRM 타기팅"으로 한정

Phase 1 8.9(페이지 방문과 검색 검사)에서 `page_visit.url`이 공식 문서와 실제
데이터 양쪽에서 "어떤 상품이 표시됐는지 알 수 없는" 익명 숫자 ID로 확인됐고,
`sku`(product_buy/add_to_cart/product_properties의 상품 식별자)와 연결할 수
있는 키가 데이터에 존재하지 않는다. 따라서 "이 상품 페이지를 본 고객이
이 상품을 구매했는가"와 같은 **상품 단위 방문→구매 퍼널은 구조적으로
불가능**하다 (근거: `reports/phase1_purchase_cart_search_behavior.md` 8.9
섹션).

이는 단순한 기술적 제약이 아니라 프로젝트 스코프 자체를 규정하는 사실이다.
가능한 것은 "고객이 얼마나 방문·검색했는가 → 그 고객이 구매했는가"라는
**고객 단위 탐색 퍼널**뿐이며, "어떤 상품을 보고 어떤 상품을 샀는가" 같은
상품 추천/상품 단위 분석은 이 데이터로 만들 수 없다. 따라서 이 프로젝트는
애초에 "다음에 살 상품 추천"이 아니라 **"어떤 고객을 CRM으로 우선 접촉할
것인가"라는 고객 단위 타기팅 문제**로 스코프가 좁혀지며, 이는 PROJECT_GUIDELINES.md
1번(프로젝트 목적)이 이미 상품 추천이 아닌 고객 라이프사이클/CRM 타기팅으로
설계된 것과 정합적이다. 이후 Phase 2\~9에서 "상품 추천"류 기능을 임의로
추가하지 않는다.

---

## 프로젝트 주제 확정(A안) 및 우측 검열(right-censoring) 고객 처리 방침

### 프로젝트 주제 확정

Phase 1 데이터 구조 분석 결과(`reports/phase1_recommendation.md`), 검토한
3개 방향 중 **A안(구매 비활성 위험 예측 + CRM 타기팅)** 이 이 데이터셋에
가장 적합한 것으로 확인됐다. B안(장바구니 이탈 특화)은 add→buy 시간
간격 등 핵심 신호가 이미 확인돼 구현 feasibility는 가장 높지만, PROJECT_GUIDELINES.md가
요구하는 고객 라이프사이클 전반을 다루지 못하고 재활성화 등 다른 CRM
목적이 스코프에서 빠진다. C안(라이프사이클 세그먼트 중심)은 해석
가능성과 실무 적용성이 크지만, "모델 기반 타기팅이 단순 규칙보다
효율적인가"라는 핵심 질문에 대한 비교 근거가 A안만큼 강하지 않다. A안은
PROJECT_GUIDELINES.md 원 설계(Phase 2\~10)와 1:1로 대응하고 재활성화(비활성 위험)와
구매 유도(구매성향) 두 CRM 목적을 함께 다룰 수 있어, 이후 모든 Phase는
A안을 기준으로 진행한다.

### 배경 — 우측 검열 문제

Phase 1 8.10에서 확인한 대로, 관측 종료(2022-12-08) 14일 이내에 마지막
구매가 있었던 고객은 138,041명(전체 구매자 909,210명의 15.18%)이다. 이
고객들은 "그 이후 14일간 구매가 없었다"는 사실이 실제 비활성인지, 아니면
데이터가 거기서 끊긴 것뿐인지 구분할 수 없다(`reports/phase1_observation_period.md`,
`docs/limitations.md`). 이 blocker를 해결하지 않고는 Phase 5\~6(구매 비활성
모델링)에 착수할 수 없다는 점을 `reports/phase1_recommendation.md`에 명시하고,
후보 3안(제외/스냅샷 설계로 원천 차단/생존분석)의 장단점을 비교 검토했다.

### 결정 내용

**스냅샷 설계로 검열 문제를 원천 차단한다 (후보 2번 채택).**

PROJECT_GUIDELINES.md 12번(`mart_customer_snapshot`의 Feature Window/Label Window 구조)과
21번(시간순 데이터 분할, 미래 정보 누수 방지 원칙)을 그대로 활용해:

- `snapshot_date`는 반드시 **관측 종료일(2022-12-08)로부터 label window
  길이(예: 14일) 이상 이전**으로만 선택한다. 즉 14일 label window를 쓴다면
  `snapshot_date ≤ 2022-11-24`.
- 이 조건을 만족하는 한, 어떤 `snapshot_date`를 선택하든 그 라벨 계산 구간
  (`snapshot_date` \~ `snapshot_date + 14일`)은 항상 완전히 관측된 데이터
  범위 안에 들어가므로, 개별 고객 단위로 "이 고객이 검열 대상인지" 판정하는
  로직이 별도로 필요 없다. 관측 종료 근처에 처음 등장한 고객은 애초에 그
  시점 이전 `snapshot_date`에서는 "과거 구매 이력이 있는 고객" 모집단에
  자연스럽게 포함되지 않거나, 포함되더라도 그 라벨은 항상 완전히 관측된
  구간에서 계산된다.
- 여러 `snapshot_date`(예: 주 단위 롤링)를 관측 기간 내에서 뽑아 학습
  표본을 구성한다.

**안전장치**: PROJECT_GUIDELINES.md 31번 "Snapshot Feature·Label 분리" 테스트 항목에
다음 데이터 테스트를 추가한다.

> `mart_customer_snapshot`의 모든 행에 대해
> `snapshot_date + INTERVAL '{label_window_days} days' <= 전체 관측 데이터의 MAX(timestamp)`
> 를 만족하는지 검증하는 pytest. 위반하는 행이 하나라도 있으면 실패 —
> 즉 "라벨 계산 구간이 실제 관측 범위를 벗어나는 스냅샷"이 마트에 존재하지
> 않음을 보장한다.

이 테스트는 Phase 2(SQL 데이터마트 `sql/tests/`)와 Phase 5(모델링 전 `tests/data_quality/`)
양쪽에 구현한다.

### 근거

- 이미 설계된 아키텍처(Feature/Label Window)를 그대로 재사용해 추가 복잡도가
  거의 없다 — 고객 단위로 "검열 여부" 플래그를 별도로 관리하지 않아도 된다.
- PROJECT_GUIDELINES.md 20\~21번의 "단순 기준선 우선", "시간순 분할, 미래 누수 방지"
  원칙과 완전히 정합적이다.
- 생존분석(후보 3번)은 통계적으로 더 엄밀하지만 이 프로젝트 스코프 대비
  구현·해석 비용이 크다고 판단해 채택하지 않았다(과설계 방지, PROJECT_GUIDELINES.md
  "처음부터 복잡한 딥러닝/과설계 모델 지양" 정신과 부합).

### 트레이드오프

- 관측 기간 167일 중 마지막 14일(2022-11-25\~2022-12-08)은 `snapshot_date`
  로 직접 사용할 수 없다 — 다만 이 구간의 이벤트 데이터 자체는 다른
  `snapshot_date`들의 label window로는 계속 활용된다. 실질적으로 사용 가능한
  `snapshot_date` 범위는 약 153일로 소폭 줄어든다(원본 이벤트 데이터
  손실은 없음).

### 관련 문서

- `reports/phase1_recommendation.md` (blocker 원문)
- `reports/phase1_observation_period.md`, `docs/limitations.md` (우측 검열 실측치)
- `docs/decisions_pending_review.md` (8.10 항목 — 이 결정으로 해결됨)

---

## 라이프사이클 상태 임계값 확정 (14일/28일/60일)

### 배경

PROJECT_GUIDELINES.md 16번은 라이프사이클 8\~9개 후보 상태를 제시하되 "기준은 임의로
결정하지 않는다. 고객별 구매간격과 행동 분포를 근거로 여러 기준을 비교한다"
고 명시했다.

### 결정

recency(마지막 구매 이후 경과일) 기준 4단계 경계값을 다음과 같이 데이터
기반으로 설정했다.

| 경계 | 값 | 근거 |
|---|---:|---|
| 활성 ↔ 구매 감소 | 14일 | 구매 간격 중앙값(9.48일, Phase 1 8.7) × 1.5 — CRM 업계에서 "정상 주기 대비 조기 경고"에 흔히 쓰이는 배수 |
| 구매 감소 ↔ 비활성 위험 | 28일 | 구매 간격 중앙값 × 3 — "고위험" 신호로 흔히 쓰이는 배수 |
| 비활성 위험 ↔ 비활성 | 60일 | 구매 간격 p90(68.05일, Phase 1 8.7)을 반올림 — 정상 구매 패턴의 90%를 벗어나는 지점 |

PROJECT_GUIDELINES.md 18번이 이미 14일과 28일을 "비교 대상"으로 언급했는데, median
기반 배수 계산 결과가 이 값들과 정확히 일치해 그대로 채택했다 — 즉 이
값들은 공식 과제 관행을 그대로 빌려온 것이 아니라, 이 데이터셋의 실제
구매 주기에서 독립적으로 도출한 뒤 PROJECT_GUIDELINES.md의 제안과 교차 검증된 값이다.

PROJECT_GUIDELINES.md 16번 후보 9개 중 "반복구매 고객"과 "활성 구매 고객"은 상호
배타적 상태로 만들기 어려워(둘 다 "최근 정상 구매 중"이라는 동일 개념)
하나의 상태로 통합했다. `n_purchase_days` 컬럼은 남겨둬 필요 시 추후
재분리 가능하게 했다.

**참고(향후 고도화 여지)**: 더 정교한 방식으로는 고객별 실제 구매주기
(`avg_purchase_gap_days`)에 개인화된 배수를 적용하는 방법도 있다(일부
성숙한 CRM/CDP가 사용). 이번엔 설명 가능성과 구현 단순성을 우선해 전체
공통 임계값을 채택했고, 개인화 버전은 Phase 6 모델링에서 feature로
`avg_purchase_gap_days` 자체를 넣어 모델이 학습하도록 하는 방식으로
대체 가능하다.

### 결과

전체 22,298,361명이 8개 상태로 남김없이 분류됨 (미분류 0건, 구매 관련
상태 합계가 구매자 수 909,210명과 정확히 일치 — `tests/data_quality/test_lifecycle.py`
로 검증). 분포는 `docs/data_dictionary.md` mart_customer_lifecycle 항목 참고.

### 관련 문서

- `sql/marts/mart_customer_lifecycle.sql`, `docs/data_dictionary.md`
- `reports/phase1_purchase_cart_search_behavior.md` (구매간격 percentile 원자료)

---

## `구매_직전_탐색형` 세분화 기준 재조정: 검색 단독 신호 → 검색-선행(search_first) 신호

### 배경

`mart_customer_segment.sql`은 탐색_고객을 `n_page_visit >= 10 OR n_search_query > 0`
조건으로 `구매_직전_탐색형`(고관여) vs `저관여_탐색형`으로 나눠왔다. 방문 10회
기준은 탐색_고객 방문횟수별 실제 전환율을 세밀하게(1회 단위)
확인한 결과, 뚜렷한 변곡점이 아니라 완만하고 연속적인 증가 곡선 위의 한
지점(p90)임이 확인됐다 — 다만 상위 10% cut·과접촉 방지라는 실무적 근거는
여전히 유효해 그대로 유지했다.

검색 조건("검색 1회 이상")은 별도로 문제가 발견됐다. 고객 전체(22,298,361명)를
첫 행동 유형별로 나눠 실제 구매전환율을 비교한 결과:

| 그룹 | 정의 | 고객 수 | 전환율 |
|---|---|---:|---:|
| search_only | 검색만 하고 방문은 전혀 없음 | 4,529 | 7.75% |
| visit_first (검색 있음, 방문<10) | 방문을 먼저 하고 그 후 검색 | 299,899 | 2.59% |
| search_first (방문<10인 하위집합) | 검색을 방문보다 먼저 함, 이후 방문 10회 미만 | 42,300 | 28.30% |
| search_first (방문 횟수 무관) | 검색을 방문보다 먼저 함 | 98,643 | 44.02% |

"검색 1회 이상"이라는 기존 조건은 이 네 그룹을 구분하지 못하고 전부 고관여로
묶어버린다. 하지만 실제로는 검색이 방문보다 먼저 발생했는지(search_first)가
핵심 신호이고, 검색만 하고 끝나거나(search_only) 방문 후 뒤늦게 검색한 경우
(visit_first, 이 표에서는 방문<10인 부분집합)는 오히려 방문 없이 검색만
있거나 탐색 의도가 약한 경우로, 실제 전환율이 낮다(2.59\~7.75%).

### 결정

`구매_직전_탐색형` 조건을 다음과 같이 변경했다.

```sql
-- 변경 전
m.n_page_visit >= 10 OR m.n_search_query > 0

-- 변경 후
m.n_page_visit >= 10
OR (검색 이벤트가 존재 AND 방문 이벤트가 존재 AND 첫 검색 시각 < 첫 방문 시각)
```

방문 10회 기준(`n_page_visit >= 10`)은 그대로 유지한다 — 변곡점은 아니지만
"상위 10% + 과접촉 방지"라는 근거 자체는 검색 조건의 결함과 무관하게 유효하기
때문이다. `first_search_ts`/`first_visit_ts`는 `mart_customer_360`이 최종
출력 컬럼으로 노출하지 않아(집계 시점에만 사용) `mart_customer_segment.sql`
내부에서 `stg_search_query`/`stg_page_visit`로부터 별도 CTE로 재계산했다.

### 결과

- `구매_직전_탐색형` 인원: 2,470,981명(전체의 11.08%) → 2,212,414명(9.92%),
  -258,567명(-10.46%) 감소.
- 규칙 자체의 판별력(전체 22,298,361명 대상, 방문<10 조건에서 검색 관련
  조건만 추가로 포착하는 증분 집단 기준): 기존 조건(검색 1회 이상, 346,728명)의
  전환율 5.80% → 신규 조건(search_first, 42,300명)의 전환율 28.30%로 상승,
  대신 포착 인원은 87.8% 감소. 즉 인원은 줄었지만 걸러낸 집단의 실제 구매
  가능성은 약 4.9배 높아졌다 — 저의도 트래픽(search_only, visit_first)을
  걸러내고 고의도 신호(search_first)만 남긴 결과로 해석된다.
- `구매_직전_탐색형` 자체는 정의상 `탐색_고객`(=`NOT is_buyer`) 하위집합이라
  세그먼트 내부에서 관측된 전환율은 항상 0%다(전체 관측기간 종료 시점 기준
  아직 구매 안 한 고객만 포함) — "실제 구매 가능성이 높아졌는가"는 이
  구간(규칙)을 전체 모집단(구매자 포함)에 적용했을 때의 과거 전환율로만
  검증할 수 있다는 점을 위 결과에 반영했다.
- `tests/data_quality/test_segment.py` 5개 전부 통과 (PK 유일성, 미분류 0건,
  세그먼트 8개, lifecycle 대응 인원 일치, 비활성형 병합 일치 — 모두 변경
  영향을 받지 않는 항목이라 회귀 없음 확인).

### 알려진 후속 정리 필요 항목 (아직 미반영)

이 변경으로 다음 파일들의 텍스트/수치가 과거(2,470,981명, 11.08\~12.60%)
기준으로 남아 최신 상태와 불일치한다. 커밋 전 별도로 갱신할지 검토 필요:

- `docs/data_dictionary.md` (세분화 기준 설명 문구, 250행)
- `reports/phase4_segment_profile.md` (세그먼트 프로파일 표/서술)
- `reports/phase9_ai_crm_report_sample.md` (샘플 리포트 인원 수치)
- `scripts/build_dashboard_data.py`, 대시보드 데이터/스크린샷 재생성 필요 여부

### 관련 문서

- `sql/marts/mart_customer_segment.sql`
- `docs/methodology.md` "라이프사이클 상태 임계값 확정" 항목 (방문 10회 p90 근거의 출처)

---

## `장바구니_이탈형`을 `장바구니_이탈형`/`장바구니_보류형`으로 분리 (8 → 9개 세그먼트)

### 배경

`장바구니_이탈형`(1,772,451명)의 CRM 목적은 "장바구니 이탈 회수(Cart
Recovery)"였는데, 실제로 이 세그먼트 안에서 "언제 장바구니에서 뺐는가"를
확인해보니(add→remove 간격 분포) 뚜렷한 이봉(bimodal) 패턴이 나와, 먼저
`cart_removal_subtype` 참고용 컬럼만 추가했다(no_removal_recorded/fast_removal/
slow_removal, 경계값 6시간은 add→remove 간격의 로그스케일 히스토그램에서
나타나는 계곡 구간의 중간값 — 임의 기준 아님).

이 컬럼을 적용해보니 `no_removal_recorded`(제거 이벤트 자체가 없음)가
1,406,964명으로 세그먼트의 **79.38%**를 차지했다. 이게 "아직 지울 시간이
없었을 뿐"(우측 검열)인지 "로깅이 빠졌을 뿐"인지 확인한 결과 둘 다
아니었다:

- **로깅 문제가 아님**: 이 그룹의 96.53%는 remove_from_cart 이벤트 자체가
  전혀 없다(add와 매칭 실패가 아니라 애초에 이벤트가 없음). 나머지
  3.47%(remove는 있으나 add와 매칭 안 됨)도 대부분(42.4%가 add 이벤트
  자체 없음) 좌측 검열(관측 시작 이전에 이미 담아둔 상품을 관측 중 제거)로
  설명 가능해 별도 처리가 필요한 데이터 결함은 아니라고 판단했다.
- **시간 부족(우측 검열) 문제도 아님**: 마지막 add부터 관측 종료일까지
  남은 시간이 중앙값 76일이고, 12.1%만 종료 14일 이내다. 87.9%는 지울
  시간이 최소 2주, 대부분 훨씬 더 있었는데도 안 지웠다.

즉 이 79.38%는 "능동적으로 거부한 적 없이 아직 결정을 안 내린" 상태다.
"이탈"(능동적 거부, remove 이벤트로 확인됨)과 "보류"(미결정, remove
이벤트 없음)는 실제 구매 재고 확률과 CRM 대응이 다를 수밖에 없어, 참고용
컬럼만으로는 부족하다고 판단해 세그먼트 자체를 분리하기로 했다.

### 결정

`장바구니_이탈형`을 다음 두 세그먼트로 분리한다(세그먼트 총 개수 8 → 9).

| 세그먼트 | 정의 | 인원 | 비중 | CRM 목적 |
|---|---|---:|---:|---|
| 장바구니_이탈형 | fast_removal + slow_removal(명시적으로 제거함) | 365,487 | 20.62% | 장바구니 이탈 회수(Cart Recovery) — 이미 "거부" 신호가 있어 대안 상품 추천이 동일 상품 리마인더보다 적합 |
| 장바구니_보류형(신설) | no_removal_recorded(제거 이벤트 없이 보류 중) | 1,406,964 | 79.38% | 체크아웃 완결 유도(Checkout Completion) — 거부 신호가 없어 가벼운 리마인더면 충분, 강한 프로모션은 불필요 |

`장바구니_이탈형`을 `장바구니_이탈형`/`장바구니_보류형`으로 분리해
PROJECT_GUIDELINES.md 17번의 세그먼트 후보를 9개로 확정했다.

### 결과

- 세그먼트 9개 전부 인원 합이 22,298,361명과 정확히 일치, `장바구니_이탈형`
  +`장바구니_보류형` 합(1,772,451명)이 lifecycle의 `장바구니_고객`과 정확히
  일치.
- `tests/data_quality/test_segment.py` 10개(신규 5개 포함) 전부 통과 —
  세그먼트 9개 확인, 두 카트 세그먼트 합이 lifecycle과 일치, `cart_removal_subtype`이
  `장바구니_보류형`에서는 항상 `no_removal_recorded`, `장바구니_이탈형`에서는
  항상 `fast_removal`/`slow_removal`인지까지 검증.
- 갱신 파일: `sql/marts/mart_customer_segment.sql`, `PROJECT_GUIDELINES.md`(17번),
  `docs/data_dictionary.md`, `reports/phase4_segment_profile.md`,
  `scripts/build_dashboard_data.py`(SEGMENT_META에 `장바구니_보류형` 추가),
  `app/pages/5_Segment_Explorer.py`("세그먼트 8개" → "9개" 문구),
  `tests/unit/test_dashboard_data.py`, 대시보드 데이터(`data/dashboard/segment_profile.csv`)
  및 스크린샷(`reports/figures/dashboard_segment_explorer.png` 등) 재생성.
- `mart_customer_lifecycle.sql`은 이 변경과 무관 — lifecycle 8개 상태
  분포는 그대로(재확인 완료).

### 관련 문서

- `sql/marts/mart_customer_segment.sql`, `sql/intermediate/int_customer_cart_behavior.sql`
- `reports/phase4_segment_profile.md` (장바구니_이탈형/장바구니_보류형 상세)
- `PROJECT_GUIDELINES.md` 17번 (취소선 + 갱신 이력)

---

## `avg_category_repurchase_rate`를 Model A/B feature로 추가 + Phase 3 리포트 정정("계산 불가" → 실제 계산)

### 배경

Phase 3 퍼널 분석(`reports/phase3_funnel_analysis.md`) 작성 시점에 "구매
고객당 평균 카테고리 수가 1.70개로 다양성이 크지 않아 카테고리별로 쪼개면
표본이 너무 작아질 것"이라는 **추정만 하고 실제로 계산을 시도하지 않은
채** "Phase 4에서 다룬다"고 미뤄뒀다. 그런데 Phase 4에서도 이 계산은
이뤄지지 않았고, 2026-08-08 감사에서 이 누락이 뒤늦게 확인됐다.

이 문제는 같은 날 기록한 `docs/limitations.md` 3번 섹션(category ID가
상품명 임베딩 기준 유사성과 낮은 일치도, NMI 0.1258/ARI 0.0137)과는
**별개의 질문**이다 — 그쪽은 "category 그룹이 상품 유사성을 얼마나
반영하는가"이고, 이번 건은 "category별 재구매율 차이가 애초에 실재하고
유의미한가"다. 두 이슈는 뒤쪽 "남은 한계" 절에서 서로 연결된다.

### 검증 방법

1. 카테고리별 고객 수 분포를 실제로 확인.
2. 최소 표본 기준(카테고리당 고객 100명 이상 — `p≈0.2` 기준 95% 신뢰구간
   오차범위가 약 ±8%p로 통상 허용 가능한 수준이라는 게 근거)을 적용해
   카테고리별 재구매율을 실제로 계산.
3. 카테고리 간 재구매율 차이가 우연인지 이항분포 근사 z-검정으로 확인.

(`reports/adhoc_category_repurchase_rate_n100plus.csv`)

### 결과

전체 6,337개 카테고리 중 다수(중앙값 35명)는 실제로 표본이 작았다 — 원래
우려("표본이 작을 것")의 방향 자체는 맞았다. 하지만 최소 표본 기준을
적용해도 **2,074개 카테고리(32.7%)가 통과했고, 이들이 전체 고객-카테고리
구매관계의 93.6%를 커버**했다. 이 범위 안에서 카테고리 간 재구매율 차이는
결코 작지 않다 — 카테고리 1096(고객 13,366명)은 28.59%, 카테고리
2964(고객 11,081명)는 20.79%로, 전체 평균(7.18%)의 3\~4배에 달했고
(이항분포 근사 z-검정 z=95.9, z=55.5 — 우연이라 보기 어려움).

즉 정확한 진단은 "표본 부족으로 계산 불가"가 아니라 **"최소 표본 필터링
없이 시도조차 하지 않았던 것"**이었다.

### Phase 3 리포트 정정

`reports/phase3_funnel_analysis.md`의 "카테고리별 퍼널 차이" 절에
`[2026-08-08 정정]` 표기로 원래 서술("표본 부족으로 계산 불가"라는
추정)을 교정하고, 위 실제 계산 결과와 근거 파일을 링크했다 — 문구를
삭제하지 않고 정정 이력을 남기는 방식(2026-08-05/08의 다른 정책 갱신과
동일한 관례).

### 모델 feature 반영 (구현)

카테고리 간 재구매율 차이를 고객 단위 feature "이 고객이 구매한
카테고리들의 평균 재구매율"(`avg_category_repurchase_rate`)로 Model
A(churn)·Model B(propensity) 양쪽에 추가했다.

- **새 intermediate 테이블 체인**을 신설했다:
  `int_customer_category_repurchase_by_snapshot`(카테고리 × snapshot_date
  단위 재구매율 — snapshot_date 이전 구매 occasion만 사용해 미래 정보
  누수를 방지하고, 표본 100명 미만 카테고리는 제외) →
  `int_customer_category_repurchase_avg_by_snapshot`(고객 × snapshot_date
  단위로, 고객이 구매한 카테고리들의 재구매율을 LEFT JOIN 후 평균 — 표본
  부족으로 제외된 카테고리는 자동으로 NULL 처리되고 `AVG`가 이를
  무시하므로 나머지 카테고리로만 평균이 계산된다).
- 원래는 각 mart 파일 내부에 인라인 CTE로 계산하려 했으나,
  `mart_purchase_propensity.sql`의 기존 무거운 조인(46.9M행
  `int_customer_daily_activity` 기반)과 한 쿼리 플랜에서 합쳐지며 8GB
  메모리 환경에서 OOM이 발생해 별도 테이블로 분리했다 — 계산을 한 번만
  하고 `mart_customer_snapshot`(Model A)·`mart_purchase_propensity`(Model
  B) 양쪽이 가벼운 LEFT JOIN으로 재사용하는 구조가 됐다(이 OOM 경험은
  이후 `mart_purchase_propensity` search_first 통일 작업에서 동일한 TEMP
  테이블 분리 패턴을 처음부터 적용하는 선례가 됐다 — 아래 항목 참고).
- **셀프 포함 편향**: 카테고리 통계에 그 고객 자신의 과거 구매 occasion도
  포함되지만, 최소 표본이 100명이므로 한 고객의 기여는 통계치를 최대
  1%p만 흔드는 수준으로 판단해 leave-one-out까지는 적용하지 않았다(합리적
  기본값 처리, `docs/decisions_pending_review.md`).

### Feature importance 결과 — 같은 feature가 모델마다 다르게 기여

| 모델 | feature 개수 | avg_category_repurchase_rate 순위 | 비고 |
|---|---:|---|---|
| Model A (churn) | 13개 | 9위(중간 기여, 최상위 대비 4.9%) | 과거 구매 이력이 있는 고객만 모집단이라 feature 값이 대부분 채워짐 |
| Model B (propensity) | 8개 | 8위(꼴찌, 최상위 `has_purchase_history` 대비 1.7%) | 모집단(활동 고객 전반) 중 구매 이력 없는 고객이 다수라 feature 자체가 NULL인 비중이 높고, 이미 `has_purchase_history` 등 훨씬 강한 신호가 존재 |

동일한 feature 정의가 모집단 구성(과거 구매자만 vs 활동 고객 전반)에 따라
얼마나 다르게 기여하는지 실측으로 확인된 사례다.

### 남은 한계 (`docs/limitations.md` 3번 섹션과의 연결)

이 feature는 "같은 category에 속한 상품은 재구매 패턴이 비슷하다"는
전제 위에 있다. 그런데 같은 날 별도로 검증한 category ID 신뢰도 결과
(NMI 0.1258, ARI 0.0137 — category ID가 상품명 임베딩 기준 유사성과
거의 무관)에 따르면, category가 명목상 그룹일 뿐 실제 상품 유사성과
약하게만 연결될 수 있다. 즉 이 feature가 포착하는 신호는 "상품
유사성에 따른 재구매 성향"이 아니라 "그 category ID 자체(운영/분류상
특성)에 따른 재구매 성향"에 가까울 수 있다 — feature importance 상
기여는 이번 z-검정으로 확인됐지만, 그 기여의 인과적 해석("비슷한 상품을
사는 고객은 재구매를 잘한다")은 이 검증만으로는 뒷받침되지 않는다.

### 관련 문서

- `reports/phase3_funnel_analysis.md` (Phase 3 정정 원문)
- `reports/adhoc_category_repurchase_rate_n100plus.csv` (z-검정 원자료)
- `docs/hypotheses.md` 6번 (가설 형식 요약), 5번 (category ID 신뢰도 검증)
- `docs/limitations.md` 3번 섹션 (category ID 신뢰도, 인과 해석 caveat)
- `sql/intermediate/int_customer_category_repurchase_by_snapshot.sql`,
  `..._avg_by_snapshot.sql`
- `reports/model_cards/model_a_churn.md`, `reports/model_cards/model_b_propensity.md`

---

## `mart_purchase_propensity` 모집단 조건을 search_first로 통일

### 배경

`mart_customer_segment.sql`의 `구매_직전_탐색형` 분류 기준은 이미 "검색
1회 이상"에서 search_first(검색이 방문보다 먼저)로 교체됐는데(위
"`구매_직전_탐색형` 세분화 기준 재조정" 항목 참고 — search_only 7.75%
vs search_first 44.02% 전환율 차이가 근거), `mart_purchase_propensity.sql`의
Model B 모집단 조건은 이 교체를
반영받지 못한 채 여전히 "검색 1회 이상"(`n_search_query >= 1` /
`cum_search >= 1`)을 쓰고 있었다. 두 mart가 JOIN으로 연결된 게 아니라
같은 판단 로직을 각자 독립적으로 구현했기 때문에 한쪽만 갱신되고 다른
쪽은 갱신되지 않은 채 남은 것 — Phase 4에서 이미 폐기한 저의도 신호가
Phase 6 모델링 모집단에는 계속 섞여 있었던 셈이다.

### 결정

`candidate_ids`(전체 관측기간 상한 후보)와 `population`(snapshot_date별
실제 모집단) 두 곳의 "검색 1회 이상" 조건을 모두 search_first로 교체한다.
`population` 쪽은 미래 누수 방지를 위해 "첫 검색·첫 방문이 모두
snapshot_date 이전에 이미 관측됐고, 첫 검색이 첫 방문보다 이르다"는
조건으로 구현했다(`candidate_ids`는 느슨한 상한 후보 필터일 뿐이라
전체 기간 기준 search_first를 써도 안전 — 이후 `population`에서
snapshot_date 기준으로 다시 걸러짐).

구현상 이 계산(첫 검색/첫 방문 시각)은 `stg_search_query`/`stg_page_visit`
원본을 다시 스캔해야 하는데, 기존 `activity_before`(46.9M행
`int_customer_daily_activity` 기반)의 무거운 조인과 한 쿼리 플랜에
합치면 다시 OOM이 날 수 있어(위 `avg_category_repurchase_rate` 추가 때
이미 겪은 문제), `tmp_candidate_ids`라는 별도 TEMP 테이블로
먼저 고정한 뒤 가볍게 JOIN하는 방식을 처음부터 적용했다.

### 결과

**모집단 크기**: 22,277,058행 → 21,119,640행 (-1,157,418행, -5.20%),
고유 고객 수 4,125,793명 → 3,916,042명 (-5.08%).

**라벨 비율(더 좁지만 더 진짜 활동 고객으로 집중)**:

| 라벨 | 변경 전 | 변경 후 |
|---|---:|---:|
| will_purchase_14d | 1.44% | 1.51% |
| will_purchase_28d | 2.56% | 2.67% |

저의도 search-only 고객이 빠지면서 양성 라벨 비율이 소폭 상승했다 —
Phase 4에서 확인한 방향(저의도 트래픽 제거 시 전환 관련 지표가 개선)과
일치한다.

**재학습 결과(LightGBM, test set)**:

| 라벨 | AUC 변경 전 | AUC 변경 후 | Lift@10% 변경 전 | Lift@10% 변경 후 |
|---|---:|---:|---:|---:|
| will_purchase_14d | 0.8670 | 0.8654 (-0.0016) | 6.31 | 6.23 |
| will_purchase_28d | 0.8598 | 0.8582 (-0.0016) | 6.03 | 5.95 |

AUC/Lift가 아주 미세하게(둘 다 -0.0016) 낮아졌다 — 저의도 고객을 제외해
"쉽게 구분되는 진짜 비활동 고객"이 모집단에서 줄어든 영향으로 추정된다.
방향과 크기 모두 우려할 수준이 아니며, 모집단을 실제 정의("활동 고객")에
더 가깝게 정정했다는 게 핵심 근거이지 AUC 최적화가 목적이 아니었다.

**Feature importance**: 순위는 변하지 않았다(1위 `has_purchase_history`
\~ 8위(꼴찌) `avg_category_repurchase_rate` 그대로). `n_search_query_28d`의
상대 중요도가 24.4% → 27.0%(최상위 feature 대비)로 소폭 상승했는데,
남은 모집단의 검색 신호가 이전보다 더 순도 높은(저의도가 섞이지 않은)
신호가 됐기 때문으로 해석된다.

### 관련 문서

- `sql/marts/mart_purchase_propensity.sql`
- `docs/methodology.md` "`구매_직전_탐색형` 세분화 기준 재조정" 항목 (search_first 원 출처)
- `reports/phase6_model_b_results.csv`, `reports/phase6_model_b_feature_importance.csv`

## Segment Explorer "오늘의 액션 리스트" 2차 정렬 기준: 인원수 → 과접촉 위험

### 배경

Segment Explorer 페이지에 접촉 우선순위(`priority`) 순 액션 리스트를 추가했다.
`priority`는 5단계뿐이라 동일 등급(예: "높음") 안에 세그먼트 6개가 묶이는데,
최초 구현은 이 동률을 인원수(n) 내림차순으로 풀었다 — 근거 없는 UI 구현
선택이었다(`reports/phase4_segment_profile.md`는 동일 등급 내 순서를 규정하지
않음).

### 결정

2차 정렬 기준을 인원수 내림차순에서 `over_contact_risk` 오름차순(안전한
순서: 매우 낮음 → 낮음 → 낮음\~중간 → 중간 → 높음 → 매우 높음)으로 변경했다.
CRM 담당자가 리스트 상단부터 순서대로 접촉을 검토한다고 가정하면, 동일
우선순위 안에서는 "인원이 많은 대상"보다 "접촉했을 때 부작용(수신거부·이탈
가속) 위험이 낮은 대상"부터 보여주는 편이 실무적으로 더 안전한 기본값이다.

### 유의사항

`priority`·`over_contact_risk` 모두 실측 접촉 이력이 아니라 Phase 4 설계
시점의 정성적 판단이므로(위 `장바구니_이탈형`/`장바구니_보류형` 분리 항목,
`reports/phase4_segment_profile.md` 참고), 이 2차 정렬도 "검증된 최적
순서"가 아니라 두 정성적 판단을 조합한 표시 순서일 뿐이다.

### 관련 코드

- `app/pages/5_Segment_Explorer.py`의 `OVER_CONTACT_RANK` 딕셔너리, 정렬 로직

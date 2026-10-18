# Phase 5 - 고객 스냅샷 구축 (mart_customer_snapshot)

## 설계 요약

| 항목 | 값 | 근거 |
|---|---|---|
| Grain | client_id × snapshot_date | PROJECT_GUIDELINES.md 12번 예시 |
| Feature Window | snapshot_date 이전 28일 | PROJECT_GUIDELINES.md 12번 예시값 채택 |
| Label Window | 이후 14일 **및** 28일 (둘 다) | PROJECT_GUIDELINES.md 18번 "14일과 28일을 비교 대상으로 명시" — 하나를 임의로 고르지 않음 |
| snapshot_date 하한 | 2022-07-21 (관측시작 +28일) | feature window 전체 확보 |
| snapshot_date 상한 | 2022-11-10 (관측종료 −28일) | 두 라벨 중 더 엄격한 28일 기준으로 우측 검열 원천 차단 (`docs/methodology.md`) |
| snapshot_date 간격 | 14일 (9개 스냅샷) | 라벨 윈도우 길이와 맞춰 인접 스냅샷 라벨 기간 중복 최소화 |
| 모집단 | snapshot_date 이전 구매 이력 있는 고객 | PROJECT_GUIDELINES.md 18번 Model A 정의 |
| 결과 행 수 | 4,196,385 | — |

## 검증 결과

**우측 검열 원천 차단이 실제로 작동했는지 스냅샷별 라벨 비율로 확인**

| snapshot_date | 모집단 | 14일 라벨(구매) 비율 | 28일 라벨(구매) 비율 |
|---|---:|---:|---:|
| 2022-07-21 | 174,978 | 6.92% | 11.28% |
| 2022-08-04 | 253,638 | 5.84% | 10.30% |
| 2022-08-18 | 320,148 | 5.87% | 10.09% |
| 2022-09-01 | 397,836 | 5.53% | 9.44% |
| 2022-09-15 | 472,098 | 5.22% | 9.18% |
| 2022-09-29 | 542,550 | 5.35% | 9.23% |
| 2022-10-13 | 611,293 | 5.26% | 9.02% |
| 2022-10-27 | 678,864 | 5.03% | 9.44% |
| 2022-11-10 | 744,980 | 5.67% | 10.23% |

**핵심 확인**: 마지막 스냅샷(2022-11-10)에서도 라벨 비율이 급락하지 않고
다른 스냅샷과 비슷한 범위(5\~7%, 9\~11%)를 유지한다. 이는 우측 검열
원천 차단 설계(`docs/methodology.md`의 "프로젝트 주제 확정(A안) 및 우측
검열(right-censoring) 고객 처리 방침" 결정)가 실제로 의도대로
작동했음을 보여준다 — 만약 검열을 막지 못했다면 마지막 스냅샷일수록
라벨 비율이 인위적으로 낮게 나왔을 것이다(`mart_customer_retention`에서
검열을 반영하기 전 실제로 관찰됐던 패턴, `docs/decisions_pending_review.md`
2026-08-05 "코호트별 재구매율의 우측 검열 처리" 항목 참고).

## 안전장치 구현

PROJECT_GUIDELINES.md 31번 "Snapshot Feature·Label 분리" 테스트 항목을 다음 두 곳에
구현했다 (`docs/methodology.md`에서 약속한 대로).

- `tests/data_quality/test_snapshot.py::test_no_label_window_censoring`
- `sql/tests/test_snapshot_no_label_censoring.sql`

두 테스트 모두 "모든 snapshot_date + 28일이 실제 관측 종료일을 넘지 않는가"를
검증하며, 현재 위반 0건으로 통과한다.

## 다음 단계로 넘길 것

- `mart_churn_target`: `label_inactive_14d`/`label_inactive_28d`를 그대로 타겟으로 사용
- `mart_purchase_propensity`: `label_purchase_14d`/`label_purchase_28d`를 그대로 타겟으로 사용
- Feature는 이 마트의 컬럼을 기본으로 하되, Phase 6에서 "최근 행동 감소율"
  등 추가 파생 feature가 필요하면 `sql/features/`에서 이 마트를 확장한다.

## 생성 파일

- `reports/phase5_snapshot_construction.md` (본 문서)
- `sql/marts/mart_customer_snapshot.sql`
- `sql/tests/test_snapshot_no_label_censoring.sql`
- `tests/data_quality/test_snapshot.py`

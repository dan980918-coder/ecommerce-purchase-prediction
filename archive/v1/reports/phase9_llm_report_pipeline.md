# Phase 9 - LLM CRM 리포트 파이프라인

## 파이프라인 구조 (PROJECT_GUIDELINES.md 27번)

```
data/dashboard/*.csv (DuckDB SQL 결과, Phase 8에서 이미 Python이 계산·검증)
  -> src/llm/data_loader.py  (Pydantic 입력으로 구성)
  -> src/llm/schemas.py      (CRMReportInput — 값 검증: 음수/NaN/범위 밖 거부)
  -> src/llm/client.py       (백엔드 선택: Anthropic > OpenAI > mock)
  -> src/llm/prompts.py      (금지 표현 목록 + 4영역 출력 지시 프롬프트)
  -> src/llm/report_generator.py (LLM 출력 검사 후 CRMReportOutput 조립)
  -> scripts/generate_crm_report.py (CLI) / app/pages/7_AI_CRM_Report.py (대시보드)
```

## 결정 1 — API 키 없이 mock 백엔드로 파이프라인만 구축 (사용자 승인)

이 세션에는 `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`가 설정되어 있지 않았다.
두 가지 선택지를 제시했고, 사용자가 **"API 키 없이 파이프라인만 구축"** 을
선택했다:
- Pydantic 스키마, 프롬프트 템플릿, DuckDB→검증 로직, 품질 테스트를 전부
  구현하되 실제 API 호출부는 함수로 분리해두고, 지금은 mock 응답으로 시연/테스트.
- 사용자가 나중에 `.env`에 API 키를 넣으면 `src/llm/client.py`의
  `get_available_backend()`가 자동으로 실제 호출로 전환한다(코드 변경 불필요).

## 결정 2 — LLM의 역할을 "액션 제안 + 가설 생성"으로만 제한

PROJECT_GUIDELINES.md 27번("LLM은 숫자를 계산하지 않는다")을 구조적으로 강제하기 위해,
`CRMReportOutput.data_facts`와 `model_predictions`는 LLM이 생성하지 않고
입력을 그대로 통과(passthrough)시킨다. LLM은 `recommended_actions`와
`testable_hypotheses` 두 필드만 채운다 — 이렇게 하면 "입력 숫자와 출력
숫자 불일치"라는 오류 자체가 설계상 발생할 수 없다.

## 결정 3 — 금지 표현을 사후 검사가 아니라 예외로 강제

`src/llm/prompts.py`의 `FORBIDDEN_PHRASES` 목록(매출 개선/이탈률 개선/전환율
향상/캠페인 효과 검증 등, PROJECT_GUIDELINES.md 29번 근거)에 해당하는 문구가 LLM
출력에 있으면 `report_generator.py`가 `ForbiddenClaimError`를 던져 **리포트
자체를 반환하지 않는다** — 경고만 로그로 남기고 그대로 내보내는 방식보다
안전하다고 판단했다(PROJECT_GUIDELINES.md 15번 "오류를 숨기거나 임의로 값을 대체하지
않는다"와 같은 맥락 — 여기서는 "위반을 숨기지 않고 실패시킨다"로 적용).

## 품질 테스트 (PROJECT_GUIDELINES.md 30번, `tests/unit/test_llm_report.py`, 24개 전부 mock 백엔드로 API 키 없이 실행 가능)

| PROJECT_GUIDELINES.md 30번 요구 항목 | 테스트 |
|---|---|
| 입력 숫자와 출력 숫자 일치 | `test_input_output_number_consistency` (passthrough 설계로 구조적 보장) |
| 기간 정보 누락 여부 | `test_period_info_present` |
| 사실과 제안 구분 | `test_facts_and_suggestions_are_separate_fields` |
| 금지된 성과 표현 | `test_forbidden_phrase_detection`(파라미터화 10건), `test_generate_crm_report_rejects_forbidden_output` |
| 동일 입력에 대한 일관성 | `test_consistent_output_for_same_input` (mock은 결정론적) |
| 빈 데이터 처리 | `test_empty_data_does_not_crash_and_does_not_fabricate` |
| 비정상 수치 처리 | `test_negative_data_fact_value_rejected`, `test_nan_data_fact_value_rejected`, `test_out_of_range_recall_rejected`, `test_period_end_before_start_rejected` |
| 모델 결과가 없는 경우의 처리 | `test_no_model_predictions_yields_no_model_hypotheses` |

## 실제 API 연결 시 확인할 점 (사용자가 나중에 키를 넣을 때)

- `.env`에 `ANTHROPIC_API_KEY` 또는 `OPENAI_API_KEY` 추가 (`.env.example` 참고)
- `test_consistent_output_for_same_input`은 mock 전제이므로, 실제 LLM은
  temperature 등에 따라 완전한 결정론이 보장되지 않을 수 있음 — 실사용 시
  별도로 재현성 허용 오차를 재검토할 것
- 실제 LLM 출력도 여전히 `ForbiddenClaimError` 검사를 통과해야 리포트로
  노출됨(코드 변경 없이 동일하게 적용)

## 생성 파일

- `src/llm/schemas.py`, `prompts.py`, `client.py`, `report_generator.py`, `data_loader.py`
- `scripts/generate_crm_report.py`
- `app/pages/7_AI_CRM_Report.py` (Phase 8 자리표시자를 실제 파이프라인으로 교체)
- `tests/unit/test_llm_report.py`
- `.env.example`
- `reports/phase9_ai_crm_report_sample.md`, `.json` (mock 백엔드로 생성한 샘플 출력)
- `reports/phase9_llm_report_pipeline.md` (본 문서)

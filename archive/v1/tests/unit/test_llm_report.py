"""Phase 9 LLM CRM 리포트 품질 테스트 (PROJECT_GUIDELINES.md 30번).

mock 백엔드로 실행 — API 키 없이도 CI에서 항상 재현 가능해야 하므로, 파이프라인
로직(스키마 검증/사실 통과/금지어 검사/일관성)을 우선 검증한다. 실제 LLM
출력 품질은 API 키가 있을 때 별도로 수동 확인한다(이 테스트 범위 밖).
"""

import sys
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.llm.prompts import FORBIDDEN_PHRASES, contains_forbidden_claim
from src.llm.report_generator import ForbiddenClaimError, generate_crm_report
from src.llm.schemas import CRMReportInput, DataFact, ModelPredictionFact, SegmentFact


@pytest.fixture(autouse=True)
def _force_mock_backend(monkeypatch):
    """client.py가 로컬 .env를 자동 로드하므로(load_dotenv), 개발자 머신에 실제
    API 키가 있어도 이 테스트는 항상 mock 백엔드로 실행되도록 강제한다 — 위
    모듈 docstring이 약속하는 "API 키 없이도 재현 가능"을 보장한다."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def make_input(**overrides) -> CRMReportInput:
    defaults = dict(
        period_start=date(2022, 6, 23),
        period_end=date(2022, 12, 8),
        data_facts=[DataFact(label="구매 고객", value=909210, unit="명")],
        segment_facts=[
            SegmentFact(segment="장바구니_이탈형", n_customers=1772451, buy_rate=0.0,
                        crm_purpose="장바구니 이탈 회수", priority="매우 높음")
        ],
        model_predictions=[
            ModelPredictionFact(model_name="Model_B_propensity", label="will_purchase_14d",
                                 contact_rate_pct=10, recall=0.63, lift=6.30, precision=0.083)
        ],
    )
    defaults.update(overrides)
    return CRMReportInput(**defaults)


# 1. 입력 숫자와 출력 숫자 일치 (data_facts/model_predictions는 passthrough)
def test_input_output_number_consistency():
    report_input = make_input()
    output = generate_crm_report(report_input)
    assert output.data_facts == report_input.data_facts
    assert output.model_predictions == report_input.model_predictions


# 2. 기간 정보 누락 여부
def test_period_info_present():
    report_input = make_input()
    output = generate_crm_report(report_input)
    assert output.period_start == date(2022, 6, 23)
    assert output.period_end == date(2022, 12, 8)


# 3. 사실과 제안 구분 (구조적으로 별도 필드 — 타입 검증)
def test_facts_and_suggestions_are_separate_fields():
    report_input = make_input()
    output = generate_crm_report(report_input)
    assert isinstance(output.data_facts, list) and all(isinstance(f, DataFact) for f in output.data_facts)
    assert isinstance(output.recommended_actions, list) and all(isinstance(a, str) for a in output.recommended_actions)
    assert isinstance(output.testable_hypotheses, list) and all(isinstance(h, str) for h in output.testable_hypotheses)


# 4. 금지된 성과 표현
@pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
def test_forbidden_phrase_detection(phrase):
    assert contains_forbidden_claim(f"이번 캠페인으로 {phrase}했습니다.") == phrase


def test_clean_text_has_no_forbidden_claim():
    assert contains_forbidden_claim("상위 10% 고객에게 리마인더를 보내는 방안을 검토할 수 있습니다.") is None


def test_generate_crm_report_rejects_forbidden_output(monkeypatch):
    def fake_call_llm(report_input):
        return {"recommended_actions": ["이 캠페인으로 매출을 증가시켰습니다."], "testable_hypotheses": []}, "mock"

    monkeypatch.setattr("src.llm.report_generator.call_llm", fake_call_llm)
    with pytest.raises(ForbiddenClaimError):
        generate_crm_report(make_input())


# 5. 동일 입력에 대한 일관성 (mock 백엔드는 결정론적이어야 함)
def test_consistent_output_for_same_input():
    report_input = make_input()
    output1 = generate_crm_report(report_input)
    output2 = generate_crm_report(report_input)
    assert output1.recommended_actions == output2.recommended_actions
    assert output1.testable_hypotheses == output2.testable_hypotheses


# 6. 빈 데이터 처리
def test_empty_data_does_not_crash_and_does_not_fabricate():
    report_input = make_input(data_facts=[], segment_facts=[], model_predictions=[])
    output = generate_crm_report(report_input)
    assert output.data_facts == []
    assert output.model_predictions == []
    assert len(output.recommended_actions) >= 1
    assert "없어" in output.recommended_actions[0] or "없음" in output.recommended_actions[0]


# 7. 비정상 수치 처리 (Pydantic이 즉시 거부해야 함 — 조용히 통과시키지 않음)
def test_negative_data_fact_value_rejected():
    with pytest.raises(ValidationError):
        DataFact(label="구매 고객", value=-5, unit="명")


def test_nan_data_fact_value_rejected():
    with pytest.raises(ValidationError):
        DataFact(label="구매 고객", value=float("nan"), unit="명")


def test_out_of_range_recall_rejected():
    with pytest.raises(ValidationError):
        ModelPredictionFact(model_name="A", label="x", contact_rate_pct=10, recall=1.5, lift=1.0, precision=0.5)


def test_period_end_before_start_rejected():
    with pytest.raises(ValidationError):
        CRMReportInput(period_start=date(2022, 12, 8), period_end=date(2022, 6, 23))


# 8. 모델 결과가 없는 경우의 처리
def test_no_model_predictions_yields_no_model_hypotheses():
    report_input = make_input(model_predictions=[])
    output = generate_crm_report(report_input)
    assert output.model_predictions == []
    assert not any("모델" in h and "타겟팅" in h for h in output.testable_hypotheses)
    # 세그먼트 기반 제안/가설은 여전히 생성되어야 함(모델 부재가 전체 실패로 이어지면 안 됨)
    assert len(output.recommended_actions) >= 1

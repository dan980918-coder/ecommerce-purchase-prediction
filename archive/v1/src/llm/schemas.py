"""Phase 9 - LLM CRM 리포트 Pydantic 스키마.

PROJECT_GUIDELINES.md 27번 파이프라인(DuckDB SQL -> Python 검증 -> Pydantic JSON -> LLM ->
CRM 리포트)에서 "Pydantic JSON" 단계에 해당한다. data_facts/model_predictions는
Python이 DuckDB에서 미리 계산·검증한 값을 그대로 담으며, LLM은 이 값을
다시 계산하거나 새 숫자를 만들지 않는다 — LLM의 역할은 recommended_actions/
testable_hypotheses 두 필드를 채우는 것으로 제한된다.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator


class DataFact(BaseModel):
    """SQL에서 확인된 사실 1건."""

    label: str
    value: float
    unit: str = ""

    @field_validator("value")
    @classmethod
    def value_must_be_finite_and_non_negative(cls, v: float) -> float:
        if v != v:  # NaN
            raise ValueError("DataFact.value는 NaN일 수 없음 — 결측 처리 후 전달할 것")
        if v < 0:
            raise ValueError(f"DataFact.value는 음수일 수 없음: {v}")
        return v


class SegmentFact(BaseModel):
    segment: str
    n_customers: int = Field(ge=0)
    buy_rate: float = Field(ge=0, le=1)
    crm_purpose: str
    priority: str


class ModelPredictionFact(BaseModel):
    model_name: str
    label: str
    contact_rate_pct: int = Field(ge=1, le=100)
    recall: float = Field(ge=0, le=1)
    lift: float = Field(ge=0)
    precision: float = Field(ge=0, le=1)


class CRMReportInput(BaseModel):
    period_start: date
    period_end: date
    data_facts: list[DataFact] = Field(default_factory=list)
    segment_facts: list[SegmentFact] = Field(default_factory=list)
    model_predictions: list[ModelPredictionFact] = Field(default_factory=list)

    @field_validator("period_end")
    @classmethod
    def end_after_start(cls, v: date, info) -> date:
        start = info.data.get("period_start")
        if start and v < start:
            raise ValueError("period_end가 period_start보다 이릅니다")
        return v


class CRMReportOutput(BaseModel):
    """4영역 구분 리포트 (PROJECT_GUIDELINES.md 28번).

    data_facts/model_predictions는 입력을 그대로 통과시킨다(passthrough) —
    LLM이 재생성하지 않으므로 입력-출력 숫자 불일치가 구조적으로 발생하지 않는다.
    """

    period_start: date
    period_end: date
    data_facts: list[DataFact]
    model_predictions: list[ModelPredictionFact]
    recommended_actions: list[str]
    testable_hypotheses: list[str]
    generated_by: str  # "mock" 또는 실제 사용된 모델 식별자

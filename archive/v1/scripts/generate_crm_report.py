"""Phase 9 - LLM CRM 리포트 생성 CLI (PROJECT_GUIDELINES.md 27~28번).

data/dashboard/의 사전 검증된 집계 파일(Python이 DuckDB에서 이미 계산·검증한
값)을 읽어 Pydantic 입력으로 구성하고, LLM(또는 API 키가 없으면 mock)을 호출해
4영역(Data Facts / Model Predictions / Recommended Actions / Testable
Hypotheses) 리포트를 생성한다.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.llm.data_loader import build_report_input
from src.llm.report_generator import escape_tildes, generate_crm_report

REPORT_DIR = Path("reports")


def render_markdown(output) -> str:
    lines = [
        "# AI CRM Report",
        "",
        f"기간: {output.period_start} ~ {output.period_end}",
        f"생성 방식: {output.generated_by}"
        + ("  (⚠️ mock — 실제 LLM 아님, .env에 API 키 추가 시 실제 호출로 전환)" if output.generated_by == "mock" else ""),
        "",
        "## 1. Data Facts",
    ]
    for f in output.data_facts:
        lines.append(f"- {f.label}: {f.value:,.0f}{f.unit}")

    lines.append("\n## 2. Model Predictions")
    for m in output.model_predictions:
        lines.append(
            f"- {m.model_name} ({m.label}), 상위 {m.contact_rate_pct}%: "
            f"Recall {m.recall*100:.1f}%, Lift {m.lift:.2f}배, Precision {m.precision*100:.1f}%"
        )

    lines.append("\n## 3. Recommended Actions")
    for a in output.recommended_actions:
        lines.append(f"- {escape_tildes(a)}")

    lines.append("\n## 4. Testable Hypotheses")
    for h in output.testable_hypotheses:
        lines.append(f"- {escape_tildes(h)}")

    return "\n".join(lines)


def main() -> None:
    report_input = build_report_input()
    output = generate_crm_report(report_input)

    REPORT_DIR.mkdir(exist_ok=True)
    with open(REPORT_DIR / "phase9_ai_crm_report_sample.json", "w", encoding="utf-8") as f:
        json.dump(output.model_dump(mode="json"), f, ensure_ascii=False, indent=2)

    md = render_markdown(output)
    with open(REPORT_DIR / "phase9_ai_crm_report_sample.md", "w", encoding="utf-8") as f:
        f.write(md)

    print(md)
    print(f"\nSaved: reports/phase9_ai_crm_report_sample.json, reports/phase9_ai_crm_report_sample.md")


if __name__ == "__main__":
    main()

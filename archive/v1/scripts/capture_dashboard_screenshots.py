"""Streamlit 대시보드를 헤드리스로 띄워 주요 페이지 스크린샷을 저장한다.

전제: streamlit이 별도 프로세스로 http://localhost:8501 에서 실행 중이어야 함.
"""

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8501"
OUT_DIR = Path("reports/figures")
OUT_DIR.mkdir(parents=True, exist_ok=True)

PAGES = [
    ("", "dashboard_home.png"),
    ("/Overview", "dashboard_overview.png"),
    ("/Funnel", "dashboard_funnel.png"),
    ("/Cohort_Retention", "dashboard_cohort_retention.png"),
    ("/Lifecycle", "dashboard_lifecycle.png"),
    ("/Segment_Explorer", "dashboard_segment_explorer.png"),
    ("/Targeting_Simulator", "dashboard_targeting_simulator.png"),
    ("/AI_CRM_Report", "dashboard_ai_crm_report.png"),
]


def main():
    # Streamlit의 메인 콘텐츠는 section[data-testid="stMain"] 내부 스크롤 컨테이너에
    # 렌더링되며, Playwright의 full_page=True는 이 내부 스크롤 높이를 인식하지 못하고
    # 뷰포트 높이(1000px)에서 잘라버린다. 실제 콘텐츠 높이를 측정해 뷰포트를 그만큼
    # 늘린 뒤 일반 스크린샷을 찍어야 전체 내용이 잘리지 않는다.
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for path, filename in PAGES:
            # 페이지마다 새 탭을 써서 이전 페이지의 리사이즈된 뷰포트가 다음 측정에
            # 섞여 들어가는(carry-over) 문제를 원천 차단한다.
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            url = BASE_URL + path
            print(f"방문: {url}")
            page.goto(url, wait_until="networkidle", timeout=30000)
            time.sleep(2.5)  # streamlit 렌더링/차트 로딩 대기
            height = page.evaluate(
                'document.querySelector("section.stMain")?.scrollHeight || 900'
            )
            page.set_viewport_size({"width": 1400, "height": min(height + 60, 8000)})
            time.sleep(0.4)
            page.screenshot(path=str(OUT_DIR / filename), full_page=False)
            print(f"저장: {OUT_DIR / filename} (height={height})")
            page.close()
        browser.close()


if __name__ == "__main__":
    main()

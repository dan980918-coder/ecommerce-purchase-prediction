"""Phase 8 - Streamlit 대시보드용 집계 데이터를 data/dashboard/에 내보낸다.

PROJECT_GUIDELINES.md 원칙: 대시보드는 3GB+ DuckDB(특히 page_visit 1.99억 행)를 라이브로
쿼리하지 않고, 여기서 미리 집계한 작은 파일만 읽는다.
"""

from pathlib import Path

import duckdb
import pandas as pd
import yaml

CONFIG_PATH = Path("config/paths.yaml")
OUT_DIR = Path("data/dashboard")

# Phase 4 세그먼트 프로필의 정성적 정보(reports/phase4_segment_profile.md)를
# 그대로 반영 — SQL로 계산할 수 없는 CRM 목적/액션 텍스트이므로 여기 고정.
SEGMENT_META = {
    "저관여_탐색형": {
        "crm_purpose": "전환 유도(효율 낮음)",
        "recommended_action": "일반 브랜드 노출/리타게팅 광고",
        "priority": "최하위",
        "over_contact_risk": "매우 높음",
    },
    "구매_직전_탐색형": {
        "crm_purpose": "구매 유도(Conversion)",
        "recommended_action": "관심 카테고리 리마인더, 프로모션 노출",
        "priority": "높음",
        "over_contact_risk": "중간",
    },
    "장바구니_이탈형": {
        "crm_purpose": "장바구니 이탈 회수(Cart Recovery)",
        "recommended_action": "대안 상품 추천(이미 명시적으로 제거한 상품이라 동일 상품 리마인더보다 적합), 강도 높은 프로모션",
        "priority": "매우 높음",
        "over_contact_risk": "낮음~중간",
    },
    "장바구니_보류형": {
        "crm_purpose": "체크아웃 완결 유도(Checkout Completion)",
        "recommended_action": "가벼운 장바구니 리마인더, 재고 임박 알림 — 아직 거부 신호 없어 강한 프로모션은 불필요",
        "priority": "높음",
        "over_contact_risk": "낮음",
    },
    "첫_관측_구매_고관여형": {
        "crm_purpose": "2차 구매 유도(Second Purchase Activation)",
        "recommended_action": "온보딩 시퀀스, 관련 상품 추천, 2차 구매 할인",
        "priority": "높음",
        "over_contact_risk": "낮음",
    },
    "안정적_반복구매형": {
        "crm_purpose": "유지·보상(Retention & Loyalty)",
        "recommended_action": "VIP/로열티 프로그램, 우선 구매권",
        "priority": "높음(유지 목적)",
        "over_contact_risk": "매우 낮음",
    },
    "반복구매_감소형": {
        "crm_purpose": "조기 재활성화(Early Re-engagement)",
        "recommended_action": "가벼운 리마인더, 신상품 알림",
        "priority": "높음",
        "over_contact_risk": "낮음",
    },
    "구매_비활성형": {
        "crm_purpose": "재활성화(Win-back)",
        "recommended_action": "강도 높은 프로모션, 설문 기반 이탈 사유 파악",
        "priority": "중간",
        "over_contact_risk": "중간",
    },
    "복귀형": {
        "crm_purpose": "복귀 고착화(Retention of Win-back)",
        "recommended_action": "복귀 환영 메시지, 재이탈 방지 안내",
        "priority": "높음",
        "over_contact_risk": "낮음~중간",
    },
}


def main() -> None:
    with open(CONFIG_PATH) as f:
        paths = yaml.safe_load(f)
    con = duckdb.connect(str(paths["database_path"]), read_only=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1) Overview KPI
    kpi = con.sql(
        """
        SELECT
            (SELECT COUNT(*) FROM mart_customer_360) AS total_customers,
            (SELECT COUNT(*) FROM mart_customer_360 WHERE is_buyer) AS buyers,
            (SELECT COUNT(*) FROM mart_customer_360 WHERE is_repeat_capable) AS repeat_buyers,
            (SELECT COUNT(*) FROM mart_customer_360 WHERE has_cart_activity) AS cart_customers,
            (SELECT COUNT(*) FROM mart_customer_lifecycle WHERE lifecycle_stage = '구매_비활성_위험_고객') AS at_risk_customers,
            (SELECT COUNT(*) FROM mart_customer_lifecycle WHERE lifecycle_stage = '비활성_고객') AS inactive_customers,
            (SELECT COUNT(*) FROM mart_purchase_propensity WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM mart_purchase_propensity) AND will_purchase_14d = 1) AS recent_converters
        """
    ).df()
    kpi_long = kpi.T.reset_index()
    kpi_long.columns = ["metric", "value"]
    kpi_long.to_csv(OUT_DIR / "overview_kpis.csv", index=False)
    print("Saved overview_kpis.csv")

    # 2) Funnel summary (customer-level, Phase 3 정의 재사용)
    funnel = con.sql(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN n_page_visit > 0 OR n_search_query > 0 THEN 1 ELSE 0 END) AS explore,
            SUM(CASE WHEN has_cart_activity THEN 1 ELSE 0 END) AS cart,
            SUM(CASE WHEN is_buyer THEN 1 ELSE 0 END) AS buy,
            SUM(CASE WHEN (n_page_visit > 0 OR n_search_query > 0) AND has_cart_activity THEN 1 ELSE 0 END) AS explore_to_cart,
            SUM(CASE WHEN has_cart_activity AND is_buyer THEN 1 ELSE 0 END) AS cart_to_buy,
            SUM(CASE WHEN is_buyer AND NOT has_cart_activity AND (n_page_visit = 0 AND n_search_query = 0) THEN 1 ELSE 0 END) AS buy_with_no_footprint
        FROM mart_customer_360
        """
    ).df()
    funnel_long = funnel.T.reset_index()
    funnel_long.columns = ["stage_metric", "value"]
    funnel_long.to_csv(OUT_DIR / "funnel_summary.csv", index=False)
    print("Saved funnel_summary.csv")

    # 3) Cohort & Retention (이미 작은 테이블 그대로)
    con.sql("SELECT * FROM mart_customer_retention ORDER BY cohort_week").df().to_csv(
        OUT_DIR / "cohort_retention.csv", index=False
    )
    print("Saved cohort_retention.csv")

    # 4) Lifecycle distribution
    con.sql(
        """
        SELECT lifecycle_stage, COUNT(*) AS n,
               ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 4) AS pct
        FROM mart_customer_lifecycle GROUP BY lifecycle_stage ORDER BY n DESC
        """
    ).df().to_csv(OUT_DIR / "lifecycle_distribution.csv", index=False)
    print("Saved lifecycle_distribution.csv")

    # 5) Segment profile (통계 + 정성 메타데이터 결합)
    seg_stats = con.sql(
        """
        SELECT
            s.segment,
            COUNT(*) AS n,
            AVG(CASE WHEN m.is_buyer THEN 1.0 ELSE 0.0 END) AS buy_rate,
            AVG(m.n_page_visit) AS avg_visit,
            AVG(m.n_search_query) AS avg_search,
            AVG(m.n_purchases) AS avg_purchases,
            AVG(g.avg_purchase_gap_days) AS avg_gap_days
        FROM mart_customer_segment s
        JOIN mart_customer_360 m ON s.client_id = m.client_id
        LEFT JOIN int_customer_purchase_gap g ON s.client_id = g.client_id
        GROUP BY s.segment
        """
    ).df()
    seg_stats["crm_purpose"] = seg_stats["segment"].map(lambda s: SEGMENT_META[s]["crm_purpose"])
    seg_stats["recommended_action"] = seg_stats["segment"].map(lambda s: SEGMENT_META[s]["recommended_action"])
    seg_stats["priority"] = seg_stats["segment"].map(lambda s: SEGMENT_META[s]["priority"])
    seg_stats["over_contact_risk"] = seg_stats["segment"].map(lambda s: SEGMENT_META[s]["over_contact_risk"])
    seg_stats = seg_stats.sort_values("n", ascending=False)
    seg_stats.to_csv(OUT_DIR / "segment_profile.csv", index=False)
    print("Saved segment_profile.csv")

    # 6) Targeting simulation (이미 계산된 결과 재사용)
    con.sql("SELECT * FROM mart_targeting_simulation").df().to_csv(
        OUT_DIR / "targeting_simulation.csv", index=False
    )
    print("Saved targeting_simulation.csv")

    print(f"\n모든 대시보드 데이터가 {OUT_DIR}/ 에 저장됨")


if __name__ == "__main__":
    main()

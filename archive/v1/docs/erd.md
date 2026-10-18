# ERD / 데이터 계보 (Data Lineage)

전통적인 FK 제약 기반 ERD보다, 이 프로젝트는 **staging → intermediate → mart**
순서로 흐르는 파이프라인 구조가 더 정확하게 관계를 보여준다. 각 화살표는
"입력으로 사용됨"을 의미한다. 상세 Grain/PK/컬럼 정의는 `docs/data_dictionary.md`
참고.

```mermaid
flowchart LR
    subgraph RAW["원본 (data/raw, 비공개)"]
        R1[product_buy.parquet]
        R2[add_to_cart.parquet]
        R3[remove_from_cart.parquet]
        R4[page_visit.parquet]
        R5[search_query.parquet]
        R6[product_properties.parquet]
    end

    subgraph STG["Staging (VIEW)"]
        S1[stg_product_buy]
        S2[stg_add_to_cart]
        S3[stg_remove_from_cart]
        S4[stg_page_visit]
        S5[stg_search_query]
        S6[stg_product_properties]
    end

    R1 --> S1
    R2 --> S2
    R3 --> S3
    R4 --> S4
    R5 --> S5
    R6 --> S6

    subgraph INT["Intermediate (TABLE)"]
        I1[int_customer_purchase_history]
        I2[int_customer_purchase_gap]
        I3[int_customer_daily_activity]
        I4[int_customer_cart_behavior]
        I5[int_customer_category_behavior]
        I6[int_customer_observation_period]
    end

    S1 --> I1
    S1 --> I2
    S1 --> I3
    S1 --> I4
    S1 --> I5
    S2 --> I3
    S2 --> I4
    S3 --> I3
    S3 --> I4
    S4 --> I3
    S4 --> I6
    S5 --> I3
    S5 --> I6
    S6 --> I5
    S2 --> I6
    S3 --> I6
    S1 --> I6

    subgraph MART["Mart (TABLE)"]
        M1[mart_customer_360]
        M2[mart_customer_cohort]
        M3[mart_customer_retention]
        M4[mart_customer_daily]
        M5[mart_customer_weekly]
        M6[mart_customer_lifecycle]
        M7[mart_customer_segment]
        M8[mart_customer_snapshot]
        M9[mart_churn_target]
        M10[mart_purchase_propensity]
        M11[mart_targeting_simulation]
    end

    I2 --> M1
    I4 --> M1
    I6 --> M1
    S4 --> M1
    S5 --> M1
    I2 --> M2
    M2 --> M3
    I1 --> M3
    I5 --> M3
    I6 --> M3
    I3 --> M4
    I3 --> M5
    M1 --> M6
    I6 --> M6
    I1 --> M6
    M6 --> M7
    M1 --> M7
    S1 --> M8
    S2 --> M8
    S3 --> M8
    S4 --> M8
    S5 --> M8
    S6 --> M8
    M8 --> M9
    M1 --> M10
    I3 --> M10
    I1 --> M10
    M9 --> M11
    M10 --> M11

    subgraph ML["모델 / 앱"]
        MA["Model A: churn 예측<br/>LightGBM"]
        MB["Model B: propensity 예측<br/>LightGBM"]
        DASH["Streamlit 대시보드<br/>7 페이지"]
        LLM[LLM CRM Report]
    end

    M9 --> MA
    M10 --> MB
    MA --> M11
    MB --> M11
    M1 --> DASH
    M3 --> DASH
    M6 --> DASH
    M7 --> DASH
    M11 --> DASH
    M7 --> LLM
    M11 --> LLM
```

## 레이어 요약

| 레이어 | 저장 방식 | 개수 | 설명 |
|---|---|---:|---|
| staging | VIEW | 6 | 원본 Parquet lazy 참조, 타입 캐스팅 + 버스트 플래그만 추가 |
| intermediate | TABLE | 6 | 고객 단위 집계·enrichment |
| mart | TABLE | 11 | 분석/모델링/대시보드가 직접 소비하는 최종 테이블 |

## Grain 빠른 참조

| 테이블 | Grain |
|---|---|
| mart_customer_360 | client_id |
| mart_customer_cohort | client_id (구매자만) |
| mart_customer_retention | cohort_week |
| mart_customer_daily | client_id × activity_date |
| mart_customer_weekly | client_id × week_start |
| mart_customer_lifecycle | client_id |
| mart_customer_segment | client_id |
| mart_customer_snapshot | client_id × snapshot_date |
| mart_churn_target | client_id × snapshot_date |
| mart_purchase_propensity | client_id × snapshot_date |
| mart_targeting_simulation | model × label × contact_rate_pct × policy |

전체 컬럼 정의·생성 SQL·품질 테스트는 `docs/data_dictionary.md` 참고.

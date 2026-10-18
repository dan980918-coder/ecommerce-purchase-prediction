"""Part 2 — k=20(Kneedle 엘보우)으로 검색 클러스터 확정 후,
각 클러스터 소속 검색 이후(같은 고객, 시간상 나중) 실제 구매 상품의
category 분포를 연결한다.
"""

import duckdb
import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans

RAW = "data/raw/synerise_dataset"
K = 20

X = np.load("/tmp/search_embeddings.npy")
meta = pd.read_parquet("/tmp/search_meta.parquet")  # client_id, search_ts

km = MiniBatchKMeans(n_clusters=K, random_state=42, n_init=10, batch_size=10000)
meta["search_cluster"] = km.fit_predict(X)

print(f"검색 클러스터 수: {K}")
print("클러스터별 검색 이벤트 수:")
print(meta["search_cluster"].value_counts().sort_index())

meta.to_parquet("/tmp/search_with_clusters.parquet")

# DuckDB로 "검색 이후(같은 고객, search_ts보다 나중) 구매"를 조인
con = duckdb.connect()
con.sql("CREATE TEMP TABLE search_clusters AS SELECT * FROM meta")

purchases = con.sql(
    f"""
    SELECT client_id, TRY_CAST(timestamp AS TIMESTAMP) AS buy_ts, sku
    FROM read_parquet('{RAW}/product_buy.parquet')
    """
).df()
con.sql("CREATE TEMP TABLE purchases AS SELECT * FROM purchases")

props = con.sql(f"SELECT sku, category FROM read_parquet('{RAW}/product_properties.parquet')").df()
con.sql("CREATE TEMP TABLE props AS SELECT * FROM props")

print("\n검색 이후 구매 조인 중 (같은 고객, buy_ts > search_ts)...")
linked = con.sql(
    """
    SELECT sc.search_cluster, p.category
    FROM search_clusters sc
    JOIN purchases pu ON sc.client_id = pu.client_id AND pu.buy_ts > sc.search_ts
    JOIN props p ON pu.sku = p.sku
    """
).df()
print(f"검색->이후구매 연결 건수: {len(linked):,}")

# 클러스터별 구매 category 분포 (상위 5개)
print("\n=== 검색 클러스터별, 이후 실제 구매한 상품의 category 분포 (상위 5개) ===")
rows = []
for c in sorted(linked["search_cluster"].unique()):
    sub = linked[linked["search_cluster"] == c]
    top5 = sub["category"].value_counts().head(5)
    top5_str = ", ".join(f"cat{idx}({cnt}건,{cnt/len(sub)*100:.1f}%)" for idx, cnt in top5.items())
    rows.append({
        "search_cluster": c,
        "n_search_events": (meta["search_cluster"] == c).sum(),
        "n_linked_purchases": len(sub),
        "n_distinct_categories_purchased": sub["category"].nunique(),
        "top1_category_pct": round(top5.iloc[0] / len(sub) * 100, 2) if len(top5) else None,
        "top5_categories": top5_str,
    })

result_df = pd.DataFrame(rows).sort_values("top1_category_pct", ascending=False)
pd.set_option("display.max_colwidth", 120)
pd.set_option("display.width", 220)
print(result_df.to_string(index=False))

# 전체적으로 검색 클러스터가 구매 category에 영향을 주는지 -> 전체 대비 각 클러스터의 top1 category 비중과
# "전체 구매 데이터에서의 category 분포"를 비교
overall_top = linked["category"].value_counts(normalize=True).head(5) * 100
print(f"\n=== 참고: 전체(모든 클러스터 통합) 구매 category 분포 상위 5 ===")
print(overall_top)

result_df.to_csv("reports/adhoc_search_cluster_purchase_category_crosstab.csv", index=False)
print("\nSaved: reports/adhoc_search_cluster_purchase_category_crosstab.csv")

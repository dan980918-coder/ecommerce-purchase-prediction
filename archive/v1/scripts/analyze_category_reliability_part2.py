"""Part 2 — k=50(Kneedle 엘보우로 결정)으로 최종 클러스터링 후 category와 교차표."""

import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans
from sklearn.metrics import normalized_mutual_info_score, adjusted_rand_score

X = np.load("/tmp/name_embeddings.npy")
df = pd.read_parquet("/tmp/product_category.parquet")

K = 50
km = MiniBatchKMeans(n_clusters=K, random_state=42, n_init=10, batch_size=10000)
df["name_cluster"] = km.fit_predict(X)

print(f"클러스터 수: {K}")
print(f"클러스터별 상품 수 분포:")
print(df["name_cluster"].value_counts().sort_index().describe())

# 전체 일치도 지표
nmi = normalized_mutual_info_score(df["category"], df["name_cluster"])
ari = adjusted_rand_score(df["category"], df["name_cluster"])
print(f"\n=== 전체 일치도 지표 ===")
print(f"Normalized Mutual Information (NMI): {nmi:.4f}  (0=무관, 1=완전 일치)")
print(f"Adjusted Rand Index (ARI): {ari:.4f}  (0=무작위 수준, 1=완전 일치)")

# 클러스터별 purity: 가장 많이 등장하는 category가 그 클러스터의 몇 %인지
print(f"\n=== 클러스터별 category 순수도(purity) 및 상위 category ===")
purities = []
rows = []
for c in sorted(df["name_cluster"].unique()):
    sub = df[df["name_cluster"] == c]
    top_cats = sub["category"].value_counts()
    top1_pct = top_cats.iloc[0] / len(sub) * 100
    purities.append(top1_pct)
    top3 = ", ".join(f"cat{idx}({cnt}건,{cnt/len(sub)*100:.1f}%)" for idx, cnt in top_cats.head(3).items())
    rows.append({"cluster": c, "n_products": len(sub), "n_distinct_categories": sub["category"].nunique(),
                 "top1_category_pct": round(top1_pct, 2), "top3_categories": top3})

result_df = pd.DataFrame(rows).sort_values("top1_category_pct", ascending=False)
pd.set_option("display.max_colwidth", 100)
pd.set_option("display.width", 200)
print(result_df.to_string(index=False))

print(f"\n전체 클러스터의 평균 purity(top1 category 비중): {np.mean(purities):.2f}%")
print(f"만약 category와 name-cluster가 완전 무관하다면 기대되는 top1 비중(무작위 기준): ~{100/6912*50:.3f}% 근처가 아니라, 클러스터 크기와 category 분포에 따라 다름 — 참고용")

result_df.to_csv("reports/adhoc_name_cluster_category_crosstab.csv", index=False)
df[["sku", "category", "name_cluster"]].to_parquet("/tmp/product_with_clusters.parquet")
print("\nSaved: reports/adhoc_name_cluster_category_crosstab.csv")

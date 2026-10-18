"""추가 분석 — product_properties.name(상품명 임베딩) 클러스터링 후 기존
category 라벨과의 일치도를 검증한다 (Phase 1 8.4~8.5 후속).

목적: category(익명 정수 ID)가 상품명 임베딩 유사도 기준으로도 신뢰할 만한
그룹핑인지 확인. 원본 데이터는 가공하지 않고 읽기만 한다.
"""

import duckdb
import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans
from sklearn.metrics import normalized_mutual_info_score, adjusted_rand_score

PATH = "data/raw/synerise_dataset/product_properties.parquet"


def parse_embedding(s: str) -> np.ndarray:
    return np.fromstring(s.strip("[]"), dtype=np.float32, sep=" ")


def main():
    con = duckdb.connect()
    df = con.sql(f"SELECT sku, category, name FROM read_parquet('{PATH}')").df()
    print(f"전체 상품 수: {len(df):,}, category 고유값: {df['category'].nunique():,}")

    print("임베딩 파싱 중...")
    X = np.vstack(df["name"].apply(parse_embedding).values)
    print(f"임베딩 shape: {X.shape}")

    # 엘보우 기법: k 후보별 inertia 계산 (MiniBatchKMeans, 대규모 데이터 대응)
    k_candidates = [5, 10, 20, 30, 50, 75, 100, 150]
    inertias = []
    print("\n엘보우 기법 — k별 inertia:")
    for k in k_candidates:
        km = MiniBatchKMeans(n_clusters=k, random_state=42, n_init=3, batch_size=10000)
        km.fit(X)
        inertias.append(km.inertia_)
        print(f"  k={k:4d}  inertia={km.inertia_:,.0f}")

    # 감소율(marginal drop) 확인 -> 엘보우 지점 판단
    print("\nk 증가에 따른 inertia 감소율:")
    for i in range(1, len(k_candidates)):
        drop_pct = (inertias[i - 1] - inertias[i]) / inertias[i - 1] * 100
        print(f"  k={k_candidates[i-1]:4d} -> k={k_candidates[i]:4d}: {drop_pct:.1f}% 감소")

    return df, X, k_candidates, inertias


if __name__ == "__main__":
    df, X, k_candidates, inertias = main()
    np.save("/tmp/name_embeddings.npy", X)
    df[["sku", "category"]].to_parquet("/tmp/product_category.parquet")
    print("\n임베딩과 category를 /tmp에 임시 저장 (다음 단계에서 재사용)")

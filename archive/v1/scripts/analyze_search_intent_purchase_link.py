"""추가 분석 — search_query 임베딩을 클러스터링해 검색 의도 그룹을 만들고,
각 검색 클러스터에 속한 고객이 이후(시간상 나중에) 실제 구매한 상품의
category 분포를 확인한다.

범위: 검색과 구매를 모두 한 고객(Phase 1 8.4 기준 319,926명)으로 한정 —
질문 자체가 "이 고객들의 검색 의도가 구매로 이어지는가"이므로, 검색만 하고
구매 안 한 고객까지 포함할 이유가 없고 계산량도 크게 줄어든다.
"""

import duckdb
import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans

RAW = "data/raw/synerise_dataset"


def parse_embedding(s: str) -> np.ndarray:
    return np.fromstring(s.strip("[]"), dtype=np.float32, sep=" ")


def main():
    con = duckdb.connect()

    print("검색+구매 모두 한 고객 범위로 축소 중...")
    overlap_clients = con.sql(
        f"""
        SELECT DISTINCT s.client_id
        FROM read_parquet('{RAW}/search_query.parquet') s
        JOIN read_parquet('{RAW}/product_buy.parquet') b USING (client_id)
        """
    ).df()
    print(f"검색+구매 중복 고객 수: {len(overlap_clients):,}")

    con.sql(f"CREATE TEMP TABLE overlap AS SELECT * FROM overlap_clients")

    searches = con.sql(
        f"""
        SELECT s.client_id, TRY_CAST(s.timestamp AS TIMESTAMP) AS search_ts, s.query
        FROM read_parquet('{RAW}/search_query.parquet') s
        JOIN overlap o ON s.client_id = o.client_id
        """
    ).df()
    print(f"해당 고객들의 검색 이벤트 수: {len(searches):,}")

    print("검색어 임베딩 파싱 중...")
    X = np.vstack(searches["query"].apply(parse_embedding).values)
    print(f"임베딩 shape: {X.shape}")

    k_candidates = [5, 10, 15, 20, 30, 50]
    inertias = []
    print("\n엘보우 기법 — k별 inertia:")
    for k in k_candidates:
        km = MiniBatchKMeans(n_clusters=k, random_state=42, n_init=3, batch_size=10000)
        km.fit(X)
        inertias.append(km.inertia_)
        print(f"  k={k:3d}  inertia={km.inertia_:,.0f}")

    np.save("/tmp/search_embeddings.npy", X)
    searches.drop(columns=["query"]).to_parquet("/tmp/search_meta.parquet")
    np.save("/tmp/search_k_candidates.npy", np.array(k_candidates))
    np.save("/tmp/search_inertias.npy", np.array(inertias))
    print("\n중간 결과 저장 완료 (다음 단계에서 재사용)")


if __name__ == "__main__":
    main()

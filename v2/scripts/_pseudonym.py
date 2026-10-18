"""client_id <-> 가명(고객00001 형식) 매핑. 매핑 파일은 v2/data/(git 제외)에만 저장한다."""
import os

import pandas as pd

MAP_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "client_pseudonym_map.csv")


def _load():
    if os.path.exists(MAP_PATH):
        df = pd.read_csv(MAP_PATH, dtype={"client_id": "int64", "pseudonym": str})
        return dict(zip(df["client_id"], df["pseudonym"]))
    return {}


def _save(mapping):
    os.makedirs(os.path.dirname(MAP_PATH), exist_ok=True)
    df = pd.DataFrame(sorted(mapping.items(), key=lambda kv: kv[1]), columns=["client_id", "pseudonym"])
    df.to_csv(MAP_PATH, index=False)


def pseudonymize(client_ids):
    """client_id 정수 리스트(또는 pandas Series) -> 가명 리스트. 새 client_id는 자동으로 다음 번호 부여."""
    mapping = _load()
    next_n = len(mapping) + 1
    changed = False
    out = []
    for cid in client_ids:
        cid = int(cid)
        if cid not in mapping:
            mapping[cid] = f"고객{next_n:05d}"
            next_n += 1
            changed = True
        out.append(mapping[cid])
    if changed:
        _save(mapping)
    return out


def pseudonymize_one(client_id):
    return pseudonymize([client_id])[0]

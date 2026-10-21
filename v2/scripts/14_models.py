"""4단계 모델링: 학습(학습 기준일)으로 학습, 검증(11-07)으로 모델·설정 선택.

00_analysis_rules.md의 결과 데이터 사용 순서를 따른다. 최종평가(11-23) 결과는
이 스크립트에서 전혀 조회하지 않는다. 선택 규칙은 사전에 고정했고 결과를 보고
바꾸지 않는다.
"""
import json
import os
import pickle
import sys

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score

sys.path.insert(0, os.path.dirname(__file__))
from _features import build_features, shift, CORE_AUX_COLS, FLAG_COLS, COUNT_LIKE_COLS  # noqa: E402

os.makedirs("docs", exist_ok=True)
SEED = 42
rng = np.random.default_rng(SEED)

DB_PATH = "data/v2.duckdb"
con = duckdb.connect(DB_PATH)
con.execute("SET threads=4")
con.execute("SET memory_limit='6GB'")
con.execute(f"SET temp_directory='{os.path.abspath('data/tmp')}'")
con.execute("SET preserve_insertion_order=false")

TRAINING_DATES = ["2022-08-22", "2022-09-05", "2022-09-19", "2022-10-03", "2022-10-17"]
VALIDATION_DATE = "2022-11-07"
ALL_FEATURE_COLS = CORE_AUX_COLS + FLAG_COLS
results = {}

# ========== 2-1. 학습 데이터: 구매 전부 + 비구매 20배 무작위(seed=42) ==========
print("## 2-1. 학습 데이터 구성")
train_frames = []
sampling_log = {}
for d in TRAINING_DATES:
    tag = d.replace("-", "")
    df = con.execute(f"SELECT client_id, outcome FROM outcome_{tag}_clean ORDER BY client_id").fetchdf()
    pos = df[df["outcome"] == 1]
    neg_pool = df[df["outcome"] == 0]
    n_neg_target = min(len(neg_pool), len(pos) * 20)
    neg = neg_pool.sample(n=n_neg_target, random_state=SEED)
    combined = pd.concat([pos, neg], ignore_index=True)
    combined["reference_date"] = d
    train_frames.append(combined)
    sampling_log[d] = {"n_purchasers": len(pos), "n_nonpurchasers_sampled": len(neg),
                        "ratio": round(len(neg) / len(pos), 2)}
    print(d, sampling_log[d])

train_ids = pd.concat(train_frames, ignore_index=True)
results["train_sampling"] = sampling_log
results["train_total_rows"] = len(train_ids)
print("학습 데이터 전체 행 수:", len(train_ids))

# ========== 2-2. 변수 생성 ==========
print("\n## 2-2. 학습 데이터 변수 생성")
train_feat_frames = []
for d in TRAINING_DATES:
    pop_d = train_ids[train_ids["reference_date"] == d][["client_id"]]
    feat_d = build_features(con, pop_d, d)
    feat_d = feat_d.merge(train_ids[train_ids["reference_date"] == d][["client_id", "outcome"]],
                           on="client_id", how="left")
    train_feat_frames.append(feat_d)
    print(d, "변수 생성 완료, 행 수:", len(feat_d))

train_df = pd.concat(train_feat_frames, ignore_index=True)
print("학습 변수 테이블 크기:", train_df.shape)

# ---------- 변환 ----------
print("\n변환: log1p(횟수형), 결측 표시 변수, p99.9 상한(로지스틱용)")
for c in CORE_AUX_COLS:
    train_df[f"{c}_missing"] = train_df[c].isna().astype(int)

for c in COUNT_LIKE_COLS:
    train_df[f"{c}_log1p"] = np.log1p(train_df[c].fillna(0))

caps = {}
logit_cols = []
for c in CORE_AUX_COLS:
    src = f"{c}_log1p" if c in COUNT_LIKE_COLS else c
    filled = train_df[src].fillna(train_df[src].median())
    cap = float(filled.quantile(0.999))
    caps[c] = cap
    train_df[f"{c}_capped"] = filled.clip(upper=cap)
    logit_cols.append(f"{c}_capped")
logit_cols += FLAG_COLS + [f"{c}_missing" for c in CORE_AUX_COLS]
results["logistic_caps_p999"] = caps

lgb_cols = CORE_AUX_COLS + FLAG_COLS  # LightGBM은 원 척도 그대로 사용(트리 모델은 단조변환에 불변)

with open("docs/models_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/models_results.json (학습 데이터까지)")
print("logistic 변수 수:", len(logit_cols), "/ lightgbm 변수 수:", len(lgb_cols))
train_df.to_parquet("data/tmp/train_df.parquet")
print("train_df 저장 완료 (data/tmp, 재사용용)")


def evaluate_ranking(score, outcome, tiebreak, fractions=(0.05, 0.10, 0.20)):
    """score: 높을수록 먼저 보낸다. tiebreak: 동률 처리용 seed=42 난수."""
    n = len(score)
    order = pd.DataFrame({"score": score, "tiebreak": tiebreak, "outcome": outcome}).sort_values(
        ["score", "tiebreak"], ascending=[False, False]
    )
    total_pos = int(outcome.sum())
    out = {}
    for frac in fractions:
        k = int(round(n * frac))
        top = order.iloc[:k]
        captured = int(top["outcome"].sum())
        out[frac] = {
            "n_sent": k, "n_captured": captured,
            "capture_rate": round(captured / total_pos, 5) if total_pos else None,
            "per_10k": round(captured / k * 10000, 2) if k else None,
        }
    try:
        auc = roc_auc_score(outcome, score)
        prauc = average_precision_score(outcome, score)
    except ValueError:
        auc, prauc = None, None
    out["auc"] = round(auc, 4) if auc is not None else None
    out["pr_auc"] = round(prauc, 4) if prauc is not None else None
    out["total_positive"] = total_pos
    out["n_population"] = n
    return out


# ========== 2-3. 검증 기준일(11-07) 모집단 변수·결과 생성 ==========
# 00_analysis_rules.md 7번(4단계 데이터 사용 순서): 모델·설정 선택은 검증 기준일로 한다.
print("\n## 검증 기준일(2022-11-07) 전체 모집단 변수·결과 생성 (모델 선택용)")
val_pop = con.execute(
    f"SELECT client_id FROM pop_{VALIDATION_DATE.replace('-', '')}_clean ORDER BY client_id"
).fetchdf()
print("검증 모집단 인원:", len(val_pop))
val_feat = build_features(con, val_pop, VALIDATION_DATE)
val_out_start, val_out_end = shift(VALIDATION_DATE, 0), shift(VALIDATION_DATE, 14)
val_outcome = con.execute(
    f"""SELECT p.client_id, CASE WHEN b.client_id IS NOT NULL THEN 1 ELSE 0 END AS outcome
        FROM pop_{VALIDATION_DATE.replace('-', '')}_clean p
        LEFT JOIN (SELECT DISTINCT client_id FROM clean_product_buy
                    WHERE timestamp >= '{val_out_start}' AND timestamp < '{val_out_end}') b
        ON p.client_id = b.client_id"""
).fetchdf()
val_df = val_feat.merge(val_outcome, on="client_id", how="left")
print("검증 변수 테이블 크기:", val_df.shape, "구매자 수:", int(val_df["outcome"].sum()),
      "구매율:", round(val_df["outcome"].mean() * 100, 4), "%")
results["validation_population"] = {"n": len(val_df), "n_purchasers": int(val_df["outcome"].sum()),
                                      "purchase_rate_pct": round(val_df["outcome"].mean() * 100, 4)}

for c in CORE_AUX_COLS:
    val_df[f"{c}_missing"] = val_df[c].isna().astype(int)
for c in COUNT_LIKE_COLS:
    val_df[f"{c}_log1p"] = np.log1p(val_df[c].fillna(0))
for c in CORE_AUX_COLS:
    src = f"{c}_log1p" if c in COUNT_LIKE_COLS else c
    filled = val_df[src].fillna(train_df[src].fillna(train_df[src].median()).median())
    val_df[f"{c}_capped"] = filled.clip(upper=caps[c])

val_df.to_parquet("data/tmp/val_df.parquet")
print("val_df 저장 완료")

rng_val = np.random.default_rng(SEED)
val_tiebreak = pd.Series(rng_val.random(len(val_df)), index=val_df.index)
rng_rand_score = np.random.default_rng(SEED)
val_random_score = pd.Series(rng_rand_score.random(len(val_df)), index=val_df.index)

baseline_scores_val = {
    "무작위": val_random_score,
    "최근활동순(현행기준)": -val_df["h1_days_since_last_activity"].fillna(1e9),
    "단순2단계규칙": val_df["ref_other_than_browsing"] * 1_000_000
                      - val_df["h1_days_since_last_activity"].fillna(1e9),
}

with open("docs/models_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/models_results.json (검증 모집단까지)")

# ========== 2-4. 로지스틱 회귀 (L2, C 그리드를 검증 상위10% 포착률로 선택) ==========
print("\n## 2-4a. 로지스틱 회귀 C 그리드")
X_train_logit = train_df[logit_cols].fillna(0).values
y_train = train_df["outcome"].values
X_val_logit = val_df[logit_cols].fillna(0).values
y_val = val_df["outcome"].values

logit_grid_results = {}
best_logit, best_logit_c, best_logit_capture10 = None, None, -1
for c in [0.01, 0.1, 1]:
    m = LogisticRegression(penalty="l2", C=c, max_iter=2000, random_state=SEED, solver="lbfgs")
    m.fit(X_train_logit, y_train)
    score = m.predict_proba(X_val_logit)[:, 1]
    ev = evaluate_ranking(pd.Series(score, index=val_df.index), val_df["outcome"], val_tiebreak)
    capture10 = ev[0.10]["capture_rate"]
    logit_grid_results[c] = {"capture_at_10pct": capture10, "auc": ev["auc"], "pr_auc": ev["pr_auc"]}
    print("C=", c, logit_grid_results[c])
    if capture10 > best_logit_capture10:
        best_logit, best_logit_c, best_logit_capture10 = m, c, capture10
print("선택된 C:", best_logit_c, "(검증 상위10% 포착률 기준)")
results["logistic_grid"] = logit_grid_results
results["logistic_selected_c"] = best_logit_c

# ========== 2-4b. LightGBM (그리드, 검증 logloss로 early stopping, 상위10% 포착률로 그리드 선택) ==========
print("\n## 2-4b. LightGBM 그리드")
lgb_train_set = lgb.Dataset(train_df[lgb_cols], label=train_df["outcome"])
lgb_val_set = lgb.Dataset(val_df[lgb_cols], label=val_df["outcome"], reference=lgb_train_set)

lgb_grid_results = {}
best_lgb, best_lgb_params, best_lgb_capture10 = None, None, -1
for num_leaves in [15, 31, 63]:
    for lr in [0.03, 0.05]:
        for min_child in [100, 500]:
            params = {
                "objective": "binary", "metric": "binary_logloss",
                "num_leaves": num_leaves, "learning_rate": lr, "min_child_samples": min_child,
                "verbose": -1, "seed": SEED,
                "deterministic": True, "num_threads": 1,
            }
            booster = lgb.train(
                params, lgb_train_set, num_boost_round=500, valid_sets=[lgb_val_set],
                callbacks=[lgb.early_stopping(30, verbose=False)],
            )
            score = booster.predict(val_df[lgb_cols], num_iteration=booster.best_iteration)
            ev = evaluate_ranking(pd.Series(score, index=val_df.index), val_df["outcome"], val_tiebreak)
            capture10 = ev[0.10]["capture_rate"]
            key = f"leaves{num_leaves}_lr{lr}_minchild{min_child}"
            lgb_grid_results[key] = {"capture_at_10pct": capture10, "auc": ev["auc"], "pr_auc": ev["pr_auc"],
                                      "best_iteration": booster.best_iteration}
            print(key, lgb_grid_results[key])
            if capture10 > best_lgb_capture10:
                best_lgb, best_lgb_params, best_lgb_capture10 = booster, params, capture10

print("선택된 LightGBM 설정:", best_lgb_params, "(검증 상위10% 포착률 기준)")
results["lightgbm_grid"] = lgb_grid_results
results["lightgbm_selected_params"] = best_lgb_params

with open("docs/models_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/models_results.json (모델 그리드까지)")

# ========== 2-5 & 2-6. 검증 평가 표 + 선택 규칙 적용 ==========
print("\n## 2-5. 검증 평가 (방법 5개 x 발송량 3개)")
logit_score_val = pd.Series(best_logit.predict_proba(X_val_logit)[:, 1], index=val_df.index)
lgb_score_val = pd.Series(best_lgb.predict(val_df[lgb_cols], num_iteration=best_lgb.best_iteration),
                           index=val_df.index)

all_scores_val = dict(baseline_scores_val)
all_scores_val["로지스틱회귀"] = logit_score_val
all_scores_val["LightGBM"] = lgb_score_val

validation_table = {}
for name, score in all_scores_val.items():
    validation_table[name] = evaluate_ranking(score, val_df["outcome"], val_tiebreak)
    print(name, validation_table[name])
results["validation_table"] = validation_table

# 선택 규칙 1: LightGBM이 로지스틱보다 상위10% 포착률 1%p 이상 높으면 LightGBM, 아니면 로지스틱
capture10_lgb = validation_table["LightGBM"][0.10]["capture_rate"]
capture10_logit = validation_table["로지스틱회귀"][0.10]["capture_rate"]
if capture10_lgb - capture10_logit >= 0.01:
    selected_model_name, selected_score_val = "LightGBM", lgb_score_val
else:
    selected_model_name, selected_score_val = "로지스틱회귀", logit_score_val
print(f"\n선택 규칙1 — 모델 선택: {selected_model_name} "
      f"(LightGBM {capture10_lgb*100:.2f}%p vs 로지스틱 {capture10_logit*100:.2f}%p, 차이 {(capture10_lgb-capture10_logit)*100:.2f}%p)")
results["rule1_model_selection"] = {
    "lightgbm_capture10": capture10_lgb, "logistic_capture10": capture10_logit,
    "diff_pp": round((capture10_lgb - capture10_logit) * 100, 3), "selected": selected_model_name,
}

# 선택 규칙 2: 기본값 검색 표시 제거 시 상위10% 포착률이 0.5%p 이상 떨어지면 유지, 아니면 제거
print("\n## 선택 규칙2 — 기본값 검색 표시 포함/제외 비교")
cols_without_flag_logit = [c for c in logit_cols if "ref_default_search_flag" not in c]
cols_without_flag_lgb = [c for c in lgb_cols if "ref_default_search_flag" not in c]
if selected_model_name == "LightGBM":
    train_set_noflag = lgb.Dataset(train_df[cols_without_flag_lgb], label=train_df["outcome"])
    val_set_noflag = lgb.Dataset(val_df[cols_without_flag_lgb], label=val_df["outcome"], reference=train_set_noflag)
    booster_noflag = lgb.train(
        best_lgb_params, train_set_noflag, num_boost_round=500, valid_sets=[val_set_noflag],
        callbacks=[lgb.early_stopping(30, verbose=False)],
    )
    score_noflag = pd.Series(booster_noflag.predict(val_df[cols_without_flag_lgb],
                                                       num_iteration=booster_noflag.best_iteration),
                              index=val_df.index)
else:
    m_noflag = LogisticRegression(penalty="l2", C=best_logit_c, max_iter=2000, random_state=SEED, solver="lbfgs")
    m_noflag.fit(train_df[cols_without_flag_logit].fillna(0).values, y_train)
    score_noflag = pd.Series(m_noflag.predict_proba(val_df[cols_without_flag_logit].fillna(0).values)[:, 1],
                              index=val_df.index)

ev_noflag = evaluate_ranking(score_noflag, val_df["outcome"], val_tiebreak)
capture10_with_flag = validation_table[selected_model_name][0.10]["capture_rate"]
capture10_without_flag = ev_noflag[0.10]["capture_rate"]
drop_pp = (capture10_with_flag - capture10_without_flag) * 100
keep_flag = drop_pp >= 0.5
print(f"포함 시 상위10% 포착률 {capture10_with_flag*100:.3f}%p, 제외 시 {capture10_without_flag*100:.3f}%p, "
      f"하락폭 {drop_pp:.3f}%p -> {'유지' if keep_flag else '제거'}")
results["rule2_default_search_flag"] = {
    "capture10_with_flag": capture10_with_flag, "capture10_without_flag": capture10_without_flag,
    "drop_pp": round(drop_pp, 3), "decision": "유지" if keep_flag else "제거",
}
final_score_val = selected_score_val if keep_flag else score_noflag

# 선택 규칙 3: 운영 권고안 — 최종모델 vs 단순2단계규칙, 1%p 이상이면 모델, 아니면 규칙
capture10_final_model = validation_table[selected_model_name][0.10]["capture_rate"] if keep_flag else capture10_without_flag
capture10_simple_rule = validation_table["단순2단계규칙"][0.10]["capture_rate"]
if capture10_final_model - capture10_simple_rule >= 0.01:
    operational_recommendation = "모델"
else:
    operational_recommendation = "단순2단계규칙"
print(f"\n선택 규칙3 — 운영 권고안: {operational_recommendation} "
      f"(모델 {capture10_final_model*100:.2f}%p vs 단순규칙 {capture10_simple_rule*100:.2f}%p)")
results["rule3_operational_recommendation"] = {
    "final_model_capture10": capture10_final_model, "simple_rule_capture10": capture10_simple_rule,
    "diff_pp": round((capture10_final_model - capture10_simple_rule) * 100, 3),
    "recommendation": operational_recommendation,
}

# ========== 변수 기여도 ==========
print("\n## 변수 기여도 (선택된 모델 기준, 상위 15개)")
if selected_model_name == "LightGBM":
    booster_final = best_lgb if keep_flag else booster_noflag
    cols_final = lgb_cols if keep_flag else cols_without_flag_lgb
    importance = pd.Series(booster_final.feature_importance(importance_type="gain"), index=cols_final)
    importance = importance.sort_values(ascending=False).head(15)
    feature_importance = importance.to_dict()
else:
    model_final = best_logit if keep_flag else m_noflag
    cols_final = logit_cols if keep_flag else cols_without_flag_logit
    coefs = pd.Series(model_final.coef_[0], index=cols_final)
    feature_importance = coefs.reindex(coefs.abs().sort_values(ascending=False).head(15).index).to_dict()
print(feature_importance)
results["feature_importance_top15"] = {k: float(v) for k, v in feature_importance.items()}
results["final_model_name"] = selected_model_name
results["final_model_keeps_default_search_flag"] = keep_flag

with open("docs/models_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print("wrote docs/models_results.json (최종)")

# 모델/변환 파라미터 저장 (내부용, git 제외 v2/data/)
with open("data/final_model.pkl", "wb") as f:
    pickle.dump({
        "model_name": selected_model_name, "keeps_default_search_flag": keep_flag,
        "logistic_model": best_logit, "logistic_c": best_logit_c, "logistic_cols": logit_cols,
        "logistic_cols_noflag": cols_without_flag_logit,
        "lightgbm_model": best_lgb, "lightgbm_params": best_lgb_params, "lightgbm_cols": lgb_cols,
        "lightgbm_cols_noflag": cols_without_flag_lgb,
        "lightgbm_model_noflag": booster_noflag if selected_model_name == "LightGBM" else None,
        "logistic_model_noflag": m_noflag if selected_model_name == "로지스틱회귀" else None,
        "caps_p999": caps, "count_like_cols": COUNT_LIKE_COLS, "core_aux_cols": CORE_AUX_COLS,
        "flag_cols": FLAG_COLS,
    }, f)
print("saved data/final_model.pkl (내부용, git 제외)")
con.close()
print("모델링 전체 완료")

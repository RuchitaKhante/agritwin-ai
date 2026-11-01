# compare_models.py - the "experimental component" your guide asked for.
# Trains Random Forest, XGBoost, GRU and LSTM on the SAME data/split and compares them with a
# persistence baseline: MAE/RMSE/R2 per horizon + 4-level soil-condition accuracy (macro-F1).
# NOTE: all numbers come from SIMULATED data - they show relative model behaviour, not field accuracy.
# Run: python compare_models.py   (after simulate_training_sequences.py)

import json
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import f1_score, accuracy_score
from sklearn.multioutput import MultiOutputRegressor
from tensorflow import keras
from xgboost import XGBRegressor

import engine_config as cfg
from dataset import build_dataset, split_by_field
from train_lstm import build_model, metrics_per_horizon
from data_utils import classify_condition

H = cfg.HORIZON


def flat(Xp, Xf):
    return np.concatenate([Xp.reshape(len(Xp), -1), Xf.reshape(len(Xf), -1)], axis=1)


def fit_keras(kind, Xp, Xf, Y, tr):
    m = build_model(kind, Xp[tr], Xf[tr], Y[tr])
    es = keras.callbacks.EarlyStopping(monitor="val_loss", patience=6, restore_best_weights=True)
    m.fit([Xp[tr], Xf[tr]], Y[tr], validation_split=0.15, epochs=40, batch_size=128, callbacks=[es], verbose=0)
    return m


def main():
    Xp, Xf, Y, F = build_dataset()
    tr, te = split_by_field(F)
    preds = {"Persistence": np.repeat(Xp[te][:, -1, 0:1], H, axis=1)}

    print("training Random Forest ..."); rf = RandomForestRegressor(n_estimators=150, n_jobs=-1, random_state=0)
    rf.fit(flat(Xp[tr], Xf[tr]), Y[tr]); preds["Random Forest"] = rf.predict(flat(Xp[te], Xf[te]))

    print("training XGBoost ..."); xgb = MultiOutputRegressor(XGBRegressor(n_estimators=250, max_depth=5, learning_rate=0.06, n_jobs=-1))
    xgb.fit(flat(Xp[tr], Xf[tr]), Y[tr]); preds["XGBoost"] = xgb.predict(flat(Xp[te], Xf[te]))

    for kind, name in (("gru", "GRU"), ("lstm", "LSTM (deployed)")):
        print(f"training {name} ...")
        m = fit_keras(kind, Xp, Xf, Y, tr); preds[name] = m.predict([Xp[te], Xf[te]], verbose=0)

    rows, detail = [], {}
    true_cls = np.array([[classify_condition(v) for v in r] for r in Y[te]])
    for name, P in preds.items():
        m = metrics_per_horizon(Y[te], P)
        pc = np.array([[classify_condition(v) for v in r] for r in P])
        detail[name] = m
        rows.append({"model": name,
                     "MAE_day1": m["h1"]["mae"], "MAE_day3": m["h3"]["mae"], "MAE_day7": m["h7"]["mae"],
                     "RMSE_day7": m["h7"]["rmse"], "R2_day1": m["h1"]["r2"], "R2_day7": m["h7"]["r2"],
                     "condition_accuracy": accuracy_score(true_cls.ravel(), pc.ravel()),
                     "condition_macro_F1": f1_score(true_cls.ravel(), pc.ravel(), average="macro")})
    df = pd.DataFrame(rows).round(3)
    df.to_csv("model_comparison.csv", index=False)
    json.dump({"data": "simulated", "per_horizon": detail}, open("model_comparison.json", "w"), indent=1)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
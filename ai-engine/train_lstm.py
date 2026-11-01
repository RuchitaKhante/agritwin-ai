# train_lstm.py  (v2 - multi-horizon LSTM with weather-forecast inputs)
#
# Inputs : past window (10 x 4) + forecast covariates for the next 7 days (7 x 3)
# Output : predicted soil moisture for each of the next 7 steps
# Also saves: forecast_intervals.json (empirical 80 % band per horizon) and model_metrics.json.
# Run:  python simulate_training_sequences.py   then   python train_lstm.py

import json
import numpy as np
from tensorflow import keras
from tensorflow.keras import layers
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

import engine_config as cfg
from dataset import build_dataset, split_by_field

W, H = cfg.WINDOW, cfg.HORIZON


def build_model(kind="lstm", Xp_train=None, Xf_train=None, Y_train=None):
    past_in = keras.Input(shape=(W, 4), name="past")
    fut_in = keras.Input(shape=(H, 3), name="future")

    norm_p = layers.Normalization(name="norm_past")
    norm_f = layers.Normalization(name="norm_future")
    if Xp_train is not None:
        norm_p.adapt(Xp_train.reshape(-1, 4)); norm_f.adapt(Xf_train.reshape(-1, 3))
    p = layers.Reshape((W, 4))(norm_p(past_in))
    f = layers.Reshape((H, 3))(norm_f(fut_in))

    Rnn = layers.LSTM if kind == "lstm" else layers.GRU
    h = Rnn(64, return_sequences=True)(p)
    h = layers.Dropout(0.1)(h)
    h = Rnn(32)(h)
    fe = layers.Dense(32, activation="relu")(layers.Flatten()(f))
    last = layers.Flatten()(layers.Cropping1D((W - 1, 0))(p))      # normalised latest reading (skip path)
    z = layers.Concatenate()([h, fe, last])
    z = layers.Dense(64, activation="relu")(z)
    out_norm = layers.Dense(H)(z)

    out = layers.Normalization(invert=True, name="denorm_moisture")
    if Y_train is not None:
        out.adapt(Y_train.reshape(-1, 1))
    # one shared mean/std for all horizons
    out_final = layers.Reshape((H,))(out(layers.Reshape((H, 1))(out_norm)))
    model = keras.Model([past_in, fut_in], out_final, name=f"moisture_{kind}")
    model.compile(optimizer="adam", loss="mse")
    return model


def metrics_per_horizon(Y, P):
    res = {}
    for k in range(H):
        res[f"h{k + 1}"] = {
            "mae": float(mean_absolute_error(Y[:, k], P[:, k])),
            "rmse": float(np.sqrt(mean_squared_error(Y[:, k], P[:, k]))),
            "r2": float(r2_score(Y[:, k], P[:, k])),
        }
    return res


def train(csv_path="simulated_sequences.csv", epochs=40, kind="lstm", save=True, seed=42):
    keras.utils.set_random_seed(seed)   # reproducible initialisation / shuffling (same machine & TF version)
    Xp, Xf, Y, F = build_dataset(csv_path)
    tr, te = split_by_field(F)
    print(f"samples: train={tr.sum()} test={te.sum()}  (split by field)")
    model = build_model(kind, Xp[tr], Xf[tr], Y[tr])
    early = keras.callbacks.EarlyStopping(monitor="val_loss", patience=6, restore_best_weights=True)
    model.fit([Xp[tr], Xf[tr]], Y[tr], validation_split=0.15, epochs=epochs,
              batch_size=128, callbacks=[early], verbose=2)
    P = model.predict([Xp[te], Xf[te]], verbose=0)

    m = metrics_per_horizon(Y[te], P)
    persistence = np.repeat(Xp[te][:, -1, 0:1], H, axis=1)
    m_base = metrics_per_horizon(Y[te], persistence)
    print("LSTM        :", {k: round(v["mae"], 2) for k, v in m.items()}, "(MAE per horizon)")
    print("Persistence :", {k: round(v["mae"], 2) for k, v in m_base.items()}, "(MAE per horizon)")

    if save:
        model.save(cfg.MODEL_PATH)
        resid = Y[te] - P
        lo, hi = cfg.INTERVAL_QUANTILES
        intervals = {"lower": [float(np.quantile(resid[:, k], lo)) for k in range(H)],
                     "upper": [float(np.quantile(resid[:, k], hi)) for k in range(H)],
                     "note": "empirical residual quantiles on SIMULATED validation data"}
        json.dump(intervals, open(cfg.INTERVALS_PATH, "w"), indent=2)
        json.dump({"data": "simulated (water-balance simulator)", "test_samples": int(te.sum()),
                   "lstm": m, "persistence_baseline": m_base}, open(cfg.METRICS_PATH, "w"), indent=2)
        print("saved:", cfg.MODEL_PATH, cfg.INTERVALS_PATH, cfg.METRICS_PATH)
    return model


if __name__ == "__main__":
    train()
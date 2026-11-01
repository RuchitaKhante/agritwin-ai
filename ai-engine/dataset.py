# dataset.py - builds multi-horizon training samples from simulated_sequences.csv
#
# For every forecast origin T inside a field:
#   past   = rows T-WINDOW+1 .. T   -> (WINDOW, 4)  [moisture, temperature, humidity, rain_chance]
#   future = FORECAST covariates for days T+1 .. T+H -> (H, 3) [temperature, humidity, rain_chance]
#            (true future values + noise, because a real weather forecast is never perfect)
#   target = true moisture for days T+1 .. T+H      -> (H,)
# The split is done BY FIELD so no field appears in both train and test.

import numpy as np
import pandas as pd
import engine_config as cfg

FEATURES = ["moisture", "temperature", "humidity", "rain_chance_percent"]


def build_dataset(csv_path="simulated_sequences.csv", seed=5):
    rng = np.random.default_rng(seed)
    df = pd.read_csv(csv_path)
    W, H = cfg.WINDOW, cfg.HORIZON
    Xp, Xf, Y, F = [], [], [], []
    for fid, g in df.groupby("field_id"):
        v = g[FEATURES].to_numpy()
        n = len(v)
        for T in range(W - 1, n - H):
            past = v[T - W + 1:T + 1]
            fut = v[T + 1:T + 1 + H]
            k = np.arange(1, H + 1)
            temp_fc = fut[:, 1] + rng.normal(0, 1.0 + 0.2 * k)
            hum_fc = fut[:, 2] + rng.normal(0, 4.0, H)
            rain_fc = np.clip(fut[:, 3] + rng.normal(0, 8.0, H), 0, 100)
            Xp.append(past)
            Xf.append(np.stack([temp_fc, hum_fc, rain_fc], axis=1))
            Y.append(fut[:, 0])
            F.append(fid)
    return (np.array(Xp, "float32"), np.array(Xf, "float32"), np.array(Y, "float32"), np.array(F))


def split_by_field(F, test_frac=0.2, seed=3):
    rng = np.random.default_rng(seed)
    fields = np.unique(F)
    rng.shuffle(fields)
    test_fields = set(fields[: int(len(fields) * test_frac)])
    test_mask = np.array([f in test_fields for f in F])
    return ~test_mask, test_mask
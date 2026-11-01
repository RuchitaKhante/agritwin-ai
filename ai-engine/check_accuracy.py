# check_accuracy.py - prints the saved evaluation of the deployed multi-horizon model.
# Run after train_lstm.py (and compare_models.py for the model comparison table).
import json, os
import pandas as pd

if os.path.exists("model_metrics.json"):
    m = json.load(open("model_metrics.json"))
    print(f"Data: {m['data']}  | test samples: {m['test_samples']}\n")
    print("Per-horizon error of the deployed LSTM vs a persistence baseline (SIMULATED data):")
    print(f"{'horizon':>8} {'LSTM MAE':>9} {'LSTM RMSE':>10} {'LSTM R2':>8} {'Persist MAE':>12}")
    for k, v in m["lstm"].items():
        b = m["persistence_baseline"][k]
        print(f"{'day ' + k[1:]:>8} {v['mae']:>9.2f} {v['rmse']:>10.2f} {v['r2']:>8.3f} {b['mae']:>12.2f}")
else:
    print("model_metrics.json not found - run train_lstm.py first.")
if os.path.exists("model_comparison.csv"):
    print("\nModel comparison (simulated data):")
    print(pd.read_csv("model_comparison.csv").to_string(index=False))
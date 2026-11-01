# explainability_engine.py
#
# Owns: soil health score (rule-based), crop stress flag (rule-based), and SHAP
# explanation (backed by a small trained model). No external dataset needed -
# training data is generated synthetically using a formula that encodes basic
# agronomic logic (weak supervision), since real labeled data isn't available yet.

import pandas as pd
import numpy as np
import joblib
import shap
from sklearn.ensemble import RandomForestRegressor

import engine_config as cfg
from data_utils import order_history

FEATURES = ["moisture", "temperature", "humidity"]
MODEL_PATH = "urgency_model.pkl"


IDEAL = {"moisture": cfg.HEALTH_IDEAL_MOISTURE, "temperature": 25, "humidity": 60}


def soil_health_breakdown(moisture, temperature, humidity):
    """
    Rule-based, deterministic soil health score (0-100) with its components, so it is explainable:
        moisture_score    = 100 - |moisture - 30| * 5        (30 % = middle of the 25-35 % normal band)
        temperature_score = 100 - |temperature - 25| * 3
        humidity_score    = 100 - |humidity    - 60|
        each component is clamped to 0-100
        score             = 0.6*moisture + 0.2*temperature + 0.2*humidity   (weights in engine_config)
    Result: critical/dry/wet soil scores low, normal soil scores high (it used to average three components
    around a 50 % ideal, which gave 78/100 for critical soil).
    """
    clamp = lambda v: max(0.0, min(100.0, v))
    comp = {
        "moisture_score": clamp(100 - abs(moisture - IDEAL["moisture"]) * cfg.HEALTH_MOISTURE_PENALTY),
        "temperature_score": clamp(100 - abs(temperature - IDEAL["temperature"]) * 3),
        "humidity_score": clamp(100 - abs(humidity - IDEAL["humidity"])),
    }
    w = cfg.HEALTH_WEIGHTS
    score = (w["moisture"] * comp["moisture_score"] + w["temperature"] * comp["temperature_score"]
             + w["humidity"] * comp["humidity_score"])
    return {"score": round(max(0, min(100, score)), 1),
            "components": {k: round(v, 1) for k, v in comp.items()},
            "weights": dict(w),
            "ideal": dict(IDEAL)}


def soil_health_score(moisture, temperature, humidity):
    """Rule-based score, 0-100. No ML needed."""
    return soil_health_breakdown(moisture, temperature, humidity)["score"]


def crop_stress_flag(moisture, temperature):
    """
    True if the crop is likely under heat or water stress right now.
    Matches the 'Soil Health & Crop Stress Logic' box in the architecture diagram -
    this is a separate signal from soil_health_score, not a replacement for it.
    """
    return bool(moisture < cfg.STRESS_MOISTURE_BELOW or temperature > cfg.STRESS_TEMP_ABOVE)


def generate_training_data(n=500, seed=42):
    """Synthetic data using weak-supervision rules - no external dataset needed."""
    rng = np.random.default_rng(seed)
    moisture = rng.uniform(10, 80, n)
    temperature = rng.uniform(15, 42, n)
    humidity = rng.uniform(20, 90, n)

    urgency = (80 - moisture) * 0.6 + (temperature - 20) * 0.8 - (humidity - 50) * 0.2
    urgency = np.clip(urgency, 0, 100)

    return pd.DataFrame({
        "moisture": moisture,
        "temperature": temperature,
        "humidity": humidity,
        "urgency": urgency,
    })


def train_and_save_model():
    """Run this ONCE to create urgency_model.pkl. Re-run only if you change the logic above."""
    df = generate_training_data()
    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(df[FEATURES], df["urgency"])
    joblib.dump(model, MODEL_PATH)
    print(f"Model trained and saved to {MODEL_PATH}")
    return model


def _load_model_and_explainer():
    import os
    if not os.path.exists(MODEL_PATH):
        train_and_save_model()
    model = joblib.load(MODEL_PATH)
    explainer = shap.TreeExplainer(model)
    return model, explainer


# Loaded once at import time, reused across every request (not reloaded per call)
_model, _explainer = _load_model_and_explainer()


def get_shap_explanation(moisture, temperature, humidity):
    """Returns each feature's relative contribution (0-1 share) to the urgency prediction."""
    input_df = pd.DataFrame([[moisture, temperature, humidity]], columns=FEATURES)
    shap_values = _explainer.shap_values(input_df)

    raw = dict(zip(FEATURES, shap_values[0]))
    total = sum(abs(v) for v in raw.values())
    if total == 0:
        return {k: round(1 / len(FEATURES), 2) for k in FEATURES}
    return {k: float(round(abs(v) / total, 2)) for k, v in raw.items()}


def analyze_soil_health(sensor_history, weather_forecast):
    """Uses the LATEST reading (history is ordered oldest-first by timestamp here, so input order no longer matters)."""
    latest = order_history(sensor_history)[-1]
    m, t, h = latest["moisture"], latest["temperature"], latest["humidity"]

    breakdown = soil_health_breakdown(m, t, h)
    return {
        "soil_health_score": breakdown["score"],
        "soil_health_breakdown": breakdown,
        "crop_stress": crop_stress_flag(m, t),
        "shap_explanation": get_shap_explanation(m, t, h),
    }


if __name__ == "__main__":
    # Quick standalone self-test - run: python explainability_engine.py
    sample_history = [
        {"moisture": 42.5, "temperature": 29.3, "humidity": 61.0, "timestamp": "2026-08-05T07:00:00"}
    ]
    sample_weather = {"temperature": 34.0, "rain_chance_percent": 10}
    print(analyze_soil_health(sample_history, sample_weather))
# simulate_training_sequences.py   (v2 - water-balance simulator, multi-day)
#
# Generates sequential training data for the multi-horizon LSTM. SF24 (soil_farming_data.csv)
# has no day-to-day order, so it is used ONLY to calibrate temperature / humidity ranges.
#
# Daily water balance per virtual field (no irrigation - the model learns the
# "do nothing" trajectory; the digital twin adds irrigation on top):
#   moisture_t = moisture_{t-1} - ET_t + infiltration(rain_t)  (+ drainage above field capacity)
#   ET (mm/day)   rises with temperature, falls with humidity, is throttled when soil is dry
#   rain_t (mm)   occurs with probability p_t (the *forecast rain chance*, a calibrated probability)
#   1 mm of water ~ 100/ROOT_ZONE_DEPTH_MM percentage points of moisture
#
# HONEST LIMITATION: this is a physically-motivated SIMULATION, not field data. Treat it as
# pre-training; re-train / fine-tune on real ESP32 + Open-Meteo history when it exists.

import numpy as np
import pandas as pd
import engine_config as cfg

SF24_PATH = "soil_farming_data.csv"
OUTPUT_PATH = "simulated_sequences.csv"
NUM_FIELDS = 300
DAYS_PER_FIELD = 120


def calibrate_from_sf24(csv_path=SF24_PATH):
    df = pd.read_csv(csv_path)
    return {
        "temp_mean": df["temperature"].mean(), "temp_std": df["temperature"].std(),
        "humid_mean": df["humidity"].mean(), "humid_std": df["humidity"].std(),
    }


def simulate(stats, num_fields=NUM_FIELDS, days=DAYS_PER_FIELD, seed=11):
    rng = np.random.default_rng(seed)
    mm_to_pts = 100.0 / cfg.ROOT_ZONE_DEPTH_MM
    rows = []
    for field_id in range(num_fields):
        temp_mu = np.clip(stats["temp_mean"] + rng.normal(0, 3), 18, 36)
        hum_mu = np.clip(stats["humid_mean"] + rng.normal(0, 8), 30, 85)
        wet_mu = rng.uniform(8, 45)                 # field's typical rain chance (%)
        field_cap = rng.uniform(36, 46)             # field capacity (% moisture)
        moisture = rng.uniform(15, 45)
        temp, hum, p = temp_mu, hum_mu, wet_mu
        for day in range(days):
            temp = np.clip(temp_mu + 0.8 * (temp - temp_mu) + rng.normal(0, 1.8), 15, 42)
            p = float(np.clip(0.7 * p + 0.3 * wet_mu + rng.normal(0, 18), 0, 100))
            rain_mm = rng.exponential(12.0) if rng.random() < p / 100.0 else 0.0
            hum = np.clip(hum_mu + 0.7 * (hum - hum_mu) + rng.normal(0, 4) + (8 if rain_mm > 0 else 0), 15, 98)

            et_mm = max(0.5, 2.0 + 0.20 * (temp - 25) + 0.03 * (55 - hum))
            throttle = float(np.clip((moisture - 8) / (30 - 8), 0.15, 1.0))
            moisture = moisture - et_mm * throttle * mm_to_pts + 0.7 * rain_mm * mm_to_pts
            if moisture > field_cap:
                moisture = field_cap + 0.75 * (moisture - field_cap)
            moisture = float(np.clip(moisture + rng.normal(0, 0.4), 3, 55))

            rows.append({"field_id": field_id, "day": day, "moisture": moisture,
                         "temperature": temp, "humidity": hum, "rain_chance_percent": p})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    stats = calibrate_from_sf24()
    print("Calibrated from SF24:", stats)
    df = simulate(stats)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"Generated {len(df)} rows ({NUM_FIELDS} fields x {DAYS_PER_FIELD} days) -> {OUTPUT_PATH}")
    print(df[["moisture", "temperature", "humidity", "rain_chance_percent"]].describe().round(1))
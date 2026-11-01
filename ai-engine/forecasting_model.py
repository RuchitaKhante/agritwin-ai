# forecasting_model.py  (v2 - multi-horizon LSTM + digital twin rollouts)
#
# Owns: 7-step soil-moisture forecast (LSTM fed with the past window AND the weather forecast
# for the coming days), uncertainty band, and the digital-twin "what-if" engine
# (rain, drier field, irrigation at a chosen time) built on the same model.
#
# Requires: moisture_lstm.keras + forecast_intervals.json  (run simulate_training_sequences.py
# then train_lstm.py once).

import json
import os
import numpy as np
from tensorflow.keras.models import load_model

import engine_config as cfg
from data_utils import order_history, classify_moisture, needs_water, legacy_status, step_date, date_label, weekday

W, H = cfg.WINDOW, cfg.HORIZON
_model = load_model(cfg.MODEL_PATH)       # loaded once, reused for every request

if os.path.exists(cfg.INTERVALS_PATH):
    _iv = json.load(open(cfg.INTERVALS_PATH))
    _LOWER, _UPPER = np.array(_iv["lower"]), np.array(_iv["upper"])
else:
    _LOWER, _UPPER = np.zeros(H), np.zeros(H)


# --------------------------------------------------------------------------------------
# Input preparation
# --------------------------------------------------------------------------------------
def build_weather_outlook(ordered_history, weather_forecast, daily_forecast=None, days=2 * H):
    """
    Returns `days` entries (day +1, +2, ...) of {temperature, humidity, rain_chance_percent, date}.
    Uses the daily forecast when given (from Open-Meteo); otherwise repeats the single
    weather_forecast value. Short lists are padded with their last day.
    """
    last = ordered_history[-1]
    out = []
    if daily_forecast:
        for d in daily_forecast:
            out.append({
                "date": d.get("date"),
                "temperature": float(d.get("temperature", weather_forecast.get("temperature", last["temperature"]))),
                "humidity": float(d["humidity"]) if d.get("humidity") is not None else float(last["humidity"]),
                "rain_chance_percent": float(d.get("rain_chance_percent", 0.0)),
            })
    if not out:
        out = [{"date": None,
                "temperature": float(weather_forecast.get("temperature", last["temperature"])),
                "humidity": float(last["humidity"]),
                "rain_chance_percent": float(weather_forecast.get("rain_chance_percent", 0.0))}]
    while len(out) < days:
        out.append(dict(out[-1]))
    for k, o in enumerate(out):
        if o["date"] is None:
            o["date"] = step_date(last.get("timestamp"), k + 1)
    return out[:days]


def build_window(ordered_history, weather_forecast):
    today_rain = float(weather_forecast.get("rain_chance_percent", 0.0))
    rows = [[r["moisture"], r["temperature"], r["humidity"],
             float(r.get("rain_chance_percent", today_rain))] for r in ordered_history]
    if len(rows) < W:
        rows = [rows[0]] * (W - len(rows)) + rows
    return [list(map(float, r)) for r in rows[-W:]]


def _predict(window_rows, outlook_slice):
    past = np.array([window_rows], dtype="float32")
    fut = np.array([[[o["temperature"], o["humidity"], o["rain_chance_percent"]] for o in outlook_slice]],
                   dtype="float32")
    return np.clip(_model([past, fut], training=False).numpy()[0], 0.0, 100.0)


# --------------------------------------------------------------------------------------
# Forecast + digital-twin rollouts
# --------------------------------------------------------------------------------------
def rollout(window_rows, outlook, events=None):
    """
    Forecast moisture for days 1..H. `events` = {origin_day: moisture_points_added}.
    An event at origin o adds water at the end of day o (= irrigation the next morning),
    after which the model is re-run from the rolled-forward state, so the twin responds
    to irrigation through the same learned dynamics.
    """
    events = dict(sorted((events or {}).items()))
    rows = [list(r) for r in window_rows]
    results = [None] * H
    start = 0
    pending = [o for o in events if 0 <= o < H]
    while True:
        if start in events:
            rows[-1][0] = min(100.0, rows[-1][0] + events[start])
        pred = _predict(rows, outlook[start:start + H])
        nxt = next((o for o in pending if o > start), None)
        stop = H if nxt is None else nxt
        for d in range(start + 1, stop + 1):
            results[d - 1] = float(pred[d - start - 1])
        if nxt is None:
            break
        for d in range(start + 1, nxt + 1):
            o = outlook[d - 1]
            rows.append([float(pred[d - start - 1]), o["temperature"], o["humidity"], o["rain_chance_percent"]])
        rows = rows[-W:]
        start = nxt
    # Round ONCE here (1 decimal = what the dashboard shows) so classification, planning and display
    # all use the identical number (e.g. 24.96 is shown as 25.0 AND treated as 25.0 -> "normal").
    return [round(v, 1) for v in results]


def add_interval(forecast_values):
    lower = np.clip(np.array(forecast_values) + _LOWER, 0, 100)
    upper = np.clip(np.array(forecast_values) + _UPPER, 0, 100)
    return [round(float(x), 1) for x in lower], [round(float(x), 1) for x in upper]


def forecast_records(values, outlook, last_ts, with_band=True):
    lo, hi = add_interval(values) if with_band else ([None] * H, [None] * H)
    recs = []
    for k, v in enumerate(values, start=1):
        date = outlook[k - 1]["date"] or step_date(last_ts, k)
        recs.append({
            "step": k, "hours_ahead": k * cfg.STEP_HOURS,
            "date": date, "label": date_label(date) or f"Day +{k}", "weekday": weekday(date),
            "moisture": round(float(v), 1), "lower": lo[k - 1], "upper": hi[k - 1],
            "condition": classify_moisture(v),
            "rain_chance_percent": round(outlook[k - 1]["rain_chance_percent"], 0),
        })
    return recs


def _trend_text(values):
    first_dry = next((k for k, v in enumerate(values, 1) if needs_water(v)), None)
    if first_dry:
        return (f"predicted to reach dry (forecast moisture {values[first_dry - 1]:.1f}% "
                f"in {first_dry} day{'s' if first_dry > 1 else ''})")
    return f"predicted moisture around {values[0]:.1f}% tomorrow and {values[-1]:.1f}% in {H} days"


def predict_trend(sensor_history, weather_forecast, daily_forecast=None):
    """Backward-compatible: same name and keys as every earlier version."""
    if not sensor_history:
        raise ValueError("sensor_history cannot be empty")
    hist = order_history(sensor_history)
    outlook = build_weather_outlook(hist, weather_forecast, daily_forecast)
    values = rollout(build_window(hist, weather_forecast), outlook)
    return {"current_status": legacy_status(hist[-1]["moisture"]), "projected_trend": _trend_text(values)}


SCENARIOS = {"delay_24h", "rain_tomorrow", "reduce_20pct", "irrigate_now"}


def mm_to_points(mm):
    return mm * cfg.APPLICATION_EFFICIENCY * 100.0 / cfg.ROOT_ZONE_DEPTH_MM


def simulate_scenario(sensor_history, weather_forecast, scenario, daily_forecast=None, amount_mm=20.0):
    """
    Digital-twin what-if. Scenarios:
      rain_tomorrow : tomorrow's rain chance forced to 90 %
      reduce_20pct  : current moisture x 0.8 (drier than measured)
      irrigate_now  : apply `amount_mm` of water today
      delay_24h     : apply `amount_mm` of water 24 h from now
    Baseline = do nothing (no irrigation).
    """
    if not sensor_history:
        raise ValueError("sensor_history cannot be empty")
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {sorted(SCENARIOS)}, got '{scenario}'")

    hist = order_history(sensor_history)
    outlook = build_weather_outlook(hist, weather_forecast, daily_forecast)
    window = build_window(hist, weather_forecast)
    last_ts = hist[-1].get("timestamp")

    base = rollout(window, outlook)

    sim_window = [list(r) for r in window]
    sim_outlook = [dict(o) for o in outlook]
    events = {}
    if scenario == "rain_tomorrow":
        sim_outlook[0]["rain_chance_percent"] = 90.0
        sim_outlook[0]["humidity"] = min(98.0, sim_outlook[0]["humidity"] + 8)
    elif scenario == "reduce_20pct":
        sim_window[-1][0] *= 0.8
    elif scenario == "irrigate_now":
        events = {0: mm_to_points(amount_mm)}
    elif scenario == "delay_24h":
        events = {1: mm_to_points(amount_mm)}
    sim = rollout(sim_window, sim_outlook, events)

    # Next-irrigation result for the baseline and the simulated case (hypothetical - never a live sensor result).
    # Planner convention: after an irrigation at origin o, the next one is searched from day o+2.
    from next_irrigation import summarize_values
    origin = next(iter(events), None)
    sim_first_day = 1 if origin is None else origin + 2
    sim_basis = "no_irrigation_applied" if origin is None else "after_simulated_irrigation"
    cur_base, cur_sim = float(hist[-1]["moisture"]), float(sim_window[-1][0])
    base_next = summarize_values(base, outlook, last_ts, 1, "no_irrigation_applied", cur_base, False)
    sim_next = summarize_values(sim, sim_outlook, last_ts, sim_first_day, sim_basis, cur_sim, origin is not None)

    def first_dry(vals):
        return next((k for k, v in enumerate(vals, 1) if needs_water(v)), None)

    return {
        "scenario": scenario,
        "amount_mm": amount_mm if scenario in ("irrigate_now", "delay_24h") else None,
        "baseline": {"current_status": legacy_status(hist[-1]["moisture"]), "projected_trend": _trend_text(base)},
        "simulated": {"current_status": legacy_status(hist[-1]["moisture"]), "projected_trend": _trend_text(sim)},
        "baseline_forecast": forecast_records(base, outlook, last_ts),
        "simulated_forecast": forecast_records(sim, sim_outlook, last_ts),
        "baseline_next_irrigation": base_next,
        "simulated_next_irrigation": sim_next,
        "comparison": {
            "min_moisture_baseline": round(min(base), 1), "min_moisture_simulated": round(min(sim), 1),
            "day7_difference": round(sim[-1] - base[-1], 1),
            "days_to_dry_baseline": first_dry(base),
            "days_to_dry_simulated": first_dry(sim),
        },
    }
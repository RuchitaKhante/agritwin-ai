# analysis_engine.py - the one function /analyze (and the chatbot) call.
# Combines: forecast + decision layer + health/SHAP + advisory, keeping every legacy field.

from datetime import timedelta

from data_utils import order_history, legacy_status, classify_moisture, needs_water, parse_ts
import forecasting_model as fm
from explainability_engine import analyze_soil_health
from decision_layer import build_dashboard_outputs
from advisory_generator import build_advisory
from next_irrigation import build_next_irrigation
import engine_config as cfg


def collect_warnings(hist, daily_forecast):
    """Plain-language notes about inputs that make the output less reliable (never raises)."""
    notes = []
    if len(hist) < cfg.WINDOW:
        notes.append(f"Only {len(hist)} reading(s) supplied; the model expects {cfg.WINDOW}, so the oldest reading is repeated.")
    last_dt = parse_ts(hist[-1].get("timestamp"))
    if last_dt is None:
        notes.append("Timestamps are not ISO-8601, so calendar dates are unavailable (steps are labelled Day +N).")
    latest_m = hist[-1]["moisture"]
    if latest_m >= cfg.SUSPICIOUS_MOISTURE_ABOVE or latest_m <= 0:
        notes.append(f"Latest moisture is {latest_m:.1f}%, which is unusual for field soil; check the sensor calibration "
                     f"(dry/wet reference values, inverted raw readings) or whether the sensor is disconnected/saturated.")
    if not daily_forecast:
        notes.append(f"No daily_forecast supplied: today's weather_forecast is reused for all {cfg.HORIZON} forecast days.")
    else:
        if len(daily_forecast) < cfg.HORIZON:
            notes.append(f"daily_forecast has {len(daily_forecast)} day(s); the last day is repeated up to {cfg.HORIZON}.")
        dates = [parse_ts(d.get("date")) for d in daily_forecast if d.get("date")]
        if dates and last_dt is not None:
            expected = (last_dt + timedelta(hours=cfg.STEP_HOURS)).date()
            if dates[0].date() != expected:
                notes.append(f"daily_forecast starts on {dates[0].date()} but step 1 is +24 h after the latest reading "
                             f"({expected}); the model treats forecast entry 1 as step 1.")
            if any((b.date() - a.date()).days != 1 for a, b in zip(dates, dates[1:])):
                notes.append("daily_forecast dates are not consecutive days; entries are used in the order given.")
    return notes


def analyze(sensor_history, weather_forecast, daily_forecast=None):
    if not sensor_history:
        raise ValueError("sensor_history cannot be empty")
    hist = order_history(sensor_history)
    dash = build_dashboard_outputs(hist, weather_forecast, daily_forecast)
    health = analyze_soil_health(hist, weather_forecast)
    values = dash["_base_values"]
    current = hist[-1]["moisture"]
    if needs_water(current):   # already dry/critical: do not say "predicted to reach dry"
        projected = (f"soil is already {classify_moisture(current)} ({current:.1f}%); without irrigation it is "
                     f"forecast at {values[0]:.1f}% tomorrow and {values[-1]:.1f}% in {len(values)} days")
    else:
        projected = fm._trend_text(values)
    trend = {"current_status": legacy_status(current), "projected_trend": projected}
    advisory = build_advisory(trend, health, dash)

    result = {**trend, **health, **advisory, **dash}
    result.pop("_base_values", None)
    outlook, window = result.pop("_outlook"), result.pop("_window")
    result["warnings"] = collect_warnings(hist, daily_forecast)
    # Future result ("when do I irrigate again?"), kept separate from the current-irrigation fields above.
    result.update(build_next_irrigation(hist, weather_forecast, daily_forecast, outlook, window, values,
                                        dash["irrigation"]["windows"], dash["irrigation"]["notes"], result["warnings"]))
    result["model_info"] = {
        "forecast_model": "multi-horizon LSTM (past window + weather forecast)",
        "horizon_steps": cfg.HORIZON, "step_hours": cfg.STEP_HOURS,
        "date_source": "daily_forecast dates" if daily_forecast and any(d.get("date") for d in daily_forecast)
                       else "latest reading timestamp + 24 h per step",
        "explainability": "SHAP TreeExplainer on a Random Forest urgency model (3 features)",
        "trained_on": "simulated water-balance sequences (not field data)",
        "interval": "80% empirical band from simulated validation residuals",
        "irrigation_depth": "heuristic estimate; depends on assumed root-zone depth",
    }
    return result
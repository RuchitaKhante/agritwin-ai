"""
Gives the chatbot the same live farm data /analyze produces. It calls the shared analysis
function (analysis_engine.analyze) directly - same process, no HTTP.

v2: also exposes the 7-day forecast, days-until-dry/critical and the suggested irrigation
window so the chatbot can answer "when will I need to irrigate?".
Keeps the earlier optional `tomorrow_forecast` argument (third positional parameter).
"""

from datetime import datetime

from analysis_engine import analyze
from data_utils import order_history
from chatbot.hypothetical import extract_hypothetical_moisture, build_hypothetical_lines


def _date_context(latest_timestamp: str) -> tuple[str, str]:
    """
    Returns (today_text, data_age_text). The LLM has no clock, so the server tells it today's date and
    whether the sensor data is old (engine dates are counted from the latest reading, not from today).
    """
    today = datetime.now().date()
    today_text = today.strftime("%A %d %b %Y")
    try:
        last = datetime.fromisoformat(str(latest_timestamp)[:19]).date()
    except ValueError:
        return today_text, "unknown"
    age = (today - last).days
    if age <= 0:
        return today_text, "up to date (latest reading is from today)"
    return today_text, (f"OLD - latest reading is {age} day(s) before today, so all dates below are counted "
                        f"from {last.strftime('%a %d %b')}; tell the farmer the data is {age} day(s) old")


def _weather_note(soil_condition: str, weather: dict) -> str:
    """Plain-language rule result so the LLM never treats rain PROBABILITY as a rain AMOUNT."""
    rain = weather.get("rain_chance_percent")
    temp = weather.get("temperature")
    try:
        rain = float(rain)
    except (TypeError, ValueError):
        return "Rain probability unknown; base the advice on soil moisture."
    note = f"Rain probability {rain:.0f}% (this says nothing about how many mm will fall; the forecast rainfall amount is not available)."
    if rain >= 60:
        if soil_condition == "critical":
            note += " Soil is already CRITICAL, so do NOT postpone irrigation because of rain."
        elif soil_condition == "dry":
            note += (" Soil is dry: do not postpone on probability alone; a delay of up to 24 hours is reasonable only if rain is "
                     "expected within 24 hours and the forecast amount is about 10-15 mm or more.")
        else:
            note += " Soil is not dry: rain may replace the next planned irrigation if the amount turns out large enough; check the sensor after the rain."
    elif rain < 30 and isinstance(temp, (int, float)) and temp >= 35:
        note += " Hot weather with low rain chance increases water use, so irrigation may be needed sooner."
    else:
        note += " No rain-based reason to change the irrigation plan."
    return note


def _next_irrigation_lines(result: dict) -> dict:
    """
    The next-irrigation answer, copied from the analysis result (the SAME object /analyze returns) so the
    chatbot can never contradict the API or the dashboard. Nothing is recomputed here.
    """
    status = result.get("next_irrigation_status", "unavailable")
    date, days = result.get("next_irrigation_date"), result.get("days_until_irrigation")
    xai = result.get("next_irrigation_xai") or {}
    ref = result.get("next_irrigation_reference_date")
    if status == "predicted":
        headline = f"{result['next_irrigation_message']} - date {date or 'unknown (timestamps not ISO)'}"
        if ref:
            headline += f", counted from the latest reading date {ref}"
    elif status == "beyond_forecast_horizon":
        headline = result["next_irrigation_message"] + " Do NOT invent a date."
    else:
        headline = "Not available - ask the farmer to send fresh readings (POST /analyze)."
    basis = {"after_current_irrigation": "after the irrigation recommended now",
             "no_irrigation_needed_now": "no irrigation is needed now, so counted with no irrigation"
             }.get(result.get("next_irrigation_basis"), "unknown")
    after = result.get("moisture_after_current_irrigation")
    factors = " ".join(f.get("detail", "") for f in xai.get("factors", []))
    unc = xai.get("uncertainty") or {}
    if unc.get("earliest_days") is not None:
        later = (f"day +{unc['latest_days']}" if unc.get("latest_days") is not None else "later than the forecast horizon")
        unc_text = f"80% band: trigger reached between day +{unc['earliest_days']} and {later} (simulated-data model)"
    else:
        unc_text = "no trigger crossing inside the 80% band" if status == "beyond_forecast_horizon" else "not available"
    trend = ", ".join(f"{(p['date'] or 'day +' + str(p['step']))}: {p['moisture']}%"
                      for p in result.get("predicted_moisture_trend", []))
    return {
        "NEXT IRRIGATION DATE (server-computed; answers 'when should I irrigate again', 'next irrigation date', 'days left')": headline,
        "Days until next irrigation": days if days is not None else "not predicted",
        "Next irrigation status": status,
        "How the next irrigation day was set": (
            f"soil-category schedule {result['next_irrigation_days_window'][0]}-{result['next_irrigation_days_window'][1]} days "
            f"(forecast alone: {result.get('forecast_days_until_irrigation') if result.get('forecast_days_until_irrigation') is not None else 'no need within 7 days'}; "
            f"day taken from: {result.get('next_irrigation_source')})")
            if result.get("next_irrigation_days_window") else "moisture forecast only",
        "Next irrigation is counted": basis,
        "Moisture right after the current irrigation (estimate)":
            f"{after}%" if after is not None else "not applicable (no irrigation needed now)",
        "Moisture level that triggers the next irrigation":
            f"below {result.get('next_irrigation_trigger_moisture', 25):g}% (soil becomes dry)",
        "WHY the next irrigation is expected then (rule-based, NOT SHAP)":
            (result.get("next_irrigation_reason", "") + " " + factors).strip(),
        "Next irrigation uncertainty": unc_text,
        "Rain effect on the next irrigation date": (xai.get("rain_effect") or {}).get("text", "not available"),
        "Predicted moisture path (no irrigation after the first one)": trend or "not available",
    }


def get_live_data(sensor_history: list[dict], weather_forecast: dict,
                  tomorrow_forecast: dict | None = None, daily_forecast: list[dict] | None = None,
                  question: str | None = None) -> dict:
    """
    Runs the same analysis /analyze runs, and reshapes the result into a flat dict
    formatted for the chatbot prompt.
    """
    result = analyze(sensor_history, weather_forecast, daily_forecast)

    # Latest reading by timestamp (works for oldest-first or newest-first input).
    latest_reading = order_history(sensor_history)[-1]

    forecast_text = ", ".join(
        f"{(f['date'] or 'day ' + str(f['step']))}: {f['moisture']}%" for f in result["forecast"][:7]
    )
    windows = result["irrigation"]["windows"]
    if windows:
        w = windows[0]
        when = "now" if w["day_offset"] == 0 else f"{w['label']} {w['start']}-{w['end']}"
        window_text = f"{when}, about {w['depth_mm']['min']:.0f}-{w['depth_mm']['max']:.0f} mm (estimate)"
    else:
        window_text = "none needed in the forecast period"
    t_dry, t_crit = result["time_to_dry"], result["time_to_critical"]

    # One plain-language action line, derived from the engine's own decision (never invented by the LLM).
    if windows and windows[0]["day_offset"] == 0:
        action = f"Irrigate NOW, about {w['depth_mm']['min']:.0f}-{w['depth_mm']['max']:.0f} mm (estimate)."
    elif windows:
        action = f"Irrigate later - {w['label']} {w['start']}-{w['end']}, about {w['depth_mm']['min']:.0f}-{w['depth_mm']['max']:.0f} mm (estimate)."
    else:
        action = "No irrigation needed in the forecast period."

    # Separate, clearly labelled lines so the bot can never confuse "next irrigation" with "the one after that".
    next_line = windows[0]["display"] if windows else "none needed in the forecast period"
    second_line = windows[1]["display"] if len(windows) > 1 else "none planned in the forecast period"
    later_line = " | ".join(win["display"] for win in windows[2:]) or "none"

    today_text, data_age_text = _date_context(latest_reading.get("timestamp", ""))
    weather_note = _weather_note(result["soil_condition"], weather_forecast)

    live_data = {
        "Today's date (server clock)": today_text,
        "Sensor data freshness": data_age_text,
        "RECOMMENDED ACTION (from analysis engine)": action,
        "NEXT irrigation (the answer to 'when should I irrigate', 'next' and 'today')": next_line,
        "SECOND scheduled irrigation (the engine's own schedule; NOT the next-irrigation date)": second_line,
        "Any later irrigations": later_line,
        **_next_irrigation_lines(result),
        "Latest sensor reading time": latest_reading.get("timestamp", "unknown"),
        "Soil moisture": f"{latest_reading.get('moisture', 'unknown')}%",
        "Soil condition": result["soil_condition"],
        "Temperature": f"{latest_reading.get('temperature', 'unknown')}°C",
        "Humidity": f"{latest_reading.get('humidity', 'unknown')}%",
        "Rain probability": f"{weather_forecast.get('rain_chance_percent', 'unknown')}%",
        "Soil health score": result.get("soil_health_score", "unknown"),
        "Crop stress": result.get("crop_stress", "unknown"),
        "Projected moisture trend": result.get("projected_trend", "unknown"),
        "Forecast moisture (no irrigation)": forecast_text,
        "Days until soil becomes dry": t_dry["steps"] if t_dry else "not within forecast period",
        "Days until soil becomes critical": t_crit["steps"] if t_crit else "not within forecast period",
        "Suggested irrigation window": window_text,
        "Weather decision note": weather_note,
        "Water stress alert": result["water_stress_alert"]["message"],
        "Current advisory": result.get("advisory", "unknown"),
    }

    # Hidden numeric value (keys starting with "_" are not printed in the prompt) used by the water calculator.
    if windows:
        live_data["_depth_mm"] = dict(windows[0]["depth_mm"])

    # What-if question ("if my moisture is 10%..."): add clearly labelled HYPOTHETICAL lines; real data is untouched.
    if question:
        what_if = extract_hypothetical_moisture(question)
        if what_if is not None:
            live_data.update(build_hypothetical_lines(what_if, sensor_history, weather_forecast, daily_forecast))

    if tomorrow_forecast:
        live_data["Tomorrow's temperature"] = f"{tomorrow_forecast.get('temperature', 'unknown')}°C"
        live_data["Tomorrow's rain probability"] = f"{tomorrow_forecast.get('rain_chance_percent', 'unknown')}%"

    return live_data
"""
"If my moisture is 10%, what should I do?"  - what-if answers for the chatbot.

The farmer's REAL data is never changed. For a what-if question we run the SAME analysis engine
(analysis_engine.analyze) on a copy of the latest stored history in which the moisture is assumed to have
been steady at the asked value (temperature, humidity, timestamps and the weather forecast stay real).
The result is added to the chat context under clearly labelled HYPOTHETICAL keys.
"""

import re

from analysis_engine import analyze

_IF_WORDS = re.compile(r"\b(if|suppose|supposing|assuming|what would)\b", re.I)
_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|percent|per cent)", re.I)
_MOISTURE_NUM = re.compile(r"(?:moisture|soil)[^0-9]{0,25}?(\d{1,3}(?:\.\d+)?)", re.I)


def extract_hypothetical_moisture(question: str) -> float | None:
    """Returns the asked moisture (0-100) for 'if my moisture is X%' style questions, else None."""
    if not question or not _IF_WORDS.search(question):
        return None
    m = _PCT.search(question) or _MOISTURE_NUM.search(question)
    if not m:
        return None
    value = float(m.group(1))
    return value if 0 <= value <= 100 else None


def _action(result: dict) -> str:
    windows = result["irrigation"]["windows"]
    if not windows:
        return "No irrigation needed in the forecast period."
    w = windows[0]
    mm = f"about {w['depth_mm']['min']:.0f}-{w['depth_mm']['max']:.0f} mm (estimate)"
    if w["day_offset"] == 0:
        return f"Irrigate NOW, {mm}."
    return f"Irrigate later - {w['label']} {w['start']}-{w['end']}, {mm}."


def build_hypothetical_lines(moisture: float, sensor_history: list[dict], weather_forecast: dict,
                             daily_forecast: list[dict] | None = None) -> dict:
    what_if_history = [dict(r, moisture=moisture) for r in sensor_history]
    r = analyze(what_if_history, weather_forecast, daily_forecast)
    return {
        "HYPOTHETICAL what-if (NOT the farm's real reading)":
            f"moisture assumed steady at {moisture:g}% (temperature, humidity and weather forecast are the real ones)",
        "HYPOTHETICAL soil condition": r["soil_condition"],
        "HYPOTHETICAL recommended action now": _action(r),
        "HYPOTHETICAL moisture right after that irrigation (estimate)":
            (f"{r['moisture_after_current_irrigation']}%" if r["moisture_after_current_irrigation"] is not None
             else "not applicable (no irrigation needed now)"),
        "HYPOTHETICAL next irrigation": r["next_irrigation_message"],
        "HYPOTHETICAL next irrigation date": r["next_irrigation_date"] or "not predicted",
        "HYPOTHETICAL days until next irrigation":
            r["days_until_irrigation"] if r["days_until_irrigation"] is not None else "not predicted",
        "HYPOTHETICAL why (rule-based, NOT SHAP)": r["next_irrigation_reason"],
    }
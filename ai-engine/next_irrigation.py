# next_irrigation.py
#
# Answers: "If I irrigate now (or, when no irrigation is needed now, if I wait), WHEN do I need to irrigate again?"
#
# Nothing here invents a number. Everything is derived from the objects the engine already produces:
#   * the LSTM moisture forecast / digital-twin rollout   (forecasting_model.rollout)
#   * the irrigation planner's windows                      (decision_layer.plan_irrigation)
#   * the configured trigger                                (engine_config.NORMAL_MIN -> "soil needs water below 25 %")
#
# Date convention (same as the existing planner): forecast step k is the calendar day
# (date of latest reading + k days, or the daily_forecast date for entry k). Irrigation is scheduled on the
# MORNING of the first day whose forecast moisture is below the trigger, skipping rain-likely days.
# `days_until_irrigation` is counted from the date of the LATEST SENSOR READING (returned as
# `next_irrigation_reference_date`), so the date and the day count always agree.
#
# The explanation is RULE-BASED (threshold crossing on the forecast). It is NOT SHAP: the SHAP model in
# explainability_engine.py explains today's urgency from 3 features and has no notion of "days until irrigation".

from datetime import date as _date

import engine_config as cfg
import forecasting_model as fm
from data_utils import classify_moisture, needs_water, parse_ts, date_label

H = cfg.HORIZON
TRIGGER = cfg.NORMAL_MIN          # soil "needs water" below this (dry/critical)

STATUS_PREDICTED = "predicted"
STATUS_BEYOND = "beyond_forecast_horizon"
STATUS_UNAVAILABLE = "unavailable"

SHAP_NOTE = ("This explanation is rule-based (it follows the moisture forecast until it crosses the irrigation "
             "trigger). It is not a SHAP result: the SHAP model only explains today's urgency and does not "
             "model the number of days until the next irrigation.")


# --------------------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------------------
def _reference_date(hist):
    dt = parse_ts(hist[-1].get("timestamp"))
    return dt.date().isoformat() if dt is not None else None


def _days_from_reference(date_str, reference, step):
    """Calendar days between the reference date and `date_str`; falls back to the forecast step."""
    if date_str and reference:
        try:
            d = (_date.fromisoformat(date_str) - _date.fromisoformat(reference)).days
            if d >= 1:
                return d
        except ValueError:
            pass
    return step


def _plural(n):
    return f"{n} day{'' if n == 1 else 's'}"


def find_next_need(values, outlook, first_day):
    """
    Same rule the irrigation planner uses (decision_layer.plan_irrigation):
    first forecast day >= first_day with moisture below the trigger, then moved past rain-likely days.
    Returns (crossing_day, irrigation_day) or None when the trigger is not reached within the horizon.
    """
    crossing = next((k for k in range(first_day, H + 1) if needs_water(values[k - 1])), None)
    if crossing is None:
        return None
    d = crossing
    while 1 <= d <= H - 1 and outlook[d - 1]["rain_chance_percent"] >= cfg.RAIN_SKIP_PERCENT:
        d += 1
    return (crossing, d) if d <= H else None


def category_window(current_moisture):
    """(min_days, max_days) allowed for the next irrigation for the CURRENT soil category, or None if disabled."""
    if not cfg.USE_CATEGORY_WINDOW:
        return None
    return cfg.NEXT_IRRIGATION_DAYS.get(classify_moisture(current_moisture))


def apply_window(window_days, forecast_days):
    """Clamp the forecast day into the category window. No forecast crossing -> latest day of the window."""
    lo, hi = window_days
    final = hi if forecast_days is None else min(max(forecast_days, lo), hi)
    return final, ("forecast" if final == forecast_days else "category_window")


def unavailable(reason, required_now=None):
    return {
        "next_irrigation_status": STATUS_UNAVAILABLE,
        "next_irrigation_date": None,
        "days_until_irrigation": None,
        "next_irrigation_reference_date": None,
        "next_irrigation_basis": None,
        "irrigation_required_now": required_now,
        "moisture_after_current_irrigation": None,
        "next_irrigation_trigger_moisture": TRIGGER,
        "next_irrigation_message": "Next irrigation could not be predicted.",
        "next_irrigation_reason": reason,
        "next_irrigation_xai": {"method": "rule_based_threshold_crossing", "is_shap": False,
                                "summary": reason, "factors": [], "shap_note": SHAP_NOTE},
        "predicted_moisture_trend": [],
    }


# --------------------------------------------------------------------------------------------------
# /analyze
# --------------------------------------------------------------------------------------------------
def build_next_irrigation(hist, weather_forecast, daily_forecast, outlook, window, base, windows, notes, warnings):
    """
    hist/outlook/window/base/windows come straight from decision_layer.build_dashboard_outputs, so this is
    the SAME forecast and schedule the rest of the response is built from. Never raises (returns 'unavailable').
    """
    try:
        return _build(hist, outlook, window, base, windows, notes, warnings)
    except Exception as exc:   # never let the add-on break /analyze
        return unavailable(f"Next irrigation could not be calculated ({type(exc).__name__}).")


def _build(hist, outlook, window, base, windows, notes, warnings):
    last_ts = hist[-1].get("timestamp")
    current = float(hist[-1]["moisture"])
    reference = _reference_date(hist)
    immediate = bool(windows) and windows[0]["day_offset"] == 0

    if immediate:
        first = windows[0]
        nxt = windows[1] if len(windows) > 1 else None
        events = {0: first["points_added"]}
        trajectory = fm.rollout(window, outlook, events)     # ONLY the current irrigation, nothing later
        after = first["moisture_after"]
        first_day = 2                                          # planner rule: next irrigation is on a later day
        basis = "after_current_irrigation"
    else:
        nxt = windows[0] if windows else None
        events, trajectory, after, first_day = {}, list(base), None, 1
        basis = "no_irrigation_needed_now"

    lower, upper = fm.add_interval(trajectory)
    recs = fm.forecast_records(trajectory, outlook, last_ts)

    out = {
        "next_irrigation_reference_date": reference,
        "next_irrigation_basis": basis,
        "irrigation_required_now": immediate,
        "moisture_after_current_irrigation": after,
        "next_irrigation_trigger_moisture": TRIGGER,
    }

    # ---------------------------------------------------------------- status / date / days
    # 1) what the moisture forecast alone says (existing planner logic)
    if nxt is None:
        f_status, f_step, f_days = STATUS_BEYOND, None, None
    else:
        f_status, f_step = STATUS_PREDICTED, nxt["day_offset"]
        f_days = _days_from_reference(nxt["date"], reference, f_step)

    # 2) category window: critical/dry 1-2 days, normal 3-4 days, wet 5-6 days (engine_config.NEXT_IRRIGATION_DAYS)
    win = category_window(current)
    source = "forecast"
    if win:
        step, source = apply_window(win, f_days)
        status = STATUS_PREDICTED
        date = outlook[step - 1]["date"]
        days = _days_from_reference(date, reference, step)
    elif nxt is None:
        status, step, date, days = STATUS_BEYOND, None, None, None
    else:
        status, step, date, days = f_status, f_step, nxt["date"], f_days

    if status == STATUS_PREDICTED:
        lbl = date_label(date)
        message = f"Next irrigation in {_plural(days)}" + (f" ({lbl})" if lbl else "")
    else:
        where = "after the current irrigation " if immediate else ""
        message = (f"No further irrigation expected within the {H}-day forecast {where}"
                   f"(lowest forecast {min(trajectory):.1f}%, trigger {TRIGGER:.0f}%).").replace("  ", " ")

    out.update({"next_irrigation_status": status, "next_irrigation_date": date,
                "days_until_irrigation": days, "next_irrigation_message": message,
                "forecast_days_until_irrigation": f_days,
                "next_irrigation_days_window": list(win) if win else None,
                "next_irrigation_source": source})
    policy = {"condition": classify_moisture(current), "window": list(win) if win else None,
              "forecast_days": f_days, "source": source}

    # ---------------------------------------------------------------- trend (marks the irrigation day)
    for r in recs:
        r["is_next_irrigation_day"] = step is not None and r["step"] == step
        r["below_trigger"] = needs_water(r["moisture"])
    out["predicted_moisture_trend"] = recs

    # ---------------------------------------------------------------- uncertainty (80 % residual band)
    lo_cross = next((k for k in range(first_day, H + 1) if needs_water(lower[k - 1])), None)
    hi_cross = next((k for k in range(first_day, H + 1) if needs_water(upper[k - 1])), None)
    uncertainty = {
        "basis": "80% empirical band from simulated validation residuals (not field data)",
        "earliest_days": lo_cross,
        "latest_days": hi_cross,
        "latest_beyond_horizon": hi_cross is None,
        "note": "Range of days at which the moisture band crosses the trigger; it ignores rain postponement.",
    }

    # ---------------------------------------------------------------- weather sensitivity (digital-twin what-if)
    rain_effect = _rain_effect(window, outlook, events, first_day, f_step, f_status, hist)

    # ---------------------------------------------------------------- explanation
    crossing = next((k for k in range(first_day, H + 1) if needs_water(trajectory[k - 1])), None)
    factors = _factors(current, immediate, windows, after, trajectory, recs, status, step, date, crossing,
                       outlook, notes, rain_effect, f_status, f_step, policy)
    summary = _summary(status, immediate, current, after, date, days, crossing, trajectory, policy)
    conf = _confidence(warnings, hist, uncertainty)

    out["next_irrigation_reason"] = summary
    out["next_irrigation_xai"] = {
        "method": "rule_based_threshold_crossing",
        "is_shap": False,
        "summary": summary,
        "factors": factors,
        "trigger_moisture_percent": TRIGGER,
        "trigger_condition": "dry (soil needs water below this level)",
        "trend_basis": ("forecast after the current irrigation, with no further irrigation" if immediate
                        else "forecast with no irrigation"),
        "forecast_horizon_days": H,
        "uncertainty": uncertainty,
        "rain_effect": rain_effect,
        "confidence_notes": conf,
        "shap_note": SHAP_NOTE,
    }
    return out


def _rain_effect(window, outlook, events, first_day, step, status, hist):
    """Re-runs the SAME twin with every rain chance set to 0 % and reports whether the date would move."""
    try:
        dry_outlook = [dict(o, rain_chance_percent=0.0) for o in outlook]
        dry_traj = fm.rollout(window, dry_outlook, events)
        hit = find_next_need(dry_traj, dry_outlook, first_day)
        dry_step = hit[1] if hit else None
    except Exception:
        return None
    rainy = [o for k, o in enumerate(outlook[:H], 1)
             if o["rain_chance_percent"] >= cfg.RAIN_SKIP_PERCENT and (step is None or k <= step)]
    if dry_step is None and step is None:
        text = "Rain chances in the forecast do not change the result: irrigation is not needed within the horizon either way."
    elif step is None:
        text = (f"Rain in the forecast is what keeps irrigation beyond the {H}-day horizon; with 0% rain chance the model "
                f"would expect irrigation on day +{dry_step}.")
    elif dry_step is None:
        text = (f"With 0% rain chance the model would not need irrigation within {H} days, so the date does not move "
                f"earlier because of rain.")
    elif dry_step == step:
        text = "Changing the forecast rain chances to 0% would not move the date in this model."
    else:
        diff = dry_step - step
        text = (f"With 0% rain chance everywhere the model would put the next irrigation on day +{dry_step} instead of "
                f"day +{step} ({abs(diff)} day{'s' if abs(diff) != 1 else ''} {'later' if diff > 0 else 'earlier'}).")
    return {
        "dry_weather_what_if_day": dry_step,
        "rain_likely_days_before_irrigation": [o["date"] or f"day +{k}" for k, o in enumerate(outlook[:H], 1)
                                               if o["rain_chance_percent"] >= cfg.RAIN_SKIP_PERCENT
                                               and (step is None or k <= step)],
        "text": text + " Rain chance is a probability, not an amount; check the sensor after real rain.",
        "method": "digital-twin what-if (all rain chances set to 0%); not SHAP",
    }


def _factors(current, immediate, windows, after, trajectory, recs, status, step, date, crossing, outlook, notes, rain_effect,
             f_status=None, f_step=None, policy=None):
    f = []
    f.append({"factor": "current_moisture",
              "detail": f"Soil moisture now is {current:.1f}% ({classify_moisture(current)})."})
    if immediate:
        w = windows[0]
        f.append({"factor": "current_irrigation",
                  "detail": (f"Irrigating now (about {w['depth_mm']['estimate']:.0f} mm, estimate) is modelled to raise "
                             f"moisture from {w['moisture_before']:.1f}% to about {after:.1f}%.")})
        if needs_water(trajectory[0]):
            f.append({"factor": "irrigation_cap",
                      "detail": (f"One irrigation is capped at {cfg.MAX_DEPTH_PER_EVENT_MM:.0f} mm, so moisture is still "
                                 f"below {TRIGGER:.0f}% tomorrow ({trajectory[0]:.1f}%); a follow-up irrigation is needed soon.")})
    else:
        f.append({"factor": "no_irrigation_now",
                  "detail": f"No irrigation is needed now; the forecast below assumes no irrigation."})
    path_to = (step if step else H)
    path = ", ".join(f"{(r['date'] or 'day +' + str(r['step']))}: {r['moisture']:.1f}%" for r in recs[:path_to])
    f.append({"factor": "moisture_path", "detail": f"Forecast moisture: {path}."})
    if crossing is not None:
        f.append({"factor": "trigger",
                  "detail": (f"The forecast first falls below the {TRIGGER:.0f}% trigger on "
                             f"{(recs[crossing - 1]['date'] or 'day +' + str(crossing))} ({trajectory[crossing - 1]:.1f}%).")})
    else:
        f.append({"factor": "trigger",
                  "detail": f"The forecast stays at or above the {TRIGGER:.0f}% trigger for all {H} days (lowest {min(trajectory):.1f}%)."})
    if f_status == STATUS_PREDICTED and crossing is not None and f_step != crossing:
        f.append({"factor": "rain_postponement",
                  "detail": (f"Irrigation is moved from day +{crossing} to day +{f_step} because the rain chance on the "
                             f"skipped day(s) is {cfg.RAIN_SKIP_PERCENT:.0f}% or more.")})
    horizon = outlook[:path_to]
    avg_t = sum(o["temperature"] for o in horizon) / len(horizon)
    max_rain = max(o["rain_chance_percent"] for o in horizon)
    f.append({"factor": "weather",
              "detail": f"Forecast average temperature {avg_t:.1f}°C; highest rain chance {max_rain:.0f}% over this period."})
    if rain_effect:
        f.append({"factor": "rain_effect", "detail": rain_effect["text"]})
    if policy and policy["window"]:
        lo, hi = policy["window"]
        fd = policy["forecast_days"]
        fc = f"the moisture forecast alone gives day +{fd}" if fd is not None else \
             f"the moisture forecast alone gives no irrigation within {H} days"
        f.append({"factor": "category_window",
                  "detail": (f"Soil category '{policy['condition']}' uses a {lo}-{hi} day schedule; {fc}, "
                             + ("which is inside the window, so it is used as is." if policy["source"] == "forecast"
                                else f"so the next irrigation is set to day +{step} (inside the window)."))})
    return f


def _summary(status, immediate, current, after, date, days, crossing, trajectory, policy=None):
    lead = (f"Irrigating now should lift moisture from {current:.1f}% to about {after:.1f}%. " if immediate
            else f"No irrigation is needed now (soil {current:.1f}%, {classify_moisture(current)}). ")
    if status == STATUS_PREDICTED and policy and policy["window"]:
        lo, hi = policy["window"]
        where = f"on {date} " if date else ""
        fd = policy["forecast_days"]
        if policy["source"] == "forecast":
            why = f"The forecast agrees with the {policy['condition']}-soil schedule of {lo}-{hi} days"
        else:
            fc = f"the forecast alone gives day +{fd}" if fd is not None else f"the forecast shows no need within {H} days"
            why = f"{fc[0].upper() + fc[1:]}, but {policy['condition']} soil follows a {lo}-{hi} day schedule"
        return lead + f"{why}, so the next irrigation is expected {where}(in {_plural(days)})."
    if status == STATUS_PREDICTED:
        where = f"on {date} " if date else ""
        return (lead + f"The forecast then dries the soil below the {TRIGGER:.0f}% trigger, so the next irrigation is "
                       f"expected {where}(in {_plural(days)}).")
    return lead + (f"The forecast stays above the {TRIGGER:.0f}% trigger for the whole {H}-day forecast "
                   f"(lowest {min(trajectory):.1f}%), so no date can be given: the next irrigation is beyond the forecast horizon.")


def _confidence(warnings, hist, uncertainty):
    notes = list(warnings or [])
    notes.append("Forecast model is trained on simulated water-balance data, not field data.")
    if uncertainty["earliest_days"] is not None and uncertainty["latest_days"] is not None \
            and uncertainty["earliest_days"] != uncertainty["latest_days"]:
        notes.append(f"Within the 80% band the trigger could be reached between day +{uncertainty['earliest_days']} "
                     f"and day +{uncertainty['latest_days']}.")
    return notes


# --------------------------------------------------------------------------------------------------
# /simulate (hypothetical - kept separate from live results)
# --------------------------------------------------------------------------------------------------
def summarize_values(values, outlook, last_ts, first_day, basis, current_moisture, irrigation_applied):
    """Compact next-irrigation result for a simulated trajectory (used by /simulate)."""
    ref = _date.fromisoformat(last_ts[:10]).isoformat() if parse_ts(last_ts) is not None else None
    hit = find_next_need(values, outlook, first_day)
    required_now = needs_water(current_moisture)
    if required_now and not irrigation_applied:
        # nothing was applied in this scenario and the soil is already below the trigger: irrigation is needed now
        return {"status": "required_now", "date": ref, "days_until_irrigation": 0, "basis": basis,
                "irrigation_required_now": True, "trigger_moisture": TRIGGER,
                "message": f"Irrigation is already required now in this scenario (soil below {TRIGGER:.0f}%)."}
    f_days = _days_from_reference(outlook[hit[1] - 1]["date"], ref, hit[1]) if hit else None
    win = category_window(current_moisture)          # same category window as /analyze
    source = "forecast"
    if win:
        step, source = apply_window(win, f_days)
    elif hit is None:
        return {"status": STATUS_BEYOND, "date": None, "days_until_irrigation": None, "basis": basis,
                "irrigation_required_now": required_now, "trigger_moisture": TRIGGER,
                "message": f"No irrigation expected within the {H}-day forecast in this scenario."}
    else:
        step = hit[1]
    date = outlook[step - 1]["date"]
    days = _days_from_reference(date, ref, step)
    lbl = date_label(date)
    return {"status": STATUS_PREDICTED, "date": date, "days_until_irrigation": days, "basis": basis,
            "irrigation_required_now": required_now, "trigger_moisture": TRIGGER,
            "forecast_days_until_irrigation": f_days, "next_irrigation_days_window": list(win) if win else None,
            "source": source,
            "message": f"Next irrigation in {_plural(days)}" + (f" ({lbl})" if lbl else "")}
# decision_layer.py
# Turns the moisture forecast into dashboard-ready decisions: soil condition, time-to-dry /
# time-to-critical, water-stress outlook, irrigation windows + depth, stress alert.
# All logic is rule-based and uses thresholds from engine_config.py. ADVISORY ONLY.

import engine_config as cfg
from data_utils import classify_moisture, needs_water, is_critical, stress_level, step_date, day_label, date_label, weekday
import forecasting_model as fm


def _first_step(values, predicate):
    """First forecast step (1-based) whose moisture satisfies `predicate`, else None."""
    return next((k for k, v in enumerate(values, 1) if predicate(v)), None)


def time_to(values, predicate, outlook, last_ts, current=None):
    """
    Days until the soil first satisfies `predicate` (needs_water / is_critical).
    steps == 0 means it ALREADY does now; None means it never does within the forecast horizon.
    """
    if current is not None and predicate(current):
        return {"steps": 0, "hours": 0, "date": step_date(last_ts, 0), "moisture": round(current, 1)}
    k = _first_step(values, predicate)
    if k is None:
        return None
    return {"steps": k, "hours": k * cfg.STEP_HOURS, "date": outlook[k - 1]["date"] or step_date(last_ts, k),
            "moisture": round(values[k - 1], 1)}


def water_stress_outlook(values, outlook, last_ts):
    out = []
    for k, v in enumerate(values, 1):
        date = outlook[k - 1]["date"] or step_date(last_ts, k)
        out.append({"step": k, "date": date, "label": date_label(date) or f"Day +{k}", "weekday": weekday(date),
                    "moisture": round(v, 1), "level": stress_level(v)})
    return out


def window_display(d, date, start, end, mm_min, mm_max):
    """Ready-to-show text for the dashboard list, e.g. 'Tomorrow, Wed 07 Oct, 06:00-09:00 | 17-22 mm'."""
    dl = date_label(date)
    if d == 0:
        when = "Now (today" + (f", {dl}" if dl else "") + ")"
    elif d == 1:
        when = "Tomorrow" + (f", {dl}" if dl else "") + f", {start}\u2013{end}"
    else:
        when = (dl or f"Day +{d}") + f", {start}\u2013{end}"
    return f"{when} \u00b7 {mm_min:.0f}\u2013{mm_max:.0f} mm"


def plan_irrigation(window, outlook, baseline, current_moisture, last_ts):
    """
    Greedy plan: irrigate on the morning of the first day the soil is predicted to fall below the
    'normal' threshold (or today if it already is), skip rain-likely days, then use the twin to
    re-forecast with that irrigation and look for the next need. Max MAX_IRRIGATION_EVENTS windows.
    """
    events, windows, notes = {}, [], []
    current = list(baseline)
    search_after = 0
    last_origin = -1          # a new irrigation must start at a LATER day than the previous one
    for _ in range(cfg.MAX_IRRIGATION_EVENTS):
        if not windows and needs_water(current_moisture):
            d = 0
        else:
            first_day = max(search_after + 1, last_origin + 2)
            s = next((k for k in range(first_day, cfg.HORIZON + 1) if needs_water(current[k - 1])), None)
            if s is None:
                break
            d = s
        d_orig = d
        while d <= cfg.HORIZON - 1 and d >= 1 and outlook[d - 1]["rain_chance_percent"] >= cfg.RAIN_SKIP_PERCENT:
            d += 1
        if d != d_orig:
            notes.append(f"Irrigation moved from day +{d_orig} to day +{d} because rain chance is "
                         f"{outlook[d_orig - 1]['rain_chance_percent']:.0f}%.")
        if d > cfg.HORIZON:
            break
        origin = max(0, d - 1)
        before = current_moisture if origin == 0 else current[origin - 1]
        max_pts = cfg.MAX_DEPTH_PER_EVENT_MM * cfg.APPLICATION_EFFICIENCY * 100.0 / cfg.ROOT_ZONE_DEPTH_MM
        pts = min(max(0.0, cfg.TARGET_MOISTURE - before), max_pts)
        if pts < 1.0:
            break
        mm = pts * cfg.ROOT_ZONE_DEPTH_MM / 100.0 / cfg.APPLICATION_EFFICIENCY
        pred_d = current[d - 1] if d >= 1 else current_moisture
        events[origin] = events.get(origin, 0.0) + pts
        current = fm.rollout(window, outlook, events)
        date = step_date(last_ts, 0) if d == 0 else (outlook[d - 1]["date"] or step_date(last_ts, d))
        start = "now" if d == 0 else cfg.IRRIGATION_WINDOW[0]
        end = None if d == 0 else cfg.IRRIGATION_WINDOW[1]
        mm_min = round(mm * (1 - cfg.DEPTH_RANGE_PCT), 0)
        mm_max = round(min(mm * (1 + cfg.DEPTH_RANGE_PCT), cfg.MAX_DEPTH_PER_EVENT_MM), 0)
        windows.append({
            "day_offset": d, "date": date, "date_label": date_label(date), "label": day_label(date, d),
            "start": start, "end": end,
            "display": window_display(d, date, start, end, mm_min, mm_max),
            "depth_mm": {"estimate": round(mm, 0), "min": mm_min, "max": mm_max},
            "moisture_before": round(before, 1),
            # additive fields (used by next_irrigation.py): estimated moisture right after this irrigation
            # (before the next day's drying) and the moisture points added to the model state
            "moisture_after": round(min(100.0, before + pts), 1),
            "points_added": round(pts, 3),
            "reason": ("soil already below the normal range" if d == 0 else
                       f"soil predicted to fall to {pred_d:.1f}% ({classify_moisture(pred_d)}) "
                       f"{'without another irrigation' if windows else 'without irrigation'}"),
        })
        search_after = d
        last_origin = origin
    return windows, current, notes


def build_dashboard_outputs(hist, weather_forecast, daily_forecast=None):
    """Everything the dashboard needs beyond the legacy fields."""
    last_ts = hist[-1].get("timestamp")
    current_moisture = float(hist[-1]["moisture"])
    outlook = fm.build_weather_outlook(hist, weather_forecast, daily_forecast)
    window = fm.build_window(hist, weather_forecast)

    base = fm.rollout(window, outlook)
    windows, planned, notes = plan_irrigation(window, outlook, base, current_moisture, last_ts)

    t_dry = time_to(base, needs_water, outlook, last_ts, current_moisture)
    t_crit = time_to(base, is_critical, outlook, last_ts, current_moisture)
    cond_now = classify_moisture(current_moisture)

    soon = needs_water(current_moisture) or (t_dry is not None and t_dry["steps"] <= 2)

    # Alerts look at the FORECAST (first future day that is critical / dry), independent of today's state.
    fc_crit = _first_step(base, is_critical)
    fc_dry = _first_step(base, needs_water)
    already_critical = is_critical(current_moisture)
    if fc_crit is not None and fc_crit <= 2:
        alert = {"active": True, "severity": "severe", "in_days": fc_crit,
                 "message": f"Severe moisture depletion predicted within {fc_crit * cfg.STEP_HOURS} hours.",
                 "already_critical": already_critical,
                 "detail": f"Soil is already critical ({current_moisture:.1f}%)." if already_critical else None}
    elif already_critical:
        alert = {"active": True, "severity": "severe", "in_days": 0,
                 "message": "Soil moisture is already critical.",
                 "already_critical": True, "detail": None}
    elif needs_water(current_moisture):
        alert = {"active": True, "severity": "moderate", "in_days": 0, "message": "Soil is currently dry.",
                 "already_critical": False, "detail": None}
    elif fc_dry is not None and fc_dry <= 2:
        alert = {"active": True, "severity": "moderate", "in_days": fc_dry,
                 "message": "Soil will become dry within 2 days.", "already_critical": False, "detail": None}
    else:
        alert = {"active": False, "severity": "none", "in_days": None, "message": "No water stress predicted.",
                 "already_critical": False, "detail": None}

    urgency = "now" if needs_water(current_moisture) else ("soon" if soon else ("later" if windows else "none"))
    return {
        "soil_condition": cond_now,
        "current_moisture": round(current_moisture, 1),
        "step_hours": cfg.STEP_HOURS,
        "thresholds": {"critical_below": cfg.CRITICAL_BELOW, "dry_below": cfg.NORMAL_MIN, "wet_above": cfg.WET_ABOVE},
        "forecast": fm.forecast_records(base, outlook, last_ts),
        "forecast_with_plan": [round(v, 1) for v in planned],
        "time_to_dry": t_dry,
        "time_to_critical": t_crit,
        "water_stress_outlook": water_stress_outlook(base, outlook, last_ts),
        "water_stress_alert": alert,
        "irrigation": {"needed": bool(windows), "urgency": urgency, "windows": windows, "notes": notes,
                       "assumptions": {"root_zone_depth_mm": cfg.ROOT_ZONE_DEPTH_MM,
                                       "target_moisture": cfg.TARGET_MOISTURE,
                                       "efficiency": cfg.APPLICATION_EFFICIENCY}},
        "weather_outlook": outlook[:cfg.HORIZON],
        "_base_values": base,
        "_outlook": outlook,    # hidden helpers for next_irrigation.py (removed by analysis_engine)
        "_window": window,
    }
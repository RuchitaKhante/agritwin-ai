# data_utils.py
# Small shared helpers: ordering sensor readings and turning thresholds into condition labels.

from datetime import datetime, timedelta
import engine_config as cfg


def parse_ts(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def order_history(sensor_history):
    """
    Returns readings OLDEST-FIRST. Sorts by timestamp when every timestamp parses as ISO
    (so newest-first input is handled); otherwise keeps the order given.
    This fixes the earlier mismatch where some modules sorted and others assumed order.
    """
    rows = [dict(r) for r in sensor_history]
    stamps = [parse_ts(r.get("timestamp")) for r in rows]
    if rows and all(s is not None for s in stamps):
        stamps = [s.replace(tzinfo=None) for s in stamps]
        rows = [r for _, r in sorted(zip(stamps, rows), key=lambda p: p[0])]
    return rows


def classify_moisture(moisture):
    """
    THE single place where soil moisture is turned into a condition (thresholds from engine_config):
        moisture < 15            -> "critical"
        15 <= moisture < 25      -> "dry"
        25 <= moisture <= 35     -> "normal"
        moisture > 35            -> "wet"
    Every other module (forecast, water stress, irrigation planner, alerts, advisory) calls this.
    """
    if moisture < cfg.CRITICAL_BELOW:
        return "critical"
    if moisture < cfg.NORMAL_MIN:
        return "dry"
    if moisture <= cfg.WET_ABOVE:
        return "normal"
    return "wet"


classify_condition = classify_moisture   # backward-compatible name used by earlier files


def needs_water(moisture):
    """True when the soil is dry or critical (i.e. below the 'normal' band)."""
    return classify_moisture(moisture) in ("dry", "critical")


def is_critical(moisture):
    return classify_moisture(moisture) == "critical"


def legacy_status(moisture):
    """3-level label kept so the existing dashboard/Spring Boot field 'current_status' keeps working."""
    c = classify_condition(moisture)
    return {"critical": "dry", "dry": "dry", "normal": "moist", "wet": "wet"}[c]


def stress_level(moisture):
    """Water-stress colour used by the 'Upcoming Water Stress' bars: healthy / warning / critical."""
    c = classify_condition(moisture)
    return {"critical": "critical", "dry": "warning", "normal": "healthy", "wet": "healthy"}[c]


def step_date(last_ts, k):
    """Date string k steps after the latest reading, or None if the timestamp is not ISO."""
    dt = parse_ts(last_ts)
    if dt is None:
        return None
    return (dt + timedelta(hours=cfg.STEP_HOURS * k)).date().isoformat()


def day_label(date_str, k):
    if date_str is None:
        return "Tomorrow" if k == 1 else ("Today" if k == 0 else f"Day +{k}")
    if k == 0:
        return "Today"
    if k == 1:
        return "Tomorrow"
    return datetime.fromisoformat(date_str).strftime("%a %d %b")


def date_label(date_str):
    """'Thu 08 Oct' for an ISO date string, or None."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str).strftime("%a %d %b")
    except Exception:
        return None


def weekday(date_str):
    """'Thu' for an ISO date string, or None."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str).strftime("%a")
    except Exception:
        return None
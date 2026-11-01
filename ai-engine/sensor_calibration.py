# sensor_calibration.py
# Converts a RAW sensor value (ADC counts) into soil-moisture PERCENT before it is sent to POST /analyze.
# The API expects percent. Most capacitive sensors read HIGH when dry and LOW when wet, so the scale is inverted.
#
# Calibrate once per sensor + soil:
#   dry_raw = reading with the sensor in dry air (or fully dried soil)
#   wet_raw = reading with the sensor in a glass of water (or saturated soil)
#
#   raw_to_percent(raw=520, dry_raw=800, wet_raw=350)  -> 62.2   (works for inverted AND non-inverted sensors)

def raw_to_percent(raw: float, dry_raw: float, wet_raw: float) -> float:
    if dry_raw == wet_raw:
        raise ValueError("dry_raw and wet_raw must differ")
    pct = (raw - dry_raw) / (wet_raw - dry_raw) * 100.0
    return round(max(0.0, min(100.0, pct)), 1)
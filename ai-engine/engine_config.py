# engine_config.py
# One place for every threshold / assumption the dashboard-facing outputs depend on.
# Change values HERE (not inside the logic files) when your guide or crop data asks for it.

# ---- Time axis of the forecasting model -----------------------------------
STEP_HOURS = 24        # one model step = 1 day (the simulated training data is daily)
HORIZON = 7            # number of future steps forecast (7 days -> matches the dashboard)
WINDOW = 10            # number of past readings fed to the LSTM

# ---- Soil condition levels (% volumetric moisture), from the project guide ----
WET_ABOVE = 35.0       # > 35  -> wet
NORMAL_MIN = 25.0      # 25-35 -> normal
CRITICAL_BELOW = 15.0  # 15-25 -> dry ; < 15 -> critical

# ---- Soil health score (0-100). Centred on the middle of the NORMAL moisture band so it agrees with the
# irrigation categories (critical/dry/wet must score LOW, normal must score HIGH). Moisture dominates the score. ----
HEALTH_IDEAL_MOISTURE = (NORMAL_MIN + WET_ABOVE) / 2   # 30 %
HEALTH_MOISTURE_PENALTY = 5.0                          # score points lost per 1 % away from the ideal moisture
HEALTH_WEIGHTS = {"moisture": 0.6, "temperature": 0.2, "humidity": 0.2}
SUSPICIOUS_MOISTURE_ABOVE = 60.0                       # field soil is rarely this wet on a capacitive sensor -> check calibration

# ---- Next-irrigation schedule by CURRENT soil category (days until the next irrigation) ----
# The forecast-based day is kept (as forecast_days_until_irrigation) and is clamped into this window, so the
# farmer always gets a date inside the policy window. Set USE_CATEGORY_WINDOW = False to use the pure forecast.
USE_CATEGORY_WINDOW = True
NEXT_IRRIGATION_DAYS = {"critical": (1, 2), "dry": (1, 2), "normal": (3, 4), "wet": (5, 6)}

# ---- Crop stress flag (unchanged from the earlier engine) -------------------
STRESS_MOISTURE_BELOW = 20.0
STRESS_TEMP_ABOVE = 38.0

# ---- Irrigation planning (heuristics, ADVISORY ONLY - calibrate per crop/soil) ----
TARGET_MOISTURE = 32.0       # irrigate up to this moisture level
ROOT_ZONE_DEPTH_MM = 250.0   # assumed root-zone depth; 1 % moisture ~ ROOT_ZONE_DEPTH_MM/100 mm of water
APPLICATION_EFFICIENCY = 0.90
RAIN_SKIP_PERCENT = 60.0     # do not schedule irrigation on days with rain chance >= this
IRRIGATION_WINDOW = ("06:00", "09:00")   # low-evaporation slot (midday irrigation wastes water)
MAX_IRRIGATION_EVENTS = 3
MAX_DEPTH_PER_EVENT_MM = 40.0   # one irrigation never suggests more than this; the plan adds a 2nd event instead
DEPTH_RANGE_PCT = 0.20       # +/-20 % band around the estimated depth (dashboard gauge)

# ---- Forecast uncertainty band -------------------------------------------------
INTERVAL_QUANTILES = (0.10, 0.90)   # 80 % empirical interval from validation residuals

# ---- Model files ------------------------------------------------------------------
MODEL_PATH = "moisture_lstm.keras"
INTERVALS_PATH = "forecast_intervals.json"
METRICS_PATH = "model_metrics.json"
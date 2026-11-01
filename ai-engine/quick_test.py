import os; os.environ["TF_CPP_MIN_LOG_LEVEL"]="3"
from analysis_engine import analyze
def hist(m): return [{"moisture":m,"temperature":32,"humidity":55,
                      "timestamp":f"2026-10-{19+i:02d}T06:00:00"} for i in range(10)]
for m in (10, 20, 30, 40):
    r = analyze(hist(m), {"temperature":32,"rain_chance_percent":10})
    print(m, r["soil_condition"], r["irrigation_required_now"],
          r["next_irrigation_status"], r["next_irrigation_date"],
          r["days_until_irrigation"], r["soil_health_score"])
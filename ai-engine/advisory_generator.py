# advisory_generator.py  (v2)
# Translates the forecast + decisions + SHAP explanation into ONE farmer-readable sentence.
# No new computation here. The old string-match bug ("will reach dry") is gone: the decision
# now comes from structured fields, not from searching text.

FEATURE_LABELS = {
    "moisture": "soil moisture level",
    "temperature": "temperature",
    "humidity": "humidity",
}


def build_advisory(trend_result, health_result, dashboard=None):
    """
    trend_result  : {"current_status","projected_trend"}
    health_result : {"soil_health_score","crop_stress","shap_explanation"}
    dashboard     : output of decision_layer.build_dashboard_outputs (optional, for the full advisory)
    """
    score = health_result["soil_health_score"]
    stressed = health_result.get("crop_stress", False)
    shap_values = health_result["shap_explanation"]
    top = max(shap_values, key=shap_values.get)
    top_label = FEATURE_LABELS.get(top, top)
    top_impact = int(shap_values[top] * 100)

    if dashboard is None:   # legacy 2-argument behaviour
        needs = trend_result["current_status"] == "dry" or "reach dry" in trend_result["projected_trend"]
        base = (f"Irrigation recommended \u2014 {trend_result['projected_trend']}." if needs
                else f"No irrigation needed yet \u2014 {trend_result['projected_trend']}.")
    else:
        irr = dashboard["irrigation"]
        cond = dashboard["soil_condition"]
        m = dashboard["current_moisture"]
        if irr["windows"]:
            w = irr["windows"][0]
            when = ("now" if w["day_offset"] == 0 else
                    f"{'tomorrow' if w['day_offset'] == 1 else 'on ' + w['label']} between {w['start']} and {w['end']}")
            lead = (f"Irrigation recommended now \u2014 soil is already {cond} ({m}%)." if w["day_offset"] == 0
                    else f"Irrigation recommended {when} \u2014 {w['reason']} (soil is {cond}, {m}% now).")
            base = (f"{lead} Estimated water: {w['depth_mm']['min']:.0f}\u2013{w['depth_mm']['max']:.0f} mm "
                    f"(advisory only; adjust to your crop and soil). "
                    f"Main driver: {top_label} ({top_impact}% impact).")
        else:
            lowest = min(dashboard["_base_values"])
            base = (f"No irrigation needed in the next {len(dashboard['forecast'])} days \u2014 soil is {cond} ({m}%) "
                    f"and is predicted to stay above {dashboard['thresholds']['dry_below']:.0f}% "
                    f"(lowest forecast {lowest:.1f}%).")
    text = f"{base} Soil health score: {score}/100."
    if stressed:
        text += " Warning: crop is currently showing signs of heat or water stress."
    return {"advisory": text}
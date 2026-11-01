"""
Tests for the next-irrigation feature (current irrigation + "when do I irrigate again?" + XAI + chat + simulate).

Run from the project root:   pytest tests -q
Same design rules as test_expected_behavior.py: tolerances / consistency rules, never hard-coded model outputs.
The chat tests replace only vector search and the Groq HTTP call; everything else is the real code.
"""
import json
import os
import subprocess
import sys
import types
from datetime import date

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

if "chatbot.retriever" not in sys.modules:       # stub the embedding search (same approach as the other test file)
    _store = json.load(open(os.path.join(ROOT, "knowledge_base", "vector_store", "chunks.json"), encoding="utf-8"))
    _fake = types.ModuleType("chatbot.retriever")

    def _search(query, top_k=4):
        pairs = list(zip(_store["chunks"], _store["metadata"]))
        words = [w for w in query.lower().split() if len(w) > 3]
        pairs.sort(key=lambda p: -sum(w in p[0].lower() for w in words))
        return [{"text": t, "source": m["source"], "score": 0.0} for t, m in pairs[:top_k]]

    _fake.search = _search
    sys.modules["chatbot.retriever"] = _fake

from fastapi.testclient import TestClient  # noqa: E402

import app as api  # noqa: E402
import engine_config as cfg  # noqa: E402
import forecasting_model as fm  # noqa: E402
import decision_layer as dl  # noqa: E402
import next_irrigation as ni  # noqa: E402
from chatbot import latest_reading_store as store  # noqa: E402
from chatbot import llm_client  # noqa: E402
from chatbot.hypothetical import extract_hypothetical_moisture  # noqa: E402
from chatbot.live_data_adapter import get_live_data  # noqa: E402
from data_utils import order_history  # noqa: E402

client = TestClient(api.app)
WEATHER = {"temperature": 32, "rain_chance_percent": 10}


def hist(m, n=6, temp=32, hum=55, month="2026-10"):
    return [{"moisture": m, "temperature": temp, "humidity": hum, "timestamp": f"{month}-{1 + i:02d}T06:00:00"}
            for i in range(n)]


def daily(rains, start=7, month="2026-10"):
    return [{"date": f"{month}-{start + i:02d}", "temperature": 33, "rain_chance_percent": r, "humidity": 55}
            for i, r in enumerate(rains)]


def analyze(m=None, history=None, weather=WEATHER, daily_forecast=None, session="t"):
    body = {"sensor_history": history or hist(m), "weather_forecast": weather, "session_id": session}
    if daily_forecast:
        body["daily_forecast"] = daily_forecast
    r = client.post("/analyze", json=body)
    assert r.status_code == 200, r.text
    return r.json()


NEXT_FIELDS = {"next_irrigation_status", "next_irrigation_date", "days_until_irrigation",
               "next_irrigation_reference_date", "next_irrigation_basis", "irrigation_required_now",
               "moisture_after_current_irrigation", "next_irrigation_trigger_moisture", "next_irrigation_message",
               "next_irrigation_reason", "next_irrigation_xai", "predicted_moisture_trend"}
CATEGORY_CASES = [(10, "critical"), (14.9, "critical"), (15, "dry"), (20, "dry"), (24.9, "dry"),
                  (25, "normal"), (30, "normal"), (35, "normal"), (35.1, "wet"), (40, "wet")]


# ------------------------------------------------------------------ fields + separation from the current result
@pytest.mark.parametrize("m,cond", CATEGORY_CASES)
def test_fields_present_and_categories_unchanged(m, cond):
    r = analyze(m)
    assert NEXT_FIELDS <= set(r)
    assert r["soil_condition"] == cond and r["current_moisture"] == m          # current result untouched
    assert r["next_irrigation_trigger_moisture"] == cfg.NORMAL_MIN == 25.0
    assert r["next_irrigation_status"] in ("predicted", "beyond_forecast_horizon")
    # legacy fields still there
    for k in ("advisory", "shap_explanation", "irrigation", "forecast", "soil_health_score", "water_stress_alert"):
        assert k in r


@pytest.mark.parametrize("m", [5, 10, 14.9, 15, 20, 24.9])
def test_dry_or_critical_irrigates_now_and_next_is_after_that_irrigation(m):
    r = analyze(m)
    w = r["irrigation"]["windows"]
    assert r["irrigation_required_now"] is True and w[0]["day_offset"] == 0          # current recommendation preserved
    assert r["next_irrigation_basis"] == "after_current_irrigation"
    assert r["moisture_after_current_irrigation"] > m                                # post-irrigation moisture used
    assert r["moisture_after_current_irrigation"] == w[0]["moisture_after"]
    if r["next_irrigation_status"] == "predicted":
        assert r["days_until_irrigation"] >= 2
        assert len(w) > 1 and r["next_irrigation_date"] == w[1]["date"]             # same schedule the planner shows
        assert r["days_until_irrigation"] == w[1]["day_offset"]
    else:
        assert len(w) == 1


@pytest.mark.parametrize("m", [25, 27, 30, 35])
def test_normal_does_not_irrigate_now_and_next_is_first_scheduled(m):
    r = analyze(m)
    w = r["irrigation"]["windows"]
    assert r["irrigation_required_now"] is False and r["next_irrigation_basis"] == "no_irrigation_needed_now"
    assert r["moisture_after_current_irrigation"] is None
    if w:
        assert r["next_irrigation_status"] == "predicted"
        assert r["next_irrigation_date"] == w[0]["date"] and r["days_until_irrigation"] == w[0]["day_offset"] >= 1
    else:
        assert r["next_irrigation_status"] == "beyond_forecast_horizon"


@pytest.mark.parametrize("m", [40, 55, 80])
def test_wet_soil_forecast_stays_above_trigger_gives_no_invented_date(m):
    r = analyze(m)
    assert r["irrigation_required_now"] is False
    assert r["next_irrigation_status"] == "beyond_forecast_horizon"
    assert r["next_irrigation_date"] is None and r["days_until_irrigation"] is None
    assert "forecast" in r["next_irrigation_message"].lower()
    assert all(not p["is_next_irrigation_day"] for p in r["predicted_moisture_trend"])
    assert min(p["moisture"] for p in r["predicted_moisture_trend"]) >= cfg.NORMAL_MIN


# ------------------------------------------------------------------ date / day-count consistency
CONSISTENCY = [(5, 10), (10, 10), (18, 30), (22, 5), (24.9, 10), (25, 10), (28, 20), (30, 10), (33, 60), (35, 10), (38, 10)]


@pytest.mark.parametrize("m,rain", CONSISTENCY)
def test_date_and_days_agree(m, rain):
    r = analyze(m, weather={"temperature": 32, "rain_chance_percent": rain})
    if r["next_irrigation_status"] != "predicted":
        return
    ref, nxt = date.fromisoformat(r["next_irrigation_reference_date"]), date.fromisoformat(r["next_irrigation_date"])
    assert (nxt - ref).days == r["days_until_irrigation"]
    flagged = [p for p in r["predicted_moisture_trend"] if p["is_next_irrigation_day"]]
    assert len(flagged) == 1 and flagged[0]["date"] == r["next_irrigation_date"]
    assert str(r["days_until_irrigation"]) in r["next_irrigation_message"]


def test_reference_date_is_the_latest_reading_even_if_history_is_newest_first():
    h = list(reversed(hist(10)))
    r = analyze(history=h)
    assert r["next_irrigation_reference_date"] == "2026-10-06"


# ------------------------------------------------------------------ rain
def test_rain_likely_days_are_never_chosen_for_the_next_irrigation():
    rains = [5, 5, 90, 90, 5, 5, 5]
    r = analyze(28, daily_forecast=daily(rains))
    assert r["next_irrigation_status"] == "predicted"
    step = next(p["step"] for p in r["predicted_moisture_trend"] if p["is_next_irrigation_day"])
    assert step == len(rains) or rains[step - 1] < cfg.RAIN_SKIP_PERCENT
    xai = r["next_irrigation_xai"]
    assert xai["rain_effect"]["text"] and "probability" in xai["rain_effect"]["text"]
    crossing = next(p["step"] for p in r["predicted_moisture_trend"] if p["below_trigger"])
    if crossing != step:
        assert any(f["factor"] == "rain_postponement" for f in xai["factors"])


def _outlook(rains):
    return [{"date": f"2026-10-{7 + i:02d}", "temperature": 33.0, "humidity": 55.0, "rain_chance_percent": float(x)}
            for i, x in enumerate(rains)]


def test_find_next_need_skips_rain_likely_days_model_free():
    values = [30, 28, 26, 24, 23, 22, 21]                          # first below 25 % on day 4
    assert ni.find_next_need(values, _outlook([5, 5, 5, 5, 5, 5, 5]), 1) == (4, 4)
    assert ni.find_next_need(values, _outlook([5, 5, 5, 90, 90, 5, 5]), 1) == (4, 6)       # moved past rain days 4-5
    assert ni.find_next_need(values, _outlook([5, 5, 5, 90, 90, 90, 90]), 1) == (4, 7)     # last day is never skipped
    assert ni.find_next_need([33] * 7, _outlook([5] * 7), 1) is None                      # never reaches the trigger
    assert ni.find_next_need([20, 30, 30, 30, 30, 30, 30], _outlook([5] * 7), 2) is None   # first_day=2 ignores day 1


@pytest.mark.parametrize("m", [18, 22, 26, 28, 30])
@pytest.mark.parametrize("rains", [[5, 5, 5, 90, 90, 5, 5], [5, 70, 70, 70, 5, 5, 5], [70] * 7])
def test_rain_postponement_is_reported_whenever_it_happens(m, rains):
    r = analyze(m, daily_forecast=daily(rains))
    trend, xai = r["predicted_moisture_trend"], r["next_irrigation_xai"]
    step = next((p["step"] for p in trend if p["is_next_irrigation_day"]), None)
    if step is None:
        return
    first = 2 if r["irrigation_required_now"] else 1
    crossing = next(p["step"] for p in trend if p["below_trigger"] and p["step"] >= first)
    assert step == len(rains) or rains[step - 1] < cfg.RAIN_SKIP_PERCENT          # never planned on a rain-likely day
    assert (step != crossing) == any(f["factor"] == "rain_postponement" for f in xai["factors"])


def test_rain_effect_text_matches_the_dry_weather_what_if():
    # soil 30 %: with the rain forecast the model keeps the soil above the trigger for 7 days; with 0 % rain it would not
    r = analyze(30, daily_forecast=daily([5, 5, 5, 5, 90, 90, 5]))
    rain = r["next_irrigation_xai"]["rain_effect"]
    if r["next_irrigation_status"] == "beyond_forecast_horizon" and rain["dry_weather_what_if_day"] is not None:
        assert "keeps irrigation beyond" in rain["text"]
    elif r["next_irrigation_status"] == "predicted" and rain["dry_weather_what_if_day"] is not None:
        assert "day +" in rain["text"] or "would not move" in rain["text"]
    assert rain["method"].startswith("digital-twin what-if")


# ------------------------------------------------------------------ missing / insufficient data
def test_single_reading_and_no_daily_forecast_still_answers_with_caveats():
    r = analyze(history=hist(20, n=1))
    assert r["next_irrigation_status"] in ("predicted", "beyond_forecast_horizon")
    notes = " ".join(r["next_irrigation_xai"]["confidence_notes"])
    assert "Only 1 reading" in notes and "No daily_forecast" in notes


def test_non_iso_timestamps_give_days_but_no_calendar_date():
    h = [{"moisture": 20, "temperature": 32, "humidity": 55, "timestamp": f"reading-{i}"} for i in range(6)]
    r = analyze(history=h)
    assert r["next_irrigation_status"] == "predicted"
    assert r["next_irrigation_date"] is None and r["next_irrigation_reference_date"] is None
    assert isinstance(r["days_until_irrigation"], int) and r["days_until_irrigation"] >= 2


def test_failure_in_the_addon_never_breaks_analyze(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(ni, "_build", boom)
    r = analyze(20)
    assert r["next_irrigation_status"] == "unavailable" and r["next_irrigation_date"] is None
    assert r["irrigation"]["windows"][0]["day_offset"] == 0          # current result still fine


# ------------------------------------------------------------------ XAI
def test_current_shap_preserved_and_next_xai_is_not_presented_as_shap():
    r = analyze(10)
    assert set(r["shap_explanation"]) == {"moisture", "temperature", "humidity"}
    assert abs(sum(r["shap_explanation"].values()) - 1.0) < 0.05
    x = r["next_irrigation_xai"]
    assert x["is_shap"] is False and x["method"] == "rule_based_threshold_crossing"
    assert "shap_values" not in x and "not a SHAP" in x["shap_note"]
    assert x["trigger_moisture_percent"] == 25.0 and x["factors"] and x["summary"] == r["next_irrigation_reason"]
    assert {f["factor"] for f in x["factors"]} >= {"current_moisture", "current_irrigation", "moisture_path", "trigger", "weather"}
    assert x["uncertainty"]["basis"] and "forecast_horizon_days" in x


def test_trend_matches_the_forecast_machinery():
    r = analyze(10)
    trend = r["predicted_moisture_trend"]
    assert len(trend) == cfg.HORIZON and all(p["lower"] <= p["moisture"] <= p["upper"] for p in trend)
    # trajectory after ONLY the current irrigation = rollout with that single event
    w0 = r["irrigation"]["windows"][0]
    hh = order_history(hist(10))
    outlook = fm.build_weather_outlook(hh, WEATHER, None)
    expected = fm.rollout(fm.build_window(hh, WEATHER), outlook, {0: w0["points_added"]})
    assert [p["moisture"] for p in trend] == expected


# ------------------------------------------------------------------ helper == planner (single rule, two call sites)
@pytest.mark.parametrize("m", [5, 10, 18, 24.9, 28, 30, 33])
@pytest.mark.parametrize("rains", [None, [5, 5, 90, 90, 5, 5, 5], [70] * 7])
def test_find_next_need_matches_the_planner(m, rains):
    hh = order_history(hist(m))
    d = daily(rains) if rains else None
    out = fm.build_weather_outlook(hh, WEATHER, d)
    win = fm.build_window(hh, WEATHER)
    base = fm.rollout(win, out)
    windows, _, _ = dl.plan_irrigation(win, out, base, float(m), hh[-1]["timestamp"])
    if windows and windows[0]["day_offset"] == 0:
        traj = fm.rollout(win, out, {0: windows[0]["points_added"]})
        hit, planned = ni.find_next_need(traj, out, 2), (windows[1]["day_offset"] if len(windows) > 1 else None)
    else:
        hit, planned = ni.find_next_need(base, out, 1), (windows[0]["day_offset"] if windows else None)
    assert (hit[1] if hit else None) == planned


# ------------------------------------------------------------------ /simulate
BODY = {"sensor_history": hist(10), "weather_forecast": WEATHER}


def simulate(scenario, **kw):
    r = client.post("/simulate", json={**BODY, "scenario": scenario, **kw})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("scenario", ["irrigate_now", "rain_tomorrow", "reduce_20pct", "delay_24h"])
def test_simulate_keeps_old_fields_and_adds_hypothetical_next_irrigation(scenario):
    j = simulate(scenario)
    assert {"baseline_forecast", "simulated_forecast", "comparison", "baseline", "simulated"} <= set(j)
    for k in ("baseline_next_irrigation", "simulated_next_irrigation"):
        assert j[k]["status"] in ("predicted", "beyond_forecast_horizon", "required_now") and j[k]["trigger_moisture"] == 25.0
        assert (j[k]["status"] == "required_now") == (j[k]["irrigation_required_now"] and j[k]["basis"] == "no_irrigation_applied")
    assert j["baseline_next_irrigation"]["basis"] == "no_irrigation_applied"


def test_simulated_irrigation_gives_same_next_date_as_analyze_for_same_water():
    live = analyze(10)
    sim = simulate("irrigate_now", amount_mm=cfg.MAX_DEPTH_PER_EVENT_MM)       # same 40 mm the planner recommends
    assert sim["simulated_next_irrigation"]["basis"] == "after_simulated_irrigation"
    assert sim["simulated_next_irrigation"]["date"] == live["next_irrigation_date"]
    assert sim["simulated_next_irrigation"]["days_until_irrigation"] == live["days_until_irrigation"]


# ------------------------------------------------------------------ chatbot
class FakeGroq:
    def __init__(self):
        self.prompts = []
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.prompts.append(kw["messages"][0]["content"])
        msg = types.SimpleNamespace(content="ok")
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason="stop")])


@pytest.fixture
def fake_groq(monkeypatch):
    f = FakeGroq()
    monkeypatch.setattr(llm_client, "_client", f)
    store._by_session.clear()
    store._global_latest = None
    return f


def _line(prompt, key_start):
    return next(l for l in prompt.splitlines() if l.startswith(key_start))


@pytest.mark.parametrize("m", [10, 22, 30, 40])
def test_chat_prompt_carries_the_same_prediction_as_analyze(fake_groq, m):
    r = analyze(m, session="s1")
    client.post("/chat", json={"message": "When should I irrigate again?", "session_id": "s1"})
    prompt = fake_groq.prompts[-1]
    assert r["next_irrigation_message"] in _line(prompt, "NEXT IRRIGATION DATE")
    assert f"Days until next irrigation: {r['days_until_irrigation'] if r['days_until_irrigation'] is not None else 'not predicted'}" in prompt
    assert f"Next irrigation status: {r['next_irrigation_status']}" in prompt
    if r["next_irrigation_date"]:
        assert r["next_irrigation_date"] in prompt
    else:
        assert "Do NOT invent a date" in prompt
    assert r["next_irrigation_reason"] in prompt and "below 25%" in prompt
    assert "Rain effect on the next irrigation date" in prompt


def test_chat_live_data_equals_analyze_fields(fake_groq):
    body = {"sensor_history": hist(10), "weather_forecast": WEATHER}
    r = client.post("/analyze", json={**body, "session_id": "s2"}).json()
    live = get_live_data(body["sensor_history"], WEATHER)
    assert str(r["days_until_irrigation"]) == str(live["Days until next irrigation"])
    assert r["next_irrigation_status"] == live["Next irrigation status"]


def test_chat_without_analysis_still_flags_missing_live_data(fake_groq):
    j = client.post("/chat", json={"message": "When should I irrigate again?", "session_id": "none"}).json()
    assert j["live_data_used"] is False and "POST /analyze" in j["warning"]
    assert "CURRENT FARM DATA" not in fake_groq.prompts[-1]


def test_hypothetical_question_adds_labelled_lines_and_keeps_real_data(fake_groq):
    analyze(40, session="s3")                                                   # real farm: wet, 40 %
    client.post("/chat", json={"message": "If my moisture is 10%, what should I do?", "session_id": "s3"})
    prompt = fake_groq.prompts[-1]
    assert "HYPOTHETICAL recommended action now: Irrigate NOW" in prompt
    assert "HYPOTHETICAL soil condition: critical" in prompt
    assert "Soil moisture: 40.0%" in prompt or "Soil moisture: 40%" in prompt     # real reading untouched
    assert "Soil condition: wet" in prompt
    client.post("/chat", json={"message": "If my moisture is 40%, should I irrigate?", "session_id": "s3"})
    assert "HYPOTHETICAL soil condition: wet" in fake_groq.prompts[-1]


def test_non_hypothetical_question_has_no_hypothetical_lines(fake_groq):
    analyze(20, session="s4")
    client.post("/chat", json={"message": "Should I irrigate now?", "session_id": "s4"})
    assert "HYPOTHETICAL" not in fake_groq.prompts[-1].split("RETRIEVED AGRICULTURE KNOWLEDGE")[0].split("CURRENT FARM DATA")[-1]


@pytest.mark.parametrize("q,expected", [
    ("If my moisture is 10%, what should I do?", 10.0),
    ("if my moisture is 40%, should I irrigate?", 40.0),
    ("What if soil moisture drops to 18.5 percent?", 18.5),
    ("Should I irrigate now?", None),
    ("Why was my moisture 20% yesterday?", None),
    ("If my moisture is 150% what then", None),
    ("If it rains tomorrow, will the date change?", None),
])
def test_hypothetical_moisture_extraction(q, expected):
    assert extract_hypothetical_moisture(q) == expected


# ------------------------------------------------------------------ CORS configuration (own process: env is read at import)
def test_cors_origins_come_from_the_environment():
    code = (
        "import os,sys,types;os.environ['TF_CPP_MIN_LOG_LEVEL']='3';sys.path.insert(0,'.');"
        "m=types.ModuleType('chatbot.retriever');m.search=lambda q,top_k=4:[];sys.modules['chatbot.retriever']=m;"
        "import app;from fastapi.testclient import TestClient as T;c=T(app.app);"
        "h={'Origin':'http://192.168.1.25:8080','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'};"
        "ok=c.options('/analyze',headers=h);bad=c.options('/analyze',headers={**h,'Origin':'http://evil.example'});"
        "print(ok.headers.get('access-control-allow-origin'),bad.headers.get('access-control-allow-origin'))"
    )
    env = {**os.environ, "CORS_ORIGINS": "http://192.168.1.25:8080"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=ROOT).stdout.strip().splitlines()[-1]
    assert out == "http://192.168.1.25:8080 None"
"""
Behaviour tests for the AgriTwin AI API (Tests 1-5 + validation + dates + random invariants).

Run from the project root:        pytest tests -q
Run the real chatbot end-to-end:  set AGRITWIN_LIVE_CHAT=1 (needs GROQ_API_KEY and the embedding model)

Design notes
* Assertions use TOLERANCES and consistency rules, never hard-coded outputs, so they hold for ANY correctly
  trained forecast model. Exact numbers that depend on one particular trained model live in the
  `TestReferenceModel` class, which runs only when the shipped reference model file is present.
* The chat tests replace only the two external pieces (vector search and the Groq HTTP call). Everything
  else - /analyze, session store, live-data adapter, prompt builder, memory, API layer - is the real code.
"""
import hashlib
import json
import os
import random
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

LIVE_CHAT = os.environ.get("AGRITWIN_LIVE_CHAT") == "1"

# ---- stub the vector search (needs the embedding model) unless running the live chatbot -------------------
if not LIVE_CHAT:
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
from chatbot import latest_reading_store as store  # noqa: E402
from chatbot import llm_client  # noqa: E402
from data_utils import classify_moisture  # noqa: E402

client = TestClient(api.app)


# ------------------------------------------------------------------ helpers / fixtures
def hist(moistures, temp=32, hum=55, day0=1, month="2026-10"):
    return [{"moisture": m, "temperature": temp, "humidity": hum,
             "timestamp": f"{month}-{day0 + i:02d}T06:00:00"} for i, m in enumerate(moistures)]


def daily(rains, start=7, month="2026-10"):
    return [{"date": f"{month}-{start + i:02d}", "temperature": 33, "rain_chance_percent": r, "humidity": 55}
            for i, r in enumerate(rains)]


TEST1 = {"sensor_history": hist([33, 32, 31, 29.5, 28, 27]),
         "weather_forecast": {"temperature": 33, "rain_chance_percent": 5},
         "daily_forecast": daily([5, 10, 10, 20, 70, 40, 10])}
TEST2 = {"sensor_history": hist([22, 20, 18, 16, 14, 12.5]),
         "weather_forecast": {"temperature": 32, "rain_chance_percent": 10}}
# NOTE: Test 3 must use sensor temperature 32 C. The 88.0 score in the expected output is only produced
# at 32 C (at 27 C the documented formula gives 93.0 - see test_soil_health_formula).
TEST3 = {"sensor_history": hist([42, 41.5, 41, 40.8, 40.5, 40], temp=32),
         "weather_forecast": {"temperature": 27, "rain_chance_percent": 30}}


def analyze(body):
    r = client.post("/analyze", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def first_dry_step(forecast):
    return next((f["step"] for f in forecast if f["condition"] in ("dry", "critical")), None)


@pytest.fixture(scope="module")
def t1():
    return analyze(TEST1)


@pytest.fixture(scope="module")
def t2():
    return analyze(TEST2)


@pytest.fixture(scope="module")
def t3():
    return analyze(TEST3)


# ------------------------------------------------------------------ classification (boundaries)
@pytest.mark.parametrize("m,expected", [
    (0, "critical"), (14.99, "critical"), (15.0, "dry"), (24.99, "dry"), (25.0, "normal"),
    (35.0, "normal"), (35.01, "wet"), (100, "wet")])
def test_classification_boundaries(m, expected):
    assert classify_moisture(m) == expected


def assert_consistent(res):
    """Every part of one response must agree with the single classifier and with each other."""
    for f in res["forecast"]:
        assert f["condition"] == classify_moisture(f["moisture"])
        assert f["lower"] <= f["moisture"] <= f["upper"]
    for s, f in zip(res["water_stress_outlook"], res["forecast"]):
        want = {"critical": "critical", "dry": "warning", "normal": "healthy", "wet": "healthy"}[f["condition"]]
        assert s["level"] == want and s["date"] == f["date"] and s["moisture"] == f["moisture"]
    assert [f["step"] for f in res["forecast"]] == list(range(1, cfg.HORIZON + 1))
    assert [f["hours_ahead"] for f in res["forecast"]] == [24 * k for k in range(1, cfg.HORIZON + 1)]
    cur = res["current_moisture"]
    assert res["soil_condition"] == classify_moisture(cur)
    # time_to_dry / time_to_critical agree with the forecast
    td, tc = res["time_to_dry"], res["time_to_critical"]
    if classify_moisture(cur) in ("dry", "critical"):
        assert td and td["steps"] == 0
    else:
        step = first_dry_step(res["forecast"])
        assert (td is None) == (step is None)
        if td:
            assert td["steps"] == step and td["date"] == res["forecast"][step - 1]["date"]
    if classify_moisture(cur) == "critical":
        assert tc and tc["steps"] == 0
    else:
        step = next((f["step"] for f in res["forecast"] if f["condition"] == "critical"), None)
        assert (tc is None) == (step is None)
        if tc:
            assert tc["steps"] == step
    # irrigation plan sanity
    ws = res["irrigation"]["windows"]
    assert res["irrigation"]["needed"] == bool(ws)
    assert len(ws) <= cfg.MAX_IRRIGATION_EVENTS
    origins = [max(0, w["day_offset"] - 1) for w in ws]
    assert origins == sorted(set(origins)), "irrigation windows must be on distinct, increasing days"
    for w in ws:
        d = w["depth_mm"]
        assert d["min"] <= d["estimate"] <= d["max"] <= cfg.MAX_DEPTH_PER_EVENT_MM
        if w["day_offset"] >= 1:
            assert w["date"] == res["forecast"][w["day_offset"] - 1]["date"]
            assert (w["start"], w["end"]) == cfg.IRRIGATION_WINDOW
    assert len(res["forecast_with_plan"]) == cfg.HORIZON


# ------------------------------------------------------------------ Test 1: normal now, dry later
class TestNormalSoil:
    def test_state(self, t1):
        assert t1["soil_condition"] == "normal"
        assert t1["current_moisture"] == 27.0
        assert t1["current_status"] == "moist"
        assert t1["crop_stress"] is False
        assert t1["soil_health_score"] == pytest.approx(83.7, abs=0.1)

    def test_forecast_declines_from_about_26_to_about_22(self, t1):
        m = [f["moisture"] for f in t1["forecast"]]
        assert 24.5 <= m[0] <= 27.5 and 20.5 <= m[-1] <= 24.5 and m[0] > m[-1]
        assert t1["forecast"][0]["condition"] == "normal"
        assert t1["forecast"][-1]["condition"] == "dry"

    def test_time_to_dry_follows_the_forecast(self, t1):
        td = t1["time_to_dry"]
        assert 2 <= td["steps"] <= 4
        assert td["moisture"] < 25 and td["date"] == t1["forecast"][td["steps"] - 1]["date"]
        assert t1["time_to_critical"] is None

    def test_irrigation_is_planned_for_the_first_dry_day(self, t1):
        irr = t1["irrigation"]
        assert irr["needed"] and irr["urgency"] in ("soon", "later")
        w = irr["windows"][0]
        assert w["date"] == t1["time_to_dry"]["date"]
        assert (w["start"], w["end"]) == ("06:00", "09:00")
        assert 10 <= w["depth_mm"]["min"] <= w["depth_mm"]["max"] <= 30
        day = w["day_offset"]
        assert t1["forecast_with_plan"][day - 1] >= t1["forecast"][day - 1]["moisture"] + 3   # moisture jumps back
        assert 27 <= t1["forecast_with_plan"][day - 1] <= 33

    def test_water_stress(self, t1):
        levels = [s["level"] for s in t1["water_stress_outlook"]]
        assert levels[0] == "healthy" and levels[-1] == "warning"
        alert = t1["water_stress_alert"]
        assert alert["active"] == (t1["time_to_dry"]["steps"] <= 2)          # only a warning when dry is <=2 days away
        assert alert["severity"] in ("none", "moderate")

    def test_explanation(self, t1):
        shap = t1["shap_explanation"]
        assert sum(shap.values()) == pytest.approx(1.0, abs=0.03)
        assert shap["moisture"] == pytest.approx(0.77, abs=0.05)
        assert shap["temperature"] == pytest.approx(0.20, abs=0.05)
        assert max(shap, key=shap.get) == "moisture"
        assert "soil moisture level" in t1["advisory"] and t1["irrigation"]["windows"][0]["label"] in t1["advisory"]

    def test_consistency(self, t1):
        assert_consistent(t1)


# ------------------------------------------------------------------ Test 2: already critical
class TestCriticalSoil:
    def test_state(self, t2):
        assert t2["soil_condition"] == "critical" and t2["current_status"] == "dry"
        assert t2["crop_stress"] is True
        assert t2["soil_health_score"] == pytest.approx(78.8, abs=0.1)
        shap = t2["shap_explanation"]
        assert shap["moisture"] == pytest.approx(0.84, abs=0.05) and shap["temperature"] == pytest.approx(0.13, abs=0.05)

    def test_forecast_stays_very_low(self, t2):
        m = [f["moisture"] for f in t2["forecast"]]
        assert all(5 <= v < 15 for v in m) and m[0] > m[-1]
        assert all(f["condition"] == "critical" for f in t2["forecast"])

    def test_already_dry_and_critical(self, t2):
        assert t2["time_to_dry"]["steps"] == 0 and t2["time_to_critical"]["steps"] == 0

    def test_irrigation_now_then_a_later_top_up(self, t2):
        irr = t2["irrigation"]
        assert irr["needed"] and irr["urgency"] == "now"
        first, second = irr["windows"][0], irr["windows"][1]
        assert first["day_offset"] == 0 and first["start"] == "now"
        assert 30 <= first["depth_mm"]["min"] and first["depth_mm"]["max"] == cfg.MAX_DEPTH_PER_EVENT_MM   # capped
        assert second["day_offset"] >= 2 and (second["start"], second["end"]) == ("06:00", "09:00")
        assert second["depth_mm"]["max"] < first["depth_mm"]["max"]   # recovered soil needs less water
        assert max(t2["forecast_with_plan"]) <= cfg.TARGET_MOISTURE + 6

    def test_alert_and_advisory(self, t2):
        a = t2["water_stress_alert"]
        assert a["active"] and a["severity"] == "severe" and a["already_critical"] is True
        assert a["message"] == "Severe moisture depletion predicted within 24 hours."
        assert "already critical" in a["detail"]
        adv = t2["advisory"]
        assert adv.startswith("Irrigation recommended now — soil is already critical (12.5%)")
        assert adv.endswith("Warning: crop is currently showing signs of heat or water stress.")

    def test_consistency(self, t2):
        assert_consistent(t2)


# ------------------------------------------------------------------ Test 3: wet soil
class TestWetSoil:
    def test_no_irrigation(self, t3):
        assert t3["soil_condition"] == "wet" and t3["current_status"] == "wet"
        assert all(f["condition"] == "wet" for f in t3["forecast"])
        assert 36 <= min(f["moisture"] for f in t3["forecast"]) and max(f["moisture"] for f in t3["forecast"]) <= 42
        irr = t3["irrigation"]
        assert irr["needed"] is False and irr["windows"] == [] and irr["urgency"] == "none"
        assert t3["water_stress_alert"]["active"] is False
        assert t3["time_to_dry"] is None and t3["time_to_critical"] is None

    def test_advisory(self, t3):
        adv = t3["advisory"]
        assert adv.startswith("No irrigation needed in the next 7 days — soil is wet (40.0%)")
        assert "predicted to stay above 25%" in adv and adv.endswith("Soil health score: 88.0/100.")

    def test_consistency(self, t3):
        assert_consistent(t3)


def test_soil_health_formula_is_deterministic_and_explainable():
    """100-|m-50|, 100-3|t-25|, 100-|h-60|, averaged. Same moisture, different temperature -> different score."""
    at_27 = analyze({**TEST3, "sensor_history": hist([42, 41.5, 41, 40.8, 40.5, 40], temp=27)})
    at_32 = analyze(TEST3)
    assert at_27["soil_health_score"] == 93.0 and at_32["soil_health_score"] == 88.0
    comp = at_32["soil_health_breakdown"]["components"]
    assert comp == {"moisture_score": 90.0, "temperature_score": 79.0, "humidity_score": 95.0}
    assert sum(comp.values()) / 3 == pytest.approx(at_32["soil_health_score"], abs=0.05)


# ------------------------------------------------------------------ Test 4: /simulate
class TestSimulate:
    def sim(self, scenario, **extra):
        return client.post("/simulate", json={**TEST1, "scenario": scenario, **extra})

    def test_irrigate_now(self):
        r = self.sim("irrigate_now", amount_mm=20)
        assert r.status_code == 200
        j = r.json()
        base = [f["moisture"] for f in j["baseline_forecast"]]
        sim = [f["moisture"] for f in j["simulated_forecast"]]
        assert all(s >= b + 3 for s, b in zip(sim, base))
        assert 30 <= sim[0] <= 36 and 25 <= sim[-1] <= 31
        c = j["comparison"]
        assert c["days_to_dry_baseline"] == first_dry_step(j["baseline_forecast"])
        assert c["days_to_dry_simulated"] is None or c["days_to_dry_simulated"] > c["days_to_dry_baseline"]
        assert j["scenario"] == "irrigate_now" and j["amount_mm"] == 20

    def test_rain_tomorrow(self):
        j = self.sim("rain_tomorrow").json()
        base = [f["moisture"] for f in j["baseline_forecast"]]
        sim = [f["moisture"] for f in j["simulated_forecast"]]
        assert all(s >= b for s, b in zip(sim, base))
        assert 1.0 <= sim[0] - base[0] <= 4.0                      # roughly +2 points
        c = j["comparison"]
        assert c["days_to_dry_baseline"] == first_dry_step(j["baseline_forecast"])
        assert c["days_to_dry_simulated"] is None or c["days_to_dry_simulated"] > c["days_to_dry_baseline"]

    @pytest.mark.parametrize("scenario", ["reduce_20pct", "delay_24h"])
    def test_other_scenarios(self, scenario):
        assert self.sim(scenario).status_code == 200

    def test_unknown_scenario_is_422(self):
        r = self.sim("bogus")
        assert r.status_code == 422 and "scenario" in json.dumps(r.json())

    def test_bad_amount_is_422(self):
        assert self.sim("irrigate_now", amount_mm=0).status_code == 422
        assert self.sim("irrigate_now", amount_mm=-5).status_code == 422

    def test_swagger_shows_a_real_schema(self):
        spec = client.get("/openapi.json").json()
        ref = spec["paths"]["/simulate"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert ref == {"$ref": "#/components/schemas/SimulateResponse"}
        assert set(spec["components"]["schemas"]["SimulateResponse"]["properties"]) >= {
            "baseline_forecast", "simulated_forecast", "comparison"}
        for path in ("/analyze", "/chat"):
            schema = spec["paths"][path]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
            assert "$ref" in schema


# ------------------------------------------------------------------ Test 5: /analyze then /chat
class FakeGroq:
    """Stands in for the Groq HTTP client: records the prompt it receives."""

    def __init__(self, text="Your soil is critical (12.5%). Irrigate now - roughly 32-40 mm as a general guide.", fail=False):
        self.prompts, self.text, self.fail = [], text, fail
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.prompts.append(kw["messages"][0]["content"])
        if self.fail:
            raise RuntimeError("simulated network failure")
        msg = types.SimpleNamespace(content=self.text)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason="stop")])


@pytest.fixture
def fake_groq(monkeypatch):
    fake = FakeGroq()
    monkeypatch.setattr(llm_client, "_client", fake)
    return fake


@pytest.mark.skipif(LIVE_CHAT, reason="uses a fake LLM; run the live chatbot manually")
class TestChat:
    QUESTION = {"message": "When should I irrigate and how much water?", "session_id": "test1"}

    def setup_method(self):
        store._by_session.clear()
        store._global_latest = None

    def test_requires_a_message(self):
        r = client.post("/chat", json={"sensor_history": TEST2["sensor_history"], "weather_forecast": TEST2["weather_forecast"]})
        assert r.status_code == 422 and "message" in json.dumps(r.json())
        assert client.post("/chat", json={"message": ""}).status_code == 422

    def test_analyze_then_chat_uses_the_real_analysis(self, fake_groq):
        analyze({**TEST2, "session_id": "test1"})
        r = client.post("/chat", json=self.QUESTION)
        assert r.status_code == 200
        j = r.json()
        assert j["live_data_used"] is True and j["warning"] is None
        assert isinstance(j["sources"], list) and j["sources"] and all(s.endswith(".txt") for s in j["sources"])
        assert j["answer"] == fake_groq.text
        prompt = fake_groq.prompts[-1]
        for fact in ("12.5%", "critical", "Suggested irrigation window", "now, about 32-40 mm (estimate)", "Soil health score: 78.8"):
            assert fact in prompt, f"live analysis value missing from the LLM prompt: {fact}"

    def test_unknown_session_falls_back_to_latest_analysis(self, fake_groq):
        analyze({**TEST2, "session_id": "farmA"})
        j = client.post("/chat", json={"message": "Should I irrigate?", "session_id": "other-session"}).json()
        assert j["live_data_used"] is True and "most recent" in j["warning"]

    def test_chat_without_any_analysis_is_still_answered_but_flagged(self, fake_groq):
        j = client.post("/chat", json=self.QUESTION).json()
        assert j["live_data_used"] is False and "POST /analyze" in j["warning"]
        assert "CURRENT FARM DATA" not in fake_groq.prompts[-1]

    def test_fresh_data_can_be_sent_with_the_question(self, fake_groq):
        r = client.post("/chat", json={**self.QUESTION, "sensor_history": TEST1["sensor_history"],
                                       "weather_forecast": TEST1["weather_forecast"], "crop": "wheat"})
        assert r.status_code == 200 and r.json()["live_data_used"] is True
        assert "27.0%" in fake_groq.prompts[-1] and "wheat" in fake_groq.prompts[-1]

    def test_half_supplied_data_is_rejected(self):
        r = client.post("/chat", json={**self.QUESTION, "sensor_history": TEST1["sensor_history"]})
        assert r.status_code == 422

    def test_llm_failure_is_a_clear_503(self, monkeypatch):
        monkeypatch.setattr(llm_client, "_client", FakeGroq(fail=True))
        analyze({**TEST2, "session_id": "test1"})
        r = client.post("/chat", json=self.QUESTION)
        assert r.status_code == 503 and "language model" in r.json()["detail"]

    def test_missing_api_key_is_a_clear_503(self, monkeypatch):
        monkeypatch.setattr(llm_client, "_client", None)
        monkeypatch.setattr(llm_client, "GROQ_API_KEY", None)
        r = client.post("/chat", json=self.QUESTION)
        assert r.status_code == 503 and "GROQ_API_KEY" in r.json()["detail"]


@pytest.mark.skipif(not LIVE_CHAT, reason="set AGRITWIN_LIVE_CHAT=1 to call the real Groq model")
def test_live_chatbot_end_to_end():
    analyze({**TEST2, "session_id": "live1"})
    j = client.post("/chat", json={"message": "When should I irrigate and how much water?", "session_id": "live1"}).json()
    assert j["live_data_used"] is True and j["sources"] and "12.5" in j["answer"]


# ------------------------------------------------------------------ dates / time axis
class TestDates:
    def test_dates_are_derived_from_the_latest_timestamp(self):
        body = {"sensor_history": hist([30, 29, 28, 27, 26, 25.5], day0=10, month="2031-03"),
                "weather_forecast": {"temperature": 31, "rain_chance_percent": 10}}
        res = analyze(body)
        assert [f["date"] for f in res["forecast"]] == [f"2031-03-{16 + k}" for k in range(7)]  # last reading = 03-15
        assert [f["hours_ahead"] for f in res["forecast"]] == [24, 48, 72, 96, 120, 144, 168]
        assert all(w["date"] == res["forecast"][w["day_offset"] - 1]["date"] for w in res["irrigation"]["windows"] if w["day_offset"])
        assert any("No daily_forecast supplied" in w for w in res["warnings"])

    def test_today_window_carries_the_date_of_the_latest_reading(self):
        res = analyze({**TEST2, "sensor_history": hist([22, 20, 18, 16, 14, 12.5], day0=3)})   # latest = 2026-10-08
        w = res["irrigation"]["windows"][0]
        assert w["date"] == "2026-10-08" and w["display"].startswith("Now (today, Thu 08 Oct)")

    def test_daily_forecast_dates_that_do_not_line_up_are_reported(self):
        res = analyze({**TEST1, "daily_forecast": daily([5] * 7, start=9)})
        assert any("daily_forecast starts on" in w for w in res["warnings"])

    def test_non_iso_timestamps_do_not_crash(self):
        rows = [{"moisture": m, "temperature": 30, "humidity": 50, "timestamp": t} for m, t in [(30, "a"), (28, "b"), (26, "c")]]
        res = analyze({"sensor_history": rows, "weather_forecast": {"temperature": 30, "rain_chance_percent": 10}})
        assert res["forecast"][0]["date"] is None and res["forecast"][0]["label"] == "Day +1"
        assert any("not ISO" in w for w in res["warnings"])

    def test_input_order_does_not_matter(self):
        a = analyze(TEST1)
        b = analyze({**TEST1, "sensor_history": list(reversed(TEST1["sensor_history"]))})
        assert a["current_moisture"] == b["current_moisture"] == 27.0
        assert [f["moisture"] for f in a["forecast"]] == [f["moisture"] for f in b["forecast"]]


# ------------------------------------------------------------------ validation
class TestValidation:
    W = {"temperature": 30, "rain_chance_percent": 10}

    def test_empty_history_is_422_not_500(self):
        assert client.post("/analyze", json={"sensor_history": [], "weather_forecast": self.W}).status_code == 422

    @pytest.mark.parametrize("field,value", [("moisture", 140), ("moisture", -1), ("humidity", 101), ("temperature", 200)])
    def test_out_of_range_readings_are_422(self, field, value):
        row = {"moisture": 30, "temperature": 30, "humidity": 50, "timestamp": "2026-10-01T06:00:00", field: value}
        assert client.post("/analyze", json={"sensor_history": [row], "weather_forecast": self.W}).status_code == 422

    def test_missing_weather_is_422(self):
        assert client.post("/analyze", json={"sensor_history": TEST1["sensor_history"]}).status_code == 422

    def test_boundary_moistures_classify_correctly_end_to_end(self):
        for m, want in [(14.9, "critical"), (15.0, "dry"), (24.9, "dry"), (25.0, "normal"), (35.0, "normal"), (35.1, "wet")]:
            res = analyze({"sensor_history": hist([m]), "weather_forecast": self.W})
            assert res["soil_condition"] == want, (m, res["soil_condition"])


# ------------------------------------------------------------------ random inputs: logic must hold for unseen data
def test_random_unseen_inputs_keep_every_invariant():
    rng = random.Random(7)
    for i in range(60):
        start = rng.uniform(5, 50)
        ms = [max(1.0, min(60.0, start + rng.uniform(-2, 2) - j * rng.uniform(-0.5, 2))) for j in range(6)]
        rains = [rng.choice([0, 10, 30, 70, 90]) for _ in range(7)]
        body = {"sensor_history": hist(ms, temp=rng.uniform(18, 38), hum=rng.uniform(30, 85), day0=1),
                "weather_forecast": {"temperature": 30, "rain_chance_percent": rains[0]}}
        if i % 2:
            body["daily_forecast"] = daily(rains)
        assert_consistent(analyze(body))


# ------------------------------------------------------------------ numbers tied to ONE trained model
REFERENCE_SHA16 = "745db8457b5bc948"
_sha = hashlib.sha256(open(os.path.join(ROOT, cfg.MODEL_PATH), "rb").read()).hexdigest()[:16]


@pytest.mark.skipif(_sha != REFERENCE_SHA16,
                    reason="moisture_lstm.keras is not the reference model; only behavioural tests apply")
class TestReferenceModel:
    """Exact expectations (with tolerances) for the shipped reference model."""

    def test_test1(self, t1):
        assert t1["time_to_dry"]["steps"] == 3 and t1["time_to_dry"]["date"] == "2026-10-09"
        assert t1["time_to_dry"]["moisture"] == pytest.approx(24.1, abs=0.6)
        assert t1["irrigation"]["urgency"] == "later" and len(t1["irrigation"]["windows"]) == 1
        w = t1["irrigation"]["windows"][0]
        assert w["label"] == "Fri 09 Oct" and 14 <= w["depth_mm"]["min"] <= 16 and 22 <= w["depth_mm"]["max"] <= 24
        assert [s["level"] for s in t1["water_stress_outlook"]] == ["healthy"] * 2 + ["warning"] * 5
        assert t1["water_stress_alert"]["active"] is False

    def test_test2(self, t2):
        ws = t2["irrigation"]["windows"]
        assert len(ws) == 2 and ws[1]["label"] == "Thu 08 Oct"
        assert 14 <= ws[1]["depth_mm"]["min"] <= 17 and 21 <= ws[1]["depth_mm"]["max"] <= 23
        m = [f["moisture"] for f in t2["forecast"]]
        assert m[0] == pytest.approx(11.5, abs=0.7) and m[-1] == pytest.approx(8.6, abs=0.7)

    def test_test3(self, t3):
        assert min(f["moisture"] for f in t3["forecast"]) == pytest.approx(38, abs=1.0)

    def test_test4(self):
        j = client.post("/simulate", json={**TEST1, "scenario": "irrigate_now", "amount_mm": 20}).json()
        assert j["comparison"]["days_to_dry_baseline"] == 3 and j["comparison"]["days_to_dry_simulated"] is None
        j = client.post("/simulate", json={**TEST1, "scenario": "rain_tomorrow"}).json()
        assert j["comparison"]["days_to_dry_baseline"] == 3 and j["comparison"]["days_to_dry_simulated"] == 5
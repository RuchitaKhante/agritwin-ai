# app.py
#
# The single FastAPI entry point. Exposes POST /analyze, POST /simulate and POST /chat.
# This file only wires the other modules together - no core logic lives here.
#
# HTTP status codes:  200 ok | 422 invalid request (bad JSON / out-of-range value / unknown scenario)
#                     503 chatbot dependency unavailable (Groq key/network, knowledge base) | 500 genuine bug

import os
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from schemas import (AnalyzeRequest, AnalyzeResponse, ChatRequest, ChatResponse,
                     SimulateRequest, SimulateResponse)
from forecasting_model import simulate_scenario
from analysis_engine import analyze as run_analysis
from chatbot.rag_pipeline import get_answer
from chatbot.llm_client import LLMUnavailableError
from chatbot.live_data_adapter import get_live_data
from chatbot.latest_reading_store import update_latest, get_latest, has_session

app = FastAPI(title="AgriTwin AI - Analysis Service")

# Browser origins allowed to call this API. Default = the original local dev origins.
# For a dashboard served from another machine set CORS_ORIGINS, e.g.
#   CORS_ORIGINS=http://192.168.1.25:8080,http://localhost:5500
# (Server-to-server calls from a Java/Spring Boot backend are NOT subject to CORS.)
_DEFAULT_ORIGINS = "http://localhost:5500,http://127.0.0.1:5500"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", _DEFAULT_ORIGINS).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _rows(items) -> Optional[List[dict]]:
    return [i.model_dump(exclude_none=True) for i in items] if items else None


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest):
    sensor_history = _rows(request.sensor_history)
    weather_forecast = request.weather_forecast.model_dump()
    daily_forecast = _rows(request.daily_forecast)

    # remember for /chat (stored under this session_id and as the global latest)
    update_latest(sensor_history, weather_forecast, daily_forecast, request.session_id)

    return run_analysis(sensor_history, weather_forecast, daily_forecast)


@app.post("/simulate", response_model=SimulateResponse)
def simulate(request: SimulateRequest):
    """Digital twin what-if simulation. `scenario` is validated (unknown value -> HTTP 422)."""
    try:
        return simulate_scenario(
            _rows(request.sensor_history), request.weather_forecast.model_dump(), request.scenario,
            _rows(request.daily_forecast), request.amount_mm,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    warning = None

    if request.sensor_history and request.weather_forecast:
        # Fresh data sent with this question - use it.
        sensor_history = _rows(request.sensor_history)
        weather_forecast = request.weather_forecast.model_dump()
        daily_forecast = _rows(request.daily_forecast)
    elif request.sensor_history or request.weather_forecast:
        raise HTTPException(status_code=422,
                            detail="Send both sensor_history and weather_forecast together, or neither.")
    else:
        # Use the latest /analyze for this session (or the most recent one overall).
        sensor_history, weather_forecast, daily_forecast = get_latest(request.session_id)
        if sensor_history is None:
            warning = ("No live sensor analysis is available yet, so this answer is general. "
                       "Call POST /analyze first (optionally with the same session_id).")
        elif not has_session(request.session_id):
            warning = (f"No analysis stored for session '{request.session_id}'; "
                       "used the most recent /analyze data instead.")

    live_data = None
    if sensor_history and weather_forecast:
        tomorrow = request.tomorrow_forecast.model_dump() if request.tomorrow_forecast else None
        # same analysis engine as /analyze (next-irrigation fields included); `question` enables what-if answers
        live_data = get_live_data(sensor_history, weather_forecast, tomorrow, daily_forecast, question=request.message)
        if request.crop:
            live_data["Selected crop"] = request.crop

    try:
        result = get_answer(question=request.message, session_id=request.session_id, live_data=live_data)
    except LLMUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=503,
                            detail=f"Knowledge base not found ({e}). Run the ingest script to build it.")

    result["warning"] = warning
    return result


@app.get("/")
def health_check():
    return {"status": "AgriTwin AI service running"}
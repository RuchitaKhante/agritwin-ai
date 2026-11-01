"""
The main orchestration function: takes a farmer's raw question,
runs it through typo correction, retrieval, prompt building, and the LLM,
and returns a structured result. Also maintains simple session memory.

v3: remembers a farm profile (crop, soil, area, irrigation method, flow), computes litres / running time
with the server-side water calculator, and runs topic-focused extra searches (crop, calculation, sensor/soil, weather).
"""

import re

from chatbot.retriever import search
from chatbot.prompt_builder import build_prompt
from chatbot.llm_client import ask_llm
from chatbot.typo_corrector import correct_typos
from chatbot.chat_memory import get_history, add_message, format_history_for_prompt
from chatbot.farm_profile import update_profile, format_profile
from chatbot.water_calculator import describe

_WATER_WORDS = ("irrigat", "water", "how much", "when", "schedule", "drip", "sprinkler", "duration")
_CALC_WORDS = re.compile(r"litre|liter|how long|duration|minute|hour|run ?time|how many|volume|cubic|m3|calculat|quantity|pump", re.I)
_STRICT_CALC_WORDS = re.compile(r"litre|liter|how long|duration|minute|hour|run ?time|how many|volume|cubic|calculat", re.I)
_WEATHER_WORDS = re.compile(r"rain|forecast|weather|hot|heat|temperature|humid|postpone|delay|skip|wait", re.I)
_SENSOR_WORDS = re.compile(r"sensor|calibrat|reading|percent|%|threshold|soil type|sandy|clay|loam|black soil|not matching|doesn.t match|looks wet|looks dry", re.I)

MAX_CHUNKS = 9


def _add(results: list[dict], extra: list[dict], limit: int) -> None:
    seen = {r["text"] for r in results}
    for r in extra[:limit]:
        if r["text"] not in seen:
            results.append(r)
            seen.add(r["text"])


def _retrieve(question: str, live_data: dict | None, profile: dict | None = None) -> list[dict]:
    """
    Vector search plus focused extra searches so the right knowledge is always available:
    irrigation amounts, the farmer's crop, litres/duration formulas, sensor/soil type and weather rules.
    """
    profile = profile or {}
    results = list(search(question))
    q = question.lower()

    if any(w in q for w in _WATER_WORDS):
        _add(results, search("general irrigation amount mm and duration reference range per session"), 2)
    if profile.get("crop"):
        _add(results, search(f"{profile['crop']} irrigation critical growth stages water need reduce stop irrigation"), 2)
    if _CALC_WORDS.search(q):
        _add(results, search("water quantity calculation litres area depth efficiency drip sprinkler duration"), 2)
    if profile.get("soil") or _SENSOR_WORDS.search(q):
        _add(results, search("soil moisture sensor calibration soil type thresholds sandy loam clay black soil conflict field check"), 2)
    if _WEATHER_WORDS.search(q):
        _add(results, search("rain probability is not rainfall amount postpone irrigation rules critical soil weather"), 2)
    return results[:MAX_CHUNKS]


def _calculation_block(question: str, profile: dict, live_data: dict | None) -> str:
    """Server-side litres / running-time calculation (empty string when the question is not about quantities)."""
    asks_quantity = bool(_CALC_WORDS.search(question)) or ("how much water" in question.lower())
    area_m2 = profile.get("area_m2")

    if not area_m2:
        if _STRICT_CALC_WORDS.search(question):
            return ("Cannot calculate litres or running time yet: the field area is unknown. Ask the farmer for the field area "
                    "(with unit: acres, hectares, guntha or m2), the irrigation method (drip, sprinkler or flood) and the flow "
                    "(drip: emitters and L/h each; others: litres per minute). Ask for these in ONE short question.")
        return ""
    if not (asks_quantity or profile.get("_gave_details_now")):
        return ""

    farmer_depth = profile.get("_depth_this_message")
    depth_range = depth_mid = None
    source = "none"
    if farmer_depth:
        depth_mid, source = farmer_depth, "farmer"
    elif live_data and live_data.get("_depth_mm"):
        d = live_data["_depth_mm"]
        depth_range, depth_mid, source = (d["min"], d["max"]), d["estimate"], "engine"
    return describe(profile.get("area_text", "given area"), depth_range, depth_mid, source, area_m2, profile)


def get_answer(question: str, session_id: str = "default", live_data: dict | None = None) -> dict:
    """
    Full RAG flow for a single question, with conversation memory.
    Returns: {"answer": str, "sources": list[str], "live_data_used": bool}
    """
    cleaned_question = correct_typos(question)

    # Learn from both the raw text (numbers/units) and remember it for later questions.
    profile = update_profile(session_id, question, crop_hint=(live_data or {}).get("Selected crop"))

    retrieved_chunks = _retrieve(cleaned_question, live_data, profile)

    if not retrieved_chunks:
        answer = "I don't have enough information in my knowledge base to answer that yet."
        add_message(session_id, "user", question)
        add_message(session_id, "assistant", answer)
        return {"answer": answer, "sources": [], "live_data_used": False}

    history_block = format_history_for_prompt(session_id)
    prompt = history_block + build_prompt(
        cleaned_question, retrieved_chunks, live_data,
        profile_block=format_profile(profile),
        calculation_block=_calculation_block(question, profile, live_data),
    )
    answer = ask_llm(prompt)

    add_message(session_id, "user", question)
    add_message(session_id, "assistant", answer)

    sources = sorted(set(chunk["source"] for chunk in retrieved_chunks))

    return {
        "answer": answer,
        "sources": sources,
        "live_data_used": live_data is not None,
    }
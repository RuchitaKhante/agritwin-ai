"""
Remembers what the farmer tells the bot (crop, growth stage, soil type, field area, irrigation method, flow rates),
per session, so a later "how many litres?" can use "my field is 2 acres" said earlier.
In-memory only, like chat_memory.py.
"""

import re

from chatbot.water_calculator import extract_farm_details

_profiles: dict[str, dict] = {}

CROPS = {  # keyword -> canonical crop name used in the knowledge base
    "wheat": "wheat", "rice": "rice/paddy", "paddy": "rice/paddy",
    "cotton": "cotton", "soybean": "soybean", "soyabean": "soybean", "soya": "soybean",
    "maize": "maize", "corn": "maize", "tomato": "tomato", "tomatoes": "tomato",
    "chili": "chili", "chilli": "chili", "chillies": "chili", "chilies": "chili", "chile": "chili",
    "onion": "onion (other vegetable)", "potato": "potato (other vegetable)", "cabbage": "cabbage (other vegetable)",
    "cauliflower": "cauliflower (other vegetable)", "brinjal": "brinjal (other vegetable)",
    "okra": "okra (other vegetable)", "vegetable": "other vegetables", "vegetables": "other vegetables",
}
STAGES = [  # (regex, label)
    (r"germinat|emergence|sowing|seedling", "germination/establishment"),
    (r"crown root|\bcri\b", "crown root initiation"),
    (r"tillering", "tillering"),
    (r"transplant", "transplanting"),
    (r"panicle|booting|heading", "panicle initiation/booting"),
    (r"flower|bloom", "flowering"),
    (r"fruit set|fruit-set|fruiting", "fruit set"),
    (r"tassel|silking", "tasseling/silking"),
    (r"boll", "boll formation"),
    (r"pod", "pod setting/filling"),
    (r"grain filling|grain-filling|milk stage|dough", "grain filling"),
    (r"ripening|maturity|mature|near harvest|before harvest", "maturity/ripening"),
    (r"vegetative", "vegetative growth"),
]
SOILS = [
    (r"black\s*(?:cotton\s*)?soil|regur|vertisol", "black cotton soil"),
    (r"\bsandy", "sandy soil"), (r"\bclay", "clay soil"), (r"\bloam", "loamy soil"),
    (r"\bred\s+soil", "red soil"), (r"\bsilt", "silt soil"),
]


def get_profile(session_id: str) -> dict:
    return _profiles.setdefault(session_id, {})


def update_profile(session_id: str, text: str, crop_hint: str | None = None) -> dict:
    """Read the farmer's message, store anything new, and return the profile (a copy)."""
    prof = get_profile(session_id)
    low = text.lower()

    if crop_hint:
        for k, v in CROPS.items():
            if k in crop_hint.lower():
                prof["crop"] = v
                break
    for word in re.findall(r"[a-z]+", low):
        if word in CROPS:
            prof["crop"] = CROPS[word]
    for rx, label in STAGES:
        if re.search(rx, low):
            prof["stage"] = label
    for rx, label in SOILS:
        if re.search(rx, low):
            prof["soil"] = label

    details = extract_farm_details(text)
    for k in ("area_m2", "area_text", "method", "emitters", "emitter_lph", "discharge_lpm", "rate_mm_h"):
        if k in details:
            prof[k] = details[k]
    # a depth the farmer states only applies to this message, not forever
    prof["_depth_this_message"] = details.get("depth_mm")
    prof["_gave_details_now"] = any(k in details for k in ("area_m2", "method", "emitters", "emitter_lph", "discharge_lpm", "rate_mm_h", "depth_mm"))
    return dict(prof)


def format_profile(prof: dict) -> str:
    """Readable block for the prompt (empty string if nothing is known)."""
    items = []
    if prof.get("crop"):
        items.append(f"Crop: {prof['crop']}")
    if prof.get("stage"):
        items.append(f"Growth stage mentioned: {prof['stage']}")
    if prof.get("soil"):
        items.append(f"Soil type: {prof['soil']}")
    if prof.get("area_text"):
        items.append(f"Field area: {prof['area_text']}")
    if prof.get("method"):
        items.append(f"Irrigation method: {prof['method']}")
    if prof.get("emitters"):
        items.append(f"Emitters: {prof['emitters']:,}")
    if prof.get("emitter_lph"):
        items.append(f"Flow per emitter: {prof['emitter_lph']:g} L/h")
    if prof.get("discharge_lpm"):
        items.append(f"System discharge: {prof['discharge_lpm']:g} L/min")
    if prof.get("rate_mm_h"):
        items.append(f"Sprinkler rate: {prof['rate_mm_h']:g} mm/h")
    if not items:
        return ""
    return "FARM PROFILE (told by the farmer in this chat):\n" + "\n".join(items) + "\n\n"


def reset_all() -> None:
    _profiles.clear()
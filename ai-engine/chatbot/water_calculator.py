"""
Deterministic irrigation water calculator. The LLM never does this arithmetic itself - the server computes
litres and running time and the prompt tells the model to quote the result exactly.

Key facts used:
  1 mm of water on 1 m2 = 1 litre.   volume (L) = depth (mm) x area (m2)
  The advisory engine's depth estimates already include ENGINE_EFFICIENCY (0.90, drip-like). For another
  method we convert back to the net depth and divide by that method's efficiency instead.
"""

import re

try:
    import engine_config as _cfg
    ENGINE_EFFICIENCY = float(_cfg.APPLICATION_EFFICIENCY)
except Exception:  # pragma: no cover - engine_config is always present in the project
    ENGINE_EFFICIENCY = 0.90

AREA_TO_M2 = {"acre": 4046.8564, "hectare": 10000.0, "sqm": 1.0, "guntha": 101.1714}
METHOD_EFFICIENCY = {"drip": 0.90, "sprinkler": 0.75, "flood": 0.60}   # FAO-56 typical values

_NUM = r"(\d[\d,]*(?:\.\d+)?)"


def _f(x: str) -> float:
    return float(x.replace(",", ""))


def area_to_m2(value: float, unit: str) -> float:
    return value * AREA_TO_M2[unit]


# ----------------------------------------------------------------------------- text parsing
def extract_farm_details(text: str) -> dict:
    """Pull area, irrigation method and flow details out of free text. Returns only what was found."""
    t = text.lower()
    found: dict = {}

    # area
    if re.search(r"\bhalf\s+(?:an\s+)?acre", t):
        found["area_m2"], found["area_text"] = 0.5 * AREA_TO_M2["acre"], "0.5 acre"
    m = re.search(_NUM + r"\s*(acres?|hectares?|ha|gunthas?|sq\.?\s*(?:m|metres?|meters?)|square\s*(?:metres?|meters?)|m2|m²)\b", t)
    if m:
        v, u = _f(m.group(1)), m.group(2)
        if u.startswith("acre"):
            unit, label = "acre", "acre(s)"
        elif u.startswith("hect") or u == "ha":
            unit, label = "hectare", "hectare(s)"
        elif u.startswith("guntha"):
            unit, label = "guntha", "guntha"
        else:
            unit, label = "sqm", "m2"
        found["area_m2"], found["area_text"] = area_to_m2(v, unit), f"{v:g} {label}"

    # irrigation method
    if re.search(r"\bdrip|dripper|emitter", t):
        found["method"] = "drip"
    elif re.search(r"sprinkler|rain\s*gun|pivot", t):
        found["method"] = "sprinkler"
    elif re.search(r"\bflood|furrow|surface irrigation|basin|border strip|canal", t):
        found["method"] = "flood"

    # emitters / drippers
    m = re.search(_NUM + r"\s*(?:emitters?|drippers?)", t)
    if m:
        found["emitters"] = int(_f(m.group(1)))

    # per-emitter flow, e.g. "4 lph", "4 l/h dripper", "4 litres per hour emitters"
    m = re.search(_NUM + r"\s*(?:lph|l\s*/\s*h(?:r|our)?|lit(?:re|er)s?\s*(?:/|per)\s*h(?:r|our)?|l\s*per\s*h(?:r|our)?)\s*(?:per|each|/)?\s*(?:emitter|dripper)?", t)
    if m:
        v = _f(m.group(1))
        near_emitter = re.search(r"emitter|dripper|each", t[max(0, m.start() - 40): m.end() + 40])
        if near_emitter or found.get("method") == "drip":
            found["emitter_lph"] = v
        else:
            found["discharge_lpm"] = v / 60.0

    # system discharge
    m = re.search(_NUM + r"\s*(?:lpm|l\s*/\s*min(?:ute)?|lit(?:re|er)s?\s*(?:/|per)\s*min(?:ute)?|l\s*per\s*min(?:ute)?)", t)
    if m:
        found["discharge_lpm"] = _f(m.group(1))
    m = re.search(_NUM + r"\s*(?:m3|m³|cubic\s*(?:metres?|meters?))\s*(?:/|per)\s*h(?:r|our)?", t)
    if m:
        found["discharge_lpm"] = _f(m.group(1)) * 1000.0 / 60.0

    # sprinkler application rate (mm per hour)
    m = re.search(_NUM + r"\s*mm\s*(?:/|per)\s*h(?:r|our)?", t)
    if m:
        found["rate_mm_h"] = _f(m.group(1))

    # farmer-specified depth, e.g. "apply 25 mm" (ignore mm per hour)
    m = re.search(_NUM + r"\s*mm\b(?!\s*(?:/|per)\s*h)", t)
    if m:
        found["depth_mm"] = _f(m.group(1))
    return found


# ----------------------------------------------------------------------------- calculation
def _hm(minutes: float) -> str:
    minutes = round(minutes)
    h, m = divmod(minutes, 60)
    return f"{h} h {m} min" if h else f"{m} min"


def compute(area_m2: float, depth_mm: float, method: str | None = None, depth_from_engine: bool = True,
            emitters: int | None = None, emitter_lph: float | None = None,
            discharge_lpm: float | None = None, rate_mm_h: float | None = None) -> dict:
    """
    Litres and running time for one irrigation event.
      depth_from_engine=True  -> depth already includes ENGINE_EFFICIENCY; rescale for the chosen method.
      depth_from_engine=False -> depth is what the farmer wants to apply (gross); used as given.
    """
    assumed_method = method is None
    method = method or "drip"
    eff = METHOD_EFFICIENCY[method]
    gross_mm = depth_mm * ENGINE_EFFICIENCY / eff if depth_from_engine else depth_mm
    litres = gross_mm * area_m2

    out = {"method": method, "method_assumed": assumed_method, "efficiency": eff, "area_m2": area_m2,
           "depth_mm_used": gross_mm, "litres": litres, "cubic_metres": litres / 1000.0,
           "litres_per_mm": area_m2, "duration_min": None, "duration_basis": None}

    total_lph = emitters * emitter_lph if emitters and emitter_lph else None
    if total_lph:
        out["duration_min"] = litres / total_lph * 60.0
        out["duration_basis"] = f"{emitters:,} emitters x {emitter_lph:g} L/h = {total_lph:,.0f} L/h"
    elif discharge_lpm:
        out["duration_min"] = litres / discharge_lpm
        out["duration_basis"] = f"system discharge {discharge_lpm:g} L/min"
    elif rate_mm_h:
        out["duration_min"] = gross_mm / rate_mm_h * 60.0
        out["duration_basis"] = f"application rate {rate_mm_h:g} mm/h"
    return out


def describe(area_text: str, depth_range: tuple[float, float] | None, depth_mid: float | None,
             depth_source: str, area_m2: float, details: dict) -> str:
    """Build the plain-text CALCULATION RESULT block that goes into the prompt."""
    lines = [f"Field area: {area_text} = {area_m2:,.0f} m2.",
             f"Litres needed per 1 mm of water applied over this field: {area_m2:,.0f} L (1 mm on 1 m2 = 1 L)."]
    method = details.get("method")
    if depth_mid is None:
        lines.append("No irrigation depth is available (no live analysis and no depth given), so only litres per mm can be stated.")
        return "\n".join(lines)

    from_engine = depth_source == "engine"
    kw = dict(emitters=details.get("emitters"), emitter_lph=details.get("emitter_lph"),
              discharge_lpm=details.get("discharge_lpm"), rate_mm_h=details.get("rate_mm_h"))
    mid = compute(area_m2, depth_mid, method, from_engine, **kw)
    lo = compute(area_m2, depth_range[0], method, from_engine, **kw) if depth_range else mid
    hi = compute(area_m2, depth_range[1], method, from_engine, **kw) if depth_range else mid

    m_txt = mid["method"] + (" (ASSUMED - method not given)" if mid["method_assumed"] else "")
    lines.append(f"Depth basis: {depth_source}. Irrigation method: {m_txt}, efficiency {mid['efficiency']:.0%}.")
    if depth_range and depth_range[0] != depth_range[1]:
        lines.append(f"Water for one irrigation event: about {lo['litres']:,.0f} to {hi['litres']:,.0f} litres "
                     f"({lo['cubic_metres']:,.1f} to {hi['cubic_metres']:,.1f} m3), "
                     f"i.e. {lo['depth_mm_used']:.0f} to {hi['depth_mm_used']:.0f} mm applied; best estimate {mid['litres']:,.0f} litres.")
    else:
        lines.append(f"Water for one irrigation event: about {mid['litres']:,.0f} litres ({mid['cubic_metres']:,.1f} m3), "
                     f"i.e. {mid['depth_mm_used']:.0f} mm applied.")
    if mid["duration_min"] is not None:
        if depth_range and depth_range[0] != depth_range[1]:
            lines.append(f"Running time ({mid['duration_basis']}): about {_hm(lo['duration_min'])} to {_hm(hi['duration_min'])}; "
                         f"best estimate {_hm(mid['duration_min'])}.")
        else:
            lines.append(f"Running time ({mid['duration_basis']}): about {_hm(mid['duration_min'])}.")
    else:
        lines.append("Running time cannot be calculated yet: ask the farmer for ONE missing item - for drip the number of emitters "
                     "and flow per emitter (L/h); for sprinkler or flood the system discharge (L/min) or sprinkler rate (mm/h).")
    if mid["method_assumed"]:
        sp = compute(area_m2, depth_mid, "sprinkler", from_engine)
        fl = compute(area_m2, depth_mid, "flood", from_engine)
        lines.append(f"If the method is different: sprinkler about {sp['litres']:,.0f} L, flood about {fl['litres']:,.0f} L for the same benefit.")
    lines.append("Assumptions: efficiency drip 90%, sprinkler 75%, flood 60% (FAO-56 typical); real flow changes with pressure, clogging and pump condition.")
    return "\n".join(lines)
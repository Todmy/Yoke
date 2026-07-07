"""Normalize raw job comp into net USD/month + a floor verdict.

Fixes the class of bug where an hourly/daily/yearly rate is treated as monthly.
Deterministic: no LLM guessing on arithmetic. The LLM decides fit; this decides
the number. Read from the source's own `unit` field — never infer unit from
magnitude.

Entry fields (all optional except a min or max):
  min, max      numbers in the SOURCE currency+unit (e.g. 45 for "45 PLN/h")
  currency      usd|eur|pln|gbp|chf  (default usd)
  unit          hour|day|month|year  (default month)
  type          b2b|permanent|uop    (default b2b)  — affects net factor
  raw           optional raw string, parsed only when min/max absent

Output adds: usd_min_mo, usd_max_mo, unit_detected, floor_verdict, floor, note
"""
import re

# Rough FX to USD (2026 ballpark). justjoin already ships USD, so this mostly
# matters for nofluff (PLN) and EU boards. Update if rates drift materially.
FX_TO_USD = {"usd": 1.0, "eur": 1.08, "gbp": 1.27, "chf": 1.12, "pln": 0.25}
HOURS_PER_MO = 168      # ~21 working days x 8h
DAYS_PER_MO = 21
# B2B invoice ~= take-home-ish; UoP/permanent gross needs a net haircut. Rough.
NET_FACTOR = {"b2b": 1.0, "permanent": 0.72, "uop": 0.72}
DEFAULT_FLOOR = 10000   # candidate brief: $10k net/mo (passive floor).


def _to_month(value, unit):
    if value is None:
        return None
    unit = (unit or "month").lower()
    if unit.startswith("hour") or unit == "h":
        return value * HOURS_PER_MO
    if unit.startswith("day") or unit == "d":
        return value * DAYS_PER_MO
    if unit.startswith("year") or unit in ("y", "yr", "annum"):
        return value / 12.0
    return value  # month


def _parse_raw(raw):
    """Best-effort: pull a min-max, currency, unit, type from a free string."""
    s = (raw or "").lower()
    nums = [float(n.replace(" ", "")) for n in re.findall(r"\d[\d ]*\d|\d", s)]
    lo = nums[0] if nums else None
    hi = nums[1] if len(nums) > 1 else lo
    cur = next((c for c in FX_TO_USD if c in s or (c == "pln" and "zł" in s)), "usd")
    if "/h" in s or "hour" in s or "/hr" in s or "godz" in s:
        unit = "hour"
    elif "/day" in s or "/d" in s or "daily" in s or "dzień" in s:
        unit = "day"
    elif "year" in s or "/yr" in s or "annum" in s or "rok" in s:
        unit = "year"
    else:
        unit = "month"
    typ = "permanent" if ("uop" in s or "permanent" in s or "employment" in s) else "b2b"
    return {"min": lo, "max": hi, "currency": cur, "unit": unit, "type": typ}


def normalize(entry: dict, floor: int = DEFAULT_FLOOR) -> dict:
    e = dict(entry)
    if e.get("min") is None and e.get("max") is None and e.get("raw"):
        e.update({k: v for k, v in _parse_raw(e["raw"]).items() if e.get(k) is None})
    cur = (e.get("currency") or "usd").lower()
    unit = (e.get("unit") or "month").lower()
    typ = (e.get("type") or "b2b").lower()
    fx = FX_TO_USD.get(cur, 1.0)
    net = NET_FACTOR.get(typ, 1.0)

    def conv(v):
        m = _to_month(v, unit)
        return None if m is None else round(m * fx * net)

    lo, hi = conv(e.get("min")), conv(e.get("max"))
    hi = hi or lo
    lo = lo or hi
    if lo is None:
        verdict, note = "unknown", "no salary figure"
    else:
        top = hi or lo
        if top >= floor:
            verdict = "above" if lo >= floor else "straddles"
        else:
            verdict = "below"
        note = f"{cur.upper()} {unit} {typ} -> net USD/mo"
    e.update({
        "usd_min_mo": lo, "usd_max_mo": hi,
        "unit_detected": unit, "floor_verdict": verdict,
        "floor": floor, "note": note,
    })
    return e

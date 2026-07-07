"""justjoin.it — PL B2B aggregator, public JSON API with real salaries.

Discovery by category (role/tech), never by company. Offers ship
USD-converted salary ranges per employment type; comp is emitted as a
STRUCTURED dict — never a preformatted string (see _comp).
"""

import json
import urllib.request

from src import collect

NAME = "justjoin"
TAGS = {"domain": "it", "country": "pl"}
COST = "free"

# categoryId: 1=JS/TS (bridge), 5=Python, 25=AI.
CATEGORIES = (1, 5, 25)

_UA = "Mozilla/5.0 (compatible; yoke/0.1)"


def available():
    return True, ""


def fetch(profile):
    out = []
    for cat in CATEGORIES:
        url = (
            "https://api.justjoin.it/v2/user-panel/offers"
            f"?categories[]={cat}&perPage=100"
        )
        req = urllib.request.Request(
            url, headers={"User-Agent": _UA, "Version": "2"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        out.extend(_parse(payload, profile))
    return out


def _unit(entry):
    """Map the employment entry's salary period field to a comp unit."""
    u = (entry.get("unit") or "").lower()
    if "hour" in u:
        return "hour"
    if "day" in u:
        return "day"
    if "year" in u or "annum" in u:
        return "year"
    return "month"


def _comp(ets):
    """employmentTypes -> structured comp dict; prefer b2b, fall back to any.

    Regression guard: the prototype's _jj_comp emitted "$lo-hi/mo" ignoring
    the salary period, so per-hour B2B rates read as monthly. Emit the unit
    explicitly and let src/comp.py do the arithmetic downstream.
    """
    for want in ("b2b", None):
        for e in ets or []:
            if (want is None or e.get("type") == want) and (
                e.get("fromUsd") or e.get("toUsd")
            ):
                return {
                    "min": int(e.get("fromUsd") or 0),
                    "max": int(e.get("toUsd") or 0),
                    "currency": "usd",
                    "unit": _unit(e),
                    "type": e.get("type") or "",
                }
    return None


def _parse(payload, profile):
    out = []
    for o in (payload or {}).get("data") or []:
        wt = (o.get("workplaceType") or "").lower()
        if wt == "office":
            continue  # remote hard-gate — skip pure on-site
        city = o.get("city") or ""
        loc = "Remote (Poland)" if wt == "remote" else f"{city}, Poland".strip(", ")
        url = f"https://justjoin.it/job-offer/{o.get('slug') or ''}"
        out.append(
            collect.norm(
                o.get("title"),
                o.get("companyName"),
                loc,
                url,
                NAME,
                posted_at=o.get("publishedAt") or "",
                comp=_comp(o.get("employmentTypes")),
            )
        )
    return out

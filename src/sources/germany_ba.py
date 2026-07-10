"""Germany Bundesagentur für Arbeit (BA) source plugin (free JSON API).

One GET against the public jobsuche endpoint, keyed by the fixed public
X-API-Key the mobile app ships. Country-gated: because available() takes no
profile, the gate lives in fetch() — it never touches the network unless the
profile selects Germany (or all-eu). _parse handles a single response payload.

The search entries carry no full description, so jd stays "" (a detail GET is
deferred); comp is None (the endpoint exposes no structured pay).
"""

import json
import urllib.parse

from src import http
from src.collect import norm

NAME = "germany_ba"
TAGS = {"domain": "any", "country": "de"}
COST = "free"

HELP = """\
Germany Bundesagentur für Arbeit (BA) — the federal jobs API (free).
Returns: German-market postings; country-gated to run when profile.countries
includes DE.
Setup: none — works out of the box.
"""

API_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/app/jobs"
API_KEY = "jobboerse-jobsuche"
DETAIL_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
PAGE_SIZE = 50


def available():
    return True, ""


def fetch(profile):
    profile = profile or {}
    if {"de", "all-eu"}.isdisjoint(set(profile.get("countries", []))):
        return []
    keywords = profile.get("lane", {}).get("keywords") or []
    was = " ".join(keywords)
    query = urllib.parse.urlencode({"was": was, "wo": "Deutschland", "size": PAGE_SIZE})
    try:
        payload = json.loads(
            http.fetch_bytes(f"{API_URL}?{query}", headers={"X-API-Key": API_KEY})
        )
    except Exception:
        return []  # Blocked / HTTP / decode error → graceful skip (never raise past fetch)
    return _parse(payload, profile)


def _parse(payload, profile):
    out = []
    if not isinstance(payload, dict) or "stellenangebote" not in payload:
        return out
    for e in payload["stellenangebote"]:
        if not isinstance(e, dict):
            continue
        ort = e.get("arbeitsort", {})
        loc_parts = [ort.get("ort"), ort.get("land")]
        location = ", ".join(p for p in loc_parts if p)
        url = e.get("externeUrl") or DETAIL_URL.format(refnr=e.get("refnr", ""))
        # the search endpoint carries no description → jd defaults to "" (a
        # detail GET is deferred); comp defaults None (no structured pay field).
        out.append(
            norm(
                e.get("titel") or e.get("beruf"),
                e.get("arbeitgeber"),
                location,
                url,
                NAME,
                e.get("aktuelleVeroeffentlichungsdatum", ""),
            )
        )
    return out

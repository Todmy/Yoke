"""EURES source plugin (EU public job-vacancy search, keyless JSON POST).

One POST per scan to the public jv-search endpoint. The country seam is
`locationCodes` (from profile.countries), the query seam is `keywords`
(from the lane). The search payload carries no structured salary and no
job URL, so comp is always None and the detail link is built from the
hit id. Full-JD detail GETs are deferred (volume bound): jd is the
search summary only.
"""

import json
from datetime import datetime, timezone

from src import http
from src.collect import JD_MAX_CHARS, norm, strip_html

NAME = "eures"
TAGS = {"domain": "any", "country": "any"}
COST = "free"

SEARCH_URL = "https://europa.eu/eures/api/jv-searchengine/public/jv-search/search"
DETAIL_URL = "https://europa.eu/eures/portal/jv-se/jv-details/"
RESULTS_PER_PAGE = 50


def available():
    return True, ""


def _location_codes(profile):
    """profile.countries -> EURES locationCodes. Empty / all-eu -> no filter."""
    return [c for c in (profile or {}).get("countries", []) if c and c != "all-eu"]


def _keywords(profile):
    return list((profile or {}).get("lane", {}).get("keywords") or [])


def _body(profile):
    return {
        "resultsPerPage": RESULTS_PER_PAGE,
        "page": 1,
        "sortSearch": "MOST_RECENT",
        "keywords": [
            {"keyword": k, "specificSearchCode": "EVERYWHERE"}
            for k in _keywords(profile)
        ],
        "locationCodes": _location_codes(profile),
        "publicationPeriod": None,
        "occupationUris": [],
        "skillUris": [],
        "requiredExperienceCodes": [],
        "positionScheduleCodes": [],
        "sectorCodes": [],
        "educationAndQualificationLevelCodes": [],
        "positionOfferingCodes": [],
        "euresFlagCodes": [],
        "otherBenefitsCodes": [],
        "requiredLanguages": [],
        "minNumberPost": None,
        "sessionId": "yoke",
        "requestLanguage": "en",
    }


def fetch(profile):
    body = _body(profile)
    try:
        payload = json.loads(
            http.fetch_bytes(
                SEARCH_URL,
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
            )
        )
    except Exception:
        return []  # Blocked / HTTP / decode error → graceful skip (never raise past fetch)
    return _parse(payload, profile)


def _location(hit):
    loc = hit.get("locationMap")
    return ", ".join(loc.keys()) if isinstance(loc, dict) else ""


def _url(hit):
    jid = (hit.get("id") or "").strip()
    return f"{DETAIL_URL}{jid}" if jid else ""


def _posted(hit):
    ms = hit.get("creationDate")
    if not isinstance(ms, (int, float)):
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _parse(payload, profile):
    """Pure: one norm() per hit in jvs[]. Malformed/empty -> []."""
    out = []
    if not isinstance(payload, dict):
        return out
    jvs = payload.get("jvs")
    if not isinstance(jvs, list):
        return out
    for j in jvs:
        if not isinstance(j, dict):
            continue
        out.append(norm(
            j.get("title"), (j.get("employer") or {}).get("name"),
            _location(j), _url(j), NAME, _posted(j), None,
            jd=strip_html(j.get("description"))[:JD_MAX_CHARS],
        ))
    return out

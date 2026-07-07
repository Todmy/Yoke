"""Remotive source plugin (free JSON API, no key).

One GET per search query; queries come from profile lane keywords with a
prototype-matching fallback. _parse handles a single response payload.
"""

import json
import urllib.parse
import urllib.request

from src.collect import norm

NAME = "remotive"
TAGS = {"domain": "it", "country": "intl"}
COST = "free"

API_URL = "https://remotive.com/api/remote-jobs"
UA = "yoke/0.1"
TIMEOUT = 20
DEFAULT_QUERIES = ("ai engineer", "machine learning", "solutions architect")


def available():
    return True, ""


def _queries(profile):
    kws = (profile or {}).get("lane", {}).get("keywords")
    return list(kws) if kws else list(DEFAULT_QUERIES)


def fetch(profile):
    out = []
    for q in _queries(profile):
        url = f"{API_URL}?{urllib.parse.urlencode({'search': q, 'limit': 40})}"
        req = urllib.request.Request(
            url, headers={"User-Agent": UA, "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            payload = json.loads(r.read())
        out.extend(_parse(payload, profile))
    return out


def _parse(payload, profile):
    out = []
    if not isinstance(payload, dict) or "jobs" not in payload:
        return out
    for j in payload["jobs"]:
        out.append(
            norm(
                j.get("title"), j.get("company_name"),
                j.get("candidate_required_location", "Remote"),
                j.get("url"), NAME, j.get("publication_date", ""),
            )
        )
    return out

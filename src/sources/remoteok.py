"""RemoteOK source plugin (free JSON API, no key).

API quirk: the response is a list whose FIRST element is a metadata/legal
notice dict (no "position" key) — _parse skips any element without one.
"""

import json
import urllib.request

from src.collect import norm

NAME = "remoteok"
TAGS = {"domain": "it", "country": "intl"}
COST = "free"

API_URL = "https://remoteok.com/api"
UA = "yoke/0.1"
TIMEOUT = 20


def available():
    return True, ""


def fetch(profile):
    req = urllib.request.Request(
        API_URL, headers={"User-Agent": UA, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        payload = json.loads(r.read())
    return _parse(payload, profile)


def _parse(payload, profile):
    out = []
    if not isinstance(payload, list):
        return out
    for j in payload:
        if not isinstance(j, dict) or "position" not in j:
            continue  # legal-notice / metadata element
        out.append(
            norm(
                j.get("position"), j.get("company"), j.get("location", "Remote"),
                j.get("url"), NAME, j.get("date", ""),
            )
        )
    return out

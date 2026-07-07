"""workingnomads.com source plugin — clean JSON feed of recent dev roles.

Net-new vs RemoteOK/Remotive: indexes companies the others miss and carries
a real location field, so the geo gate works well on it.
"""

import json
import urllib.request

from src.collect import norm

NAME = "workingnomads"
TAGS = {"domain": "it", "country": "intl"}
COST = "free"

API_URL = "https://www.workingnomads.com/api/exposed_jobs/"
UA = "Mozilla/5.0 (compatible; yoke/0.1)"


def available():
    return True, ""


def fetch(profile):
    req = urllib.request.Request(API_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = resp.read().decode("utf-8", "replace")
    return _parse(payload, profile)


def _parse(payload, profile):
    """JSON list of job dicts -> list[norm]. Anything malformed -> []."""
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for j in data:
        if not isinstance(j, dict) or not j.get("title"):
            continue
        out.append(
            norm(
                j.get("title"),
                j.get("company_name"),
                j.get("location", "Remote"),
                j.get("url"),
                NAME,
                j.get("pub_date", ""),
            )
        )
    return out

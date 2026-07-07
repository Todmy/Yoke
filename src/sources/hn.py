"""HN who-is-hiring source: latest "Ask HN: Who is hiring?" thread via Algolia.

Comments mentioning "remote" become records; their first 160 plain-text chars
stand in for a title, so the module sets bypass_lane — collect.run_collect
skips the lane-keyword-in-title rule and gates on tech hits instead.
"""

import json
import re
import urllib.request

from src.collect import norm

NAME = "hn"
TAGS = {"domain": "it", "country": "intl"}
COST = "free"
bypass_lane = True  # comment titles aren't job titles

SEARCH_URL = (
    "https://hn.algolia.com/api/v1/search"
    "?query=%22Ask%20HN%3A%20Who%20is%20hiring%3F%22&tags=story&hitsPerPage=1"
)
ITEM_URL = "https://hn.algolia.com/api/v1/items/{id}"
UA = "yoke/0.1"
TIMEOUT = 20


def available():
    return True, ""


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_thread_search(payload):
    """Algolia search payload -> objectID of the latest who-is-hiring story."""
    hits = (payload or {}).get("hits") or []
    if not hits:
        return None
    return hits[0].get("objectID")


def _parse_comments(payload, profile):
    """Algolia item payload -> norm records for comments mentioning remote."""
    out = []
    for c in (payload or {}).get("children") or []:
        txt = c.get("text") or ""
        if not txt or "remote" not in txt.lower():
            continue
        plain = re.sub(r"<[^>]+>", " ", txt)
        plain = re.sub(r"\s+", " ", plain).strip()
        url = f"https://news.ycombinator.com/item?id={c.get('id')}"
        out.append(
            norm(plain[:160], "(HN who-is-hiring)", "see post", url, NAME,
                 str(c.get("created_at") or ""))
        )
    return out


def fetch(profile):
    story_id = _parse_thread_search(_get_json(SEARCH_URL))
    if not story_id:
        return []
    return _parse_comments(_get_json(ITEM_URL.format(id=story_id)), profile)

"""weworkremotely.com source plugin — regex-parse the programming-jobs RSS.

Deliberately regex, not an XML parser: stdlib XML parsers are XXE-prone and
defusedxml is not stdlib. The feed is a trusted fixed shape with
<title>Company: Role</title> items.
"""

import re
import urllib.request

from src.collect import norm

NAME = "wwr"
TAGS = {"domain": "it", "country": "intl"}
COST = "free"

FEED_URL = "https://weworkremotely.com/categories/remote-programming-jobs.rss"
UA = "Mozilla/5.0 (compatible; yoke/0.1)"


def available():
    return True, ""


def fetch(profile):
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = resp.read().decode("utf-8", "replace")
    return _parse(payload, profile)


def _tag(block, name):
    """First <name>...</name> value in block; CDATA unwrapped; '' if absent."""
    m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", block, re.S)
    if not m:
        return ""
    val = m.group(1).strip()
    cm = re.search(r"<!\[CDATA\[(.*?)\]\]>", val, re.S)
    return (cm.group(1) if cm else val).strip()


def _parse(payload, profile):
    """RSS text -> list[norm]. Titles split as 'Company: Role'."""
    out = []
    for block in re.findall(r"<item>(.*?)</item>", payload or "", re.S):
        title = _tag(block, "title")
        link = _tag(block, "link")
        region = _tag(block, "region") or "Remote"
        company = title.split(":")[0].strip() if ":" in title else ""
        role = title.split(":", 1)[1].strip() if ":" in title else title
        out.append(norm(role, company, region, link, NAME, _tag(block, "pubDate")))
    return out

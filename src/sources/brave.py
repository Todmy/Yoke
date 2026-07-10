"""Source plugin: Brave web-search dorks over ATS hosts + PL aggregators.

COST="key" — needs BRAVE_API_KEY in the environment (v0 checks ONLY the env
var). Dork queries are built from the profile's lane keywords and target ATS
hosts that carry thousands of company boards (the hidden recruiter layer),
plus PL/EU aggregators whose direct feeds are WAF-blocked or API-less
(nofluffjobs) but which Brave indexes. The 1.1 s inter-query sleep (Brave
free tier ~1 req/s) lives in fetch, never in _parse.
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request

from src.collect import EU_TERMS, NON_EU, norm

NAME = "brave"
TAGS = {"domain": "any", "country": "any"}
COST = "key"

HELP = """\
Brave Search — web-search dorks over ATS hosts + PL aggregators.
Returns: postings matched by lane-keyword dorks against job-board hosts.
Setup: needs a Brave Search API key.
  1. Get a key: https://brave.com/search/api/
  2. export BRAVE_API_KEY=<key>
Notes: paid API (a free tier ~2k queries/mo exists); the key is read only from
the environment.
"""

API_URL = "https://api.search.brave.com/res/v1/web/search"
TIMEOUT = 20
SLEEP_BETWEEN_QUERIES = 1.1

# ATS hosts to dork — finds roles at companies not in any watchlist.
_ATS_DORK_HOSTS = (
    "job-boards.greenhouse.io",
    "boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "apply.workable.com",
)
# PL/EU B2B aggregators — discovery by role+tech, not by company. nofluffjobs
# has no usable API (its search endpoints 500 / ignore criteria), so the
# Brave dork covers it instead.
_PL_AGG_DORK_HOSTS = ("justjoin.it", "nofluffjobs.com")

_ATS_HOST_RE = re.compile(
    r"https?://(?:job-boards|boards)\.greenhouse\.io/([^/]+)|"
    r"https?://jobs\.lever\.co/([^/]+)|"
    r"https?://jobs\.ashbyhq\.com/([^/]+)|"
    r"https?://apply\.workable\.com/([^/]+)"
)
# Hosts whose job URLs carry no company slug — attribute the company from the
# result title, best-effort. On these hosts a role is KEPT even when parsing
# fails: discovery of companies we don't know exists is the whole point.
_SOFT_HOSTS = (
    "justjoin.it", "nofluffjobs.com", "theprotocol.it",
    "workatastartup.com", "wellfound.com", "startup.jobs",
)
_TITLE_COMPANY_RE = re.compile(r"\bat\s+(.+?)(?:\s*[|\-–—]|$)", re.IGNORECASE)
# Board-name tails + category/location noise tokens to strip when splitting a
# "Role - Company - Board" or "Role Job | Cat | Company | Remote | Board" title.
_BOARD_NAMES = {
    "just join it", "justjoinit", "just join it - #1 job board for tech",
    "no fluff jobs", "nofluffjobs", "theprotocol.it", "the protocol",
    "wellfound", "y combinator", "y combinator's work at a startup",
    "work at a startup", "startup.jobs",
    # pipe-format category/location tags (never a company)
    "ai", "data", "remote", "hybrid", "on-site", "onsite", "fullremote",
}


def available():
    if os.environ.get("BRAVE_API_KEY"):
        return (True, "")
    return (False, "BRAVE_API_KEY not set")


def _dork_queries(profile):
    kws = [k for k in ((profile.get("lane") or {}).get("keywords") or []) if k]
    if not kws:
        return []
    or_block = "(" + " OR ".join(f'"{k}"' for k in kws) + ")"
    return [f"site:{h} {or_block} remote" for h in _ATS_DORK_HOSTS + _PL_AGG_DORK_HOSTS]


def fetch(profile):
    key = os.environ.get("BRAVE_API_KEY", "")
    out = []
    for i, q in enumerate(_dork_queries(profile)):
        if i:
            time.sleep(SLEEP_BETWEEN_QUERIES)  # Brave free tier: ~1 req/s
        url = API_URL + "?" + urllib.parse.urlencode({"q": q, "count": 20})
        req = urllib.request.Request(url, headers={
            "X-Subscription-Token": key,
            "Accept": "application/json",
            "User-Agent": "yoke/0.1",
        })
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        out.extend(_parse(payload, q))
    return out


def _company_from_url(url):
    m = _ATS_HOST_RE.search(url or "")
    if not m:
        return ""
    slug = next((g for g in m.groups() if g), "")
    return slug.replace("-", " ").replace("_", " ").title()


def _company_from_title(title):
    # "Software Engineer at Lago | Y Combinator's Work at a Startup" -> "Lago"
    m = _TITLE_COMPANY_RE.search(title or "")
    if m:
        return m.group(1).strip()
    # "Role - Company - Board" / "Role @ Company" (justjoin);
    # "Role Job | Cat | Company | Remote | Board" (nofluff, pipe-separated).
    parts = [p.strip() for p in re.split(r"\s*[|]\s*|\s[-–—@]\s+", title or "") if p.strip()]
    parts = [p for p in parts if p.lower().rstrip(".").strip() not in _BOARD_NAMES]
    if len(parts) >= 2:
        return parts[-1]  # last non-board, non-noise segment = usually the company
    return ""


def _parse(payload, query):
    """Brave web-search payload -> list of norm records. Pure, no I/O."""
    results = ((payload or {}).get("web") or {}).get("results") or []
    out = []
    for r in results:
        link = r.get("url", "")
        title = r.get("title", "")
        host = link.split("/")[2].lower() if "://" in link else ""
        company = _company_from_url(link)
        is_soft_host = any(h in host for h in _SOFT_HOSTS)
        if not company and is_soft_host:
            company = _company_from_title(title)
        if not company:
            if is_soft_host:
                # keep the role visible even unattributed — discovery hosts
                company = f"{host} (unattributed)" if host else "unknown"
            else:
                continue  # generic host we can't attribute — not a job board hit
        desc = (r.get("description") or "").lower()
        loc = next((w.title() for w in EU_TERMS + NON_EU if w.strip() and w in desc), "")
        # jd stays empty: search snippets aren't the JD — full JD needs per-offer fetch — M1
        out.append(norm(title, company, loc, link, f"dork:{host or 'dork'}"))
    return out

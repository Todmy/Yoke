"""justjoin.it — PL B2B aggregator, public JSON API with real salaries.

Discovery by category (role/tech), never by company. Offers ship
USD-converted salary ranges per employment type; comp is emitted as a
STRUCTURED dict — never a preformatted string (see _comp).

The list API carries no full JD, so fetch() enriches each record with a
per-offer GET of the offer page, pulling the description out of its
server-rendered JSON-LD JobPosting block. JD is fetched once ever and
cached to home()/jd_cache.json ({url: jd_text}) so a re-scan never refetches.
"""

import json
import re
import urllib.request

from src import collect, http
from src.paths import ensure_home, home

NAME = "justjoin"
TAGS = {"domain": "it", "country": "pl"}
COST = "free"

HELP = """\
justjoin.it — Polish B2B tech aggregator (public JSON, real salaries).
Returns: PL/remote roles discovered by category, with structured USD-converted
comp.
Setup: none — works out of the box.
"""

# categoryId: 1=JS/TS (bridge), 5=Python, 25=AI.
CATEGORIES = (1, 5, 25)

_UA = "Mozilla/5.0 (compatible; yoke/0.1)"

_JD_CACHE = "jd_cache.json"
_LD_JSON_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I
)


def available():
    return True, ""


def _jd_cache_load() -> dict:
    """Read home()/jd_cache.json ({url: jd_text}); missing/garbage -> {}."""
    path = home() / _JD_CACHE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _jd_cache_save(cache: dict) -> None:
    """Write the {url: jd_text} cache back to home()/jd_cache.json."""
    ensure_home()
    path = home() / _JD_CACHE
    path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _extract_jd(html_text: str) -> str:
    """Pull the JobPosting description from the offer page's JSON-LD block.

    justjoin renders the offer body client-side (Next.js) but ships a
    server-side <script type="application/ld+json"> JobPosting whose
    `description` carries the full text. Degrade to "" if absent/unparseable.
    """
    for block in _LD_JSON_RE.findall(html_text):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if isinstance(node, dict) and node.get("@type") == "JobPosting":
                desc = node.get("description")
                if desc:
                    return str(desc)
    return ""


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

    # Enrich with per-offer full JD; cache short-circuits refetch (once ever).
    cache = _jd_cache_load()
    for record in out:
        url = record["url"]
        if url in cache:
            record["jd"] = cache[url]
            continue
        try:
            raw = http.fetch_bytes(url, headers={"User-Agent": _UA})
        except Exception:
            continue  # jd stays "", role kept — a dead offer never drops it
        jd = collect.strip_html(
            _extract_jd(raw.decode("utf-8", "replace"))
        )[: collect.JD_MAX_CHARS]
        record["jd"] = jd
        cache[url] = jd
    _jd_cache_save(cache)
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
            collect.norm(  # jd stays empty: full JD needs per-offer fetch — M1
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

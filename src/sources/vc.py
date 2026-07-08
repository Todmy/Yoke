"""VC-portfolio discovery: turn a fund's portfolio into ATS job roles.

YC (public JSON API) and a16z (portfolio page — no JSON API, the company array
is embedded in the HTML as an entity-escaped blob) are crawled for company
names/websites. Each company's ATS is discovered once by probing the same
public endpoints ats.py already knows (greenhouse/lever/ashby/personio/
smartrecruiters/workable/recruitee); the result is cached in
home()/vc_companies.json so re-runs never re-probe. Roles are then emitted
through the real ats parsers, so a vc role is indistinguishable from a direct
ats role (same source="ats:{provider}:{slug}", same 8-key shape).

Network lives in the list-loaders and _probe/emit; parsing is delegated to
ats._PARSERS so tests feed fixtures straight in — no network in tests.
"""

import html
import json
import re
import urllib.parse

from src import http
from src.paths import ensure_home, home
from src.sources import ats

NAME = "vc"
TAGS = {"domain": "any", "country": "any"}
COST = "free"

CAP = 40  # max new (unprobed) companies per scan — bounds the probe fan-out

YC_URL = "https://api.ycombinator.com/v0.1/companies"
A16Z_URL = "https://a16z.com/portfolio/"

# a16z has no JSON API; its /portfolio/ HTML embeds the company array as an
# entity-escaped attribute. This marker is UNVERIFIED — confirm live in stage 6.
_A16Z_MARKER = 'data-portfolio-companies="'

_CACHE_FILE = "vc_companies.json"


def available():
    return (True, "")


# --- cache: {slug: provider|"none"} ---------------------------------------

def _cache_load():
    path = home() / _CACHE_FILE
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _cache_save(cache):
    ensure_home()
    (home() / _CACHE_FILE).write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# --- slug derivation: an ATS board slug is usually the bare domain name ----

def _domain_slug(website):
    """Registrable label of a company website -> probe slug.

    'https://simantic.dev/' -> 'simantic'; 'http://coasty.ai/' -> 'coasty'.
    """
    host = urllib.parse.urlsplit(website or "").netloc or (website or "")
    host = host.lower().split("/")[0].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host.split(".")[0] if host else ""


def _slugify(name):
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def _company(name, website):
    slug = _domain_slug(website) or _slugify(name)
    return {"slug": slug, "name": name or slug}


# --- portfolio list loaders (best-effort, degrade to []) ------------------

def _load_yc():
    try:
        payload = ats._get_json(YC_URL)
        return [
            _company(c.get("name"), c.get("website"))
            for c in payload.get("companies", [])
            if c.get("website") or c.get("name")
        ]
    except Exception:
        return []


def _extract_a16z_json(html_text):
    """Pull a16z's entity-escaped company array out of the portfolio HTML."""
    start = html_text.index(_A16Z_MARKER) + len(_A16Z_MARKER)
    end = html_text.index('"', start)
    return json.loads(html.unescape(html_text[start:end]))


def _load_a16z():
    try:
        raw = http.fetch_bytes(A16Z_URL, headers={"User-Agent": ats.UA})
        companies = _extract_a16z_json(raw.decode("utf-8", "replace"))
        return [
            _company(
                c.get("name") or c.get("post_title"),
                c.get("company_url") or c.get("url") or c.get("external_url"),
            )
            for c in companies
        ]
    except Exception:
        return []


def _load_companies(portfolios):
    out = []
    for name in portfolios:
        if name == "yc":
            out += _load_yc()
        elif name == "a16z":
            out += _load_a16z()
    return out


# --- ATS discovery --------------------------------------------------------

def _probe(slug):
    """Discover a company's ATS by trying each provider's public endpoint.

    Returns the first provider whose feed parses into >=1 role, else "none".
    A failure/Blocked on any provider just moves on to the next.
    """
    for provider, url_tmpl in ats._URLS.items():
        try:
            url = url_tmpl.format(slug=slug)
            payload = ats._get_xml(url) if provider in ats._XML_ATS else ats._get_json(url)
            if ats._PARSERS[provider](payload, {"slug": slug}):
                return provider
        except Exception:
            continue
    return "none"


def fetch(profile):
    conf = (profile.get("sources") or {}).get("vc") or {}
    if not conf.get("enabled", True):
        return []
    cap = conf.get("cap", CAP)
    portfolios = conf.get("portfolios", ["yc", "a16z"])

    companies = _load_companies(portfolios)
    names = {c["slug"]: c["name"] for c in companies if c["slug"]}

    cache = _cache_load()
    seen = set(cache)
    new = []
    for c in companies:
        slug = c["slug"]
        if slug and slug not in seen:
            seen.add(slug)
            new.append(slug)
            if len(new) >= cap:
                break
    for slug in new:
        cache[slug] = _probe(slug)
    _cache_save(cache)

    out = []
    for slug, provider in cache.items():
        if provider == "none":
            continue
        try:
            url = ats._URLS[provider].format(slug=slug)
            payload = ats._get_xml(url) if provider in ats._XML_ATS else ats._get_json(url)
            out += ats._PARSERS[provider](payload, {"slug": slug, "name": names.get(slug, slug)})
        except Exception:
            continue
    return out

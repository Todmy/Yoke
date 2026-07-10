"""Company ATS boards: greenhouse / lever / ashby / personio / smartrecruiters
/ workable / recruitee public APIs.

Companies come from profile["sources"]["companies"] as [{slug, ats}].
Network (fetch) is split from parsing (_parse_*) so tests feed fixtures
straight into the parsers — no network in tests.

Personio ships an untrusted XML feed. It is parsed with **defusedxml**
(optional dependency, lazy-imported inside `_get_xml` so it never trips the
no-module-level-third-party-import invariant). If defusedxml is not installed
personio companies are skipped, never the whole scan. Stdlib `xml.etree` must
never touch network XML — it is open to XXE / billion-laughs attacks.
"""

import json
import sys

from src import http
from src.collect import JD_MAX_CHARS, norm, strip_html

NAME = "ats"
TAGS = {"domain": "it", "country": "any"}
COST = "free"

HELP = """\
Company ATS boards — greenhouse / lever / ashby / personio / smartrecruiters /
workable / recruitee public APIs.
Returns: open roles from the companies you list in profile.sources.companies
([{slug, ats}]).
Setup: none — works out of the box; add companies to profile.sources.companies
to widen coverage.
"""

UA = "Mozilla/5.0 (yoke job scan)"

_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
    "personio": "https://{slug}.jobs.personio.de/xml",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{slug}",
    "recruitee": "https://{slug}.recruitee.com/api/offers/",
}

_XML_ATS = {"personio"}  # providers whose feed is XML, not JSON


def available():
    return (True, "")


def _get_json(url):
    return json.loads(http.fetch_bytes(url, headers={"User-Agent": UA}))


def _get_xml(url):
    """Parse an untrusted XML feed safely. defusedxml is a lazy plugin-edge
    dep; if it is missing the caller's per-company try/except SKIPs personio."""
    try:
        from defusedxml.ElementTree import fromstring
    except ImportError as exc:  # optional dep — degrade to skipping personio
        raise RuntimeError(
            "personio needs defusedxml: pip install defusedxml"
        ) from exc
    return fromstring(http.fetch_bytes(url, headers={"User-Agent": UA}))


def _name(company):
    return company.get("name") or company.get("slug", "")


def _parse_greenhouse(payload, company):
    out = []
    if not isinstance(payload, dict) or "jobs" not in payload:
        return out
    slug = company.get("slug", "")
    for j in payload["jobs"]:
        out.append(norm(
            j.get("title"), _name(company),
            (j.get("location") or {}).get("name", ""),
            j.get("absolute_url"), f"ats:greenhouse:{slug}",
            j.get("updated_at", ""),
            jd=strip_html(j.get("content"))[:JD_MAX_CHARS],
        ))
    return out


def _parse_lever(payload, company):
    out = []
    if not isinstance(payload, list):
        return out
    slug = company.get("slug", "")
    for j in payload:
        cats = j.get("categories") or {}
        sr = j.get("salaryRange") or {}
        comp = None
        if sr.get("min") and sr.get("max"):
            comp = f"{sr.get('currency', '')}{sr['min']}-{sr['max']}".strip()
        elif j.get("salaryDescriptionPlain"):
            comp = j["salaryDescriptionPlain"]
        out.append(norm(
            j.get("text"), _name(company), cats.get("location", ""),
            j.get("hostedUrl"), f"ats:lever:{slug}",
            str(j.get("createdAt", "")), comp,
            jd=strip_html(j.get("descriptionPlain") or j.get("description"))[:JD_MAX_CHARS],
        ))
    return out


def _parse_ashby(payload, company):
    out = []
    if not isinstance(payload, dict) or "jobs" not in payload:
        return out
    slug = company.get("slug", "")
    for j in payload["jobs"]:
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or None
        out.append(norm(
            j.get("title"), _name(company), j.get("location", ""),
            j.get("jobUrl"), f"ats:ashby:{slug}",
            j.get("publishedAt", ""), comp,
            jd=strip_html(j.get("descriptionPlain") or j.get("descriptionHtml"))[:JD_MAX_CHARS],
        ))
    return out


def _parse_personio(root, company):
    # XML <position> elements. The feed carries no URL or salary; the job URL
    # is built from the id, and the description lives in nested jobDescriptions.
    out = []
    if root is None:
        return out
    slug = company.get("slug", "")
    for pos in root.iter("position"):
        pid = (pos.findtext("id") or "").strip()
        jd_el = pos.find("jobDescriptions")
        parts = [d.findtext("value") or "" for d in jd_el.findall("jobDescription")] if jd_el is not None else []
        url = f"https://{slug}.jobs.personio.de/job/{pid}" if pid else ""
        out.append(norm(
            pos.findtext("name"), _name(company), pos.findtext("office") or "",
            url, f"ats:personio:{slug}", pos.findtext("createdAt") or "", None,
            jd=strip_html(" ".join(parts))[:JD_MAX_CHARS],
        ))
    return out


def _parse_smartrecruiters(payload, company):
    # The public postings list carries no description or salary → jd "", comp None.
    out = []
    if not isinstance(payload, dict) or "content" not in payload:
        return out
    slug = company.get("slug", "")
    for j in payload["content"]:
        loc = j.get("location") or {}
        ident = (j.get("company") or {}).get("identifier") or slug
        pid = j.get("id") or ""
        url = f"https://jobs.smartrecruiters.com/{ident}/{pid}" if pid else ""
        out.append(norm(
            j.get("name"), _name(company),
            loc.get("fullLocation") or loc.get("city", ""),
            url, f"ats:smartrecruiters:{slug}", j.get("releasedDate", ""), None,
        ))
    return out


def _parse_workable(payload, company):
    # The widget feed carries neither description nor salary → jd "", comp None.
    out = []
    if not isinstance(payload, dict) or "jobs" not in payload:
        return out
    slug = company.get("slug", "")
    for j in payload["jobs"]:
        loc = ", ".join(p for p in (j.get("city"), j.get("country")) if p)
        out.append(norm(
            j.get("title"), _name(company), loc,
            j.get("url"), f"ats:workable:{slug}", j.get("published_on", ""), None,
        ))
    return out


_RC_PERIOD = {"hourly": "hour", "daily": "day", "monthly": "month", "yearly": "year"}


def _recruitee_comp(offer):
    """Recruitee salary object -> canonical {min,max,currency,unit,type} or None.

    Only builds a comp dict when a bound is actually present — a null-valued
    salary object degrades to None, never an empty/preformatted string.
    """
    sal = offer.get("salary") or {}
    lo, hi = sal.get("min"), sal.get("max")
    if not (lo or hi):
        return None
    period = (sal.get("period") or "yearly").lower()
    return {
        "min": lo, "max": hi,
        "currency": (sal.get("currency") or "usd").lower(),
        "unit": _RC_PERIOD.get(period, "year"),
        "type": offer.get("employment_type_code") or "",
    }


def _parse_recruitee(payload, company):
    out = []
    if not isinstance(payload, dict) or "offers" not in payload:
        return out
    slug = company.get("slug", "")
    for o in payload["offers"]:
        out.append(norm(
            o.get("title"), _name(company), o.get("location", ""),
            o.get("careers_url"), f"ats:recruitee:{slug}",
            o.get("published_at", ""), _recruitee_comp(o),
            jd=strip_html(o.get("description"))[:JD_MAX_CHARS],
        ))
    return out


_PARSERS = {
    "greenhouse": _parse_greenhouse,
    "lever": _parse_lever,
    "ashby": _parse_ashby,
    "personio": _parse_personio,
    "smartrecruiters": _parse_smartrecruiters,
    "workable": _parse_workable,
    "recruitee": _parse_recruitee,
}


def fetch(profile):
    out = []
    for company in profile.get("sources", {}).get("companies", []):
        provider = company.get("ats")
        parser = _PARSERS.get(provider)
        slug = company.get("slug")
        if parser is None or not slug:
            continue  # unknown ATS or missing slug — skip, don't kill the scan
        try:
            url = _URLS[provider].format(slug=slug)
            payload = _get_xml(url) if provider in _XML_ATS else _get_json(url)
        except Exception as exc:  # one dead slug must not kill the other companies
            print(f"ats: {slug} SKIP ({exc})", file=sys.stderr)
            continue
        out.extend(parser(payload, company))
    return out

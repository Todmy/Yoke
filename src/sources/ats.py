"""Company ATS boards: greenhouse / lever / ashby public JSON APIs.

Companies come from profile["sources"]["companies"] as [{slug, ats}].
Network (fetch) is split from parsing (_parse_*) so tests feed fixtures
straight into the parsers — no network in tests.
"""

import json
import sys
import urllib.request

from src.collect import norm

NAME = "ats"
TAGS = {"domain": "it", "country": "any"}
COST = "free"

UA = "Mozilla/5.0 (yoke job scan)"
TIMEOUT = 20

_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
}


def available():
    return (True, "")


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
        ))
    return out


_PARSERS = {
    "greenhouse": _parse_greenhouse,
    "lever": _parse_lever,
    "ashby": _parse_ashby,
}


def fetch(profile):
    out = []
    for company in profile.get("sources", {}).get("companies", []):
        parser = _PARSERS.get(company.get("ats"))
        slug = company.get("slug")
        if parser is None or not slug:
            continue  # unknown ATS or missing slug — skip, don't kill the scan
        try:
            payload = _get_json(_URLS[company["ats"]].format(slug=slug))
        except Exception as exc:  # one dead slug must not kill the other companies
            print(f"ats: {slug} SKIP ({exc})", file=sys.stderr)
            continue
        out.extend(parser(payload, company))
    return out

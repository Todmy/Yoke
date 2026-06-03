#!/usr/bin/env python3
"""Standalone job scanner — finds hidden remote AI/eng roles for the user.

Pulls from layers that megaboards miss:
  1. Company ATS directly (Greenhouse / Lever / Ashby JSON APIs) — roles appear
     here the day they're posted, before any aggregator indexes them.
  2. Remote aggregators with clean APIs (RemoteOK, Remotive, WeWorkRemotely RSS).
  3. HN "Who is hiring" monthly thread (Algolia) — dense with remote AI startups.

Each match is filtered to your profile (AI/LLM/MCP/agent/SA/FDE + senior
generalist, remote, EU-OK, no UK-only, no RU/BY). Deterministic collection only
— NO notifications. Results land in two places:
  - ~/PBaaS/job-scans/_index.json  — master dedup index with first_seen/last_seen
  - ~/PBaaS/job-scans/YYYY-MM-DD-HH-MM.json  — raw per-scan snapshot (history)
On-demand AI analysis is the separate `/jobsearch` command, which reads the
index, windows by "new since last review" (cap 14 days), and ranks fit.

Run:  python3 job-scan.py            # scan + save + update index
      python3 job-scan.py --dry-run  # print to stdout, no save

Add companies: edit COMPANIES below, or drop a job-scan-config.json next to
this script with {"companies": [...]} to extend without touching code.
"""

import argparse
import fcntl
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import SCANS_DIR, INDEX as INDEX_FILE, JD_CACHE, YOKE_HOME, load_sources  # noqa: E402

LOCK_FILE = Path("/tmp/yoke-collect.lock")
TIMEOUT = 20
UA = "Yoke/1.0 (+https://github.com/Todmy/Yoke)"
PRUNE_DAYS = 45                                  # drop index entries unseen this long (role closed)

# No notifications. collect does deterministic gathering only; `analyze` does the
# on-demand AI scoring of what's gathered here.

# ── Default target companies (ATS direct) ────────────────────
# ats: greenhouse | lever | ashby ; slug = the board identifier in their URL.
# Override/extend via config: $YOKE_HOME/config/sources.json "companies".
# Unknown/wrong slugs just 404 and are skipped — safe to leave guesses.
DEFAULT_COMPANIES = [
    {"name": "Anthropic", "ats": "greenhouse", "slug": "anthropic"},
    {"name": "ClickHouse", "ats": "greenhouse", "slug": "clickhouse"},
    {"name": "Databricks", "ats": "greenhouse", "slug": "databricks"},
    {"name": "Cohere", "ats": "ashby", "slug": "cohere"},
    {"name": "Mistral", "ats": "lever", "slug": "mistral"},
]

# ── Filter vocabulary ────────────────────────────────────────
# A role matches if its TITLE hits a ROLE term. Tech terms add signal/score.
ROLE_TERMS = [
    "ai engineer", "applied ai", "ml engineer", "machine learning engineer",
    "solutions architect", "solution architect", "forward deployed", "fde",
    "applied engineer", "founding engineer", "ai solutions", "llm engineer",
    "gen ai", "genai", "agent engineer", "developer advocate", "developer experience",
    "staff engineer", "principal engineer", "senior software engineer",
    "senior engineer", "full stack", "fullstack", "full-stack", "platform engineer",
    "software engineer", "sales engineer", "customer engineer",
]
TECH_TERMS = [
    "llm", "mcp", "agent", "agentic", "rag", "claude", "openai", "anthropic",
    "langchain", "vector", "eval", "embedding", "prompt", "vue", "python",
    "typescript", "django", "node", "ai ", " ai", "genai", "inference",
]
# Hard excludes (origin)
GEO_BLOCK = ["russia", "belarus", "moscow", "minsk", "russian federation"]
# EU / remote-anywhere markers (he can work from Poland). UK is geo-Europe but
# work-auth-blocked, so it is NOT here — only passes when paired with an EU term.
EU_TERMS = [
    "europe", "emea", "eu ", " eu", "(eu", "eu,", "eu)", "anywhere", "worldwide",
    "global", "distributed", "poland", "warsaw", "germany", "berlin", "munich",
    "netherlands", "amsterdam", "spain", "madrid", "barcelona", "portugal",
    "lisbon", "france", "paris", "ireland", "dublin", "italy", "milan", "rome",
    "denmark", "copenhagen", "sweden", "stockholm", "finland", "helsinki",
    "norway", "oslo", "austria", "vienna", "belgium", "brussels", "czech",
    "prague", "romania", "bucharest", "estonia", "lithuania", "latvia",
    "remote europe", "remote - eu", "remote eu", "emea",
]
# Non-EU country markers — reject if present AND no EU term alongside.
NON_EU = [
    "united states", "u.s.", "usa", "us remote", "remote - us", "remote (us",
    "remote, us", "us-based", "us based", "(us)", "canada", "toronto", "india",
    "bangalore", "singapore", "israel", "tel aviv", "australia", "sydney",
    "brazil", "latam", "apac", "japan", "tokyo", "united kingdom", " uk", "uk ",
    "(uk", "uk)", "london", "mexico", "argentina", "philippines", "north america",
    "north american", "us/canada", "us & canada", "americas only",
    # common US-state remote markers ("Remote - California", etc.)
    "california", "arizona", "texas", "new york", "washington", "oregon",
    "colorado", "florida", "illinois", "georgia", "virginia", "massachusetts",
    "north carolina", "remote - us", "san francisco", "seattle", "austin",
]


# ── HTTP helpers ─────────────────────────────────────────────
def fetch_json(url, headers=None):
    h = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        h.update(headers)
    try:
        req = Request(url, headers=h)
        with urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except HTTPError as e:
        print(f"  WARN {e.code}: {url[:70]}", file=sys.stderr)
    except (URLError, TimeoutError, json.JSONDecodeError, ValueError) as e:
        print(f"  WARN: {url[:70]} -> {e}", file=sys.stderr)
    return None


def fetch_text(url):
    try:
        req = Request(url, headers={"User-Agent": UA})
        with urlopen(req, timeout=TIMEOUT) as r:
            return r.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError) as e:
        print(f"  WARN: {url[:70]} -> {e}", file=sys.stderr)
    return None


def norm(title, company, location, url, source, posted_at="", comp=""):
    return {
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "location": (location or "").strip(),
        "url": (url or "").strip(),
        "source": source,
        "posted_at": posted_at,
        "comp": (comp or "").strip(),
    }


# ── JD enrichment: cache full description to a sidecar (keeps _index.json lean).
# prepare.py reads it back by sha1(url) so geo/comp can be classified from the JD,
# not just the title. comp (short) rides inline on the norm dict / index.
# (JD_CACHE imported from paths)


def _strip_html(s):
    import html
    s = html.unescape(s or "")        # greenhouse content is entity-escaped — unescape FIRST
    s = re.sub(r"<[^>]+>", " ", s)     # then strip the now-literal tags
    return re.sub(r"\s+", " ", s).strip()


def jd_cache_path(url):
    import hashlib
    return JD_CACHE / (hashlib.sha1((url or "").encode()).hexdigest() + ".json")


def cache_jd(url, description="", comp=""):
    if not url or not (description or comp):
        return
    p = jd_cache_path(url)
    if p.exists():
        return  # already cached — append-only, cheap re-scans
    JD_CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(
        {"url": url, "comp": comp, "description": (description or "")[:8000]},
        ensure_ascii=False))


# ── ATS fetchers ─────────────────────────────────────────────
def scan_greenhouse(name, slug):
    # content=true returns the full JD per job (for the sidecar cache)
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    data = fetch_json(url)
    out = []
    if not data or "jobs" not in data:
        return out
    for j in data["jobs"]:
        u = j.get("absolute_url")
        cache_jd(u, _strip_html(j.get("content", "")))
        out.append(norm(j.get("title"), name, (j.get("location") or {}).get("name", ""),
                        u, f"ats:greenhouse:{slug}", j.get("updated_at", "")))
    return out


def scan_lever(name, slug):
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    data = fetch_json(url)
    out = []
    if not isinstance(data, list):
        return out
    for j in data:
        cats = j.get("categories") or {}
        sr = j.get("salaryRange") or {}
        comp = ""
        if sr.get("min") and sr.get("max"):
            comp = f"{sr.get('currency','')}{sr['min']}-{sr['max']}".strip()
        elif j.get("salaryDescriptionPlain"):
            comp = j["salaryDescriptionPlain"]
        u = j.get("hostedUrl")
        cache_jd(u, j.get("descriptionPlain") or _strip_html(j.get("description", "")), comp)
        out.append(norm(j.get("text"), name, cats.get("location", ""),
                        u, f"ats:lever:{slug}", str(j.get("createdAt", "")), comp))
    return out


def scan_ashby(name, slug):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    data = fetch_json(url)
    out = []
    if not data or "jobs" not in data:
        return out
    for j in data["jobs"]:
        comp_obj = j.get("compensation") or {}
        comp = comp_obj.get("compensationTierSummary") or ""
        u = j.get("jobUrl")
        cache_jd(u, j.get("descriptionPlain") or _strip_html(j.get("descriptionHtml", "")), comp)
        out.append(norm(j.get("title"), name, j.get("location", ""),
                        u, f"ats:ashby:{slug}", j.get("publishedAt", ""), comp))
    return out


ATS_FETCH = {"greenhouse": scan_greenhouse, "lever": scan_lever, "ashby": scan_ashby}


# ── Aggregator fetchers ──────────────────────────────────────
def scan_remoteok():
    data = fetch_json("https://remoteok.com/api")
    out = []
    if not isinstance(data, list):
        return out
    for j in data:
        if not isinstance(j, dict) or "position" not in j:
            continue
        out.append(norm(j.get("position"), j.get("company"), j.get("location", "Remote"),
                        j.get("url"), "remoteok", j.get("date", "")))
    return out


def scan_remotive():
    out = []
    for q in ("ai+engineer", "machine+learning", "solutions+architect"):
        data = fetch_json(f"https://remotive.com/api/remote-jobs?search={q}&limit=40")
        if not data or "jobs" not in data:
            continue
        for j in data["jobs"]:
            out.append(norm(j.get("title"), j.get("company_name"),
                            j.get("candidate_required_location", "Remote"),
                            j.get("url"), "remotive", j.get("publication_date", "")))
    return out


def scan_wwr_rss():
    # Regex-parse the RSS (trusted fixed feed) to avoid an XML parser entirely:
    # stdlib XML parsers are XXE-prone and defusedxml isn't stdlib.
    out = []
    xml = fetch_text("https://weworkremotely.com/categories/remote-programming-jobs.rss")
    if not xml:
        return out

    def tag(block, name):
        m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", block, re.S)
        if not m:
            return ""
        val = m.group(1).strip()
        cm = re.search(r"<!\[CDATA\[(.*?)\]\]>", val, re.S)
        return (cm.group(1) if cm else val).strip()

    for block in re.findall(r"<item>(.*?)</item>", xml, re.S):
        title = tag(block, "title")
        link = tag(block, "link")
        region = tag(block, "region") or "Remote"
        company = title.split(":")[0].strip() if ":" in title else ""
        role = title.split(":", 1)[1].strip() if ":" in title else title
        out.append(norm(role, company, region, link, "weworkremotely", tag(block, "pubDate")))
    return out


def scan_hn_hiring():
    """Latest 'Ask HN: Who is hiring?' thread, comments containing REMOTE."""
    out = []
    s = fetch_json("https://hn.algolia.com/api/v1/search?query=%22Ask%20HN%3A%20Who%20is%20hiring%3F%22"
                   "&tags=story&hitsPerPage=1")
    if not s or not s.get("hits"):
        return out
    story_id = s["hits"][0]["objectID"]
    thread = fetch_json(f"https://hn.algolia.com/api/v1/items/{story_id}")
    if not thread:
        return out
    for c in (thread.get("children") or []):
        txt = c.get("text") or ""
        if not txt or "remote" not in txt.lower():
            continue
        plain = re.sub(r"<[^>]+>", " ", txt)
        plain = re.sub(r"\s+", " ", plain).strip()
        first = plain[:160]
        url = f"https://news.ycombinator.com/item?id={c.get('id')}"
        out.append(norm(first, "(HN who-is-hiring)", "see post", url, "hn:hiring",
                        str(c.get("created_at", ""))))
    return out


# ── Brave Search dorks (recruiter-style ATS X-ray) ───────────
# Set BRAVE_API_KEY to enable (free tier at brave.com/search/api). Skipped if unset.
def brave_api_key():
    return os.environ.get("BRAVE_API_KEY") or None


# Each dork targets an ATS domain that hosts thousands of company boards — this
# finds roles at companies NOT in the configured list (the hidden recruiter layer).
# Override via config: $YOKE_HOME/config/sources.json "dork_queries".
DEFAULT_DORK_QUERIES = [
    'site:job-boards.greenhouse.io ("AI engineer" OR "forward deployed" OR "solutions architect") remote',
    'site:boards.greenhouse.io ("applied ai" OR "ai engineer") (remote OR europe)',
    'site:jobs.lever.co ("applied ai" OR "ml engineer" OR "ai engineer") remote',
    'site:jobs.ashbyhq.com ("ai engineer" OR "applied ai" OR agent) remote',
    'site:apply.workable.com "AI engineer" (remote europe OR EMEA)',
    'site:jobs.ashbyhq.com ("solutions architect" OR "forward deployed") europe',
    # early-stage startups (YC / VC-backed) live here, not on the big ATS hosts
    'site:workatastartup.com ("AI engineer" OR "founding engineer" OR "forward deployed" OR "applied ai") remote',
    'site:wellfound.com ("AI engineer" OR "founding engineer" OR "applied ai") remote europe',
]
_ATS_HOST_RE = re.compile(
    r"https?://(?:job-boards|boards)\.greenhouse\.io/([^/]+)|"
    r"https?://jobs\.lever\.co/([^/]+)|"
    r"https?://jobs\.ashbyhq\.com/([^/]+)|"
    r"https?://apply\.workable\.com/([^/]+)|"
    r"https?://(?:www\.)?workatastartup\.com/companies/([^/?#]+)|"
    r"https?://(?:www\.)?wellfound\.com/company/([^/?#]+)")
# startup hosts where the job URL carries no company slug (e.g. /jobs/<id>) —
# attribute the company from the result title instead ("Role at <Company> | ...").
_STARTUP_HOSTS = ("workatastartup.com", "wellfound.com")
_TITLE_COMPANY_RE = re.compile(r"\bat\s+(.+?)(?:\s*[|\-–—]|$)", re.IGNORECASE)


def _company_from_url(url):
    m = _ATS_HOST_RE.search(url or "")
    if not m:
        return ""
    slug = next((g for g in m.groups() if g), "")
    return slug.replace("-", " ").replace("_", " ").title()


def _company_from_title(title):
    # "Software Engineer at Lago | Y Combinator's Work at a Startup" -> "Lago"
    m = _TITLE_COMPANY_RE.search(title or "")
    return m.group(1).strip() if m else ""


def scan_brave_dorks():
    key = brave_api_key()
    out = []
    if not key:
        print("  brave: no BRAVE_API_KEY, skipping dorks", file=sys.stderr)
        return out
    for q in (load_sources().get("dork_queries") or DEFAULT_DORK_QUERIES):
        url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
            {"q": q, "count": 20})
        data = fetch_json(url, headers={"X-Subscription-Token": key,
                                        "Accept": "application/json"})
        results = ((data or {}).get("web") or {}).get("results") or []
        for r in results:
            link = r.get("url", "")
            company = _company_from_url(link)
            host = link.split("/")[2].lower() if "://" in link else ""
            if not company and any(h in host for h in _STARTUP_HOSTS):
                company = _company_from_title(r.get("title"))  # /jobs/<id> carries no slug
            if not company:
                continue  # not an ATS posting we can attribute
            desc = (r.get("description") or "").lower()
            loc = next((w.title() for w in EU_TERMS + NON_EU if w.strip() and w in desc), "")
            host = host or "dork"
            out.append(norm(r.get("title"), company, loc, link,
                            f"dork:{host}", ""))
        time.sleep(1.1)  # Brave free tier: ~1 req/sec
    return out


# ── JobSpy (LinkedIn / Indeed / Google Jobs / Glassdoor) ─────
# Optional dependency: pip install python-jobspy. Gracefully skipped if absent,
# so the rest of the scan still runs. Adds the big boards we don't poll directly,
# plus real salary data (min/max/interval/currency).
JOBSPY_SEARCHES = [
    {"search_term": "AI engineer", "google_search_term": "AI engineer remote europe jobs"},
    {"search_term": "forward deployed engineer", "google_search_term": "forward deployed engineer remote europe jobs"},
    {"search_term": "AI solutions architect", "google_search_term": "AI solutions architect remote europe jobs"},
]


def scan_jobspy():
    try:
        from jobspy import scrape_jobs
    except ImportError:
        print("  jobspy not installed (pip install python-jobspy) — skipping", file=sys.stderr)
        return []
    out = []
    for s in JOBSPY_SEARCHES:
        try:
            df = scrape_jobs(
                site_name=["indeed", "linkedin", "google"],
                search_term=s["search_term"],
                google_search_term=s["google_search_term"],
                location="European Union",
                country_indeed="Poland",
                is_remote=True,          # note: Indeed allows only one of {hours_old, is_remote} — keep is_remote
                results_wanted=20,
                description_format="markdown",
                verbose=0,
            )
        except Exception as e:  # network/rate-limit/parse — never kill the whole scan
            print(f"  jobspy '{s['search_term']}': {type(e).__name__}: {str(e)[:80]}", file=sys.stderr)
            continue
        if df is None or len(df) == 0:
            continue
        for r in df.to_dict("records"):
            def g(k):
                v = r.get(k)
                return "" if v is None or str(v) == "nan" else v
            loc = ", ".join(str(g(k)) for k in ("city", "state", "country") if g(k)) \
                or ("Remote" if g("is_remote") else "")
            site = g("site") or "jobspy"
            j = norm(g("title"), g("company"), loc, g("job_url"),
                     f"jobspy:{site}", str(g("date_posted")))
            mn, mx, interval, cur = g("min_amount"), g("max_amount"), g("interval"), g("currency")
            if mn or mx:
                j["salary"] = f"{cur} {mn or '?'}-{mx or '?'}/{interval}".strip()
            out.append(j)
    return out


# ── v1 source short-list (FR-001): manual import + UA/aggregator scrapers ─────
# NOTE: the three web scrapers below are stdlib best-effort against live HTML/JSON
# whose structure can change; they are error-isolated by run() and degrade to [].
# Manual import is the always-available offline fallback.

def scan_manual():
    """Read user-supplied roles from $YOKE_HOME/import.json — the always-available
    fallback so the pipeline works with every scraper down (FR-001). Format: a JSON
    list of {title, company, location, url, comp?} (extra keys ignored)."""
    p = YOKE_HOME / "import.json"
    if not p.exists():
        return []
    try:
        rows = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    out = []
    for r in (rows if isinstance(rows, list) else rows.get("roles", [])):
        if not isinstance(r, dict):
            continue
        out.append(norm(r.get("title"), r.get("company"), r.get("location", "Remote"),
                        r.get("url"), "manual", r.get("posted_at", ""), r.get("comp", "")))
    return out


def scan_hiringcafe():
    """Hiring Cafe aggregator (one high-yield remote source). Best-effort against
    its search API; schema unverified here — defensive parsing, degrades to []."""
    body = json.dumps({"searchQuery": "engineer", "workplaceTypes": ["Remote"], "size": 100}).encode()
    try:
        req = Request("https://hiring.cafe/api/search-jobs", data=body,
                      headers={"User-Agent": UA, "Content-Type": "application/json",
                               "Accept": "application/json"})
        with urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read())
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as e:
        print(f"  hiringcafe: {type(e).__name__}", file=sys.stderr)
        return []
    out = []
    results = data if isinstance(data, list) else (data.get("results") or data.get("jobs") or [])
    for j in results:
        if not isinstance(j, dict):
            continue
        info = j.get("job") or j
        out.append(norm(info.get("title") or info.get("position"),
                        info.get("company") or (info.get("organization") or {}).get("name"),
                        info.get("location") or "Remote",
                        info.get("url") or info.get("applyUrl") or info.get("link"),
                        "hiringcafe", str(info.get("postedAt", "")), info.get("salary", "")))
    return out


_DJINNI_RE = re.compile(r'<a[^>]+href="(/jobs/(\d+)[^"]*)"[^>]*>\s*(.*?)\s*</a>', re.S)


def scan_djinni():
    """Djinni (UA board, no public API). Best-effort HTML scrape, rate-limited;
    selectors unverified here — degrades to [] if the markup differs."""
    out = []
    for q in ("AI+Engineer", "Python", "Golang"):
        html_txt = fetch_text(f"https://djinni.co/jobs/?primary_keyword={q}&employment=remote")
        if not html_txt:
            continue
        for href, _jid, raw in _DJINNI_RE.findall(html_txt):
            title = re.sub(r"<[^>]+>", " ", raw)
            title = re.sub(r"\s+", " ", title).strip()
            if not title:
                continue
            out.append(norm(title, "", "Remote (Djinni)", f"https://djinni.co{href}",
                            "djinni", ""))
        time.sleep(2)  # polite rate limit (FR-001)
    return out


_DOU_RE = re.compile(r'<a[^>]+class="vt"[^>]+href="(https://jobs\.dou\.ua/[^"]+)"[^>]*>(.*?)</a>', re.S)


def scan_dou():
    """DOU (UA board, no public API). Best-effort HTML scrape, rate-limited;
    selectors unverified here — degrades to [] if the markup differs."""
    out = []
    for cat in ("Python", "Golang", "AI%2FML"):
        html_txt = fetch_text(f"https://jobs.dou.ua/vacancies/?category={cat}&remote")
        if not html_txt:
            continue
        for href, raw in _DOU_RE.findall(html_txt):
            title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).strip()
            if title:
                out.append(norm(title, "", "Remote (DOU)", href, "dou", ""))
        time.sleep(2)  # polite rate limit (FR-001)
    return out


# ── Filtering ────────────────────────────────────────────────
def matches_profile(job):
    t = (job["title"] or "").lower()
    loc = (job["location"] or "").lower()
    blob = f"{t} {loc} {job['company']}".lower()

    # hard geo block (origin)
    if any(b in blob for b in GEO_BLOCK):
        return False, 0

    # location: reject a non-EU marker unless an EU term sits alongside. Dork /
    # aggregator hits often have a blank location with the geo in the title, so
    # fall back to the title for the geo signal.
    geo = loc if loc else t
    has_eu = any(g in geo for g in EU_TERMS)
    has_non_eu = any(b in geo for b in NON_EU)
    if has_non_eu and not has_eu:
        return False, 0
    # ATS with a real location but no remote/EU signal → skip (likely onsite non-EU)
    if job["source"].startswith("ats:") and loc and not has_eu and "remote" not in loc:
        return False, 0

    # role match required (HN posts bypass title rule, scored by tech)
    is_hn = job["source"] == "hn:hiring"
    role_hit = any(r in t for r in ROLE_TERMS)
    if not role_hit and not is_hn:
        return False, 0

    score = 0
    score += sum(2 for r in ROLE_TERMS if r in t)
    score += sum(1 for k in TECH_TERMS if k in blob)
    if is_hn and score == 0:
        return False, 0
    return True, score


# ── Dedup ────────────────────────────────────────────────────
def job_key(job):
    return (job["url"] or f"{job['company']}|{job['title']}").strip().lower()


def role_key(job):
    """Collapse the same role posted across several locations into one."""
    t = re.sub(r"[^a-z0-9 ]", "", (job["title"] or "").lower())
    t = re.sub(r"\s+", " ", t).strip()
    return f"{job['company'].lower()}|{t}"


# ── Master index (dedup + first_seen / last_seen) ────────────
def load_index():
    if INDEX_FILE.exists():
        try:
            return json.loads(INDEX_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def update_index(index, matches, now_iso):
    """Merge current matches into the index. New keys get first_seen=now."""
    new_keys = []
    for j in matches:
        k = job_key(j)
        if k in index:
            index[k]["last_seen"] = now_iso
            index[k]["score"] = j["_score"]
            index[k]["location"] = j["location"] or index[k].get("location", "")
            if j.get("salary"):
                index[k]["salary"] = j["salary"]
            if j.get("comp"):
                index[k]["comp"] = j["comp"]
        else:
            index[k] = {
                "title": j["title"], "company": j["company"], "location": j["location"],
                "url": j["url"], "source": j["source"], "score": j["_score"],
                "role_key": role_key(j), "first_seen": now_iso, "last_seen": now_iso,
            }
            if j.get("salary"):
                index[k]["salary"] = j["salary"]
            if j.get("comp"):
                index[k]["comp"] = j["comp"]
            new_keys.append(k)
    return new_keys


def prune_index(index, now):
    cutoff = now - timedelta(days=PRUNE_DAYS)
    drop = []
    for k, v in index.items():
        try:
            ls = datetime.fromisoformat(v.get("last_seen", "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if ls < cutoff:
            drop.append(k)
    for k in drop:
        del index[k]
    return len(drop)


# ── Source registry (pluggable) ──────────────────────────────
# Every collector is registered here behind the common norm() contract, so
# adding a source = register one fetch() (or drop a module in sources/ that
# calls register_source on import). Each is config-toggleable via
# job-scan-config.json {"sources": {"<name>": {"enabled": false}}} and
# error-isolated in run() so one failing source can't kill the scan.
SOURCES = []  # [{"name": str, "fetch": callable -> list[norm dict]}]


def register_source(name, fetch):
    SOURCES.append({"name": name, "fetch": fetch})


def load_config():
    return load_sources()  # $YOKE_HOME/config/sources.json, fallback to the example


def load_config_companies():
    cfg_companies = load_config().get("companies")
    # if the user configured companies, use those; otherwise the built-in defaults
    return list(cfg_companies) if cfg_companies else list(DEFAULT_COMPANIES)


def source_enabled(name, cfg):
    return ((cfg.get("sources") or {}).get(name) or {}).get("enabled", True)


def _fetch_ats():
    out = []
    for c in load_config_companies():
        fn = ATS_FETCH.get(c["ats"])
        if not fn:
            continue
        got = fn(c["name"], c["slug"]) or []
        if got:
            print(f"    {c['name']} ({c['ats']}): {len(got)}", file=sys.stderr)
        out.extend(got)
    return out


# built-in sources (order = collection order). New source → one register_source.
register_source("ats", _fetch_ats)
register_source("remoteok", scan_remoteok)
register_source("remotive", scan_remotive)
register_source("weworkremotely", scan_wwr_rss)
register_source("hackernews", scan_hn_hiring)
register_source("dorks", scan_brave_dorks)
register_source("jobspy", scan_jobspy)          # includes LinkedIn (read-only) — FR-001 T011
register_source("hiringcafe", scan_hiringcafe)  # FR-001 T008
register_source("djinni", scan_djinni)          # FR-001 T009
register_source("dou", scan_dou)                # FR-001 T010
register_source("manual", scan_manual)          # FR-001 T012 (offline fallback)


def run(args):
    raw = []
    cfg = load_config()
    for src in SOURCES:
        if not source_enabled(src["name"], cfg):
            print(f"→ {src['name']}: disabled (config)", file=sys.stderr)
            continue
        print(f"→ {src['name']}...", file=sys.stderr)
        try:
            got = src["fetch"]() or []
        except Exception as e:  # one source must never kill the scan
            print(f"  {src['name']}: ERROR {type(e).__name__}: {e}", file=sys.stderr)
            continue
        print(f"  {src['name']}: {len(got)}", file=sys.stderr)
        raw.extend(got)

    # filter + score
    matches = []
    seen_in_run = set()
    for j in raw:
        k = job_key(j)
        if k in seen_in_run:
            continue
        ok, score = matches_profile(j)
        if not ok:
            continue
        seen_in_run.add(k)
        j["_score"] = score
        matches.append(j)

    # collapse same role across multiple EU locations into one (highest score wins)
    by_role = {}
    for j in matches:
        rk = role_key(j)
        if rk not in by_role or j["_score"] > by_role[rk]["_score"]:
            by_role[rk] = j
    matches = list(by_role.values())
    matches.sort(key=lambda x: x["_score"], reverse=True)

    if args.dry_run:
        for j in matches[:40]:
            print(f"[{j['_score']:>2}] {j['title'][:70]} | {j['company']} | "
                  f"{j['location'][:30]} | {j['source']}")
        print(f"\nTotal matches: {len(matches)} (raw fetched: {len(raw)})", file=sys.stderr)
        return

    SCANS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # update master index (dedup + first_seen tracking) — this is the source of
    # truth /jobsearch reads; per-scan snapshot below is raw history.
    index = load_index()
    new_keys = update_index(index, matches, now_iso)
    pruned = prune_index(index, now)
    INDEX_FILE.write_text(json.dumps(index, ensure_ascii=False, indent=2))

    ts = now.strftime("%Y-%m-%d-%H-%M")
    out_file = SCANS_DIR / f"{ts}.json"
    out_file.write_text(json.dumps({
        "scanned_at": ts, "raw_count": len(raw),
        "match_count": len(matches), "new_count": len(new_keys),
        "matches": matches,
    }, ensure_ascii=False, indent=2))
    print(f"Saved {out_file.name}: {len(matches)} matches, {len(new_keys)} new, "
          f"{len(index)} in index ({pruned} pruned)", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        run(args)
        return

    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Another scan is running, exiting.", file=sys.stderr)
        return
    try:
        run(args)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()

"""Source plugin: python-jobspy (indeed/linkedin/google) — optional dep.

`jobspy` is a third-party package and is NEVER imported at module level;
both available() and fetch() import it lazily so the plugin registry can
load this module without the dependency installed.
"""

from ..collect import JD_MAX_CHARS, norm, strip_html

NAME = "jobspy"
TAGS = {"domain": "any", "country": "any"}
COST = "free"

HELP = """\
python-jobspy — Indeed / LinkedIn / Google jobs (optional dependency).
Returns: postings scraped via the jobspy package.
Setup: pip install python-jobspy
Notes: OFF by default — LinkedIn/Indeed terms restrict scraping; enable at your
own discretion. The package is imported lazily, so the plugin loads without it.
"""

_INTERVAL_TO_UNIT = {
    "hourly": "hour",
    "daily": "day",
    "weekly": "week",
    "monthly": "month",
    "yearly": "year",
}


def available():
    try:
        import jobspy  # noqa: F401
    except ImportError:
        return (False, "python-jobspy not installed")
    return (True, "")


def _clean(v):
    """Dataframe rows leak NaN/None — collapse both to ''."""
    if v is None or str(v) == "nan":
        return ""
    return v


def _rows_to_norms(rows, profile):
    """Pure mapper: plain row dicts (dataframe .to_dict('records')) -> norms."""
    out = []
    for r in rows:
        g = lambda k: _clean(r.get(k))  # noqa: E731
        loc = ", ".join(str(g(k)) for k in ("city", "state", "country") if g(k)) or (
            "Remote" if g("is_remote") else ""
        )
        site = g("site") or "jobspy"
        comp = None
        mn, mx = g("min_amount"), g("max_amount")
        if mn or mx:
            interval = str(g("interval")).lower()
            comp = {
                "min": mn or None,
                "max": mx or None,
                "currency": str(g("currency")).lower() or "usd",
                "unit": _INTERVAL_TO_UNIT.get(interval, interval or "year"),
                "type": str(g("job_type")),
            }
        out.append(
            norm(
                str(g("title")),
                str(g("company")),
                loc,
                str(g("job_url")),
                f"jobspy:{site}",
                str(g("date_posted")),
                comp,
                jd=strip_html(g("description"))[:JD_MAX_CHARS],
            )
        )
    return out


def fetch(profile):
    from jobspy import scrape_jobs  # lazy: optional dependency

    search = profile.get("search", {})
    keywords = search.get("keywords") or profile.get("lane", {}).get("keywords", [])
    location = search.get("location", "European Union")
    out = []
    for term in keywords:
        try:
            df = scrape_jobs(
                site_name=["indeed", "linkedin", "google"],
                search_term=term,
                google_search_term=f"{term} jobs {location}",
                location=location,
                country_indeed="Poland",
                is_remote=True,  # Indeed allows only one of {hours_old, is_remote}
                results_wanted=20,
                description_format="markdown",
                verbose=0,
            )
        except Exception:  # network/rate-limit/parse — never kill the whole scan
            continue
        if df is None or len(df) == 0:
            continue
        out.extend(_rows_to_norms(df.to_dict("records"), profile))
    return out

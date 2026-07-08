"""Collect spine: normalize, dedup keys, profile gate, source registry, index.

No fetchers live here — sources are plugin modules under src/sources/, each
exposing NAME / TAGS / COST / available() / fetch(profile). run_collect is
error-isolated per source: one failing plugin never kills the scan.
"""

import difflib
import html
import importlib
import json
import pkgutil
import re
import sys
from datetime import datetime, timedelta, timezone

from src.paths import ensure_home

PRUNE_DAYS = 45  # drop index entries unseen this long (role closed)
REQUIRED_ATTRS = ("NAME", "TAGS", "COST", "available", "fetch")
JD_MAX_CHARS = 8000  # plugins cap jd at this — keeps _index.json bounded
DEFAULT_DEDUP_RATIO = 0.90  # WS4 near-duplicate title-similarity threshold

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text):
    """Payload text -> plain text: unescape entities, strip tags, collapse ws.

    Unescape runs BEFORE the tag-strip because greenhouse ships HTML-escaped
    HTML ("&lt;p&gt;..."); for already-plain text both steps are no-ops.
    """
    if not text:
        return ""
    plain = html.unescape(str(text))
    plain = _TAG_RE.sub(" ", plain)
    return re.sub(r"\s+", " ", plain).strip()

# EU / non-EU location markers for the remote-geo gate (ported from prototype).
EU_TERMS = [
    "europe", "emea", "eu ", " eu", "(eu", "eu,", "eu)", "anywhere", "worldwide",
    "global", "distributed", "poland", "warsaw", "germany", "berlin", "munich",
    "netherlands", "amsterdam", "spain", "madrid", "barcelona", "portugal",
    "lisbon", "france", "paris", "ireland", "dublin", "italy", "milan", "rome",
    "denmark", "copenhagen", "sweden", "stockholm", "finland", "helsinki",
    "norway", "oslo", "austria", "vienna", "belgium", "brussels", "czech",
    "prague", "romania", "bucharest", "estonia", "lithuania", "latvia",
    "remote europe", "remote - eu", "remote eu",
    "ukraine", "kyiv", "lviv",
]
# Non-EU country markers — reject if present AND no EU term alongside.
NON_EU = [
    "united states", "u.s.", "usa", "us remote", "remote - us", "remote (us",
    "remote, us", "us-based", "us based", "(us)", "canada", "toronto", "india",
    "bangalore", "singapore", "israel", "tel aviv", "australia", "sydney",
    "brazil", "latam", "apac", "japan", "tokyo", "united kingdom", " uk", "uk ",
    "(uk", "uk)", "london", "mexico", "argentina", "philippines", "north america",
    "north american", "us/canada", "us & canada", "americas only",
    "california", "arizona", "texas", "new york", "washington", "oregon",
    "colorado", "florida", "illinois", "georgia", "virginia", "massachusetts",
    "north carolina", "san francisco", "seattle", "austin",
]

# ISO-2 country -> location terms, matched with the SAME boundary-aware matcher
# as the geo gate. Selecting a country flattens its terms into target_markers,
# which un-blocks an otherwise non-EU location (and signals country of interest
# to routed sources like eures / germany_ba). "all-eu"/unknown codes -> [].
COUNTRY_MARKERS = {
    "uk": ["united kingdom", "uk", "london", "manchester", "edinburgh"],
    "de": ["germany", "deutschland", "berlin", "munich", "hamburg", "frankfurt"],
    "ca": ["canada", "toronto", "vancouver", "montreal"],
    "us": ["united states", "usa", "us", "new york", "san francisco", "seattle", "austin"],
    "ch": ["switzerland", "zurich", "geneva", "basel"],
    "au": ["australia", "sydney", "melbourne"],
}


def _has_geo_marker(text, markers):
    """Boundary-aware marker match: 'uk' must not fire inside 'ukraine'.

    The padded list variants (' uk', '(uk', 'uk)') collapse to one token;
    letters may not touch a marker on either side.
    """
    for m in markers:
        token = m.strip().strip("(),")
        if token and re.search(rf"(?<![a-z]){re.escape(token)}(?![a-z])", text):
            return True
    return False


def norm(title, company, location, url, source, posted_at="", comp=None, jd=""):
    """Common record shape every source fetcher must emit.

    comp passes through untouched: structured dict, raw string, or None.
    jd is plain JD text; plugins strip_html + cap at JD_MAX_CHARS before
    passing it in ("" when the payload carries no full text).
    """
    return {
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "location": (location or "").strip(),
        "url": (url or "").strip(),
        "source": source,
        "posted_at": posted_at,
        "comp": comp,
        "jd": jd or "",
    }


def job_key(job):
    """Dedup key: URL when present, else company|title. Lowercased."""
    return (job["url"] or f"{job['company']}|{job['title']}").strip().lower()


def role_key(job):
    """Collapse the same role posted across several locations into one."""
    t = re.sub(r"[^a-z0-9 ]", "", (job["title"] or "").lower())
    t = re.sub(r"\s+", " ", t).strip()
    return f"{job['company'].lower()}|{t}"


# Seniority tokens dropped before near-duplicate comparison (WS4), each mapped
# to a coarse level. Stripping collapses formatting variance ("Sr" vs "Senior"),
# but two titles with DIFFERENT explicit levels are distinct roles, not dupes.
_SENIORITY_LEVEL = {
    "senior": "senior", "sr": "senior",
    "junior": "junior", "jr": "junior",
    "mid": "mid", "middle": "mid",
    "lead": "lead", "staff": "staff", "principal": "principal",
}
_SENIORITY = set(_SENIORITY_LEVEL)


def _normalize_title(title):
    """Lowercase, drop seniority tokens, unify js/node aliases, strip punctuation.

    Feeds the WS4 near-duplicate check — collapses cosmetic title variance so
    reposts of one role read as one. Aliases are unified BEFORE punctuation is
    stripped (node.js carries a dot). Pure, stdlib only.
    """
    t = (title or "").lower()
    t = re.sub(r"\bnode\.?js\b", "nodejs", t)
    t = re.sub(r"\bjavascript\b", "js", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return " ".join(w for w in t.split() if w not in _SENIORITY)


def _seniority(title):
    """Coarse seniority level of a title, or None when unspecified."""
    for w in re.sub(r"[^a-z ]", " ", (title or "").lower()).split():
        if w in _SENIORITY_LEVEL:
            return _SENIORITY_LEVEL[w]
    return None


def _title_similar(a, b, ratio):
    """True when two titles are near-duplicates after normalization (WS4).

    Two DIFFERENT explicit seniority levels (senior vs junior) are never
    duplicates even at ratio 1.0 — level changes comp/fit. Titles that
    normalize to nothing (pure seniority) never match.
    """
    na, nb = _normalize_title(a), _normalize_title(b)
    if not na or not nb:
        return False
    la, lb = _seniority(a), _seniority(b)
    if la and lb and la != lb:
        return False
    return difflib.SequenceMatcher(None, na, nb).ratio() >= ratio


def matches_profile(job, profile, bypass_lane=False):
    """Deterministic gate: (keep, match_score). Match score ≠ fit score.

    bypass_lane skips the title-keyword requirement (e.g. HN comment threads
    lack clean titles); such jobs must still score via tech terms.
    """
    t = (job["title"] or "").lower()
    loc = (job["location"] or "").lower()
    blob = f"{t} {loc} {job['company']}".lower()

    lane = profile.get("lane", {})
    keywords = [k.lower() for k in lane.get("keywords", [])]
    anti = [a.lower() for a in lane.get("anti", [])]
    block = [b.lower() for b in profile.get("geo", {}).get("block", [])]
    tech = [x.lower() for x in profile.get("tech", {}).get("primary", [])]

    # hard geo block (instant reject)
    if any(b in blob for b in block):
        return False, 0

    # reject a non-EU marker unless an EU term sits alongside; aggregator hits
    # often carry a blank location with the geo in the title, so fall back to it
    geo = loc if loc else t
    has_eu = _has_geo_marker(geo, EU_TERMS)
    has_non_eu = _has_geo_marker(geo, NON_EU)
    # a selected country un-blocks its own non-EU location (empty countries ->
    # target_markers == [] -> has_target False -> gate identical to before).
    target_markers = [
        m for c in profile.get("countries", []) for m in COUNTRY_MARKERS.get(c, [])
    ]
    has_target = _has_geo_marker(geo, target_markers)
    if has_non_eu and not has_eu and not has_target:
        return False, 0

    # anti-lane hit rejects outright
    if any(a in blob for a in anti):
        return False, 0

    # lane keyword required in title unless the source bypasses the lane rule
    lane_hits = sum(1 for k in keywords if k in t)
    if lane_hits == 0 and not bypass_lane:
        return False, 0

    score = 2 * lane_hits + sum(1 for x in tech if x in blob)
    if bypass_lane and score == 0:
        return False, 0
    return True, score


def load_sources():
    """Import every plugin under src/sources; skip+warn malformed modules."""
    import src.sources as sources_pkg

    mods = []
    for info in pkgutil.iter_modules(sources_pkg.__path__):
        qualname = f"{sources_pkg.__name__}.{info.name}"
        try:
            mod = importlib.import_module(qualname)
        except Exception as e:  # noqa: BLE001 — one bad plugin must not kill the registry
            print(f"WARN source {info.name}: import failed: {e}", file=sys.stderr)
            continue
        missing = [a for a in REQUIRED_ATTRS if not hasattr(mod, a)]
        if missing:
            print(
                f"WARN source {info.name}: missing {', '.join(missing)} — skipped",
                file=sys.stderr,
            )
            continue
        mods.append(mod)
    return mods


def _now_utc():
    return datetime.now(timezone.utc)


def _find_dupe(new_entry, index, ratio):
    """job_key of the canonical near-duplicate for new_entry, or None (WS4).

    Same normalized company only — never across companies ("Backend Engineer"
    is identical across many firms). The earliest first_seen wins as canonical.
    Augments role_key/applied-ledger, never replaces them; any error is a
    non-match (best-effort). Empty/confidential companies never dedup-merge.
    """
    company = (new_entry.get("company") or "").strip().lower()
    if not company:
        return None
    matches = [
        (key, e) for key, e in index.items()
        if (e.get("company") or "").strip().lower() == company
        and _title_similar(new_entry["title"], e.get("title", ""), ratio)
    ]
    if not matches:
        return None
    return min(matches, key=lambda ke: ke[1].get("first_seen", ""))[0]


def update_index(jobs, index, dedup_ratio=DEFAULT_DEDUP_RATIO):
    """Merge jobs into the index; stamp first/last_seen; prune stale entries.

    New keys get first_seen = last_seen = now. Existing keys keep their
    (earliest) first_seen, refresh last_seen and mutable fields. A new entry
    that is a same-company near-duplicate of an existing one is tagged
    dupe_of=<canonical job_key> (WS4). Entries unseen for PRUNE_DAYS are
    dropped. Returns the updated index.
    """
    now_iso = _now_utc().isoformat()
    for j in jobs:
        k = job_key(j)
        entry = index.get(k)
        if entry is None:
            new_entry = {
                "title": j["title"], "company": j["company"],
                "location": j["location"], "url": j["url"],
                "source": j["source"], "posted_at": j.get("posted_at", ""),
                "comp": j.get("comp"), "score": j.get("_score", 0),
                "jd": j.get("jd", ""), "role_key": role_key(j),
                "first_seen": now_iso, "last_seen": now_iso,
            }
            dupe = _find_dupe(new_entry, index, dedup_ratio)
            if dupe is not None:
                new_entry["dupe_of"] = dupe
            index[k] = new_entry
        else:
            entry["last_seen"] = now_iso
            entry["score"] = j.get("_score", entry.get("score", 0))
            entry["location"] = j["location"] or entry.get("location", "")
            if j.get("comp") is not None:
                entry["comp"] = j["comp"]
            entry["jd"] = j.get("jd") or entry.get("jd", "")

    cutoff = _now_utc() - timedelta(days=PRUNE_DAYS)
    for k in list(index):
        try:
            last_seen = datetime.fromisoformat(
                index[k].get("last_seen", "").replace("Z", "+00:00")
            )
        except ValueError:
            continue  # unparseable stamp — keep, never destroy data on a bug
        if last_seen < cutoff:
            del index[k]
    return index


def run_collect(profile, selected, log):
    """Fetch selected sources, gate through matches_profile, persist index.

    Returns per-source status: "N roles" / "SKIP (reason)" / "ERROR (msg)".
    Writes home()/_index.json and a scans/<ts>.json snapshot of this run.
    """
    root = ensure_home()
    index_path = root / "_index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        index = {}

    registry = {getattr(m, "NAME", ""): m for m in load_sources()}
    dedup_ratio = profile.get("dedup", {}).get("title_ratio", DEFAULT_DEDUP_RATIO)
    results = {}
    snapshot = []
    for name in selected:
        mod = registry.get(name)
        if mod is None:
            results[name] = "SKIP (unknown source)"
            log(f"  {name}: {results[name]}")
            continue
        ok, reason = mod.available()
        if not ok:
            results[name] = f"SKIP ({reason})"
            log(f"  {name}: {results[name]}")
            continue
        try:
            jobs = mod.fetch(profile)
        except Exception as e:  # noqa: BLE001 — a raising source must not kill the run
            results[name] = f"ERROR ({e})"
            log(f"  {name}: {results[name]}")
            continue
        bypass = bool(getattr(mod, "bypass_lane", False))
        matched = []
        for j in jobs:
            keep, score = matches_profile(j, profile, bypass_lane=bypass)
            if keep:
                j["_score"] = score
                matched.append(j)
        index = update_index(matched, index, dedup_ratio)
        snapshot.extend(matched)
        results[name] = f"{len(matched)} roles"
        log(f"  {name}: {results[name]}")

    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    ts = _now_utc().strftime("%Y-%m-%d-%H-%M-%S")
    (root / "scans" / f"{ts}.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return results

"""Prepare: window filter, deterministic hard gates, feature cards.

100% deterministic — no network, no LLM, no I/O beyond reading the index/state
passed in and writing home()/_cards.json. Any gate fail → tier "C" and
needs_ai=False, so analyze never sees the card and spends nothing on it.
A bare-city location is a friction ("verify"), never a gate fail: a human or
the model confirms remoteness; determinism only rejects what it can prove.
"""

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from src import comp
from src.collect import EU_TERMS, NON_EU
from src.paths import ensure_home

WINDOW_DAYS = 14
# Ghost/liveness signals (WS3): apply-URL shorteners, posting-age thresholds,
# and confidential-employer markers. All pure metadata checks — no network.
SHORTENER_HOSTS = {"bit.ly", "tinyurl.com", "forms.gle", "goo.gl", "t.co", "rb.gy"}
STALE_DAYS = 30       # posted_at older than this → stale_posting
EVERGREEN_DAYS = 30   # first→last_seen span beyond this → repost_churn
CONFIDENTIAL_MARKERS = {"", "confidential", "undisclosed", "stealth", "n/a"}
REMOTE_TERMS = [
    "remote", "anywhere", "worldwide", "global", "distributed",
    "work from home", "wfh",
]
# Spoken-language requirement markers for the language gate.
LANGUAGE_NAMES = {
    "english": "en", "german": "de", "french": "fr", "polish": "pl",
    "spanish": "es", "dutch": "nl", "italian": "it", "portuguese": "pt",
}


def _parse_ts(s):
    try:
        ts = datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def ghost_flags(entry, now=None):
    """Deterministic ghost/liveness red-flag categories from card metadata (WS3).

    Pure, no network — these feed the same WS1 penalty seam analyze applies.
    Returns a subset of {stale_posting, repost_churn, untrusted_apply_domain,
    confidential_employer}. Missing or unparseable fields contribute nothing
    (flag-never-drop: a false heuristic must never delete a real role).
    """
    now = now or datetime.now(timezone.utc)
    flags = []

    posted = _parse_ts(entry.get("posted_at"))
    if posted is not None and posted < now - timedelta(days=STALE_DAYS):
        flags.append("stale_posting")

    first = _parse_ts(entry.get("first_seen"))
    last = _parse_ts(entry.get("last_seen"))
    if first and last and last - first > timedelta(days=EVERGREEN_DAYS):
        flags.append("repost_churn")

    host = urlparse(entry.get("url") or "").netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host in SHORTENER_HOSTS:
        flags.append("untrusted_apply_domain")

    if (entry.get("company") or "").strip().lower() in CONFIDENTIAL_MARKERS:
        flags.append("confidential_employer")

    return flags


def window_slice(index, last_run, days=WINDOW_DAYS):
    """Entries with first_seen > max(last_run, now - days), key attached."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    lr = _parse_ts(last_run) if last_run else None
    if lr is not None and lr > cutoff:
        cutoff = lr
    out = []
    for k in sorted(index):
        fs = _parse_ts(index[k].get("first_seen"))
        if fs is not None and fs > cutoff:
            out.append({"key": k, **index[k]})
    return out


def _blob(job):
    return (
        f"{job.get('title', '')} {job.get('location', '')} {job.get('company', '')}"
    ).lower()


def _geo(job, profile):
    """(failed, friction). Fail only on provable mismatch: block terms, or a
    non-EU marker with no EU term alongside. Remote/EU/allowed-geo signal
    passes clean; a bare city or empty location -> friction "verify"."""
    loc = (job.get("location") or "").lower()
    block = [b.lower() for b in profile.get("geo", {}).get("block", [])]
    if any(b in _blob(job) for b in block):
        return True, None
    # blank locations often carry the geo in the title (aggregators)
    geo = loc if loc else (job.get("title") or "").lower()
    has_eu = any(t in geo for t in EU_TERMS)
    if any(t in geo for t in NON_EU) and not has_eu:
        return True, None
    allow = [a.lower() for a in profile.get("geo", {}).get("allow", [])]
    if has_eu or any(t in geo for t in REMOTE_TERMS) or any(a in geo for a in allow):
        return False, None
    return False, "verify"


def _comp_norm(job, profile):
    """Normalized comp dict or None. Strings go through comp's raw parser."""
    c = job.get("comp")
    if c is None or c == "":
        return None
    floor = profile.get("comp", {}).get("floor_net_usd_mo", comp.DEFAULT_FLOOR)
    entry = {"raw": c} if isinstance(c, str) else c
    return comp.normalize(entry, floor)


def apply_gates(job, profile):
    """Failed hard-gate names for this job. Pure: profile data only, no I/O."""
    return _apply_gates(job, profile, _comp_norm(job, profile))


def _apply_gates(job, profile, comp_norm):
    failed = []
    blob = _blob(job)
    title = (job.get("title") or "").lower()

    geo_fail, _ = _geo(job, profile)
    if geo_fail:
        failed.append("geo")

    anti = [a.lower() for a in profile.get("lane", {}).get("anti", [])]
    if any(a in blob for a in anti):
        failed.append("lane")

    if comp_norm is not None and comp_norm.get("floor_verdict") == "below":
        failed.append("comp_floor")

    avoid = [a.lower() for a in profile.get("tech", {}).get("avoid_primary", [])]
    if any(a in title for a in avoid):
        failed.append("tech_spine")

    levels = profile.get("language_levels", {})
    for name, code in LANGUAGE_NAMES.items():
        needed = (f"{name} required" in blob or f"fluent {name}" in blob
                  or f"native {name}" in blob)
        if needed and code not in levels:
            failed.append("language")
            break

    for rule in profile.get("stage_rules", []):
        term = rule[3:] if rule.lower().startswith("no ") else rule
        if term.lower().strip() in blob:
            failed.append("stage")
            break

    return failed


def build_cards(profile, index, state):
    """Feature cards for every index entry; writes home()/_cards.json.

    in_window marks new-in-window cards explicitly — only that slice may ever
    reach analyze/board (out-of-window cards keep their earlier board records).
    needs_ai = in_window AND (zero failed gates) — analyze structurally spends
    only on that slice. Gate-failed cards ship with tier "C" pre-set.
    """
    window_keys = {e["key"] for e in window_slice(index, state.get("last_run"))}
    cards = []
    for k in sorted(index):
        entry = index[k]
        comp_norm = _comp_norm(entry, profile)
        gates_failed = _apply_gates(entry, profile, comp_norm)
        _, friction = _geo(entry, profile)
        in_window = k in window_keys
        card = {
            "key": k,
            **entry,
            "comp_norm": comp_norm,
            "gates_failed": gates_failed,
            "ghost_flags": ghost_flags(entry),
            "frictions": [friction] if friction else [],
            "in_window": in_window,
            "needs_ai": in_window and not gates_failed,
        }
        if gates_failed:
            card["tier"] = "C"
        cards.append(card)

    root = ensure_home()
    (root / "_cards.json").write_text(
        json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return cards

#!/usr/bin/env python3
"""Deterministic pre-pass for the /jobsearch AI step.

Goal: shrink the AI surface so a weak model (Haiku) only fills narrow gaps.
This does ZERO AI — pure rules on the data already in _index.json:
  • geo verdict   — remote / verify / unknown   (from the location string)
  • lane verdict  — in / out / ambiguous         (from the title; off-lane employers flagged)
  • comp          — [stated] if the index carries it, else flagged for AI/JD
Each role becomes a "feature card" with `needs_ai` listing only what a model
must still decide. The card feeds the weak-model step; everything pre-filled
here is stable and objectively testable (no model variance).

Usage:
  prepare.py                # window = roles new since last_review (cap 14d), like /jobsearch
  prepare.py --days N       # window = last N days (ignore last_review)
  prepare.py --all          # whole index (for coverage analysis)
  prepare.py --coverage     # print a determinism-coverage report to stderr, no JSON
"""
import json
import re
import sys
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import INDEX, STATE, JD_CACHE  # noqa: E402


def load_jd(url):
    """Read the sidecar JD (description+comp) cached by job-scan.py, if present."""
    import hashlib
    if not url:
        return {}
    p = JD_CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}

# ── geo: a location is "remote" only when it SAYS so ─────────────────────────
_REMOTE_RE = re.compile(
    r"\b(remote|anywhere|distributed|worldwide|work from home|wfh|"
    r"eu[\s-]?remote|remote[\s-]?eu|fully remote|home[\s-]?based)\b", re.I)
# non-EU / blocker signals that override a bare "remote" (UK-only, US-only, etc.)
_NONEU_RE = re.compile(
    r"\b(united states|u\.s\.|usa|us[\s-]?only|us[\s-]?based|"
    r"united kingdom|uk[\s-]?only|uk[\s-]?based|canada|apac|"
    r"latam|india|singapore|australia)\b", re.I)

# ── lane: title-keyword gate (first filter, before comp) ─────────────────────
_LANE_IN_RE = re.compile(
    r"\b(founding (?:ai |software )?engineer|applied ai|forward[\s-]?deployed|fde|"
    r"solutions? architect|solutions? engineer|ai engineer|agentic|agent engineer|"
    r"ml engineer|machine learning engineer|gen[\s-]?ai|deployment (?:engineer|strategist))\b", re.I)
_LANE_OUT_RE = re.compile(
    r"\b(full[\s-]?stack|back[\s-]?end|front[\s-]?end|product engineer|\bios\b|"
    r"android|mobile|devops|\bsre\b|site reliability|data engineer|growth engineer|"
    r"infrastructure engineer|platform engineer|qa\b|security engineer)\b", re.I)
# big consultancies / outstaffers: an "AI Solution Architect" title here is off-lane
# (enterprise GenAI consulting, not AI infra/devtools/agent) -> needs AI to judge employer
_OFFLANE_EMPLOYERS = {
    "accenture", "cgi", "bcg", "bcg platinion", "deloitte", "capgemini", "exl",
    "infosys", "tcs", "wipro", "cognizant", "epam", "globallogic", "ciklum",
    "msx international", "itrex group", "senovo it ltd", "strabag",
}

# ── comp: rough net/mo from a stated annual band (PL B2B ~0.86) ──────────────
_COMP_RE = re.compile(
    r"(?:\$|€|£|usd|eur|gbp)\s?(\d{2,3})\s?[kK]\b\s*[-–to]+\s*"
    r"(?:\$|€|£)?\s?(\d{2,3})\s?[kK]\b", re.I)


def _today():
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def classify_geo(location):
    loc = (location or "").strip()
    if not loc:
        return {"verdict": "unknown", "basis": "no location in index — needs JD"}
    if _NONEU_RE.search(loc) and not _REMOTE_RE.search(loc):
        return {"verdict": "verify", "basis": f"non-EU signal in '{loc}'"}
    if _REMOTE_RE.search(loc):
        if _NONEU_RE.search(loc):
            return {"verdict": "verify", "basis": f"remote but non-EU region in '{loc}'"}
        return {"verdict": "remote", "basis": f"explicit remote in '{loc}'"}
    return {"verdict": "verify", "basis": f"bare location '{loc}' — no remote word"}


def classify_lane(title, company):
    t, c = title or "", (company or "").strip().lower()
    is_in = bool(_LANE_IN_RE.search(t))
    is_out = bool(_LANE_OUT_RE.search(t))
    offlane_emp = any(c == e or c.startswith(e) for e in _OFFLANE_EMPLOYERS)
    if is_in and offlane_emp:
        return {"verdict": "ambiguous", "basis": f"in-lane title but off-lane employer ({company})"}
    if is_out and not is_in:
        return {"verdict": "out", "basis": "generic eng title (full-stack/backend/etc.)"}
    if is_in:
        return {"verdict": "in", "basis": "AI-lane title (FDE/SA/applied-AI/agent)"}
    return {"verdict": "ambiguous", "basis": "title not clearly in/out"}


def classify_comp(entry, jd):
    # prefer inline comp (lever/ashby), then the cached JD's comp, then a regex
    # over the JD description. ×0.86 ≈ PL B2B net.
    blob = " ".join(str(x) for x in (
        entry.get("comp", ""), entry.get("salary", ""),
        jd.get("comp", ""), jd.get("description", ""), entry.get("title", "")))
    m = _COMP_RE.search(blob)
    if not m:
        basis = ("no comp in JD — needs AI [est]" if jd else
                 "no JD cached yet — needs scrape/AI [est]")
        return {"found": False, "basis": basis}
    lo, hi = int(m.group(1)), int(m.group(2))
    net_lo, net_hi = round(lo / 12 * 0.86, 1), round(hi / 12 * 0.86, 1)
    return {"found": True, "raw": m.group(0),
            "net_mo_est": f"~${net_lo}-{net_hi}k", "basis": "stated band, ×0.86 PL net"}


def build_card(entry):
    url = entry.get("key") or entry.get("url")
    jd = load_jd(entry.get("url") or url)
    geo = classify_geo(entry.get("location"))
    lane = classify_lane(entry.get("title"), entry.get("company"))
    comp = classify_comp(entry, jd)
    needs = ["fit_features"]  # the irreducible AI judgment: match JD reqs vs CV
    if geo["verdict"] in ("verify", "unknown"):
        needs.append("geo_verify")
    if lane["verdict"] == "ambiguous":
        needs.append("lane_tiebreak")
    if not comp["found"]:
        needs.append("comp_est")
    return {
        "key": url,
        "role_key": entry.get("role_key"),
        "company": entry.get("company"),
        "title": entry.get("title"),
        "url": entry.get("url"),
        "location_raw": entry.get("location"),
        "source": entry.get("source"),
        "geo": geo, "lane": lane, "comp": comp,
        "has_jd": bool(jd.get("description")),
        # excerpt for the model to verify geo/comp/fit on real JD text, not just title
        "jd_excerpt": (jd.get("description", "")[:1500] if jd else ""),
        "hard_gate_fail": lane["verdict"] == "out",  # deterministic Tier-C, skip AI entirely
        "needs_ai": needs,
    }


def window_entries(mode, days):
    idx = json.loads(INDEX.read_text()) if INDEX.exists() else {}
    st = json.loads(STATE.read_text()) if STATE.exists() else {"last_review": None, "reviewed": [], "applied": []}
    now = datetime.datetime.now(datetime.timezone.utc)
    known = set(st.get("reviewed", [])) | set(st.get("applied", []))
    if mode == "all":
        start = None
    elif mode == "days":
        start = now - datetime.timedelta(days=days)
    else:
        cap = now - datetime.timedelta(days=14)
        start = max(datetime.datetime.fromisoformat(st["last_review"]), cap) if st.get("last_review") else cap
    out = []
    for k, v in idx.items():
        if mode != "all":
            try:
                if datetime.datetime.fromisoformat(v["first_seen"]) < start:
                    continue
            except Exception:
                continue
            if k in known or v.get("role_key") in known:
                continue
        out.append({"key": k, **v})
    return out


def coverage_report(cards):
    n = len(cards)
    if not n:
        print("no roles in window", file=sys.stderr)
        return
    geo = {}
    lane = {}
    gate = sum(1 for c in cards if c["hard_gate_fail"])
    no_ai = gate  # fully decided by rules
    comp_found = sum(1 for c in cards if c["comp"]["found"])
    has_jd = sum(1 for c in cards if c.get("has_jd"))
    for c in cards:
        geo[c["geo"]["verdict"]] = geo.get(c["geo"]["verdict"], 0) + 1
        lane[c["lane"]["verdict"]] = lane.get(c["lane"]["verdict"], 0) + 1
    p = lambda x: f"{x} ({round(100*x/n)}%)"
    print(f"\n── determinism coverage on {n} roles ──", file=sys.stderr)
    print(f"JD cached (flows to model): {p(has_jd)}", file=sys.stderr)
    print(f"GEO   deterministic: remote={p(geo.get('remote',0))}  "
          f"verify={p(geo.get('verify',0))}  unknown={p(geo.get('unknown',0))}", file=sys.stderr)
    print(f"LANE  deterministic: in={p(lane.get('in',0))}  out={p(lane.get('out',0))}  "
          f"ambiguous={p(lane.get('ambiguous',0))}", file=sys.stderr)
    print(f"COMP  deterministic from JD regex: {p(comp_found)}  (rest -> AI [est])", file=sys.stderr)
    print(f"HARD-GATE rejects (Tier C, no AI needed at all): {p(gate)}", file=sys.stderr)
    print(f"AI surface: fit always; geo_verify on {p(geo.get('verify',0)+geo.get('unknown',0))}; "
          f"lane_tiebreak on {p(lane.get('ambiguous',0))}; comp_est on {p(n-comp_found)}", file=sys.stderr)
    print(f"→ {p(no_ai)} fully resolved by rules; the rest hit the model with a NARROW card "
          f"+ real JD excerpt where cached ({p(has_jd)}).", file=sys.stderr)


def main():
    args = sys.argv[1:]
    mode, days, coverage_only = "window", 14, False
    if "--all" in args:
        mode = "all"
    if "--coverage" in args:
        coverage_only = True
        if mode == "window":
            mode = "all"  # coverage is most useful over the whole index
    if "--days" in args:
        mode = "days"
        days = int(args[args.index("--days") + 1])
    entries = window_entries(mode, days)
    cards = [build_card(e) for e in entries]
    if coverage_only:
        coverage_report(cards)
        return
    coverage_report(cards)  # always print the summary to stderr
    print(json.dumps({"generated": _today(), "count": len(cards), "cards": cards}, ensure_ascii=False))


if __name__ == "__main__":
    main()

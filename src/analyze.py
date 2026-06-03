#!/usr/bin/env python3
"""Keystone: turn deterministic feature cards (prepare.py) into scored, tiered
board roles. The weak model fills ONLY a narrow feature schema; the FIT SCORE is
a deterministic formula over those features (the model can't fudge the number).

Flow:
  prepare.py | analyze.py [--mock] [--limit N] [--no-board]
    • hard-gate cards (lane=out)         -> Tier C, NO model call
    • everything else                    -> model fills feature schema (1 role/call,
                                            narrow context = weak-model friendly)
    • fit = formula(features) · tier = f(fit, geo, comp-floor) · board.py add (A/B only)

Backend is whatever llm.get_backend() selects (claude_code A / openrouter B) — analyze
never knows which. --mock skips the model (deterministic stub from the card) to test
the plumbing without spending calls.

PROFILE below is the user's. TODO(B/multi-profile): load from profiles/<user>/profile.json.
"""
import argparse
import json
import subprocess
import sys
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm import get_backend  # noqa: E402
import store  # noqa: E402  (fit weights live here, tunable by the Improve loop)
from paths import load_profile  # noqa: E402
from scoring import THRESHOLD, TIER_A  # noqa: E402  (single-source tier cutlines, Δ3)

BOARD_PY = Path(__file__).resolve().parent / "board.py"

# ── user profile (from $YOKE_HOME/config/profile.json, fallback to the example) ──
_PROFILE = load_profile()
PROFILE = _PROFILE.get("prompt", "")
if _PROFILE.get("resume_text"):  # pasted CV (Profile page) — give the model the real thing
    PROFILE += "\n\nResume:\n" + _PROFILE["resume_text"]
OUTPUT_LANG = _PROFILE.get("output_language", "en")
COMP_FLOOR = float(_PROFILE.get("comp_floor_net_mo_usd") or 0)

_DEFAULT_SCORING = """You score how COMPETITIVE the candidate is for THIS role vs the likely applicant
pool, by matching the role against their profile above. Fill ONLY the schema. Be conservative: default
booleans to the cautious value when unsure. differentiator_hits = how many of the candidate's named
differentiators the role actually calls for (0-5). lane_match: 'in' = squarely the candidate's target
lane; 'adjacent' = related but off-center; 'out' = clearly a different kind of role. employer_winnable:
false if it's a bar the candidate can't realistically clear (e.g. PhD/research-only). geo_verdict:
'remote' only if the candidate's allowed location is explicitly eligible; 'verify' if unclear; 'blocked'
if the role excludes them (wrong country/relocation/work-auth). comp_est_net_mo: your net/mo USD estimate
for the candidate ONLY if comp isn't already known, else null — base the estimate on the COMPANY (stage,
size, kind) and the TARGET MARKET/geo the role hires in, not the title alone (the same title can pay 2-3x
across companies and markets); mark it as an estimate. note: ONE short line in {lang}."""

SCORING_INSTRUCTIONS = (_PROFILE.get("scoring_instructions")
                        or _DEFAULT_SCORING).replace("{lang}", OUTPUT_LANG)

FEATURE_SCHEMA = {
    "fit_features": {
        "lane_match": "in|adjacent|out",
        "differentiator_hits": "integer 0-5",
        "seniority_ok": "boolean",
        "lang_ok": "boolean",
        "employer_winnable": "boolean",
    },
    "geo_verdict": "remote|verify|blocked",
    "comp_est_net_mo": "string like '~$8-11k' or null",
    "note": "one short line",
}


def label_of(fit, geo="remote"):
    # "Top candidate" requires a confirmed-remote geo — otherwise the gate (tier_of)
    # caps the role at B and the label must agree, never overstating (truthfulness,
    # FR-014). The verify state itself is carried by the adjacent geo cell, so we
    # only demote the top band here — no redundant "verify" suffix on the label.
    if fit >= 85: return "🟢 Top candidate" if geo == "remote" else "🟢 Strong"
    if fit >= 70: return "🟢 Strong"
    if fit >= 55: return "🟡 Good"
    if fit >= 40: return "🟡 Stretch"
    return "🔴 Reach"


def comp_display(comp, estimated, below):
    """Render the comp cell. A model-estimated band is flagged 'est' (ed66a591:
    never present a guess as a scraped fact); below-floor gets the gate marker."""
    return (comp or "? [research]") + (" est" if estimated and comp else "") + (" ⛔<floor" if below else "")


def score_fit(f, w=None):
    """Deterministic weighted formula — the model only supplies the features.
    Weights come from store (tunable by the Improve loop); pass w explicitly in
    tight loops (tune.py) to avoid re-reading the DB per call."""
    w = w or store.get_weights()
    lane = {"in": w["lane_in"], "adjacent": w["lane_adjacent"], "out": 0}.get(f.get("lane_match"), 25)
    diff = min(int(f.get("differentiator_hits", 0) or 0), w["diff_cap"]) * w["diff_per_hit"]
    sen = w["seniority_ok"] if f.get("seniority_ok") else w["seniority_no"]
    lang = w["lang_ok"] if f.get("lang_ok", True) else w["lang_no"]
    emp = 0 if f.get("employer_winnable", True) else w["emp_no"]
    return max(0, min(100, lane + diff + sen + lang + emp))


_GEO_DISPLAY = {"remote": "✅ remote", "verify": "⚠️ verify", "blocked": "⛔ blocked", "unknown": "⚠️ verify"}


def tier_of(fit, geo, comp_below_floor):
    if geo == "blocked":
        return "C"
    if comp_below_floor:
        return "C"  # passive-search floor: below ~$10k net is not an option
    if fit >= TIER_A and geo == "remote":
        return "A"
    if fit >= THRESHOLD or (fit >= TIER_A and geo == "verify"):
        return "B"
    return "C"


def mock_fill(card):
    """Deterministic stub from the card — for --mock plumbing tests, no model call."""
    lane = {"in": "in", "out": "out", "ambiguous": "adjacent"}.get(card["lane"]["verdict"], "adjacent")
    return {
        "fit_features": {"lane_match": lane, "differentiator_hits": 1,
                         "seniority_ok": True, "lang_ok": True, "employer_winnable": True},
        "geo_verdict": card["geo"]["verdict"] if card["geo"]["verdict"] != "unknown" else "verify",
        "comp_est_net_mo": (card["comp"].get("net_mo_est") if card["comp"]["found"] else "~$8-11k [est]"),
        "note": "(mock)",
    }


def model_fill(backend, card):
    role = {k: card.get(k) for k in ("title", "company", "location_raw", "url", "source")}
    role["deterministic_geo"] = card["geo"]
    role["deterministic_lane"] = card["lane"]
    role["comp_known"] = card["comp"]
    prompt = "Role:\n" + json.dumps(role, ensure_ascii=False, indent=2)
    jd = card.get("jd_excerpt")
    if jd:  # real JD text → judge geo/comp/fit on content, not just the title
        prompt += "\n\nJob description (excerpt):\n" + jd
    prompt += "\n\nFill the feature schema for this role."
    return backend.complete(prompt, schema=FEATURE_SCHEMA, system=PROFILE + "\n\n" + SCORING_INSTRUCTIONS)


def comp_below_floor(comp_str):
    """Flag if the high end of a '~$X-Yk' net/mo estimate is below the profile's
    comp floor (in $k/mo). Floor 0 (the default) means nothing is below it."""
    if not COMP_FLOOR or not comp_str:
        return False
    import re
    m = re.search(r"\$?\s?(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*k", comp_str, re.I)
    if not m:
        return False
    return float(m.group(2)) < (COMP_FLOOR / 1000.0)  # comp in $k/mo vs floor in $/mo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="skip the model, deterministic stub")
    ap.add_argument("--limit", type=int, default=0, help="process at most N non-rejected roles")
    ap.add_argument("--no-board", action="store_true", help="print results, don't push to board.py")
    ap.add_argument("--cards", help="read cards from file instead of stdin")
    args = ap.parse_args()

    payload = json.loads(Path(args.cards).read_text() if args.cards else sys.stdin.read())
    cards = payload.get("cards", payload if isinstance(payload, list) else [])
    backend = None if args.mock else get_backend()
    if backend:
        print(f"backend: {backend.name} ({getattr(backend,'model','?')})", file=sys.stderr)

    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    roles, tiers = [], {"A": 0, "B": 0, "C": 0}
    processed = 0
    for card in cards:
        if card.get("hard_gate_fail"):  # lane=out -> Tier C, no model call
            tiers["C"] += 1
            continue
        if args.limit and processed >= args.limit:
            break
        processed += 1
        try:
            fill = mock_fill(card) if args.mock else model_fill(backend, card)
        except Exception as e:
            print(f"  SKIP {card.get('company')}/{card.get('title')}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        fit = score_fit(fill.get("fit_features", {}))
        geo = fill.get("geo_verdict") or card["geo"]["verdict"]
        comp = (card["comp"].get("net_mo_est") if card["comp"]["found"]
                else fill.get("comp_est_net_mo"))
        comp_estimated = (not card["comp"]["found"]) and bool(comp)  # model guess, not scraped (ed66a591)
        below = comp_below_floor(comp)
        tier = tier_of(fit, geo, below)
        tiers[tier] += 1
        if tier == "C":
            continue
        roles.append({
            "key": card["key"], "role_key": card.get("role_key"),
            "company": card.get("company"), "title": card.get("title"), "url": card.get("url"),
            "fit": fit, "label": label_of(fit, geo),
            "geo": _GEO_DISPLAY.get(geo, geo),
            "comp": comp_display(comp, comp_estimated, below),
            "lane": fill.get("fit_features", {}).get("lane_match", card["lane"]["verdict"]),
            "note": fill.get("note", ""),
            "tier": tier, "date_added": today,
            # raw model features → board → label snapshot → tunable by Improve
            "features": json.dumps(fill.get("fit_features", {}), ensure_ascii=False),
        })

    print(f"\nscored {processed} (A={tiers['A']} B={tiers['B']} C+rejected={tiers['C']}) "
          f"-> {len(roles)} to board", file=sys.stderr)
    if args.no_board or not roles:
        print(json.dumps({"roles": roles}, ensure_ascii=False, indent=2))
        return
    subprocess.run([sys.executable, str(BOARD_PY), "add"],
                   input=json.dumps(roles, ensure_ascii=False), text=True, check=True)


if __name__ == "__main__":
    main()

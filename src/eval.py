#!/usr/bin/env python3
"""Eval harness — measures a weak candidate model against an Opus reference on a
frozen golden set, so we can trust/improve/auto-escalate the model with numbers
instead of vibes. Safety gates (geo false-positive, Tier-A overreach, parse
failure) dominate fuzzy fit-±; a failing gate blocks trusting the candidate.

  eval.py build-golden --n 12 [--mock]   # freeze N cards + Opus REFERENCE -> golden.json
  eval.py run [--model M] [--mock]       # CANDIDATE (default Haiku) vs reference -> scorecard
                                         #   + eval-report-<date>.json for drift tracking

Reference = analyze.py's model_fill driven by Opus; candidate = same on the weak
model. Both reuse the deterministic score_fit/tier_of so we compare apples to apples
(only the model-supplied FEATURES differ). --mock skips models (tests the math).
"""
import argparse
import json
import os
import sys
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm import get_backend  # noqa: E402
from analyze import score_fit, tier_of, model_fill, mock_fill, comp_below_floor  # noqa: E402
from paths import YOKE_HOME, ensure_home  # noqa: E402

GOLDEN = YOKE_HOME / "eval-golden.json"
REF_MODEL = os.environ.get("YOKE_REF_MODEL", "claude-opus-4-8")    # ground truth
CAND_MODEL = os.environ.get("YOKE_MODEL", "claude-haiku-4-5")      # model under test


def _score(fill, card):
    """Collapse a model fill + card into the comparable verdict tuple."""
    fit = score_fit(fill.get("fit_features", {}))
    geo = fill.get("geo_verdict") or card["geo"]["verdict"]
    comp = card["comp"].get("net_mo_est") if card["comp"]["found"] else fill.get("comp_est_net_mo")
    tier = tier_of(fit, geo, comp_below_floor(comp))
    lane = fill.get("fit_features", {}).get("lane_match", card["lane"]["verdict"])
    return {"fit": fit, "geo": geo, "tier": tier, "lane": lane}


def _sample(cards, n):
    cards = [c for c in cards if not c.get("hard_gate_fail")]  # model-judgment roles only
    if len(cards) <= n:
        return cards
    step = len(cards) / n
    return [cards[int(i * step)] for i in range(n)]


def build_golden(n, mock):
    ensure_home()
    payload = json.loads(sys.stdin.read())
    cards = _sample(payload.get("cards", payload), n)
    ref = None if mock else get_backend(force="claude_code", model=REF_MODEL)
    print(f"reference: {'mock' if mock else REF_MODEL} over {len(cards)} roles", file=sys.stderr)
    items = []
    for i, c in enumerate(cards, 1):
        try:
            fill = mock_fill(c) if mock else model_fill(ref, c)
        except Exception as e:
            print(f"  [{i}] REF SKIP {c.get('company')}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        items.append({"card": c, "ref_fill": fill, "ref": _score(fill, c)})
        print(f"  [{i}/{len(cards)}] {c.get('company')}: ref tier {items[-1]['ref']['tier']}", file=sys.stderr)
    GOLDEN.write_text(json.dumps(
        {"built": datetime.datetime.now(datetime.timezone.utc).isoformat(),
         "ref_model": "mock" if mock else REF_MODEL, "items": items}, ensure_ascii=False, indent=2))
    print(f"\ngolden set saved: {len(items)} roles -> {GOLDEN}", file=sys.stderr)


def run_eval(model, mock):
    if not GOLDEN.exists():
        print("no golden set — run `eval.py build-golden` first", file=sys.stderr)
        sys.exit(1)
    golden = json.loads(GOLDEN.read_text())
    items = golden["items"]
    cand = None if mock else get_backend(model=model or CAND_MODEL)
    cand_name = "mock" if mock else f"{cand.name}:{getattr(cand,'model','?')}"
    print(f"candidate: {cand_name} vs reference {golden['ref_model']} on {len(items)} roles", file=sys.stderr)

    n = 0
    geo_fp = tierA_overreach = parse_fail = 0
    tier_exact = tier_within1 = lane_exact = geo_exact = 0
    fit_abs = 0
    tier_rank = {"A": 0, "B": 1, "C": 2}
    rows = []
    for it in items:
        card, ref = it["card"], it["ref"]
        try:
            fill = mock_fill(card) if mock else model_fill(cand, card)
        except Exception as e:
            parse_fail += 1
            rows.append({"company": card.get("company"), "error": f"{type(e).__name__}: {e}"})
            continue
        cand_v = _score(fill, card)
        n += 1
        # ── safety gates ──
        if cand_v["geo"] == "remote" and ref["geo"] in ("verify", "blocked"):
            geo_fp += 1
        if cand_v["tier"] == "A" and ref["tier"] in ("B", "C"):
            tierA_overreach += 1
        # ── soft agreement ──
        if cand_v["tier"] == ref["tier"]:
            tier_exact += 1
        if abs(tier_rank[cand_v["tier"]] - tier_rank[ref["tier"]]) <= 1:
            tier_within1 += 1
        if cand_v["lane"] == ref["lane"]:
            lane_exact += 1
        if cand_v["geo"] == ref["geo"]:
            geo_exact += 1
        fit_abs += abs(cand_v["fit"] - ref["fit"])
        rows.append({"company": card.get("company"), "ref": ref, "cand": cand_v})

    pct = lambda x: round(100 * x / n) if n else 0
    gates_pass = (geo_fp == 0 and parse_fail == 0 and tierA_overreach <= max(1, round(0.05 * n)))
    soft_pass = (pct(tier_within1) >= 80 and pct(lane_exact) >= 70)
    verdict = "PASS" if (gates_pass and soft_pass) else "FAIL"

    report = {
        "ran": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "candidate": cand_name, "reference": golden["ref_model"], "n": n,
        "hard_gates": {"geo_false_positive": geo_fp, "tierA_overreach": tierA_overreach,
                       "parse_fail": parse_fail, "pass": gates_pass},
        "soft": {"tier_exact_pct": pct(tier_exact), "tier_within1_pct": pct(tier_within1),
                 "lane_exact_pct": pct(lane_exact), "geo_exact_pct": pct(geo_exact),
                 "fit_mae": round(fit_abs / n, 1) if n else None, "pass": soft_pass},
        "verdict": verdict,
    }
    out = BASE / f"eval-report-{report['ran'][:10]}.json"
    out.write_text(json.dumps({**report, "rows": rows}, ensure_ascii=False, indent=2))

    print(f"\n── EVAL: {cand_name} vs {golden['ref_model']} (n={n}) ──")
    print(f"HARD GATES  {'✅ PASS' if gates_pass else '❌ FAIL'}")
    print(f"  geo false-positive (said remote, truth wasn't): {geo_fp}   [must be 0]")
    print(f"  Tier-A overreach (A but truth B/C):             {tierA_overreach}   [≤{max(1, round(0.05*n))}]")
    print(f"  parse failures (bad/no JSON):                    {parse_fail}   [must be 0]")
    print(f"SOFT AGREEMENT  {'✅' if soft_pass else '⚠️'}")
    print(f"  tier exact:    {pct(tier_exact)}%      tier ±1: {pct(tier_within1)}%   [≥80]")
    print(f"  lane exact:    {pct(lane_exact)}%   [≥70]   geo exact: {pct(geo_exact)}%")
    print(f"  fit MAE:       {report['soft']['fit_mae']} pts")
    print(f"\nVERDICT: {verdict}   (report: {out.name})")
    if verdict == "FAIL":
        print("→ failures tell you what to determinize next "
              "(e.g. geo FP high → move geo to a deterministic JD classifier, "
              "model stops touching it) OR auto-escalate those roles to Sonnet.")
    sys.exit(0 if verdict == "PASS" else 2)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("build-golden")
    g.add_argument("--n", type=int, default=12)
    g.add_argument("--mock", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--model", default=None)
    r.add_argument("--mock", action="store_true")
    a = ap.parse_args()
    if a.cmd == "build-golden":
        build_golden(a.n, a.mock)
    else:
        run_eval(a.model, a.mock)


if __name__ == "__main__":
    main()

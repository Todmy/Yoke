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

BASE = YOKE_HOME                                                   # eval reports land here
GOLDEN = YOKE_HOME / "eval-golden.json"
REF_MODEL = os.environ.get("YOKE_REF_MODEL", "claude-opus-4-8")    # reference draft (human-reviewed → truth)
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
        sc = _score(fill, c)
        # `expected` seeds from the reference but is a DRAFT for human review (FR-015);
        # `ref` is kept for provenance. The human edits `expected` + flips reviewed.
        items.append({"card": c, "ref_fill": fill, "ref": sc, "expected": sc, "reviewed": False})
        print(f"  [{i}/{len(cards)}] {c.get('company')}: ref tier {sc['tier']}", file=sys.stderr)
    GOLDEN.write_text(json.dumps(
        {"built": datetime.datetime.now(datetime.timezone.utc).isoformat(),
         "ref_model": "mock" if mock else REF_MODEL, "reviewed": False, "items": items},
        ensure_ascii=False, indent=2))
    print(f"\ngolden set saved: {len(items)} roles -> {GOLDEN}", file=sys.stderr)
    print("NEXT (FR-015): human-review the `expected` labels and seed known-unsafe traps, "
          "then `eval.py curate --done`. Opus output is a DRAFT reference, not ground "
          "truth until a human signs off.", file=sys.stderr)


def evaluate(items, fill_for):
    """Grade candidate fills against each item's curated `expected` truth (falls
    back to `ref`). Safety gates dominate (geo false-positive, Tier-A overreach,
    parse failure). PURE — returns the report dict; no file write, no exit, so it
    is unit-testable with a stub `fill_for(card)` and seeded trap items."""
    n = 0
    geo_fp = tierA_overreach = parse_fail = 0
    tier_exact = tier_within1 = lane_exact = geo_exact = 0
    fit_abs = 0
    tier_rank = {"A": 0, "B": 1, "C": 2}
    rows = []
    for it in items:
        card = it["card"]
        truth = it.get("expected") or it["ref"]   # curated label is the ground truth
        try:
            fill = fill_for(card)
        except Exception as e:
            parse_fail += 1
            rows.append({"company": card.get("company"), "error": f"{type(e).__name__}: {e}"})
            continue
        cand_v = _score(fill, card)
        n += 1
        if cand_v["geo"] == "remote" and truth["geo"] in ("verify", "blocked"):
            geo_fp += 1
        if cand_v["tier"] == "A" and truth["tier"] in ("B", "C"):
            tierA_overreach += 1
        if cand_v["tier"] == truth["tier"]:
            tier_exact += 1
        if abs(tier_rank[cand_v["tier"]] - tier_rank[truth["tier"]]) <= 1:
            tier_within1 += 1
        if cand_v["lane"] == truth["lane"]:
            lane_exact += 1
        if cand_v["geo"] == truth["geo"]:
            geo_exact += 1
        fit_abs += abs(cand_v["fit"] - truth["fit"])
        rows.append({"company": card.get("company"), "expected": truth, "cand": cand_v})

    pct = lambda x: round(100 * x / n) if n else 0
    gates_pass = (geo_fp == 0 and parse_fail == 0 and tierA_overreach <= max(1, round(0.05 * n)))
    soft_pass = (pct(tier_within1) >= 80 and pct(lane_exact) >= 70)
    return {
        "n": n,
        "hard_gates": {"geo_false_positive": geo_fp, "tierA_overreach": tierA_overreach,
                       "parse_fail": parse_fail, "pass": gates_pass},
        "soft": {"tier_exact_pct": pct(tier_exact), "tier_within1_pct": pct(tier_within1),
                 "lane_exact_pct": pct(lane_exact), "geo_exact_pct": pct(geo_exact),
                 "fit_mae": round(fit_abs / n, 1) if n else None, "pass": soft_pass},
        "verdict": "PASS" if (gates_pass and soft_pass) else "FAIL",
        "rows": rows,
    }


def run_eval(model, mock):
    if not GOLDEN.exists():
        print("no golden set — run `eval.py build-golden` first", file=sys.stderr)
        sys.exit(1)
    golden = json.loads(GOLDEN.read_text())
    items = golden["items"]
    if not golden.get("reviewed"):
        print("⚠️  golden set UNREVIEWED — `expected` labels are raw reference-model output, "
              "not human-curated ground truth. Verdict is PROVISIONAL until `eval.py curate "
              "--done` (FR-015).", file=sys.stderr)
    cand = None if mock else get_backend(model=model or CAND_MODEL)
    cand_name = "mock" if mock else f"{cand.name}:{getattr(cand, 'model', '?')}"
    print(f"candidate: {cand_name} vs reference {golden['ref_model']} on {len(items)} roles", file=sys.stderr)

    fill_for = (lambda card: mock_fill(card)) if mock else (lambda card: model_fill(cand, card))
    report = {"ran": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "candidate": cand_name, "reference": golden["ref_model"],
              "reviewed": bool(golden.get("reviewed")), **evaluate(items, fill_for)}
    n = report["n"]
    geo_fp = report["hard_gates"]["geo_false_positive"]
    tierA_overreach = report["hard_gates"]["tierA_overreach"]
    parse_fail = report["hard_gates"]["parse_fail"]
    gates_pass = report["hard_gates"]["pass"]
    soft_pass = report["soft"]["pass"]
    pct = lambda key: report["soft"][key]
    tier_exact, tier_within1 = pct("tier_exact_pct"), pct("tier_within1_pct")
    lane_exact, geo_exact = pct("lane_exact_pct"), pct("geo_exact_pct")
    verdict = report["verdict"]
    out = BASE / f"eval-report-{report['ran'][:10]}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    print(f"\n── EVAL: {cand_name} vs {golden['ref_model']} (n={n}) ──")
    print(f"HARD GATES  {'✅ PASS' if gates_pass else '❌ FAIL'}")
    print(f"  geo false-positive (said remote, truth wasn't): {geo_fp}   [must be 0]")
    print(f"  Tier-A overreach (A but truth B/C):             {tierA_overreach}   [≤{max(1, round(0.05*n))}]")
    print(f"  parse failures (bad/no JSON):                    {parse_fail}   [must be 0]")
    print(f"SOFT AGREEMENT  {'✅' if soft_pass else '⚠️'}")
    print(f"  tier exact:    {tier_exact}%      tier ±1: {tier_within1}%   [≥80]")
    print(f"  lane exact:    {lane_exact}%   [≥70]   geo exact: {geo_exact}%")
    print(f"  fit MAE:       {report['soft']['fit_mae']} pts")
    print(f"\nVERDICT: {verdict}   (report: {out.name})")
    if verdict == "FAIL":
        print("→ failures tell you what to determinize next "
              "(e.g. geo FP high → move geo to a deterministic JD classifier, "
              "model stops touching it) OR auto-escalate those roles to Sonnet.")
    sys.exit(0 if verdict == "PASS" else 2)


def curate(done, seed):
    """FR-015: human-review step. `--seed FILE` merges curated known-unsafe trap
    roles ({card, expected}); `--done` marks the golden set human-reviewed so the
    eval verdict stops being provisional."""
    if not GOLDEN.exists():
        print("no golden set — run `eval.py build-golden` first", file=sys.stderr)
        sys.exit(1)
    golden = json.loads(GOLDEN.read_text())
    if seed:
        traps = json.loads(Path(seed).read_text())
        traps = traps if isinstance(traps, list) else traps.get("items", [])
        for t in traps:
            t.setdefault("ref", t.get("expected"))
            t["reviewed"] = True
            golden["items"].append(t)
        print(f"curate: merged {len(traps)} seed/trap item(s)", file=sys.stderr)
    if done:
        golden["reviewed"] = True
        for it in golden["items"]:
            it["reviewed"] = True
        print("curate: golden set marked HUMAN-REVIEWED (FR-015) — verdicts are now authoritative.",
              file=sys.stderr)
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=2))
    print(f"golden set: {len(golden['items'])} items, reviewed={golden.get('reviewed', False)}",
          file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("build-golden")
    g.add_argument("--n", type=int, default=12)
    g.add_argument("--mock", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--model", default=None)
    r.add_argument("--mock", action="store_true")
    c = sub.add_parser("curate")
    c.add_argument("--done", action="store_true", help="mark the golden set human-reviewed (FR-015)")
    c.add_argument("--seed", default=None, help="JSON file of curated trap roles to merge")
    a = ap.parse_args()
    if a.cmd == "build-golden":
        build_golden(a.n, a.mock)
    elif a.cmd == "curate":
        curate(a.done, a.seed)
    else:
        run_eval(a.model, a.mock)


if __name__ == "__main__":
    main()

"""Eval: score the current model against a frozen golden set.

The `score` half makes ZERO model calls — it compares pre-recorded model
outputs (`_eval_run.json`, produced by `record`) against human-reviewed truth
labels (`_golden.json`). Safety gates dominate the verdict; per-dimension
diagnostics localise which part of the process underperforms; aggregate
tier-agreement is subordinate.
"""

import json

from src import analyze
from src.paths import ensure_home, home, load_profile

GOLDEN_FILE = "_golden.json"
EVAL_RUN_FILE = "_eval_run.json"
_JSON_KEYS = ("n", "backend", "safety", "dimensions", "fit", "verdict")

_TIER_RANK = {"A": 3, "B": 2, "C": 1}


def _tier_rank(tier: str) -> int:
    return _TIER_RANK.get(tier, 0)


def _rate(num: float, den: float) -> float:
    return num / den if den else 0.0


def load_golden() -> list[dict]:
    """Read home()/_golden.json; fail open (missing/malformed/non-list -> [])."""
    path = home() / GOLDEN_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def score(eval_run: dict, golden: list[dict]) -> dict:
    """Compare frozen model outputs to golden truth. Zero model calls.

    Returns a scorecard: dominant safety hard-counts + per-dimension diagnostics
    + subordinate tier-agreement + a safety verdict.
    """
    by_key = {m.get("key"): m for m in eval_run.get("roles", [])}
    geo_fp = tier_op = unparseable = 0
    geo_agree = comp_agree = tier_exact = tier_adj = 0
    evaluable = 0
    rf_tp = rf_fp = rf_fn = 0
    feat_err: dict[str, list[float]] = {}

    for g in golden:
        m = by_key.get(g.get("key"))
        truth = g.get("truth", {})
        if m is None or "geo" not in m or "tier" not in m:
            unparseable += 1
            continue
        evaluable += 1
        # safety (dominant)
        if m["geo"] == "remote_confirmed" and truth.get("geo") == "onsite":
            geo_fp += 1
        if _tier_rank(m["tier"]) > _tier_rank(truth.get("tier", "C")):
            tier_op += 1
        # per-dimension diagnostics
        geo_agree += m["geo"] == truth.get("geo")
        comp_agree += m.get("comp_vs_floor") == truth.get("comp_vs_floor")
        mset, tset = set(m.get("red_flags", [])), set(truth.get("red_flags", []))
        rf_tp += len(mset & tset)
        rf_fp += len(mset - tset)
        rf_fn += len(tset - mset)
        # subordinate fit/tier agreement
        tier_exact += m["tier"] == truth.get("tier")
        tier_adj += abs(_tier_rank(m["tier"]) - _tier_rank(truth.get("tier", "C"))) <= 1
        # optional per-feature error
        tf = truth.get("features")
        if tf:
            mf = m.get("features", {})
            for name, tv in tf.items():
                feat_err.setdefault(name, []).append(abs(mf.get(name, 0) - tv))

    dimensions: dict[str, dict] = {
        "geo": {"agreement": _rate(geo_agree, evaluable)},
        "comp_vs_floor": {"agreement": _rate(comp_agree, evaluable)},
        "red_flags": {
            "recall": _rate(rf_tp, rf_tp + rf_fn),
            "precision": _rate(rf_tp, rf_tp + rf_fp),
        },
    }
    if feat_err:
        dimensions["features"] = {
            name: {"mae": _rate(sum(errs), len(errs))} for name, errs in feat_err.items()
        }

    total = geo_fp + tier_op + unparseable
    return {
        "n": len(golden),
        "backend": eval_run.get("backend"),
        "safety": {
            "geo_false_positive": geo_fp,
            "tier_over_promotion": tier_op,
            "unparseable": unparseable,
            "total": total,
        },
        "dimensions": dimensions,
        "fit": {
            "tier_exact": _rate(tier_exact, evaluable),
            "tier_adjacent": _rate(tier_adj, evaluable),
        },
        "verdict": "safety-fail" if total else "safety-clean",
    }


def record(golden: list[dict], backend, log=lambda *a: None) -> dict:
    """Run the current backend over the golden roles once, freeze to _eval_run.json.

    The ONLY model-touching function in eval — reuses the analyze scoring path
    (backend injected, so eval imports no llm). Returns the eval_run dict.
    """
    profile = load_profile()
    cards = [{
        "key": g.get("key"), "company": g.get("company", ""), "title": g.get("title", ""),
        "location": g.get("location", ""), "url": g.get("url", ""),
        "source": g.get("source", ""), "jd": g.get("jd", ""),
        "needs_ai": True, "comp_norm": None,
    } for g in golden]
    records = analyze.analyze_cards(cards, profile, backend, log)

    roles = []
    for rec in records:
        feats = rec.get("features", {})
        comp_ev = feats.get("comp_vs_floor", {}).get("evidence", "")
        verdict = comp_ev.removeprefix("floor verdict: ") if comp_ev else "unknown"
        roles.append({
            "key": rec.get("key"),
            "geo": rec.get("geo_certainty", ""),
            "tier": rec.get("tier", ""),
            "comp_vs_floor": verdict,
            "red_flags": [rf["category"] for rf in rec.get("red_flags", []) if rf.get("category")],
            "fit": rec.get("fit", 0),
            "features": {name: fv.get("score", 0) for name, fv in feats.items()},
        })
    eval_run = {"backend": backend.describe(), "roles": roles}
    ensure_home()
    (home() / EVAL_RUN_FILE).write_text(
        json.dumps(eval_run, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return eval_run


def _paint(text: str, code: str, use_color: bool) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if use_color else text


def render_scorecard(card: dict, use_color: bool = False) -> str:
    """Human render: verdict + safety FIRST (dominant), then per-dimension
    diagnostics (actionable), then subordinate tier agreement."""
    s, d, fit = card["safety"], card["dimensions"], card["fit"]
    color = "31" if card["verdict"] == "safety-fail" else "32"
    lines = [
        f"Eval scorecard — {card['n']} roles via {card['backend']}",
        "",
        _paint(f"VERDICT: {card['verdict']}", color, use_color),
        "Safety (dominant):",
        f"  geo false-positive:  {s['geo_false_positive']}",
        f"  tier over-promotion: {s['tier_over_promotion']}",
        f"  unparseable:         {s['unparseable']}",
        "",
        "Dimensions (which part of the process is weak):",
        f"  geo agreement:            {d['geo']['agreement']}",
        f"  comp_vs_floor agreement:  {d['comp_vs_floor']['agreement']}",
        f"  red_flags recall/prec:    {d['red_flags']['recall']}/{d['red_flags']['precision']}",
    ]
    for name, stats in d.get("features", {}).items():
        lines.append(f"  feature {name} MAE:      {stats['mae']}")
    lines += [
        "",
        "Fit (subordinate):",
        f"  tier exact:    {fit['tier_exact']}",
        f"  tier adjacent: {fit['tier_adjacent']}",
    ]
    return "\n".join(lines)


def scorecard_json(card: dict) -> dict:
    """Stable --json contract: the fixed key set only."""
    return {k: card[k] for k in _JSON_KEYS}

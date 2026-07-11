"""Eval: score the current model against a frozen golden set.

The `score` half makes ZERO model calls — it compares pre-recorded model
outputs (`_eval_run.json`, produced by `record`) against human-reviewed truth
labels (`_golden.json`). Safety gates dominate the verdict; per-dimension
diagnostics localise which part of the process underperforms; aggregate
tier-agreement is subordinate.
"""

import json

from src.paths import home

GOLDEN_FILE = "_golden.json"
EVAL_RUN_FILE = "_eval_run.json"

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

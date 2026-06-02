#!/usr/bin/env python3
"""Fit-weight tuner — the self-improvement step. Refits the fit-formula weights
to your REAL decisions (labels), so the score separates roles he pursues
(applied/interested) from roles he rejects. Deterministic grid-search, ZERO
model calls. The Improve button (serve.py) calls this.

  tune.py            # report: current vs proposed weights + objective before/after
  tune.py --json     # machine-readable (for serve.py)
  tune.py --apply    # persist the proposed weights to the store

Objective = balanced accuracy at the "worth pursuing" threshold (fit >= 55):
fraction of pursued roles scored >=55 AND fraction of rejected roles scored <55,
averaged. Needs BOTH classes with RAW features — otherwise it can't separate and
says so (that's the honest gate, not a crash)."""
import argparse
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store  # noqa: E402
from analyze import score_fit  # noqa: E402
from scoring import THRESHOLD  # noqa: E402  (single-source cutline shared with analyze.tier_of, Δ3)

# coarse grid around the most impactful weights (kept small: deterministic + fast)
GRID = {
    "lane_in": [40, 50, 60],
    "lane_adjacent": [20, 30],
    "diff_per_hit": [5, 7, 9, 11],
    "seniority_ok": [5, 10, 15],
}


# Δ2: the tuner refuses to fit below these (configurable via store meta 'tune_gate').
# A handful of points per class overfits the weight grid and yields a misleading
# before/after — so it declines and explains, rather than producing junk weights.
GATE_DEFAULTS = {"min_applied": 5, "min_rejected": 5, "min_total": 20}


def gate_thresholds():
    g = dict(GATE_DEFAULTS)
    g.update(store.get_meta("tune_gate", {}) or {})
    return g


def _split(labels):
    # Δ1: positive class = `applied` ONLY. `interested` is a bookmark, not a label —
    # the tuner learns from action (applied) vs rejection, not from intent.
    pos = [l for l in labels if l["decision"] == "applied"]
    neg = [l for l in labels if l["decision"] == "rejected"]
    return pos, neg


def objective(pos, neg, w):
    if not pos or not neg:
        return None
    tp = sum(score_fit(l["features"], w) >= THRESHOLD for l in pos) / len(pos)
    tn = sum(score_fit(l["features"], w) < THRESHOLD for l in neg) / len(neg)
    return round((tp + tn) / 2, 4)


def tune(labels):
    pos, neg = _split(labels)
    base = store.get_weights()
    g = gate_thresholds()
    total = len(pos) + len(neg)
    if len(pos) < g["min_applied"] or len(neg) < g["min_rejected"] or total < g["min_total"]:
        return {"ok": False,
                "reason": (f"not enough decisions to fit reliably — need >={g['min_applied']} applied, "
                           f">={g['min_rejected']} rejected, >={g['min_total']} total; "
                           f"have {len(pos)} applied / {len(neg)} rejected / {total} total"),
                "n_pos": len(pos), "n_neg": len(neg), "gate": g, "weights": base}
    base_obj = objective(pos, neg, base)
    best, best_obj = base, base_obj
    keys = list(GRID)
    for combo in itertools.product(*GRID.values()):
        w = dict(base)
        w.update(dict(zip(keys, combo)))
        o = objective(pos, neg, w)
        if o is not None and o > best_obj:
            best, best_obj = w, o
    return {"ok": True, "n_pos": len(pos), "n_neg": len(neg),
            "objective_before": base_obj, "objective_after": best_obj,
            "weights_before": base, "weights_after": best,
            "changed": {k: best[k] for k in GRID if best[k] != base[k]}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    labels = store.labeled_decisions(require_raw=True)
    res = tune(labels)
    if a.json:
        print(json.dumps(res, ensure_ascii=False))
        return
    if not res["ok"]:
        print(f"tune: {res['reason']} (pursued={res['n_pos']}, rejected={res['n_neg']})", file=sys.stderr)
        sys.exit(2)
    print(f"labels: {res['n_pos']} pursued / {res['n_neg']} rejected")
    print(f"balanced accuracy: {res['objective_before']} -> {res['objective_after']}")
    print(f"weight changes: {res['changed'] or '(none — defaults already best)'}")
    if a.apply and res["changed"]:
        store.set_weights(res["weights_after"])
        print("applied new weights to store.")
    elif a.apply:
        print("nothing to apply.")


if __name__ == "__main__":
    main()

"""Weight tuner: refit the additive scoring weights to real apply/drop labels.

Deterministic grid-search, ZERO model calls. Maximises balanced accuracy at the
worth-pursuing threshold (fit >= 55, the Tier-B cutline — fixed, never tuned).
Refits only the additive fit_base weights (sum to 100); tier cutlines and the
red-flag penalty map are out of scope (ADR-0001/0003). It PROPOSES — never
mutates profile.yml (ADR-0005).
"""

import json
from math import comb

from src import scoring
from src.paths import ensure_home, home

TUNED_FILE = "_tuned_weights.json"
_JSON_KEYS = (
    "cold_start", "n", "objective", "threshold",
    "before", "after", "ba_before", "ba_after",
)
_MAX_COMPOSITIONS = 200_000


def balanced_accuracy(pairs: list[tuple[dict, str]], weights: dict, threshold: int = 55) -> float:
    """0.5*(TPR+TNR) over labeled roles. positive = "applied".

    pred = scoring.fit(scores, weights) >= threshold. An empty class contributes
    0.0 for its rate (refit's cold-start guard prevents empty classes in practice).
    """
    tp = fp = tn = fn = 0
    for scores, label in pairs:
        pred = scoring.fit(scores, weights) >= threshold
        if label == "applied":
            tp += pred
            fn += not pred
        else:
            fp += pred
            tn += not pred
    tpr = tp / (tp + fn) if (tp + fn) else 0.0
    tnr = tn / (tn + fp) if (tn + fp) else 0.0
    return 0.5 * (tpr + tnr)


def _compositions(keys: list[str], total: int, step: int):
    """Yield every {key: weight} where each weight is a multiple of `step`,
    weights are >= 0, and they sum to `total`. Deterministic order."""
    if not keys:
        return
    units = total // step
    n = len(keys)

    def rec(i, remaining):
        if i == n - 1:
            yield {keys[i]: remaining * step}
            return
        for u in range(remaining + 1):
            for rest in rec(i + 1, remaining - u):
                yield {keys[i]: u * step, **rest}

    yield from rec(0, units)


def refit(pairs, base_weights: dict, step: int = 5, threshold: int = 55, min_each: int = 5) -> dict:
    """Grid-search the weight simplex (sum=100) for max balanced accuracy.

    Returns a proposal dict. Below min_each applied OR dropped -> cold_start
    (after == before). Never proposes a strictly-worse weight set. Tie-break:
    smallest L1 distance from base_weights.
    """
    n_applied = sum(1 for _, lbl in pairs if lbl == "applied")
    n_dropped = sum(1 for _, lbl in pairs if lbl == "dropped")
    ba_before = balanced_accuracy(pairs, base_weights, threshold)
    result = {
        "cold_start": False,
        "n": {"applied": n_applied, "dropped": n_dropped},
        "objective": f"balanced_accuracy@fit>={threshold}",
        "threshold": threshold,
        "before": base_weights,
        "after": base_weights,
        "ba_before": ba_before,
        "ba_after": ba_before,
    }
    if n_applied < min_each or n_dropped < min_each:
        result["cold_start"] = True
        return result

    keys = list(base_weights)
    if keys:
        units = 100 // step
        if comb(units + len(keys) - 1, len(keys) - 1) > _MAX_COMPOSITIONS:
            step = 10  # one coarsen; grid still sums to 100

    best_rank = None  # (ba, -L1_distance)
    best_cand = base_weights
    best_ba = ba_before
    for cand in _compositions(keys, 100, step):
        ba = balanced_accuracy(pairs, cand, threshold)
        dist = sum(abs(cand[k] - base_weights.get(k, 0)) for k in keys)
        rank = (ba, -dist)
        if best_rank is None or rank > best_rank:
            best_rank, best_cand, best_ba = rank, cand, ba

    if best_ba > ba_before:
        result["after"] = best_cand
        result["ba_after"] = best_ba
    return result


def _paint(text: str, code: str, use_color: bool) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if use_color else text


def render_proposal(result: dict, use_color: bool = False) -> str:
    """Human render: cold-start decline, or the before->after weight diff + BA delta."""
    n = result["n"]
    if result["cold_start"]:
        return (
            f"tune declined: need >=5 applied and >=5 dropped labels "
            f"(have {n['applied']}/{n['dropped']})."
        )
    before, after = result["before"], result["after"]
    lines = [
        f"Tuned-weights proposal ({result['objective']}) "
        f"— {n['applied']} applied / {n['dropped']} dropped",
        "",
    ]
    for k in before:
        b, a = before[k], after.get(k, 0)
        row = f"  {k}: {b} -> {a}"
        lines.append(_paint(row, "33", use_color) if a != b else row)
    lines += [
        "",
        f"Balanced accuracy: {result['ba_before']} -> {result['ba_after']}",
        "Written to _tuned_weights.json — apply manually; profile.yml unchanged.",
    ]
    return "\n".join(lines)


def proposal_json(result: dict) -> dict:
    """Stable --json contract: the fixed key set only."""
    return {k: result[k] for k in _JSON_KEYS}


def write_proposal(result: dict) -> None:
    """Write the proposal to home()/_tuned_weights.json."""
    ensure_home()
    (home() / TUNED_FILE).write_text(
        json.dumps(proposal_json(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )

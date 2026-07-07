"""Additive fit formula and tier cutlines.

Single home of the tier cutlines — nothing else may redefine them.
The model never does this arithmetic; scores come in, code computes fit/tier.
"""

TIER_A = 70
TIER_B = 55


def fit(scores: dict[str, float], weights: dict[str, float]) -> int:
    """Weighted additive fit: round(sum(weights[k] * scores[k] / 100)).

    Iterates keys present in weights; a missing score contributes 0.
    Result clamped to 0-100.
    """
    total = sum(weights[k] * scores.get(k, 0) / 100 for k in weights)
    return max(0, min(100, round(total)))


def tier_of(fit: int, geo_ok: bool, comp_ok: bool, frictions: list[str]) -> str:
    """Tier from fit + hard conditions.

    A: fit >= TIER_A and geo_ok and comp_ok and no frictions.
    B: TIER_B <= fit < TIER_A, or fit >= TIER_A demoted by friction.
    C: everything else.
    """
    if fit >= TIER_A:
        if geo_ok and comp_ok and not frictions:
            return "A"
        if frictions:
            return "B"
        return "C"
    if fit >= TIER_B:
        return "B"
    return "C"

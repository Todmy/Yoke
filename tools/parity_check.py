"""Parity harness: compare Yoke's tiering against the prototype's on one window.

NOT part of the shipped src/ core — a verification tool. Both sides export a
list of {role_key, tier, fit} records (the prototype baseline proto.json is
produced out-of-band, e.g. an exported prototype-scored window). This joins
them on role_key and reports how far the two rankings agree:

  tier_agreement  confusion counts keyed by (yoke_tier, proto_tier)
  topN_overlap    Jaccard of the two shortlist sets (tier A or B)
  divergences     roles where the two tiers differ (rank distance >= 1)
  unmatched       role_keys present on only one side

Deterministic; stdlib only.

    python tools/parity_check.py yoke.json proto.json
"""

import json
import sys

_RANK = {"A": 2, "B": 1, "C": 0}
_SHORTLIST_TIERS = ("A", "B")


def compare(yoke: list[dict], proto: list[dict]) -> dict:
    """Join two {role_key, tier, fit} record lists and score their agreement."""
    y = {r["role_key"]: r for r in yoke}
    p = {r["role_key"]: r for r in proto}
    common = y.keys() & p.keys()

    tier_agreement: dict = {}
    divergences = []
    for k in sorted(common):
        yt, pt = y[k]["tier"], p[k]["tier"]
        tier_agreement[(yt, pt)] = tier_agreement.get((yt, pt), 0) + 1
        if abs(_RANK.get(yt, 0) - _RANK.get(pt, 0)) >= 1:
            divergences.append({"role_key": k, "yoke_tier": yt, "proto_tier": pt})

    y_top = {k for k, r in y.items() if r["tier"] in _SHORTLIST_TIERS}
    p_top = {k for k, r in p.items() if r["tier"] in _SHORTLIST_TIERS}
    union = y_top | p_top
    topN_overlap = 1.0 if not union else len(y_top & p_top) / len(union)

    return {
        "matched": len(common),
        "tier_agreement": tier_agreement,
        "topN_overlap": topN_overlap,
        "divergences": divergences,
        "unmatched": {
            "yoke_only": sorted(y.keys() - p.keys()),
            "proto_only": sorted(p.keys() - y.keys()),
        },
    }


def format_report(report: dict) -> str:
    """Human-readable rendering of a compare() result."""
    lines = [
        f"matched roles: {report['matched']}",
        f"top-N overlap (Jaccard of tier A/B sets): {report['topN_overlap']:.3f}",
        "tier agreement (yoke → proto):",
    ]
    for (yt, pt), n in sorted(report["tier_agreement"].items()):
        mark = "" if yt == pt else "  ✗"
        lines.append(f"  {yt} → {pt}: {n}{mark}")
    lines.append(f"divergences: {len(report['divergences'])}")
    for d in report["divergences"]:
        lines.append(f"  {d['role_key']}: yoke {d['yoke_tier']} vs proto {d['proto_tier']}")
    um = report["unmatched"]
    lines.append(f"unmatched: {len(um['yoke_only'])} yoke-only, {len(um['proto_only'])} proto-only")
    for k in um["yoke_only"]:
        lines.append(f"  yoke-only: {k}")
    for k in um["proto_only"]:
        lines.append(f"  proto-only: {k}")
    return "\n".join(lines)


def _load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 2:
        print("usage: python tools/parity_check.py yoke.json proto.json", file=sys.stderr)
        return 2
    print(format_report(compare(_load(argv[0]), _load(argv[1]))))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Single source of truth for the fit-score cutlines (spec Δ3, FR-004).

Imported by analyze.py (`tier_of`) and tune.py (the tuner objective) so the board
and the tuner can never optimize against different boundaries. Fixed in v1 — NOT
user-overridable; the tuner moves weights only, never these cutlines.
"""

THRESHOLD = 55  # fit >= this == "worth pursuing" == Tier B boundary
TIER_A = 70     # fit >= this (with remote geo) == Tier A

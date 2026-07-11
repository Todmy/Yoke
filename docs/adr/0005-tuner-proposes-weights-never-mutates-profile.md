# ADR-0005: The M3 tuner proposes weights, never mutates profile.yml

Date: 2026-07-11 · Status: accepted (feature: m3-self-improvement)

## Context

ADR-0001 makes the scoring weights **user-declared data in `profile.yml`** (`scoring.features[].weight`, summing to 100). M3's `tune` refits those weights to the user's real apply/drop labels. The obvious design is to have the tuner overwrite `profile.yml` and close the loop automatically — but recon (context.md) flagged the tension, and three constraints rule it out:

- `profile.yml` is **hand-edited YAML with comments**, user-owned, never committed (constitution #8). A PyYAML round-trip destroys comments/formatting and silently drifts user-owned data.
- Constitution #2 demands the score be **auditable and stable** — a weight set that changes under the user without an explicit action is neither.
- The feature's own reframe: M3 "self-improvement" is about diagnosing **process quality** (what `eval` surfaces), and weight-refit is *one narrow lever*. Auto-overwriting weights over-privileges that lever and hides the more important per-dimension diagnostic.

## Decision

- **`tune` proposes, never mutates.** It computes the refit weights, prints a per-feature `before → after` diff plus the balanced-accuracy improvement, and writes the proposal to `home()/_tuned_weights.json` (a `--json`-friendly structured artifact, so the mode-2 agent contract can consume it). It **never writes `profile.yml`.**
- **Applying a proposal is a separate, explicit user action** (manual copy into `profile.yml`, or a future opt-in `tune --apply`). The default path never changes live scoring silently.
- **The refit target is only the additive feature+deterministic weights (`fit_base`)**, constrained to sum = 100 (`paths._validate_profile`). Tier cutlines (`TIER_A`/`TIER_B`) and the red-flag penalty map are out of scope — invariants, per ADR-0001/ADR-0003.
- **Objective:** balanced accuracy at the worth-pursuing threshold (fit ≥ 55 = Tier-B cutline; applied = positive, dropped = negative), via a **deterministic integer grid-search** over weight compositions summing to 100. **Cold-start guard:** below a minimum count of applied/dropped labels the tuner declines with a clear message rather than overfit a tiny set.

## Consequences

- The loop is closed **with a human in it**: the tuner surfaces a suggestion, the user accepts it. Auditable, no silent drift — consistent with constitution #2/#8.
- `profile.yml` comments and formatting are never clobbered.
- Only labels captured **after** M3 ships carry features (the `_labels.json` store is populated at apply/drop from this milestone on), so early `tune` runs may hit the cold-start guard and decline — expected, not a failure.
- Mode-2 agents consume the proposal via `_tuned_weights.json` / `--json`; a future `tune --apply` can add opt-in write-back **without reversing this default**.

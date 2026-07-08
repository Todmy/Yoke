# ADR-0003: Red flags reduce fit via a clamped penalty multiplier, not the additive sum

Date: 2026-07-08 · Status: accepted (feature: m2-input-quality)

## Context

`analyze` already collects a model-emitted `red_flags[]` (ADR-0001 fixed system output) but discards it — red flags never touch `fit` or `tier` today. M2 requires red flags to actually lower a role's score. The obvious move — add red flags as another additive feature — is wrong: a strong role with a serious red flag should be *pulled down proportionally*, not merely offset. But ADR-0001 deliberately kept `fit = Σ wᵢ·featureᵢ` purely additive so the M3 grid-search tuner can refit the weights; a multiplicative blend inside the sum would break that tuner.

There is also a determinism requirement (constitution #2, restated this feature as the project's north star: the harness turns non-deterministic AI judgment + deterministic job data + semi-deterministic user experience into deterministic software). The model may *judge*, but must never own an arithmetic number.

## Decision

- **`fit_base` stays exactly the additive weighted sum of ADR-0001** — untouched, tuner-refittable. This ADR does not contradict ADR-0001; it adds a layer *after* the sum.
- **The red-flag penalty is a separate, clamped multiplier:** `fit_final = round(fit_base × (1 − min(Σ penalty, cap)))`, where `cap` (default `0.5`) is the modifier-floor clamp — red flags can strip at most `cap` of a role's score, never zero a strong role.
- **Penalties are profile data; the model only classifies.** The model classifies each red flag into a fixed enum (its non-deterministic part); a profile map `scoring.red_flags: {category: penalty}` owns the numbers (deterministic); code does the arithmetic. Red flags are never a keyword→tier classifier (constitution #9).
- **Two penalty sources feed the same multiplier:** *model-classified* flags (from JD text) and *code-detected* ghost/liveness signals (posting age, repost frequency, apply-domain trust, confidential company — all computed from card metadata, no network). One seam, not two (constitution #4).
- **Tier is computed from `fit_final`.** The existing cutlines and the `onsite`/`lane off` hard-C path are unchanged.

## Consequences

- Exact-fit test locks (`test_analyze.py` fit=92/77) change deliberately, with new expected values; `test_scoring` gains penalty/clamp cases.
- Ghost/liveness (WS3) is not a separate filter and not a hard gate — it is a deterministic red-flag *source*, so a suspected ghost sinks in score but is never auto-dropped (flag-never-drop; a false heuristic must not delete a real role).
- `fit_base` remains the tuner's target, so M3 is unaffected; the penalty map is a second, smaller thing the tuner could later learn separately.
- The feature schema stays a versioned contract (ADR-0001): the red-flag enum is part of it — changing the enum shape versions the schema.

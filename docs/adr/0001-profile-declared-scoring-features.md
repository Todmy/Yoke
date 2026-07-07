# ADR-0001: Scoring features are declared in the profile, not hardcoded

Date: 2026-07-07 · Status: accepted (feature: yoke-v0)

## Context

The fit score needs person-specific judgments (e.g. contract-form compatibility matters to one user, visa sponsorship to another). Hardcoding one user's feature set into `analyze` would make every new user a code change and contradict the "concrete with seams" principle. The reference prototype carried two competing formulas (a multiplicative blend and an additive rubric); the constitution demands one readable, auditable formula.

## Decision

- The fit formula is a generic additive weighted sum: `fit = Σ wᵢ·featureᵢ`, 0–100.
- Profile-declared scoring features live in `profile.yml` as `{name, description, weight}`; `analyze` passes each description to the model, which returns a 0–100 judgment plus a one-line evidence string per feature.
- Deterministic features (comp-vs-floor) are computed by code and join the same sum; the model never does arithmetic, the formula and tier cutlines are code.
- Fixed system outputs the model always fills regardless of profile: `geo_certainty`, `lane` (on/adjacent/off), `red_flags[]`, one-line note, and — when a source provided no structured comp — a parsed `{min,max,currency,unit,type}` from the JD text (then normalized deterministically).

## Consequences

- New user = new profile, zero code changes; the M3 tuner later refits the same weights (grid-search over an additive form works; a multiplicative blend would not fit that tuner).
- The model prompt is built from profile data, so prompt-injection surface via JD text must be treated as data, never as instructions (verify stage checks this).
- The feature schema is a contract: changing its shape breaks stored analyses; version it if it evolves.

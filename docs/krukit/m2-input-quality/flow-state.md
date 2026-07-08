# Krukit Flow: m2-input-quality
Started: 2026-07-08 | Route: full
Task: M2 "Input quality" (ROADMAP.md) — 4 workstreams: (1) scoring formula = red-flags multiplier + modifier-floor clamp + lenses; (2) comp-estimation in prepare (benchmark tables); (3) ghost/liveness filter; (4) semantic dedup. Slug entered as "scoring-depth"; scope confirmed = whole M2.
- [x] 1 recon — done 2026-07-08, artifact: context.md
- [x] 2 grill — done 2026-07-08, artifact: flow-state.md
- [x] 3 design — done 2026-07-08, artifact: design.md
- [x] 4 plan — done 2026-07-08, artifact: plan.md
- [x] 5 act — done 2026-07-08, artifact: plan.md
- [x] 6 verify — done 2026-07-08, artifact: verify.md
- [x] 7 review — done 2026-07-08, artifact: flow-state.md

## Routing evidence (Stage 0)
> "M2 'scoring-depth' scope = Whole M2 input-quality" + "Route = full (Recommended)" — 2026-07-08 (AskUserQuestion, verbatim option selections)

Pre-route recon finding: windowing (`prepare.window_slice`/`build_cards`) and applied-dedup (`board._prune`/`mark_applied`) already exist — off the table. Real scoring gap = red_flags never affect fit/tier.

## Grill summary (Stage 2)

**North star (user-stated, drove every decision):** the harness turns non-deterministic AI judgment + deterministic job data + semi-deterministic user experience → deterministic software. Model may *judge/classify*; code owns every number. (Sharpened form of constitution #2.)

**Resolved decisions:**
- **WS1 scoring formula** — `fit_base` stays the additive ADR-0001 sum (tuner-refittable). Red flags reduce score via a **clamped penalty multiplier** `fit_final = round(fit_base × (1 − min(Σpenalty, cap)))`, `cap` default `0.5`. Penalties = profile `scoring.red_flags: {category: penalty}` data; the model only classifies each flag into a fixed enum. → **ADR-0003**.
- **WS2 comp-estimation** — **model-estimated comp band** when both source and JD comp are absent (implements active decision `ed66a591` / spec FR-002/FR-004). The model returns an estimated band as a flagged feature in its fixed schema, informed by **company + target-market context** (not title/JD alone — the same role varies 2-3× across companies/markets); code normalizes it and compares to floor. **Soft**: the estimate never drops a role to Tier C and never assumes zero (gate-to-C on missing comp explicitly rejected — would empty the EU board); it fills `comp_vs_floor` + display and carries an "estimated comp" friction. Precedence: source comp → JD-parsed comp → model estimate. *Deterministic benchmark-table mechanism rejected — a static table can't capture the company/market variance the model can.*
- **WS3 ghost/liveness** — **not a separate filter**: deterministic code-detected red flags (age, repost frequency, apply-domain trust, confidential company) feeding the *same* WS1 penalty seam. No network (keeps `prepare` pure), flag-never-drop (no hard gate) — a false heuristic must not delete a real role.
- **WS4 semantic dedup** — deterministic **stdlib fuzzy** match (embeddings rejected: heavy dep + non-deterministic). Match **same company first, then fuzzy title** within that company; never across companies. Augments `role_key`, never replaces it. Threshold = profile `dedup:` data. → **ADR-0004**.

**Sharpened terms (→ CONTEXT.md):** red flag, red-flag penalty, ghost/liveness signal, comp estimate, near-duplicate.

**ADRs created:** ADR-0003 (red-flag penalty multiplier), ADR-0004 (deterministic dedup over embeddings).

**Deferred:** "lenses" as alternate weight-*sets* per role-type — out of this flow, separable later feature (would not affect the additive base; revisit post-M3).

**Contradiction caught & resolved (Valis check at grill close):** the initial WS2 proposal (deterministic benchmark table) contradicted active decision `ed66a591` (spec FR-002/FR-004: model-estimated band). WS2 reopened; user ruled 2026-07-08 to **honor the prior decision** — WS2 = model-estimated band, soft gate. Proposed grill-outcome `9ae32222` superseded by corrected entry.
> "Дотримати попереднього рішення — модель оцінює band" — 2026-07-08

**Gate:** no unresolved contradiction between idea and code/docs (WS2/`ed66a591` conflict surfaced and resolved); all 8 recon Open questions resolved (Q1 deferred-as-noted, Q2–Q8 resolved); summary appended.

## Design gate evidence (Stage 3)
- DoD choice: parity-comparison with prototype included.
> "+" — 2026-07-08 (design approved as-is; fixed-universal red-flag enum accepted, defaults cap=0.5 / dedup ratio=0.90 accepted)

## Review summary (Stage 7)

Independent fresh-eyes review of the full m2 diff (1173 lines, 12 files). 7 findings resolved on merits — **4 fixed, 2 declined, 1 addressed**:

- **#1 CRITICAL (fixed)** — `build_cards` dropped a live role when its `dupe_of` canonical was pruned; now fails open on a dangling canonical (commit a893b3c).
- **#3/#5 IMPORTANT+MINOR (fixed)** — seniority stripping merged distinct senior/junior roles, and empty-normalized titles matched at ratio 1.0; added a seniority-level discriminator + empty guard (commit f4bb55a).
- **#4 IMPORTANT (fixed)** — a red-flag category could double-count across model+ghost; penalties deduped per category (commit 6c02206).
- **#2 IMPORTANT (declined)** — earliest-`first_seen` canonical is required for WS3 `repost_churn` + windowing (freshest would corrupt the span); role still surfaces via canonical; not re-scoring dupes is the design's intended cost-saving.
- **#6 MINOR (declined)** — estimate feeding `fit_base` is the design's soft behavior, capped at B by the "estimated comp" friction.
- **#7 MINOR (addressed)** — the pruned-canonical / dedup-edge test gap is closed by the new fix tests.

Invariants re-confirmed by the reviewer (fit purity, hard-C independence, prepare purity, no third-party module import, 8-key norm, WS2 gate-safety). **Final suite: 207 tests green.** Branch outcome: **pushed to origin/main** (fast-forward `b59b472..6c02206`, explicit user permission). Knowledge: 2 Valis entries (proposed) — parity deferral + fuzzy-dedup lifecycle lessons.

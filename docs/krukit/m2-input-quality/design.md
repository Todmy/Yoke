# Design: m2-input-quality

## Goal
Four deterministic workstreams that make Yoke's shortlist cleaner and its ranking sharper, closing v1.0 parity with the `~/PBaaS` jobsearch prototype:
- **WS1** red-flag penalty multiplier (a clamped layer around the additive `fit`)
- **WS2** model-estimated comp band when pay is absent (honors `ed66a591` / FR-002/FR-004)
- **WS3** ghost/liveness as deterministic code-detected red flags feeding WS1's seam
- **WS4** deterministic stdlib fuzzy near-duplicate collapse

North star (constitution #2, sharpened this feature): the model **judges/classifies** (non-deterministic), **code owns every number** (deterministic), tunables live as profile **data**.

## Architecture overview
The pipeline shape (`collect → prepare → analyze → board`) is unchanged. The four workstreams layer on:

- **One penalty seam (WS1+WS3).** `analyze` computes `fit_base` exactly as today (additive), then applies a single clamped penalty multiplier from **two penalty sources**: model-classified red flags (from JD text) and code-detected ghost signals (from card metadata, computed in `prepare`). Both are categories in one fixed enum; the profile owns the penalty per category.
- **Comp precedence chain (WS2).** `analyze`'s comp resolution becomes: source comp (collect) → JD-parsed verbatim (`comp_parsed`) → model estimate (`comp_estimated`). The estimate is soft — it feeds the score/display and a friction, never the hard gate.
- **Dedup at ingest (WS4).** `collect.update_index` gains a deterministic fuzzy near-duplicate pass, same-company-scoped, augmenting `role_key`.

## WS1 — Red-flag penalty multiplier

**Formula (new, in `scoring.py`, pure + tested):**
```
penalized_fit(fit_base, penalties, cap) = round(fit_base × (1 − min(sum(penalties), cap)))
```
- `fit_base` = the existing additive `scoring.fit(scores, weights)` — untouched (ADR-0001; the M3 tuner still refits it).
- `cap` (default `0.5`) = the modifier-floor clamp: red flags strip at most `cap` of the score, never zero a strong role. Profile-overridable (`scoring.red_flag_cap`).
- Clamped to 0–100 (inherits `fit`'s clamp). Applied **before** `tier_of`, so a red-flag-heavy A naturally demotes via the lower fit. The `onsite`/`lane off` hard-C path (`analyze.py:198-201`) is unchanged and independent.

**Red-flag enum — fixed universal set in code (decision, grounded in ADR-0001):** the model always classifies into the same stable enum, so `ANALYSIS_SCHEMA` stays a versioned contract independent of the profile; the profile only sets penalties (0 = ignore a category). *Alternative rejected:* profile-declared categories would make the model's classification target — and thus the schema — profile-dependent and un-versionable.

Proposed starting enum (tunable data, split by source):
- *Model-classified (from JD text):* `scam_signal`, `unrealistic_requirements`, `legal_risk`, `comp_opacity`, `culture_flag`
- *Code-detected (from metadata, WS3):* `stale_posting`, `repost_churn`, `untrusted_apply_domain`, `confidential_employer`

**Schema change:** `red_flags` moves from `array<string>` to `array<{category: <enum>, evidence: string}>` (the model classifies, not free-texts). This versions `ANALYSIS_SCHEMA` (ADR-0001 §consequences).

**Profile:**
```yaml
scoring:
  red_flag_cap: 0.5
  red_flags:            # category: penalty (0..1); 0 disables
    scam_signal: 0.5
    unrealistic_requirements: 0.15
    legal_risk: 0.3
    comp_opacity: 0.1
    culture_flag: 0.1
    stale_posting: 0.15
    repost_churn: 0.2
    untrusted_apply_domain: 0.4
    confidential_employer: 0.1
```

## WS2 — Model-estimated comp band

Implements active decision `ed66a591` / spec FR-002/FR-004.

**Schema:** add `comp_estimated: {min,max,currency,unit,type} | null` alongside the existing verbatim `comp_parsed`. System prompt instructs: if the posting states pay → fill `comp_parsed` verbatim; **else** → fill `comp_estimated` with your best band from **this company and the candidate's target market** (not title/JD alone — the same role varies 2-3× across companies/markets), `comp_parsed=null`. The model supplies the raw band (judgment); **code does all arithmetic** (`comp.normalize` → net USD/mo → floor verdict).

**Precedence (in `analyze`):** `card.comp_norm` (source, from collect) → `comp.normalize(comp_parsed)` → `comp.normalize(comp_estimated)`. First present wins.

**Soft behavior (never drops a role):**
- An estimated comp sets the `comp_vs_floor` **score** (via the existing `COMP_SCORE` map on its verdict) and `comp_display` (marked "≈ estimated").
- It adds an **"estimated comp" friction** (demote A→B), like today's "comp unknown".
- It **never** sets `comp_ok=False` for tiering and **never** touches the `prepare` hard `comp_floor` gate (which already only sees source comp). A below-floor *estimate* lowers fit via the score, but cannot force Tier C or assume zero (ed66a591: rejected gate-to-C on missing comp — would empty the EU board).

## WS3 — Ghost/liveness as code-detected red flags

A new **pure** function (in `prepare.py`, no network) computes ghost signals from data already on the card and emits `{category: penalty-source}` entries into the same red-flag list `analyze` consumes:
- `stale_posting` — `posted_at` older than N days, or `last_seen − first_seen` span beyond a threshold (evergreen).
- `repost_churn` — the `role_key` seen across many scans / long recurrence.
- `untrusted_apply_domain` — apply URL host in a shortener/forms blocklist (`bit.ly`, `forms.gle`, `tinyurl`, …) and not in the ATS allowlist.
- `confidential_employer` — empty/"confidential" company.

Thresholds (age days, repost count) are **code constants** for v1 (constitution #4, concrete-with-seams; profile-overridable later, not now). These signals **feed the WS1 penalty** — no hard gate, flag-never-drop: a suspected ghost sinks in score but is never auto-dropped (a false heuristic must not delete a real role). Because it's pure metadata math, `prepare` stays network-free (#2, ADR-0002).

## WS4 — Deterministic fuzzy near-duplicate collapse

In `collect.update_index` (or a dedicated pure pass over new entries), before minting a fresh index entry:
1. **Same company first** — restrict comparison to entries with the same normalized company (never cross-company: "Senior Backend Engineer" is identical across many firms).
2. **Fuzzy title** — hard-normalize both titles (strip seniority words `senior/junior/lead/staff/principal`, punctuation, unify `js`↔`javascript`, lowercase, collapse whitespace), then `difflib.SequenceMatcher(None, a, b).ratio() ≥ threshold` → near-duplicate.
3. On match, attach `dupe_of: <canonical job_key>` to the newer entry; the canonical keeps earliest `first_seen`. **`role_key` and the board applied-ledger prune are untouched** (WS4 augments, never replaces them).

Threshold = profile `dedup.title_ratio` (default `0.90`), stdlib-only (no embeddings — ADR-0004). Postings collapse to one board record; the deduped variant is not separately scored (cost saved, like a `role_key` collapse).

## Parity harness (DoD deliverable)

A script `tools/parity_check.py` (outside `src/`, not part of the shipped core) that, on a real collected window:
- runs the window through Yoke's `analyze`/scoring, and through a thin adapter over the prototype's scoring rubric;
- reports **tier agreement** (A/B/C confusion), **top-N overlap** (Jaccard on the tier-A+B set), and a **divergence list** (roles where the two disagree by ≥1 tier) with the reason.
Purpose: prove M2 reaches v1.0 parity (or surface where it doesn't). Not a shipped feature; a verification tool.

## Data flow (one card, end to end)
`collect.norm` (8 keys) → `update_index` (+`role_key`,`first_seen`,`last_seen`, **+`dupe_of`** WS4) → `prepare.build_cards` (+`comp_norm`,`gates_failed`,`frictions`,`in_window`,`needs_ai`, **+`ghost_flags`** WS3) → `analyze.analyze_cards` (model returns classified `red_flags`+`comp_estimated`; code computes `fit_base`, applies **penalty** WS1, resolves **comp precedence** WS2, tiers) → board record → `board.upsert`/`render`.

## Error handling
- Model returns an unknown red-flag category → dropped with a logged warning, penalty 0 (fail-open, never crash). Schema `enum` also rejects it at validation.
- `comp_estimated` present but un-normalizable → treated as unknown comp (existing "comp unknown" friction path).
- WS4 dedup is best-effort: any comparison error → treat as non-duplicate (never merge on error).
- One bad card still ships as `analysis_failed`, tier C (existing contract, `analyze.py:167-170`).

## Testing strategy
- **WS1** — `test_scoring`: `penalized_fit` table cases (no flags → identity; single/summed penalties; cap clamp; 0-100 clamp). `test_analyze`: classified red_flags → expected `fit_final`; the existing exact-fit locks (92→new, 77→new) updated deliberately.
- **WS2** — `test_analyze`: precedence (source > parsed > estimated); estimated-below never sets `comp_ok=False`, adds "estimated comp" friction, never Tier C; `comp_display` marks estimate. Model path via mock backend.
- **WS3** — `test_prepare`: each ghost signal fires on a crafted card and is absent otherwise; purity (no network); signals appear as penalties in `analyze` output.
- **WS4** — `test_collect`: near-title variants same company collapse; identical title different company does NOT; `role_key`/applied-prune unaffected; fixtures drive the real path (#6).
- **Regression** — full existing suite green (143 → higher).
- **Live-run** (#10) — one real free-source window through the full pipeline → sane shortlist.
- **Parity** — `tools/parity_check.py` on that window; report tier agreement + top-N overlap.

## Sequencing (for krukit-plan)
WS1 → WS3 → WS2 → WS4 → parity harness + live-run. WS1/WS2/WS3 all touch `ANALYSIS_SCHEMA`, so they run in sequence (not parallel) to avoid schema churn; WS4 is isolated in `collect`. Natural commit/`/clear` checkpoint after WS1+WS3 (the scoring core).

## Definition of Done
1. Per-WS deterministic unit tests green (WS1 penalty/clamp, WS2 precedence/soft-gate, WS3 signals/purity, WS4 dedup scope).
2. Model-path tests (schema classify + comp_estimated) via mock backend green.
3. Full existing suite green (no regression); `ANALYSIS_SCHEMA` version bumped.
4. One live-run (free sources, real window) → sane shortlist (constitution #10).
5. `tools/parity_check.py` runs on that window and reports tier agreement + top-N overlap + divergences vs the prototype.

## Constitution check
| Principle (MUST) | Verdict |
|---|---|
| #1 Local-first | pass — no data leaves the machine; model calls already consented; parity harness is local. |
| #2 Deterministic core, thin AI surface | pass — `fit_base` stays additive; penalty math, dedup, ghost signals, comp arithmetic are all code; the model only classifies (red flags into a fixed enum) and estimates a raw band (judgment, not arithmetic). |
| #3 Flat files | pass — no DB; `dupe_of` is a field on the flat index. |
| #4 Concrete with seams | pass — ghost thresholds are code constants (no speculative profile config); one penalty seam reused by WS3 (no parallel mechanism); no new core module beyond an M2-milestone need. |
| #5 Sources are plugins / stdlib-lean core | pass — WS4 uses stdlib `difflib` only; no heavy dep in `src/` (embeddings rejected, ADR-0004). |
| #6 Core test-first, fetchers on fixtures | pass — all four are deterministic units written test-first; WS4 fixtures drive the real parse path. |
| #7 No paid call without consent / analyze only new-in-window | pass — no new paid surface; WS2 estimation happens inside the already-consented `analyze` call on the in-window slice; the estimate never expands the `needs_ai` set. |
| #8 Moat barrier & small commits | pass — profile red-flag/dedup config stays in `.private`/profile; plan sequences small per-WS commits. |
| #9 Competitor ban-list | pass — red flags are model-classified into an enum, **not** a keyword→tier classifier; no embeddings/heaviness; no WebSearch collection; no LinkedIn loop. |
| #10 Live-run verification | pass — DoD #4 mandates a real-network dry-run + the parity harness; verify stage enforces it. |

No violations.

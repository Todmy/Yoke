# Data Model: Yoke job-search harness

Phase 1. Reflects the **existing** SQLite schema (`src/store.py`) plus the v1 deltas. The store is the single source of truth (WAL mode, `$YOKE_HOME`); the scan index (`collect.py`) stays a file with an `fcntl` lock.

## Entities

### Profile — `config/profile.json` (file, not DB)
| Field | Notes |
|---|---|
| `resume_text` | the single **base CV** (v1). Named variants → v2. |
| `prompt` | scoring system prompt fragment |
| `scoring_instructions` | overrides the default schema-fill instructions |
| `output_language` | drives note + cover-letter language |
| `comp_floor_net_mo_usd` | deterministic comp gate input |
| target lane / allowed locations | encoded in the prompt + geo rules |
| per-role model-spend budget (FR-025) | **v2** — cost/quality lever governing re-scoring/escalation; v1 ships the feature-caching baseline only |
| provider config | `YOKE_PROVIDER` / key / model (env or settings) |

### Role — `roles` table
`role_key` (PK), `key`, `company`, `title`, `url`, `fit` (int), `label`, `geo`, `comp`, `lane`, `note`, `tier`, `date_added`, `features` (JSON of raw model features), `status` (`live`|`applied`|`interested`|`rejected`).
- **Dedup identity**: `role_key` + `key` (normalized company|title) → an applied/rejected role never resurfaces (FR-009). Reposts under a new URL caught by the normalized key.
- **Pruning (Δ, FR-005)**: live roles pruned by **posting-URL liveness** on later collects (404/410 → drop; transient → keep).

### Feature card — transient (prepare.py → analyze.py)
Geo verdict (`remote`/`verify`/`blocked`), lane (`in`/`adjacent`/`out`/`ambiguous`), comp (`found` + `net_mo_est`), `needs_ai` list, `hard_gate_fail`. Not persisted.

### Score features — `roles.features` (JSON) + the formula
Model fills a fixed schema only: `lane_match`, `differentiator_hits` (0–5), `seniority_ok`, `lang_ok`, `employer_winnable`, `geo_verdict`, `comp_est_net_mo` (estimate when comp absent — FR-002), `note`. `score_fit()` computes the number from `store.get_weights()`; the model never emits it.
- **Tier (FR-004)**: `tier_of(fit, geo, comp_below_floor)` using **fixed cutlines from `scoring.py`** (Δ3): `TIER_A=70` (remote), `THRESHOLD=55` (B). Not user-overridable in v1.

### Decision (label) — `decisions` table
`id`, `ts`, `slug`, `role_key`, `company`, `title`, `decision` (`applied`|`interested`|`rejected`), `reason`, `comment`, `features` (raw, for tuning), `source`, `status`, `status_note`, `updated`, `url`, `resume`.
- **Δ1 (FR-008/017)**: training signal = `applied` vs `rejected` only. `interested` is a **bookmark**, excluded from the tuner's positive class.
- **Δ-CV (FR-007)**: `resume` = **immutable snapshot** of the exact CV text sent (base + accepted edits, possibly just base).
- Idempotent on `(slug, role_key, decision)` — re-ingest can't double-log.

### Application — `decisions` rows where `decision='applied'`
Status pipeline: `applied → screening → interview → offer → accepted/rejected/ghosted` (`APP_STATUSES`). `application_stats()` derives response/interview/offer rates (FR-010). Manual status set by hand is never overwritten by US5 sync.

### Weights — `meta` table key `fit_weights` (JSON)
Tunable coefficients (`DEFAULT_WEIGHTS`: `lane_in`, `lane_adjacent`, `diff_per_hit`, `diff_cap`, `seniority_ok/no`, `lang_ok/no`, `emp_no`). Refit by `tune.py` (weights only). **Distinct from cutlines** (fixed, in `scoring.py`) which the tuner never moves.

### Golden set / scorecard — eval.py
Frozen roles + curated expected labels (geo truth, expected tier band, known-unsafe traps), bootstrapped by a stronger model then human-reviewed and frozen. Eval grades the candidate against the **fixed labels**, zero reference-model calls; safety gates (geo FP, tier overreach, parse fail) dominate the verdict deterministically (FR-015/016).

### Gap result — gap (deterministic + optional model)
Matched + ranked-missing skills (tools, knowledge domains, meta-qualities) via taxonomy+alias (no required model call), an honest match indicator (qualitative band + number on expand), and accept/reject learning/tuning suggestions. Per-vacancy tailored copy produced at apply (v1); semantic augmentation + variant library = v2.

## v2 / later (not in this plan's schema)
- `cv_variants` table (named/per-role variants, live editor) — v2.
- Email-source provenance on status changes (US5) — uses existing `status_note`/`source`; later phase.

## Schema deltas this plan introduces
| Δ | Location | Change |
|---|---|---|
| Δ1 | `tune.py`, `store.py` | positive class = `applied` only; `interested` excluded from tuner |
| Δ2 | `tune.py` | gate ≥5/≥5/≥20 (configurable in `meta`) |
| Δ3 | `scoring.py` (new), `analyze.py`, `tune.py` | single cutline source `THRESHOLD`/`TIER_A` |
| Δ4 | `board.py`/`serve.py`, `store.py` | tailor-at-apply → immutable `resume` snapshot |
| Δ5 | `collect.py` | URL-liveness pruning; new source adapters |

No destructive migration: existing `ALTER TABLE` pattern in `store._init` already adds columns idempotently; `resume` column exists.

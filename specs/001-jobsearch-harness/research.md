# Research: Yoke job-search harness

Phase 0. Resolves the unknowns and the spec↔code deltas that the plan depends on. Each item: Decision · Rationale · Alternatives.

## R1 — Testing framework (under zero-dependency)

**Decision**: stdlib `unittest`, in a `tests/` tree, runnable with `python3 -m unittest discover -s tests`.
**Rationale**: The core is a hard zero-dependency project (serve.py, store.py, llm/ all stdlib). Adding `pytest` as even a dev dep contradicts the "runs anywhere with python3" promise and the SC-002 "deterministic path runs with nothing configured" ethos. The high-value targets are pure functions (`score_fit`, `tier_of`, tuner `objective`, dedup key, `comp_below_floor`) — `unittest` covers them fine. `analyze.py --mock` already gives a no-model end-to-end harness.
**Alternatives**: `pytest` (richer fixtures/parametrize) — rejected to hold zero-dep; can be a personal local choice but not a repo requirement.

## R2 — Semantic skill-similarity (FR-011) under zero-dependency

**Decision**: v1 ships the **deterministic taxonomy + alias** matcher only (no LLM, no embeddings). The semantic-similarity augmentation is **v2**, and when built will reuse the configured **LLM backend's** embedding/judgement rather than a Python ML dependency.
**Rationale**: Embeddings in-process (sentence-transformers/numpy) would break zero-dep and bloat install. The taxonomy+alias pass is deterministic, inspectable, and explains "why missing" — which is the whole honesty point of FR-011. FR-011 already says semantic is "MAY augment", so deferring it is spec-compliant. The skill model (tools + knowledge domains + meta-qualities) is encoded as the taxonomy's structure, not as an embedding space.
**Alternatives**: in-process embeddings (rejected: dep + size); always-on LLM call (rejected: violates "without a required model call").

## R3 — Source scrapers for the v1 short-list (FR-001) under zero-dependency

**Decision**: Per-source, cheapest viable adapter, all behind the existing pluggable `collect.py` source interface:
- **Hiring Cafe** — JSON/HTTP endpoint via stdlib `urllib` (aggregator → one high-yield source).
- **Djinni, DOU** — no public API; stdlib `urllib` + `html.parser`/`re` scrapers, polite rate-limited. If a board proves too JS-heavy for stdlib, fall back to the **optional `.venv` `jobspy`** path (already wired in `run.sh`), never a core dep.
- **LinkedIn** — read-only, **no logged-in actions**; via `jobspy` (venv-optional) which supports LinkedIn search, or skipped if unavailable. Honors the FR + assumption.
- **Manual paste/CSV import** — always-available stdlib fallback so the pipeline works even if every scraper is down.
**Rationale**: Keeps the core stdlib; isolates the one heavier need (JS-rendered boards) behind the venv that already exists for `jobspy`. Matches "pluggable sources, adding/removing one doesn't change the pipeline" (FR-001) and the LinkedIn read-only assumption.
**Rationale (delta)**: `collect.py` today scrapes Greenhouse/Lever/Ashby/RemoteOK/Remotive/WWR/HN — a *different* set. The four spec sources are **new adapters to build**, not edits to existing ones; the existing ATS/RSS sources stay (more pluggable sources is strictly fine).
**Alternatives**: official APIs only (rejected: drops Djinni/DOU, the UA-market core); scrape-everything incl. logged-in LinkedIn (rejected: ToS/ban risk, violates assumption).

## R4 — Δ1: `interested` is a bookmark, not a training label

**Decision**: `store.labeled_decisions` / `tune._split` positive class = `applied` **only** (not `applied`+`interested`). `interested` stays a board state and a tracker entry but is excluded from the tuner.
**Rationale**: The tuner must learn from **action** (applied) vs **rejection**, not intention (bookmarked). Pooling `interested` dilutes the taste signal (FR-008/017).
**Code touch**: `tune.py:_split` (drop `interested` from `pos`); revisit `store.label_counts` `pos`/`both_classes` semantics used by the gate.
**Alternatives**: keep pooling (rejected: dilutes signal); drop `interested` entirely (rejected: it's a useful board bookmark).

## R5 — Δ2: tuner gate ≥5 applied / ≥5 rejected / ≥20 total

**Decision**: Replace `tune.py`'s `if not pos or not neg` (≥1 each) with a configurable gate defaulting to ≥5 applied, ≥5 rejected, ≥20 total; decline below it with an explanation (FR-017).
**Rationale**: A 4-weight grid fit on 1–2 points per class overfits and produces a misleading before/after, contradicting SC-004 "demonstrably improves". Thresholds live in config (store.meta) for override.
**Code touch**: `tune.py:tune` gate; surface counts in the decline message.
**Alternatives**: keep ≥1 each (rejected: meaningless fit); statistical adequacy / CV folds (rejected: over-engineered for a personal tool).

## R6 — Δ3: single shared cutline source (no drift)

**Decision**: New tiny `src/scoring.py` exporting `THRESHOLD = 55`, `TIER_A = 70` (and any tier constants); `analyze.py:tier_of` and `tune.py` import from it.
**Rationale**: Today `55` is hard-coded in both `analyze.py:tier_of` and `tune.py:THRESHOLD` — they can silently drift, which would make the tuner optimize a different boundary than the board uses. One source removes the hazard. Fixed (not user-overridable) in v1 per the clarification; the tuner moves weights only, never cutlines.
**Code touch**: add `scoring.py`; edit `analyze.py` + `tune.py` to import.
**Alternatives**: leave duplicated (rejected: drift hazard); user-overridable now (rejected: deferred to roadmap).

## R7 — Δ4 + CV: immutable snapshot & tailor-at-apply (v1)

**Decision**: At apply, the `decisions.resume` column stores an **immutable snapshot** of the exact CV text sent = base CV + any accepted tailoring edits (possibly just base). v1 produces a **per-application tailored copy** from accepted gap edits at apply time; **no `cv_variants` table, no library, no editor** (those are v2).
**Rationale**: The snapshot makes the decision log honest ground truth for the tuner even after the base CV changes (FR-007/008). Tailor-at-apply delivers ~80% of ATS-tailoring value at ~30% of the cost and serves the primary (passive) persona; the library/editor serve the secondary (high-volume) persona → v2.
**Code touch**: `store.mark(resume=...)` already accepts `resume`; ensure board/serve apply-flow passes the tailored text; freeze it (never a mutable ref).
**Alternatives**: full variant model in v1 (rejected: starves the harness — the real differentiator — of build time); label-only (rejected: loses what was actually sent).

## R8 — `cover` command (FR-026)

**Decision**: New `src/cover.py` — a standalone CLI command (+ thin serve.py surface) that, given a role + the base/tailored CV, asks the configured backend for a cover-letter draft in `profile.output_language`, grounded only in CV+JD; output to stdout/file, accept/reject/edit by the human, never auto-sent, never fabricating.
**Rationale**: Felt-value at the apply moment, cheap, reuses the existing backend + profile; standalone (not wired into apply flow) per the clarification. Truthfulness guard mirrors FR-013.
**Alternatives**: bake into apply flow (rejected per clarification); defer (rejected: it's a cheap buyer-value steal).

## R9 — ICP-default profile preset (SC-001)

**Decision**: Ship `config/profile.example.json` as an opinionated **Ukrainian-IT-remote** preset (lane, allowed locations = remote/UA-OK, output language, a sensible comp floor, scoring instructions) so a new user reaches a scored board in one session without hand-editing config.
**Rationale**: SC-001 (empty → scored board in one session). The example already exists; this just makes it ICP-opinionated rather than generic.
**Alternatives**: generic empty preset (rejected: forces hand-editing, fails SC-001's "no hand-editing" intent).

## Open items intentionally deferred to /speckit-tasks or v2

- Per-source scraper field-mapping details (HTML structure of Djinni/DOU) — task-level.
- `cv_variants` schema, variant CRUD, live editor — v2.
- Semantic skill-similarity backend — v2.
- Email outcome loop (US5) — later phase.
- Scheduling: cron/launchd already driven by `run.sh`; no new requirement.

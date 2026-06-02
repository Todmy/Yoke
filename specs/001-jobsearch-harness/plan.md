# Implementation Plan: Yoke — job-search harness

**Branch**: `001-jobsearch-harness` | **Date**: 2026-06-02 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-jobsearch-harness/spec.md`

## Summary

Yoke scores job roles against a CV with a deterministic core and a thin LLM surface, wraps the scoring in an eval harness and a self-improving tuner, keeps a self-pruning board plus a first-class application tracker with a dedup guarantee, and offers truthfulness-guarded gap analysis with per-vacancy CV tailoring and a cover-letter command. CLI-first; the web panel is a thin client.

This plan is a **retrofit**: ~3000 LOC of working, stdlib-only Python already implements most of US1/US2/US4. The plan's real work is (a) reconciling the code with the clarified spec (5 code deltas surfaced by the zoom-out), and (b) building the newly-scoped v1 additions (CV tailor-at-apply, `cover` command, the Djinni/DOU/Hiring Cafe/LinkedIn source scrapers, ICP-default profile). The full named-variant library, live editor, and email outcome loop are v2/later.

## Technical Context

**Language/Version**: Python 3 (3.11+ assumed; `from __future__` + stdlib idioms throughout)
**Primary Dependencies**: **None (stdlib-only core)** — `sqlite3`, `http.server`, `urllib`, `subprocess`, `argparse`, `fcntl`, `html.parser`, `re`, `json`. Optional `.venv` carries `jobspy` for scraping only (venv-gated, never required by the core). This zero-dependency posture is a hard project invariant (see `serve.py`).
**Storage**: SQLite in WAL mode, single file under `$YOKE_HOME` (see `paths.py`); `fcntl` file locks for the scan index. No data in the repo.
**Testing**: `unittest` (stdlib) to preserve zero-dependency — see research.md. Pure functions (`score_fit`, `tier_of`, tuner `objective`, dedup key, comp parsing) are the high-value unit targets; the deterministic pipeline runs end-to-end with `--mock` (no model).
**Target Platform**: Local machine, cross-platform (macOS/Linux/Windows), single user. Web UI is stdlib `http.server` bound to 127.0.0.1.
**Project Type**: CLI-first single project (`src/`) + a thin stdlib web client (`serve.py`). Electron is later.
**Performance Goals**: Single-user, local; not latency-bound. v1 controls cost by feature-caching (recompute the formula with zero model calls; re-call only on new/changed/stale roles) — the per-role spend budget (FR-025) is v2; ~¼ of roles are decided by rules with **zero** model calls (SC-002). Eval and tuner make zero or bounded model calls.
**Constraints**: Local-first (no personal data leaves the machine, none in the repo — FR-020); zero third-party deps in the core; concurrent cron+UI access must not corrupt state (SQLite WAL); the model never emits the fit number (auditable formula); no auto-apply, no fabrication (FR-013/021).
**Scale/Scope**: Thousands of roles in the index (comparable feeds run ~5k active); single profile in v1 (multi-profile is a `TODO(B)` in `analyze.py`).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The project constitution (`.specify/memory/constitution.md`) is **ratified v1.0.0** (2026-06-02), codifying the seven principles below. Gates are taken from it and evaluated.

| Principle (de-facto) | Plan compliance |
|---|---|
| CLI-first; UI is a thin client | ✅ Every v1 addition (`cover`, tailor-at-apply, scrapers) is a CLI command first; serve.py stays a thin client |
| Determinize what you can; no model for rule-able attributes | ✅ No new mandatory model calls in deterministic stages; comp-band estimate stays inside the existing thin model schema |
| Model proposes features; code computes the score | ✅ No change to `score_fit`'s authority; cutline-constant extraction *strengthens* this |
| Ground truth = user behavior | ✅ Tuner reconciliation (positive = `applied` only) makes this stricter |
| Safety gates over fuzzy accuracy | ✅ Eval reference (frozen golden labels) unchanged; safety gates remain deterministic |
| The human decides (no auto-apply, no auto-rewrite) | ✅ CV tailoring + cover letter are assisted/accept-reject, truthfulness-guarded |
| Pluggable everywhere | ✅ New sources are scraper plugins; backends unchanged |
| Zero-dependency core | ⚠️ Two FRs press on this — semantic skill-similarity (FR-011) and new scrapers (FR-001). Resolved in research.md by keeping the core stdlib and gating any heavier need behind the optional venv or deferring (semantic → v2). |

**Verdict**: No unjustified violations. Two zero-dependency tensions are resolved in Phase 0 (research.md), not by adding core deps.

## Project Structure

### Documentation (this feature)

```text
specs/001-jobsearch-harness/
├── plan.md              # This file
├── research.md          # Phase 0 — resolved unknowns (testing, semantic-sim, scrapers, deltas)
├── data-model.md        # Phase 1 — entities, schema, the 5 code deltas
├── quickstart.md        # Phase 1 — empty setup → scored board in one session (SC-001)
├── contracts/
│   └── cli-commands.md   # Phase 1 — the CLI command contract (the public interface)
└── tasks.md             # Phase 2 — created by /speckit-tasks (NOT here)
```

### Source Code (repository root) — existing, extended

```text
src/
├── collect.py          # pull + normalize + dedup roles  → EXTEND: Djinni/DOU/Hiring Cafe/LinkedIn scrapers; URL-liveness pruning
├── prepare.py          # deterministic feature cards (geo/lane/comp)
├── analyze.py          # thin LLM fill → score_fit → tier   → EDIT: cutline constant (Δ3); comp-band already built
├── board.py            # board CLI (add/apply/drop/render)  → EXTEND: tailor-at-apply copy (Δ4)
├── store.py            # SQLite store                        → EDIT: resume snapshot (Δ3-CV); interested not-a-label feeds tuner (Δ1)
├── tune.py             # weight tuner                        → EDIT: positive=applied only (Δ1); gate 5/5/20 (Δ2); shared cutline (Δ3)
├── eval.py             # scorecard + safety gates
├── prepare.py / paths.py / serve.py
├── gap.py              # NEW: deterministic skill match/gap + guarded learning/tuning suggestions (US3, FR-011/012)
├── cover.py            # NEW: standalone cover-letter command (FR-026)
├── scoring.py          # NEW (small): shared cutline constants (THRESHOLD/A/B) imported by analyze.py + tune.py (Δ3)
├── data/
│   └── skills.json     # NEW: skill taxonomy (tools + knowledge domains + meta-qualities) with aliases (US3)
└── llm/                # claude_code (subscription) + openai_compatible (API+local)

tests/                  # NEW: stdlib unittest
├── test_scoring.py     # score_fit, tier_of, cutlines
├── test_tune.py        # objective, gate, positive-class split
├── test_dedup.py       # role-key normalization, applied-never-resurfaces
└── test_pipeline.py    # prepare|analyze --mock end-to-end
```

**Structure Decision**: Single CLI-first Python project, extending the existing `src/` layout. Two new small modules (`cover.py`, `scoring.py`) and a new `tests/` tree. No restructuring — the existing module boundaries already match the spec's stage model.

## Complexity Tracking

> No constitution violations requiring justification. The one watch-item is scope: the spec's v1 was deliberately bounded (CV tailor-at-apply, not the full variant library) precisely to avoid over-building the least-differentiated layer; the plan honors that boundary.

| Watch-item | Why bounded | If unbounded |
|---|---|---|
| CV variants | v1 = per-application tailored copy only (no new tables) | Full variant library + editor would add a `cv_variants` table, CRUD, selection UX — deferred to v2 |
| Skill semantic-similarity (FR-011) | v1 = deterministic taxonomy+alias only | Embeddings need a dep or LLM calls — semantic augmentation deferred to v2 |
| Sources | v1 = the 4-source short-list as scraper plugins | Broad-feed competition explicitly rejected (positioning) |

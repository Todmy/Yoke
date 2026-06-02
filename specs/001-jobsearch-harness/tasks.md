# Tasks: Yoke — job-search harness

**Input**: Design documents from `/specs/001-jobsearch-harness/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-commands.md

**Nature**: This is a **retrofit**. US1/US2/US4 are largely implemented in ~3000 LOC of stdlib-only Python; their tasks are *reconcile-to-spec* deltas + a few new builds. **US3 (gap/cover) is greenfield** (`gap.py`/`cover.py` do not exist). US5 (email) is deferred post-v1.

**Tests**: Included — the plan (research R1) chose stdlib `unittest`, and the deltas (tuner positive-class, gate, cutline-drift) are correctness-critical.

**Zero-dependency invariant**: no new third-party imports in the core; `jobspy` stays venv-optional (scraping only).

## Format: `[ID] [P?] [Story] Description`
- **[P]**: parallelizable (different file, no incomplete deps)
- **[Story]**: US1–US5; Setup/Foundational/Polish carry no story label

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 [P] Create `tests/` tree runnable via `python3 -m unittest discover -s tests` (stdlib unittest, per research R1)
- [X] T002 [P] Make `config/profile.example.json` an opinionated Ukrainian-IT-remote ICP preset (lane, remote/UA locations, comp floor, output language, scoring instructions) so a new user reaches a board with no JSON hand-editing (research R9, SC-001)

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ Blocks US1 (tier) and US4 (tuner) — the cutline must be a single source before either is reconciled.**

- [X] T003 Create `src/scoring.py` exporting the single-source cutline constants `THRESHOLD = 55` and `TIER_A = 70` (Δ3, FR-004)
- [X] T004 Refactor `src/analyze.py` `tier_of` to import cutlines from `src/scoring.py` (remove the local 55/70 literals)
- [X] T005 Refactor `src/tune.py` to import `THRESHOLD` from `src/scoring.py` (remove its duplicate `THRESHOLD = 55`)
- [X] T006 [P] Add `tests/test_scoring.py` — assert one shared cutline source; `score_fit` monotonicity and `tier_of` boundaries at 55/70 (geo/comp gates)

**Checkpoint**: cutlines unified — scorer and tuner can no longer drift.

---

## Phase 3: User Story 1 — Trustworthy scored shortlist (Priority: P1) 🎯 MVP

**Goal**: A board of Tier A/B roles with transparent fit, that self-prunes and pulls from the v1 sources.

**Independent Test**: `prepare | analyze --mock --no-board` yields tiered roles with ~¼ rules-decided and zero model calls; re-collect drops dead-URL roles.

- [ ] T007 [US1] Implement posting-URL liveness pruning in `src/board.py` (or `src/collect.py`): a live role whose source URL returns 404/410 on re-collect is removed; transient errors (timeout/5xx) do NOT prune (FR-005)
- [ ] T008 [P] [US1] Hiring Cafe source adapter in `src/collect.py` via stdlib `urllib` (JSON aggregator → one high-yield source) (FR-001, research R3)
- [ ] T009 [P] [US1] Djinni source adapter in `src/collect.py` via stdlib `urllib` + `html.parser`/`re`, rate-limited (≥2s between requests, exponential backoff on 429/5xx) (FR-001)
- [ ] T010 [P] [US1] DOU source adapter in `src/collect.py` via stdlib `urllib` + `html.parser`/`re`, rate-limited (≥2s between requests, exponential backoff on 429/5xx) (FR-001)
- [ ] T011 [P] [US1] LinkedIn read-only adapter (venv-optional `jobspy`, no logged-in actions; skip gracefully if absent) (FR-001, assumptions)
- [ ] T012 [P] [US1] Manual paste/CSV import adapter in `src/collect.py` (stdlib fallback so the pipeline works with every scraper down) (FR-001)
- [ ] T013 [US1] Confirm/extend `model_fill` so the comp-band estimate (`comp_est_net_mo`) is informed by company + target-market context, not title/JD alone, in `src/analyze.py` (FR-002 — schema already present)
- [ ] T014 [P] [US1] Add `tests/test_dedup.py` — role-key normalization (URL + normalized company|title); an applied/rejected role never resurfaces, incl. repost under a new URL (FR-009, SC-005)
- [ ] T015 [P] [US1] Add `tests/test_pipeline.py` — `prepare | analyze --mock` end-to-end runs with no provider; assert tiering + roughly a quarter hard-gated with zero model calls (FR-006, SC-002)

**Checkpoint**: trustworthy, self-pruning board from v1 sources — independently shippable.

---

## Phase 4: User Story 2 — Track applications without double-applying (Priority: P2)

**Goal**: Apply is a logged assisted flow that snapshots the CV sent; tracker shows the funnel; dedup holds.

**Independent Test**: apply a role → it enters the tracker with an immutable CV snapshot; re-collect doesn't resurface it; funnel rates update.

- [ ] T016 [US2] Ensure `board apply` writes an **immutable** `resume` snapshot (base CV + any accepted tailoring edits, possibly just base) in `src/store.py` + `src/board.py` — never a mutable reference (Δ4, FR-007)
- [ ] T017 [US2] Treat `interested` as a board-side bookmark in the tracker UI/CLI (distinct from a training label) in `src/store.py`/`src/serve.py` (Δ1, FR-008)
- [ ] T018 [P] [US2] Add `tests/test_tracker.py` — snapshot immutability after base-CV edit; `application_stats` response/interview/offer rates; status set by hand is preserved (FR-007/010)

**Checkpoint**: tracker + dedup + honest CV snapshot.

---

## Phase 5: User Story 3 — Close the skill & CV gap (Priority: P2)

**Goal**: Deterministic gap analysis, guarded learning/tuning suggestions, per-vacancy tailored copy, and a cover-letter command. **Greenfield.**

**Independent Test**: `gap <role>` returns matched/ranked-missing skills + honest band; no suggestion asserts a skill absent from the CV; `cover <role>` drafts a letter grounded only in CV+JD.

- [ ] T019 [US3] Create the skill taxonomy data file (tools + knowledge domains e.g. high-load + meta-qualities e.g. fast-learner, with aliases) at `src/data/skills.json` (FR-011, research R2)
- [ ] T020 [US3] Create `src/gap.py` — deterministic taxonomy+alias matched/missing-skill extraction ranked by relevance + honest match indicator (qualitative band + number on expand), no required model call (FR-011)
- [ ] T021 [US3] Add model-backed learning suggestions for genuinely-missing skills in `src/gap.py` (FR-012)
- [ ] T022 [US3] Add accept/reject bullet-level tuning suggestions, only for skills the CV supports, truthfulness-guarded (never fabricate skill/metric/seniority) in `src/gap.py` (FR-013/014)
- [ ] T023 [US3] Produce a per-application tailored CV copy from accepted edits at apply time (feeds the T016 snapshot); CLI-reachable (FR-012, depends on T016)
- [ ] T024 [US3] Create `src/cover.py` — standalone `cover <role_key>` command (CLI + thin serve.py surface): cover-letter draft in `profile.output_language`, grounded only in CV+JD, accept/reject/edit, never auto-sent, never fabricated (FR-026)
- [ ] T025 [P] [US3] Add `tests/test_gap.py` — no suggestion or cover draft asserts a skill/metric/seniority absent from the CV (SC-006); match indicator framed as relevance, not ATS-beating (FR-014)

**Checkpoint**: gap + tailor-at-apply + cover, all CLI-usable, truthfulness-guarded.

---

## Phase 6: User Story 4 — Trust & improve the scoring (Priority: P2)

**Goal**: Eval scorecard with dominating safety gates (built); tuner reconciled to learn from `applied` vs `rejected` with an honest gate.

**Independent Test**: `eval` always emits a scorecard and a seeded geo-FP forces fail; `tune` shows before/after on seeded labels and declines below the gate.

- [X] T026 [US4] Change `tune._split` positive class to `applied` only — exclude `interested` (Δ1, FR-017) in `src/tune.py` (after T005)
- [X] T027 [US4] Update `store.labeled_decisions` / `label_counts` positive-class + `both_classes` semantics to match (`applied` vs `rejected`) in `src/store.py` (Δ1)
- [X] T028 [US4] Replace the `≥1-each` gate with a configurable ≥5 applied / ≥5 rejected / ≥20 total gate that declines with an explanatory message in `src/tune.py` (Δ2, FR-017, SC-004)
- [X] T029 [P] [US4] Add `tests/test_tune.py` — gate thresholds; applied-only positive class; before/after objective improves on seeded labels; declines below gate (SC-004)
- [ ] T030 [P] [US4] Add `tests/test_eval.py` — scorecard always emitted; a seeded safety violation (geo false-positive) forces a fail regardless of fit closeness (SC-003, FR-016)

**Checkpoint**: harness reconciled — the differentiator is sound and tested.

---

## Phase 7: User Story 5 — Email outcome loop (Priority: P3) — ⏸ DEFERRED (post-v1)

**Not in v1.** Listed for completeness; do not implement in the v1 cycle (spec assumptions + plan). Read-only, user-supplied credentials, never overwrites a hand-set status.

- [ ] T031 [US5] (post-v1) Read-only mailbox connector with locally-stored user-supplied credentials, never the primary password (FR-022)
- [ ] T032 [US5] (post-v1) Match employer replies to tracked applications; advance status with a source note; never overwrite a hand-set status (FR-023)
- [ ] T033 [US5] (post-v1) Guarantee read-only mail access — never send/delete/modify (FR-024)

---

## Phase 8: Polish & Cross-Cutting

- [ ] T034 [P] Run the `quickstart.md` smoke checklist end-to-end; confirm SC-001..SC-008 hold
- [ ] T035 [P] Update `README.md` with the new `gap` / `cover` commands, the v1 source set, and the ICP preset
- [ ] T036 [P] Guard the project invariants (a tiny test/CI grep): (a) no new third-party import in `src/` core, `jobspy` confined to the venv path; (b) no personal data committed to the repo — all under `$YOKE_HOME` (FR-020); (c) no auto-apply / auto-send / auto-rewrite code path — every irreversible action is human-confirmed (FR-021)
- [ ] T037 Wire `cover` (and `gap` if scheduled) into `src/serve.py` thin client + `src/run.sh` where appropriate (FR-018)

---

## Dependencies & Execution Order

- **Setup (T001-T002)** → no deps; do first.
- **Foundational (T003-T006)** → blocks US1 tiering reconcile and US4 tuner; `scoring.py` (T003) before T004/T005.
- **US1 (P1, T007-T015)** → MVP. Depends only on Foundational. Source adapters T008-T012 are mutually parallel.
- **US2 (T016-T018)** → independent of US1/US3/US4 (shares `store.py` with US4 — sequence store edits T016/T017 vs T027 to avoid churn).
- **US3 (T019-T025)** → greenfield; T023 depends on T016 (snapshot target). Otherwise independent.
- **US4 (T026-T030)** → T026/T028 after T005 (same file, `tune.py`); T027 after/with T017 (both touch `store.py` decision semantics).
- **US5 (T031-T033)** → deferred, post-v1.
- **Polish (T034-T037)** → after the v1 stories (US1-US4) land.

### Parallel opportunities
- T001 ∥ T002 (setup).
- T008 ∥ T009 ∥ T010 ∥ T011 ∥ T012 (five source adapters, distinct code paths).
- T014 ∥ T015 ∥ T006 (independent test files).
- T029 ∥ T030 (independent test files).
- Across stories after Foundational: US1, US2, US3 finder/build work can proceed in parallel; only the noted `store.py`/`tune.py` co-edits need sequencing.

---

## Implementation Strategy

**MVP = US1 (P1).** It's the core value and mostly built — the MVP increment is: unify cutlines (Foundational) + URL-liveness pruning + the four v1 source adapters + the deterministic-path tests. Ship that as a trustworthy, self-pruning board.

**Then, in priority order:** US2 (snapshot + tracker reconcile) → US3 (greenfield gap/cover — the biggest new build and the buyer-value steal) → US4 (tuner reconciliation — the differentiator's correctness). US5 stays deferred until the launch-ready core (US1-US4) is solid.

**Brownfield caution**: T004/T005 (cutline imports), T026/T027 (decision semantics), T016 (snapshot) touch existing, working files — make surgical edits, run the new unit tests after each, and avoid refactoring adjacent code.

---

## Task count
- Setup: 2 · Foundational: 4 · US1: 9 · US2: 3 · US3: 7 · US4: 5 · US5 (deferred): 3 · Polish: 4
- **Total: 37** (34 in the v1 cycle; 3 deferred to post-v1)

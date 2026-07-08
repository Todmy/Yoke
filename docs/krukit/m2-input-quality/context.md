# Recon: m2-input-quality

## Goal
M2 "Input quality" (ROADMAP.md) — four **deterministic** workstreams that make the shortlist cleaner and the ranking sharper: **WS1** red-flags multiplier + modifier-floor clamp + "lenses" in scoring; **WS2** comp-estimation in prepare (benchmark tables); **WS3** ghost/liveness filter; **WS4** semantic dedup. Parity target = the `~/PBaaS` jobsearch prototype (this closes v1.0 parity).

## Affected map
| File | Role / symbol | Dependents | WS |
|---|---|---|---|
| `src/scoring.py` | `fit()` (:11, additive `Σw·s/100`, clamp 0-100); `tier_of()` (:21); `TIER_A=70/TIER_B=55` (:7-8) | `analyze_cards` (:197,201); `test_scoring`, `test_analyze` | WS1 |
| `src/analyze.py` | `analyze_cards()` (:135); `red_flags` **collected but discarded before scoring** (schema :41, stored :205); `fit`/`tier_of` seam (:197-201); LLM comp fallback (:174-176); `COMP_SCORE` (:22) | `yoke._run` (:164); `test_analyze`, `test_pipeline`, `test_yoke` | WS1 (red-flags hook), WS2 |
| `src/comp.py` | `normalize()` (:65); `floor_verdict` (:82-90); output keys `usd_min_mo/usd_max_mo/unit_detected/floor_verdict/floor/note`; `DEFAULT_FLOOR=10000` (:26) | `prepare._comp_norm` (:85), `analyze` (:176,141); `test_comp` | WS2 |
| `src/prepare.py` | `_comp_norm()` (:78-85, returns None on unknown-comp); `_apply_gates()` (:93, `comp_floor` gate :106); `build_cards()` (:130); `window_slice` (:39); "no network, no LLM" (:1-8) | `yoke._run`; `test_prepare` | WS2 (estimate plugs in), WS3 (new gate) |
| `src/collect.py` | `norm()` (:89, **8-key contract**); `job_key`(:108)/`role_key`(:113); `update_index()` (:196, `first_seen/last_seen`, `PRUNE_DAYS=45`) | 11 source plugins; `board._prune`/`mark_applied` depend on `role_key`; `test_collect` | WS3 (age signals), WS4 (dedup hook) |
| `src/board.py` | `_MUTABLE` (:19-22); `_prune` applied-ledger (:65-74); `render` cols (:176-184) | `yoke._run`; `test_board` | WS1/WS2 (only if new persisted keys) |
| `profile.example.yml` | `scoring.features`/`scoring.deterministic` weights **sum to 100** (:51-58); `comp.floor_net_usd_mo` (:22) | `analyze`(:140), `scoring.fit` | all (new config extends here) |

**Pipeline backbone** (`yoke._run` :118-172): `collect.run_collect` → `prepare.build_cards` → window filter (`in_window`→`needs_ai`) → `analyze.analyze_cards` (only the `needs_ai` slice hits the backend) → `board.upsert`+`render`. Each stage only *adds* keys to the record; downstream reads by `.get`.

## Patterns to follow
- **Deterministic logic = pure, no-I/O functions** with module-constant tunables: `scoring.fit/tier_of`, `comp.normalize`, `prepare._apply_gates`. New math lands the same way; the model never does arithmetic (constitution #2, `analyze.py:8-9`).
- **Config in profile, logic in code** — ADR-0001. Weights/bands/penalties are *data* in `profile.yml`; extension points: `scoring.red_flags:` (WS1, a `{flag→penalty}` map + `modifier_floor`, sibling of features/deterministic), `comp.benchmarks:` (WS2), top-level `dedup:` threshold (WS4). Keep additive weights summing to 100 — the multiplier lives *outside* the sum.
- **Test-first, table tests** — `test_scoring.py:18` (`40+15+0=55`), `test_comp.py:58/82` (verdicts + hourly regression), `test_prepare.py:100`. Fixtures under `tests/fixtures/` drive the **real** parse path (constitution #6); new benchmark/dedup fixtures drop here as JSON.
- **Raw material for WS2/WS3 already written as prose** — `candidate-brief.md §4` (:57-70) has the comp bands (PL-local $7.3-10.9k, EU-remote $6.5-8.7k, US→EU $7.5-13.3k; platform anchors) = the benchmark table. Ghost/liveness + semantic-dedup exist **only** as steal-report recipes (`~/PBaaS/.../steal-reports/{career-ops,job-hunter,job-harness}.md`), not in prototype code — WS3/WS4 are net-new.
- **The red-flags hook already exists** — `analyze.py` parses `result["red_flags"]` (:205) and throws it away before `fit`. WS1 is a clamp/multiplier layer on an existing seam, not greenfield.

## Invariants (must not break)
- **Fit = pure additive weighted sum, clamped 0-100** (`scoring.py:11-18`; `test_scoring.py:18-35`). Tier cutlines live in ONE place (`scoring.py:7-8`; `test_scoring.py:38-54`). `test_analyze.py:112-149` locks **exact fit values** (92, 77) — WS1 will change these expected numbers deliberately, not by accident.
- **Model never does arithmetic**; `comp_vs_floor` deterministic (`COMP_SCORE`, `analyze.py:22,192`). Hard-fail (`onsite`/`lane off`)→C; frictions demote A→B (`analyze.py:173-201`; `test_analyze.py:123-137`).
- **Comp**: unit read from source field, never inferred from magnitude; output-dict keys are a consumed contract (`comp.py:1-16`; `test_comp.py:17-92`).
- **Prepare pure** (no net/LLM/I-O); `needs_ai = in_window AND not gates_failed`; window strict `first_seen > max(last_run, now−14d)` (`prepare.py:1-8,39-50,146-156`; `test_prepare`).
- **Collect**: 8-key `norm` contract (`test_collect.py:38-59`); `role_key` repost-collapse is load-bearing for the board (`collect.py:113`; `test_collect.py:91-102`). **Applied is a forever-ledger** — key OR role_key in `applied[]` → pruned forever (`board.py:65-74`; `test_board.py:57-77`).
- **Money/consent**: analyze scores only the new-in-window slice; no keyed/paid source without explicit consent (`test_yoke.py:147-247`, `test_pipeline.py:147-154`). Constitution #7.
- **Import hygiene**: no module-level third-party import in `src/**` (`test_invariants.py:53-61`); source-plugin contract locked (`:64-80`).

**Windowing + applied-dedup already exist** — the parity-bar "scoring depth (lenses/windowing/applied-dedup)" is 2/3 done; do not rebuild them.

## Risks
- **WS1** — a multiplier changes the formula shape ADR-0001 deliberately kept additive (the M3 grid-search tuner needs additive; ADR-0001:18). Mitigation: apply `fit_base × (1−penalty)` *around* the sum, clamped, base stays tuner-refittable. Risk: red_flags degenerating into a keyword→tier classifier (#9 ban); clamp double-interacting with the existing 0-100 clamp and the onsite/lane-off hard-C path.
- **WS2** — estimated (non-source) comp could silently flip `floor_verdict` → flip the `comp_floor` gate → change the `needs_ai` set → change what analyze spends money on (#7). Must stay deterministic, separable from real-source comp, stdlib-only.
- **WS3** — a network liveness probe (404 check) breaks prepare's purity (`prepare.py:1-8`) and needs fixture tests (#6) + graceful degrade (ADR-0002). Wrong-drop of live roles / wrong-keep of dead ones. Gate vs flag-never-drop sub-score is a design choice.
- **WS4 — HIGH** — embeddings trip the third-party-import ban (`test_invariants.py:53-61`), #5 stdlib-lean core, #9 no-heaviness, and #2 stability (embedding drift across model/lib versions is non-auditable). Must augment, never replace, `role_key`/applied-ledger.

## Open questions (→ grill)
1. **WS1 "lenses"** — ADR-0001 rejected the prototype's multiplicative comp×work-model blend. So what does "lenses" mean here? (a) alternate weight-*sets* selected per role-type, still additive; (b) drop the lens concept, ship only red-flags multiplier + clamp; (c) revisit ADR-0001 (would need a superseding ADR). **Recommend (b)** for this flow — smallest, keeps the tuner contract; "lenses" as (a) is a separable later feature.
2. **WS1 penalty source** — the model emits free-text `red_flags[]`; a *multiplier* needs deterministic penalties. Map model-classified flag categories → profile-declared `{category→penalty}`? Confirm the model classifies into a fixed enum (thin AI surface) and code owns the penalty numbers.
3. **WS1 clamp semantics** — what does `modifier_floor` clamp exactly (a min multiplier so a strong role can't be zeroed; a cap so stacked penalties don't run away)? Interaction with the hard-C path.
4. **WS2 gate-safety** — does an *estimated* comp feed `floor_verdict`/the `comp_floor` gate (changes `needs_ai`), or stay "soft" (informs display/score, never gates)? Precedence vs the existing analyze LLM comp fallback (`analyze.py:174-176`).
5. **WS3 shape** — deterministic-only (age/repost-count/domain-trust from data already in the index: `posted_at`, `last_seen`, repost frequency) vs a network liveness re-check. Hard gate (→C) or flag-never-drop sub-score (steal recipe keeps ghost independent so a fake with 5/5 fit still scores low)? **Recommend** deterministic-only in prepare; any network probe lives at the collect/fetcher edge, fixture-tested.
6. **WS4 approach** — given the HIGH constitution tension: (a) defer WS4 to its own later flow; (b) optional plugin-edge Ollama embeddings, lazy-imported + graceful-degrade, augmenting role_key; (c) a deterministic stdlib fuzzy dedup (token-set / MinHash / normalized-title similarity) instead of embeddings. **Recommend (c) or defer** — (c) is cheap, deterministic, no heavy dep, and captures most repost-collapse value.
7. **Sequencing** — one design covering all four, or split? **Recommend** design covers all four but plan/act sequence them WS1 → WS2 → WS3 → WS4 (value-first, risk-last), with stage/`/clear` boundaries between workstreams.
8. **Scope re-confirm on WS4** — the "whole M2" choice was made before the WS4 constitution risk was visible. Grill should explicitly re-confirm WS4 stays in this flow (approach c) vs. deferring it.

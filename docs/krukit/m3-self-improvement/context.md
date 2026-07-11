# Recon: m3-self-improvement

## Goal
Build M3 "self-improvement loop": `eval.py` (scores the weak model against a **frozen golden set**, safety gates dominate, zero model calls) + `tune.py` (refits the additive scoring weights to the user's real apply/drop labels via a deterministic grid-search, zero model calls). Two new top-level CLI commands off the hot path; both read already-recorded data.

## Affected map
| File | Role | Depends / depended-on |
|---|---|---|
| `src/scoring.py:11-18` `fit(scores, weights)` | additive `Σ wᵢ·(scoreᵢ/100)`, clamp 0-100 — **tune's target function** | consumed by `analyze.py:286` |
| `src/scoring.py:7-8` `TIER_A=70/TIER_B=55`; `:21-31 penalized_fit`; `:34-49 tier_of` | cutlines + red-flag multiplier + tiering — **outside the tunable sum** | eval/tune consume, never redefine |
| `src/analyze.py:191-193` | builds `weights = {name: weight}` from `profile.scoring.features[] + deterministic[]` | reads profile |
| `src/paths.py:47-104` `load_profile`, `_validate_profile`, `ProfileError` | profile loader; **validates feature+det weights sum to exactly 100** (`:91-99`) | tune's refit MUST preserve sum=100 |
| `src/board.py:46-56,77-145` `_board.json`, `mark_applied`, `drop`, `_prune` | apply/drop ledgers + scored `roles{}` — **tune's ground-truth source** | see Blocker below |
| `src/yoke.py:17` `COMMANDS`; `:616-640` `_build_parser`; `:434-475` `_cmd_sources`; `:645-663` `main` dispatch | CLI seam for new `eval`/`tune` subcommands | template = `sources` |
| `src/analyze.py:151-171` `mock_fill` (crc32-derived, model-free) | deterministic fixture/replay generator | useful to seed golden set |
| NEW `src/eval.py`, `src/tune.py`, `tests/test_eval.py`, `tests/test_tune.py` | the M3 modules | — |

**On-disk shapes.** Analyzed role record (built `analyze.py:201-299`) carries `features:{<name>:{score,evidence}, comp_vs_floor:{...}}, fit, tier, geo_certainty, red_flags[], ...` — but lives **only** in `_board.json roles{}`. `scans/*.json` (collect) and `_cards.json` (prepare) hold **no fit/features**. Labels: `applied[]` = bare key+role_key strings; `dropped[]` = `{key, reason, date}`.

## Patterns to follow
- **Pure module-level functions on plain dicts** (no classes; `scoring.py`/`comp.py`/`prepare.py` style); dense module docstring stating the purity contract; all-caps structural constants at top, tuning knobs in profile (ADR-0001).
- **CLI slice = 4 coordinated edits** (`COMMANDS` tuple → `_build_parser` subparser with `help=` + `--json` → pure `_render_*` string renderer + `_<x>_json` shape builder → `_cmd_*` handler doing I/O + dispatch branch). `yoke help` auto-lists any new subparser. Unknown target → stderr + `return 2`. `--json` = per-subcommand, stable key set, guarded by a test.
- **State via `paths.py`** (`home()`, `ensure_home()`); persist as `json.dumps(..., ensure_ascii=False, indent=2)`.
- **Tests: stdlib `unittest`** (no pytest), tmp `$YOKE_HOME` set before importing `src`, renderers asserted as pure strings, table-driven inline-arithmetic math tests. **Zero-model-call is proven** by `mock.patch.object(yoke.llm,"get_backend", side_effect=AssertionError)` — ship this guard for eval/tune. New `src/*.py` auto-swept by `test_invariants.py` (no third-party imports).

## Invariants (MUST NOT break)
1. `fit` stays the pure additive weighted sum, clamp 0-100 (`test_scoring.py:18-35`).
2. Feature+deterministic weights **sum to 100** (`test_analyze.py:452-455`, `test_profile.py:99-101`) — tune's search space must preserve this.
3. Tier cutlines `70/55` stay single-homed in `scoring.py:7-8`.
4. Hard safety gates unchanged: onsite/lane-off→C, geo-verify→friction, below-floor comp gate (`analyze.py:247-290`) — eval treats violations as dominant; tune must not weaken them.
5. `fit_base` (additive) is the tuner's target; red-flag **penalty map stays outside the sum and out of M3 scope** (ADR-0003).
6. Zero model calls in both scripts (constitution #2/#7; README:40).
7. stdlib-only, no module-level third-party imports (`test_invariants.py:53-61`; ADR-0004 precedent — rules out numpy/sklearn for grid-search).
8. Golden set, labels, tuned weights are user data → never committed (constitution #8).

## Risks
- **BLOCKER — labels don't store features.** `apply`/`drop` record only the key and then **delete the role from `roles{}`** (`board.py:120-142`), so the feature vector is unrecoverable afterwards. `tune.py` therefore **cannot refit against real labels without re-analyzing (a model call M3 forbids)**. M3 must add **feature-snapshotting at decision time** (before prune) as its first dependency. Reference: `.private/prototype/board.py:238-359` did this via a SQLite `store` — must be re-cut to flat-JSON. Consequence: only labels recorded *after* M3 ships will be tunable (cold-start).
- Golden set has **no ground-truth geo/safety labels source** defined; a prior Opus-frozen set was flagged **not human-reviewed** (gap vs FR-015) — quality of the reference is unsettled.
- `desc` vs `description` key drift: code reads `f.get('desc')` (`analyze.py:114`), ADR-0001 prose says `description`. Use `desc`.
- Writing tuned weights back into hand-edited `profile.yml` risks silent drift of user-owned data.

## Open questions (feed grill)
1. **Feature-snapshot design (blocker resolution):** where/when to persist the per-role feature vector at apply/drop — new flat store (`home()/_labels.json` / `labels.jsonl`) vs extend `_board.json`? What fields (features, fit, tier, geo, gates, label, date)? Confirm cold-start (only post-M3 labels are tunable) is acceptable.
2. **Tuned-weights sink:** does `tune` (a) auto-write `profile.yml scoring.*.weight`, (b) emit an opt-in sidecar the user accepts, or (c) print a suggested diff only? (Constitution #2/#8 lean b/c.)
3. **Golden-set format + bootstrap + storage:** source of trusted geo/safety labels (hand-labeled vs frozen stronger-model output); does M3 require human review or accept Opus-frozen + spot-check? Committed sanitized fixture (`tests/fixtures/`) vs private under `$YOKE_HOME`? JD must be preserved (m2 parity lesson).
4. **eval data flow:** since eval calls no model, does it read pre-recorded weak-model analyze records (requiring a prior `yoke run` over the golden set), or does the golden artifact store both weak-model output and reference labels together?
5. **eval scorecard + metric:** exact gates counted (geo false-positive, tier over-promotion, hallucinated requirement, unparseable output) and how "safety dominates fit-delta" is quantified (hard safety-fail count separate from fit MAE?).
6. **tune objective precision:** balanced accuracy at which threshold (Tier-B cutline 55 = "worth pursuing"? applied=positive, dropped=negative), grid-search step/granularity under sum=100, minimum labels before tune runs.
7. **Sequencing:** ship eval + tune together in this one flow, or eval-first (safety half + portfolio signal) then tune? They have independent new dependencies (golden-set artifact vs feature-snapshot plumbing).

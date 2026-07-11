# Plan: m3-self-improvement

**Goal.** M3 self-improvement loop: `eval` (frozen-golden scoring, zero model calls at scoring, safety-dominant per-dimension scorecard) + `tune` (deterministic grid-search refit of additive weights, proposes only) + `labels.py` feature-snapshot store. Reframe: self-improvement = improving *process quality*; eval localizes the weak pipeline part, tune's weight-refit is one lever.

**Stack / global constraints.** Python 3.14, stdlib-only, flat-JSON under `$YOKE_HOME`. Pure module-level functions on dicts; state via `paths.home()/ensure_home()`; JSON dumped `ensure_ascii=False, indent=2`. Tests: stdlib `unittest` (no pytest), tmp `$YOKE_HOME`, zero network, zero-model proven by `mock.patch.object(yoke.llm, "get_backend", side_effect=AssertionError(...))`. CLI slice mirrors `sources`.

**MUST NOT break (invariants from context.md):**
1. `scoring.fit` stays the pure additive weighted sum, clamp 0-100.
2. Feature+deterministic weights **sum to 100** (`test_analyze.py:452`, `test_profile.py:99`).
3. Tier cutlines `TIER_A=70`/`TIER_B=55` single-homed in `scoring.py:7-8`.
4. Hard safety gates (`analyze.py:247-290`) unchanged.
5. `fit_base` (additive) is the tuner's only target; red-flag penalty map + cutlines out of scope (ADR-0001/0003/0005).
6. Zero model calls in `eval.score` + all of `tune`.
7. stdlib-only, no module-level third-party imports (`test_invariants.py:53`).
8. Golden set, labels, tuned weights never committed (only a sanitized fixture is).

**Task order / parallelism.** Chains: (T1→T2 labels+board), (T3→T4 tune), (T5→T6 eval) are disjoint file sets — chain heads **T1/T3/T5 are [P]** with one another. T7 needs T1,T3-T6. T9 needs T3. T8 is doc-only [P].

---

## T1 [P] — labels store (`src/labels.py`)
- **Creates:** `src/labels.py`. **Tests:** `tests/test_labels.py`.
- **Produces:**
  ```
  LABELS_FILE = "_labels.json"
  record(role: dict, label: str, reason: str | None = None) -> dict
  load_labels() -> list[dict]
  ```
- **Contract.** `record` builds the snapshot dict `{key, role_key, company, title, label, features, fit, tier, geo_certainty, red_flags, reason, date}` — `key/role_key/company/title/features/fit/tier/geo_certainty/red_flags` copied from `role` via `.get`; `date = datetime.date.today().isoformat()`; `reason` passed through (null for applied). Appends to `home()/_labels.json` (load-or-`[]`, append, `ensure_home()` + dump), returns the record. `load_labels` reads the list; **fail-open** (the `_last_run_counts` pattern): missing file → `[]`, `OSError`/`JSONDecodeError` → `[]`, non-list → `[]`, non-dict entries skipped.
- **Tests:** `test_record_builds_snapshot_fields` (board-shaped role → all keys present, features preserved); `test_record_appends_to_list` (two records → len 2); `test_record_reason_null_for_applied`; `test_load_missing_returns_empty`; `test_load_malformed_returns_empty`; `test_load_skips_non_dict_entries`.

## T2 — board snapshot hooks (`src/board.py`)
- **Modifies:** `src/board.py` (`mark_applied` `:103-128`, `drop` `:131-145`). **Tests:** extend `tests/test_board.py`. **Affected-map pattern:** board is in the Affected map — the hook only *adds* a side-write; `applied[]`/`dropped[]` shapes + `_prune` stay untouched (invariant).
- **Contract.** `import from src import labels`. In `mark_applied`, for each `r` in `hit`: `labels.record(r, "applied")` **before** `_prune`. In `drop`, `labels.record(r, "dropped", reason)` **before** `del b["roles"][key]`. The no-hit fallback (ledgers the raw match string, no role) snapshots nothing.
- **Tests:** `test_apply_snapshots_features_before_prune` (apply a role carrying `features` → `_labels.json` has 1 `applied` record with those features); `test_drop_snapshots_with_reason` (drop → 1 `dropped` record, `reason` set); `test_apply_no_hit_no_snapshot`; `test_apply_ledger_shape_unchanged` (regression: `applied[]` still sorted key list, `dropped[]` still `{key,reason,date}`).

## T3 [P] — tune core: balanced_accuracy + refit (`src/tune.py`)
- **Creates:** `src/tune.py`. **Tests:** `tests/test_tune.py`. **Consumes:** `scoring.fit`.
- **Produces:**
  ```
  balanced_accuracy(pairs: list[tuple[dict, str]], weights: dict, threshold: int = 55) -> float
  refit(pairs, base_weights: dict, step: int = 5, threshold: int = 55, min_each: int = 5) -> dict
  _compositions(keys: list[str], total: int, step: int)   # generator of {key: weight} dicts
  ```
- **Contract.**
  - `pairs` = `[(scores, label)]` where `scores = {name: score}` (0-100) and `label ∈ {"applied","dropped"}`.
  - `balanced_accuracy`: `pred = scoring.fit(scores, weights) >= threshold`; positive = `applied`. `TPR = TP/(TP+FN)`, `TNR = TN/(TN+FP)`; return `0.5*(TPR+TNR)`. If a class is empty, its rate term contributes 0.0 (refit's guard prevents this in practice).
  - `_compositions`: deterministically yields every `{key: w}` where each `w` is a multiple of `step`, `w >= 0`, and `sum == total`, over `keys` in given order (recursive stdlib enumeration).
  - `refit`: build pairs; count `applied`/`dropped`. **Cold-start:** if either `< min_each` → `{cold_start: True, n, before: base_weights, after: base_weights, ba_before, ba_after: ba_before, objective, threshold}`. Else: **feasibility** — `C(total/step + K-1, K-1)`; if `> 200_000`, set `step = 10` (single coarsen) and note via the result (no separate field needed — the grid still sums to 100). Enumerate `_compositions(keys=list(base_weights), total=100, step)`; score each with `balanced_accuracy`; pick max BA, tie-break = smallest L1 distance to `base_weights`. Return `{cold_start: False, n: {"applied","dropped"}, objective: "balanced_accuracy@fit>=55", threshold, before: base_weights, after: best, ba_before, ba_after}`.
  - Every candidate (and `after`) sums to 100 by construction (invariant 2).
- **Tests:** `test_balanced_accuracy_perfect` (separable pairs → 1.0); `test_balanced_accuracy_imbalance` (10 dropped/2 applied, predict-all-negative → BA ≈ 0.5, not high); `test_compositions_sum_and_step` (all yields sum 100, multiples of step); `test_refit_finds_known_optimum` (labels where one weight config clearly separates → returned); `test_refit_cold_start` (<5 applied → `cold_start True`, `after == before`); `test_refit_after_sums_100`; `test_refit_deterministic` (two runs identical); `test_refit_tie_break_smallest_change`.

## T4 — tune renderers + proposal write (`src/tune.py`)
- **Modifies:** `src/tune.py`. **Tests:** extend `tests/test_tune.py`.
- **Produces:**
  ```
  TUNED_FILE = "_tuned_weights.json"
  render_proposal(result: dict, use_color: bool = False) -> str
  proposal_json(result: dict) -> dict
  write_proposal(result: dict) -> None      # dumps home()/_tuned_weights.json
  ```
- **Contract.** `render_proposal`: header (objective, `n applied/dropped`), a per-feature `name  before → after` diff (unchanged rows shown plain, changed rows marked), `BA before → after`. Cold-start → a single clear line: `declined: need ≥5 applied and ≥5 dropped (have A/D)`. No ANSI escapes when `use_color=False` (gate color behind `_paint`-style helper, like `sources`). `proposal_json` returns the stable key set `{objective, threshold, n, before, after, ba_before, ba_after, cold_start}`. `write_proposal` = `ensure_home()` + dump.
- **Tests:** `test_render_proposal_shows_diff`; `test_render_cold_start_message`; `test_render_no_color_no_escapes` (`assertNotIn("\x1b[", out)`); `test_proposal_json_key_set` (`assertEqual(set(obj), {...})`); `test_write_proposal_creates_file`.

## T5 [P] — eval score + fixtures (`src/eval.py`)
- **Creates:** `src/eval.py`, `tests/fixtures/golden.json`, `tests/fixtures/eval_run.json`. **Tests:** `tests/test_eval.py`.
- **Produces:**
  ```
  GOLDEN_FILE = "_golden.json";  EVAL_RUN_FILE = "_eval_run.json"
  load_golden() -> list[dict]
  score(eval_run: dict, golden: list[dict]) -> dict
  _tier_rank(t: str) -> int          # A=3, B=2, C=1
  ```
- **Contract.** `load_golden` reads `home()/_golden.json`, fail-open `[]`. `score` joins `eval_run["roles"]` to `golden` by `key`; per joined role:
  - `safety.geo_false_positive += (model.geo == "remote_confirmed" and truth.geo == "onsite")`
  - `safety.tier_over_promotion += _tier_rank(model.tier) > _tier_rank(truth.tier)`
  - `safety.unparseable += (model role missing geo or tier)`
  - `dimensions.geo.agreement = mean(model.geo == truth.geo)`; `dimensions.comp_vs_floor.agreement = mean(model.comp_vs_floor == truth.comp_vs_floor)`
  - `dimensions.red_flags`: aggregate category-set TP/FP/FN across roles → `recall`, `precision`
  - `dimensions.features[name].mae = mean(|model.score - truth.score|)` **only** for roles whose `truth.features` is present; omit the `features` block entirely if no role carries it
  - `fit.tier_exact = mean(model.tier == truth.tier)`; `fit.tier_adjacent = mean(|rank diff| <= 1)`
  - `safety.total = geo_false_positive + tier_over_promotion + unparseable`; `verdict = "safety-fail" if total>0 else "safety-clean"`; `n = joined count`; `backend = eval_run["backend"]`
  - Division-by-zero safe (empty join → agreements 0.0, verdict safety-clean, n 0).
- **Fixtures.** `golden.json` = 4-6 sanitized roles with `jd` + `truth {geo, tier, comp_vs_floor, red_flags, features}`. `eval_run.json` = `{backend, roles[]}` matching by `key`, crafted so tests can assert exact safety/dimension numbers (include ≥1 clean role; a variant fixture or inline dict supplies a geo-false-positive case).
- **Tests:** `test_score_safety_clean_fixture` (verdict safety-clean, `safety.total 0`); `test_geo_false_positive_flips_verdict`; `test_tier_over_promotion_counts`; `test_dimension_agreement_math` (known fraction); `test_red_flag_recall_precision`; `test_feature_mae_present_when_truth_features`; `test_feature_block_absent_when_no_truth_features`; `test_score_zero_model_calls` (`get_backend→AssertionError` patched, `score` runs clean).

## T6 — eval record + renderers (`src/eval.py`)
- **Modifies:** `src/eval.py`. **Tests:** extend `tests/test_eval.py`. **Consumes:** the analyze scoring path (reuse, do not reimplement).
- **Produces:**
  ```
  record(golden: list[dict], backend, log=lambda *a: None) -> dict   # writes home()/_eval_run.json
  render_scorecard(card: dict, use_color: bool = False) -> str
  scorecard_json(card: dict) -> dict
  ```
- **Contract.** `record` builds a minimal feature card per golden role (`{title, company, location, url, jd, ...}`) and scores it through the **same analyze routine `_run` uses** (`analyze.analyze_cards` or its per-card equivalent) with the injected `backend`; collects `{key, geo, tier, comp_vs_floor, red_flags, fit, features:{name:score}}` per role into `eval_run["roles"]`; sets `eval_run["backend"] = backend.describe()`; writes `home()/_eval_run.json`; returns it. **The only model-touching function in eval.** `render_scorecard` prints, in order: **verdict + safety counts first** (marked `✗` on violations), then per-dimension diagnostics (the actionable block), then `fit` tier-agreement last; no ANSI when `use_color=False`. `scorecard_json` = stable key set mirroring the scorecard shape.
- **Tests:** `test_record_via_mock_backend` (mock backend → `eval_run["roles"]` populated, `_eval_run.json` written); `test_record_sets_backend_describe`; `test_render_scorecard_safety_before_fit` (index of safety section < index of fit section); `test_render_no_color`; `test_scorecard_json_key_set`.

## T7 — CLI wiring: eval + tune (`src/yoke.py`)
- **Modifies:** `src/yoke.py` (`COMMANDS` `:17`, `_build_parser` `:616-640`, new `_cmd_eval`/`_cmd_tune`, dispatch `:649-663`). **Tests:** extend `tests/test_yoke.py`. **Affected-map pattern:** follow the `sources` 4-edit template.
- **Contract.**
  - `COMMANDS += ("eval", "tune")`.
  - Parser: `eval` → `--record` (store_true), `--json` (store_true), both with `help=`; `tune` → `--json` (store_true), `help=`.
  - `_cmd_eval(record, as_json) -> int`: if `record` → `g = eval.load_golden()`; empty → `print("no golden set: create home()/_golden.json", file=sys.stderr); return 2`; `backend = llm.get_backend()`; `eval.record(g, backend, log=...)`; print `recorded N roles via <backend>`; return 0. Else (score) → load golden + read `home()/_eval_run.json`; either missing → `stderr "run \`yoke eval --record\` first"; return 2`; `card = eval.score(run, g)`; `as_json` → `print(json.dumps(eval.scorecard_json(card)))` else `print(eval.render_scorecard(card, use_color=sys.stdout.isatty()))`; return 0.
  - `_cmd_tune(as_json) -> int`: `pairs` from `labels.load_labels()` (extract `{name: feat["score"]}` + label); `weights` from `load_profile()` mirroring `analyze.py:191-193` (`features + deterministic`); `res = tune.refit(pairs, weights)`; `tune.write_proposal(res)`; `as_json` → `print(json.dumps(tune.proposal_json(res)))` else `print(tune.render_proposal(res, use_color=sys.stdout.isatty()))`; return 0. `ProfileError` handled by the existing `main` wrapper.
  - Dispatch branches for `eval`/`tune` in `main()`.
- **Tests:** `test_help_lists_eval_and_tune`; `test_eval_score_json_key_set`; `test_eval_missing_golden_exit2`; `test_eval_score_missing_run_exit2`; `test_eval_record_via_mock` (patch `get_backend` → mock, `--record` writes run); `test_tune_json_key_set`; `test_tune_cold_start_message`; zero-model guard asserts `tune` + `eval`-score dispatch construct no backend.

## T8 [P] — README docs (`README.md`)
- **Modifies:** `README.md`. **Tests:** none.
- **Contract.** Document `yoke eval` / `yoke eval --record` / `yoke tune` + `--json` in the commands section (like the sources-help additions). Add a short "Build a golden set" note: the `_golden.json` schema (roles + `jd` + `truth{geo,tier,comp_vs_floor,red_flags,features}`), that it lives private under `$YOKE_HOME`, and the hand-build steps. Align the "Under the hood" eval/tune sentences with reality now that both exist (drop the `(roadmap)` markers on `eval`/`tune` lines `:27-28`; keep the present-tense description honest).

## T9 — invariant guards (`tests/test_invariants.py`)
- **Modifies:** `tests/test_invariants.py`. **Tests:** self.
- **Contract.** `test_tune_refit_preserves_weight_sum` (a sample `refit` → `sum(after.values()) == 100`). `test_selfimprovement_modules_dont_import_src_llm` (AST/import scan of `labels.py`, `tune.py`, `eval.py`: none imports `src.llm` at module level — the backend is injected). The existing third-party-import sweep already covers the new modules (no change needed there).

---

## Spec coverage (design DoD → tasks)
- DoD 1 (`eval --record` → `_eval_run.json`) → T6, T7. DoD 2 (`eval` zero-call scorecard + `--json`) → T5, T6, T7. DoD 3 (`tune` grid refit, proposes, cold-start) → T3, T4, T7 + ADR-0005. DoD 4 (apply/drop snapshot before prune) → T1, T2. DoD 5 (golden schema + fixture + docs) → T5, T8. DoD 6 (suite green, zero-model proven, sum=100) → T3, T9 + guards across T5-T7.

## Learnings
(append-only; populated during act)

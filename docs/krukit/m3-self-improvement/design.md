# Design: m3-self-improvement

**Goal.** Ship M3's self-improvement loop: `eval` (scores the current model against a frozen golden set, zero model calls at scoring, safety-dominant per-dimension diagnostic) + `tune` (refits the additive scoring weights to real apply/drop labels via a deterministic grid-search, proposes only). Reframe: *self-improvement = improving the process quality* — eval localizes which pipeline part underperforms; tune's weight-refit is one narrow lever.

**Stack / constraints (verbatim from context.md + grill).** Python 3.14, stdlib-only, flat-JSON state under `$YOKE_HOME`. Both modules zero model calls at their core (eval scoring + tune), stdlib-only grid-search (no numpy), proven by the `get_backend → AssertionError` guard. Refit target = additive `fit_base` weights only, preserving sum=100; tier cutlines + red-flag penalty map out of scope (ADR-0001/0003/0005). Golden-set tooling = schema + committed fixture + documented manual build (bootstrap deferred).

## Architecture

Four new/edited units, each with one job, off the `collect→prepare→analyze→board` hot path:

| Unit | Kind | Responsibility |
|---|---|---|
| `src/labels.py` | NEW | the labels store — snapshot a decided role's feature vector to `home()/_labels.json` before board prune; load it back |
| `src/board.py` | EDIT (2 hooks) | `mark_applied`/`drop` call `labels.record(role, label, reason)` on each hit **before** prune/del |
| `src/eval.py` | NEW | `record` (the one model-touching op → `_eval_run.json`) + pure `score` → scorecard + renderers |
| `src/tune.py` | NEW | pure `refit` (grid-search) + `balanced_accuracy` + renderers; writes the `_tuned_weights.json` proposal |
| `src/yoke.py` | EDIT | `eval`/`tune` subcommands (COMMANDS, parser, `_cmd_*`, dispatch), `--json` contracts |

`labels.py`, the `score` half of `eval.py`, and all of `tune.py` are pure/deterministic and import no `src.llm`. Only `eval.record` and the CLI edge touch a backend.

## Components & interfaces

### `src/labels.py` — the labels store
```
record(role: dict, label: str, reason: str | None = None) -> dict
    # builds the snapshot, appends to home()/_labels.json, returns it
load_labels() -> list[dict]        # fail-open: skip malformed entries, [] on missing/bad file
```
Snapshot record (append-only list in `_labels.json`):
```
{ "key", "role_key", "company", "title",
  "label": "applied" | "dropped",
  "features": { "<name>": {"score": int, "evidence": str}, "comp_vs_floor": {...} },
  "fit": int, "tier": "A|B|C", "geo_certainty": str, "red_flags": [...],
  "reason": str | null, "date": "YYYY-MM-DD" }
```
`features` is copied straight from the board record (analyze already stored it there). Only decisions made **after** M3 ships carry features — cold-start, accepted.

### `src/board.py` — snapshot hooks (surgical)
- `mark_applied`: for each role in `hit`, call `labels.record(r, "applied")` **before** `_prune`.
- `drop`: call `labels.record(r, "dropped", reason)` **before** `del b["roles"][key]`.
- The no-board-hit fallback in `mark_applied` (ledgers the raw match string) has no role → nothing to snapshot; skip.
- Invariant: `applied[]`/`dropped[]` shapes and the prune logic are untouched — the hook only *adds* a side-write.

### `src/eval.py`
```
load_golden() -> list[dict]                        # home()/_golden.json (real, private)
record(golden: list, backend, log) -> dict         # runs backend over golden roles -> _eval_run.json; the ONE model call
score(eval_run: dict, golden: list) -> dict        # PURE, zero model calls -> scorecard
render_scorecard(card: dict, use_color=False) -> str
scorecard_json(card: dict) -> dict                 # stable --json contract
```
**Golden schema (`_golden.json`, list):**
```
{ "key", "title", "company", "location", "url", "source",
  "jd": str,                                        # preserved JD (m2 parity lesson)
  "truth": { "geo": "remote_confirmed|verify|onsite",
             "tier": "A|B|C",
             "comp_vs_floor": "above|straddles|below|unknown",
             "red_flags": ["category", ...],
             "features": { "<name>": int, ... } } }   # optional; enables per-feature MAE
```
**`_eval_run.json`** (the current model's take over the golden roles):
```
{ "backend": "<backend.describe()>",
  "roles": [ { "key", "geo", "tier", "comp_vs_floor", "red_flags": [...],
               "fit": int, "features": {"<name>": int} }, ... ] }
```
**Scorecard (`score` output):**
```
{ "n": int, "backend": str,
  "safety": { "geo_false_positive": int,   # model remote_confirmed, truth onsite
              "tier_over_promotion": int,   # model tier strictly better than truth (C→B/A, B→A)
              "unparseable": int, "total": int },
  "dimensions": { "geo": {"agreement": float},
                  "comp_vs_floor": {"agreement": float},
                  "red_flags": {"recall": float, "precision": float},
                  "features": { "<name>": {"mae": float} } },   # only when truth.features present
  "fit": { "tier_exact": float, "tier_adjacent": float },
  "verdict": "safety-clean" | "safety-fail" }                    # safety-fail iff safety.total > 0
```
Render order encodes "safety dominates": **verdict + safety counts first (bold/✗)**, then per-dimension diagnostics (the actionable "improve this part"), then the subordinate fit/tier agreement last.

### `src/tune.py`
```
balanced_accuracy(pairs, weights, threshold=55) -> float   # 0.5*(TPR+TNR); pairs=[(scores,label)]
refit(pairs, base_weights, step=5, threshold=55, min_each=5) -> dict
render_proposal(result, use_color=False) -> str            # before→after weight diff + BA delta
proposal_json(result) -> dict
```
`refit` result:
```
{ "cold_start": bool, "n": {"applied": int, "dropped": int},
  "objective": "balanced_accuracy@fit>=55", "threshold": 55,
  "before": {name: w}, "after": {name: w},          # after==before when cold_start
  "ba_before": float, "ba_after": float }
```
**Grid-search.** Keys = the profile weight names (features + deterministic). Enumerate integer compositions summing to 100 in multiples of `step` (default 5) — deterministic stdlib generator. Score each candidate with `balanced_accuracy` over the labels; pick max; tie-break = smallest L1 distance from `before` (minimal change). Positives = applied, negatives = dropped. Threshold fixed at 55 (Tier-B cutline; never tuned — invariant). Objective on `fit_base` only (the additive sum) — gates/penalty layers are deliberately excluded (they are separate, non-tuned layers; ADR-0001/0003).
**Feasibility guard.** #compositions = C(100/step + K−1, K−1). For the current K≈5–7 at step 5 this is ≤~230k evaluations (each cheap) — fine. If it would exceed a 200k cap (K too large), coarsen `step` to 10 and note it in the output; the design targets today's feature count (constitution #4).
**Cold-start guard.** `applied < min_each` or `dropped < min_each` → return `cold_start: True` (after==before, ba_after==ba_before); the CLI prints a clear "need ≥5 applied and ≥5 dropped, have X/Y" and exits 0 (declined, not an error).

### `src/yoke.py` — CLI (template = `sources`)
- `COMMANDS += ("eval", "tune")`.
- `eval` subparser: `--record` (store_true), `--json` (store_true). `tune` subparser: `--json`.
- `_cmd_eval(record, as_json)`:
  - `--record`: `load_golden()` (missing → stderr + exit 2); `backend = llm.get_backend()`; `eval.record(...)` → `_eval_run.json`; print "recorded N roles via <backend>". This is the ONE consented model op — the explicit `--record` flag is the consent.
  - default (score): load golden + `_eval_run.json` (either missing → stderr "run `yoke eval --record` first" + exit 2); `score` → scorecard; `--json` → `json.dumps(scorecard_json(...))`, else `render_scorecard(use_color=isatty)`.
- `_cmd_tune(as_json)`: `load_labels()`; weights from `load_profile()` (ProfileError → the existing exit-2 wrapper); `refit(...)`; write `_tuned_weights.json`; `--json` → `proposal_json`, else `render_proposal`. Cold-start prints the decline message.
- Dispatch branches added in `main()`; `yoke help` auto-lists both (help strings on the subparsers).

## Data flow
```
apply/drop ─► board hook ─► labels.record ─► _labels.json ──► tune.refit ─► _tuned_weights.json (+ diff)   [zero model calls]
_golden.json ─► eval.record(current backend) ─► _eval_run.json ─► eval.score ─► scorecard   [model call only in --record]
```

## Error handling
- Missing/empty `_golden.json` or `_eval_run.json` → actionable stderr + exit 2 (mirrors `_cmd_sources` unknown-name).
- Malformed `_labels.json` → fail-open, skip bad rows (the `_last_run_counts` isinstance-guard pattern; the sources-help review bug).
- Cold-start → declined message, exit 0, `--json {"cold_start": true, ...}`.
- `tune` never writes `profile.yml`; only `_tuned_weights.json` (ADR-0005).

## Testing (constitution #6: test-first, fixtures, no network)
- `tests/test_labels.py`: record shape from a board role; append/load round-trip; malformed-file fail-open.
- `tests/test_eval.py`: `score` on committed fixture golden + fixture eval_run → asserted scorecard (safety counts, per-dimension agreement math, verdict); safety-fail detection (a geo false-positive flips verdict); `record` via **mock backend**; **zero-model guard** (`get_backend → AssertionError`) on the score path.
- `tests/test_tune.py`: `balanced_accuracy` table-driven; `refit` finds a known optimum on a crafted label set; cold-start guard; **sum=100 preserved**; **determinism** (same input → identical output); zero-model guard.
- `tests/test_yoke.py`: `_cmd_eval`/`_cmd_tune` dispatch, `--json` key-set contract tests, missing-artifact exit-2, cold-start path.
- `tests/test_board.py` (or extend): apply/drop now write a `_labels.json` snapshot before prune.
- `tests/test_invariants.py`: auto-sweeps `eval.py`/`tune.py`/`labels.py` for the third-party-import ban; add a guard that `tune.refit` output weights sum to 100.
- Fixtures: `tests/fixtures/golden.json` (small, sanitized) + a matching `eval_run.json`.

## Definition of Done
1. `yoke eval --record` runs the current backend over the golden roles and freezes `_eval_run.json` (consented model op).
2. `yoke eval` scores frozen outputs vs golden with **zero model calls** → per-dimension scorecard (safety dominant), text + `--json`.
3. `yoke tune` refits additive weights via deterministic grid (sum=100, BA@fit≥55), **proposes** (diff + `_tuned_weights.json`), never mutates `profile.yml`; cold-start guard fires below 5/5.
4. apply/drop snapshot the role's features to `_labels.json` **before** prune (new `labels.py`).
5. `_golden.json` schema defined; sanitized fixture committed under `tests/fixtures/`; manual build documented in `README.md`.
6. Full suite green; zero model calls proven by the guard on the score/tune paths; weights-sum-100 invariant holds after tune.

## Prior art (Valis `b9ecd80d`)
An earlier informal eval found the weak model (Haiku) **safety-clean but fit-noisy** (MAE~25, tier-exact 25%). This corroborates the design's cut: safety and fit are *separate* diagnostic axes, and a model can pass one while failing the other — exactly what the per-dimension scorecard must surface.

## Constitution check

| Principle (MUST) | Verdict |
|---|---|
| 1 Local-first | pass — golden set, labels, tuned weights are user data, all local/private under `$YOKE_HOME`; never leave the machine |
| 2 Deterministic core, thin AI surface, auditable/stable | pass — `eval.score` + all of `tune` are pure/deterministic, zero model calls; the sole model call (`eval --record`) is the weak model's normal analyze work being *measured*, not new AI logic |
| 3 Flat files, no DB | pass — `_labels.json`, `_golden.json`, `_eval_run.json`, `_tuned_weights.json` are flat inspectable JSON |
| 4 Concrete with seams; new core module ⇔ ROADMAP milestone | pass — `eval`/`tune`/`labels` ARE M3; concrete to today's feature count, no speculative abstraction; golden-build tooling deferred (YAGNI) |
| 5 Sources are plugins, stdlib-lean core | pass — no new dependency; grid-search is stdlib-only (no numpy/sklearn) |
| 6 Core test-first, fetchers on fixtures, no network in tests | pass — test-first plan; golden/eval_run committed fixtures; zero network |
| 7 No paid call without consent | pass — `eval --record` is the only model op, gated by the explicit `--record` flag (opt-in = consent); `eval` score + `tune` spend nothing |
| 8 Moat barrier; labels/profile/.private never committed | pass — real golden set + `_labels.json` + `_tuned_weights.json` are private under `$YOKE_HOME`, never committed; only a sanitized fixture is committed. `tune` never mutates `profile.yml` (ADR-0005) |
| 9 Competitor ban-list (no keyword tier-classifier) | pass — `tune` refits numeric additive weights only; never a keyword→tier classifier |
| 10 Live-run verification | pass (adapted) — the network-collector dry-run clause is N/A (eval/tune touch no network/collectors); the independent zero-context diff review still applies at stage 7, and a real `yoke eval`/`yoke tune` dry-run over a small real golden set / real labels substitutes for the collector run if feasible |

Zero violations.


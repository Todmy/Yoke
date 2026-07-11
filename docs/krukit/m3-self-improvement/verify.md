# Verify: m3-self-improvement

## Evidence (run fresh 2026-07-11)
- **Full suite:** `python3 -m unittest discover -s tests -p 'test_*.py'` → **301 tests, OK** (252 baseline + 49 new).
- **Live run** — real scratch `$YOKE_HOME`, no mocks in the CLI path, zero network:
  - `yoke help` → lists `eval` and `tune` with their purposes. ✓
  - `yoke eval` (with `_golden.json` + `_eval_run.json`) → scorecard: `VERDICT: safety-clean`, safety counts 0/0/0, per-dimension agreements (geo/comp 1.0, red_flags 1.0/1.0, feature MAE 1.0), fit subordinate. **Zero model calls** (scores a pre-recorded run). ✓
  - `yoke eval --json` → the 6-key contract `{n, backend, safety, dimensions, fit, verdict}`. ✓
  - `yoke tune` — **real refit proven**: base weights `{hire_probability:60, comp_vs_floor:40}` at BA **0.0** on base-suboptimal labels → refit `{40, 60}` at BA **1.0**; wrote `_tuned_weights.json`; profile.yml untouched. ✓
  - `yoke tune --json` → the 8-key contract. ✓
  - Cold-start: 2 applied / 0 dropped → `tune declined: need >=5 applied and >=5 dropped (have 2/0)`, exit 0. ✓
  - `yoke eval` with no `_golden.json` → `no golden set: ...` on stderr, **exit 2**. ✓

No `discovery.md` (krukit-discovery not run) → no Validation plan to execute.

## Reality-check (design.md + plan.md vs code)
- All plan file paths exist: `src/labels.py`, `src/eval.py`, `src/tune.py`, `src/board.py`, `src/yoke.py`, `tests/test_{labels,tune,eval,board,yoke,invariants}.py`, `tests/fixtures/{golden,eval_run}.json`, `README.md`. ✓
- All new symbols resolve and are wired (live run is proof): `labels.record/load_labels`; `eval.load_golden/score/record/render_scorecard/scorecard_json/_tier_rank`; `tune.balanced_accuracy/refit/_compositions/render_proposal/proposal_json/write_proposal`; `yoke._cmd_eval/_cmd_tune`; `COMMANDS += eval,tune`; subparsers + dispatch present. ✓
- DoD 1–6 all implemented and live-proven. ✓
- Constitution MUST holds: #2 zero model calls at scoring (live "via mock" run + `get_backend→AssertionError` guards) ✓; #3 flat files ✓; #4 new modules ⇔ M3 milestone ✓; #5/#7-import stdlib-only, backend injected (invariant test) ✓; #6 test-first fixtures, no network ✓; #8 `_golden/_labels/_tuned_weights/_eval_run.json` **not tracked** — only sanitized fixtures committed ✓.
- No TODO/placeholder in new code; no terminology drift (glossary terms match code). ✓

## Findings
| ID | Severity | Location | Summary | Recommendation |
|---|---|---|---|---|
| V1 | LOW | `eval.record` (`src/eval.py`) | `comp_vs_floor` verdict is recovered by parsing the analyze record's `features["comp_vs_floor"]["evidence"]` prefix (`"floor verdict: X"`) — brittle coupling to analyze's evidence-string format. | A dedicated verdict field on the analyze record would decouple it. Recorded in plan.md Learnings; carry to stage 7. |
| V2 | LOW | `yoke eval --record` | The one model-touching path was NOT exercised live (needs a real backend + model spend, constitution #7 consent). Covered by `test_record_via_mock_backend` with the deterministic MockBackend. | Accept: deferred live-record; mock unit test proves the record path. |
| V3 | LOW | `tune.refit` feasibility guard | The `comb(...) > _MAX_COMPOSITIONS → step=10` coarsen branch is not covered by a test (current profiles have ≤7 features, below the cap). | Accept (concrete-with-seams #4); add a many-feature test if a profile ever approaches the cap. |

## Metrics
Requirements: 6 DoD / 6 implemented · Findings: 3 (0 CRITICAL / 0 HIGH / 0 MEDIUM / 3 LOW).

Zero CRITICAL, zero HIGH → gate clear. All three LOW recorded for stage 7 (krukit-review).

# Verify: sources-help

## Evidence (run fresh 2026-07-10)
- **Full suite:** `python3 -m unittest discover -s tests -p 'test_*.py'` → **247 tests, OK** (222 baseline + 25 new).
- **Live run (constitution #10)** — real `~/.yoke`, no mocks:
  - `./yoke help` → lists all 6 commands + purposes + flags pointer. ✓
  - `./yoke sources` → Available/Unavailable groups; geo badges (any/remote/PL/DE), cost (free/key), enabled/disabled, roles-last-run (`hn 18 roles`); recommended-first ordering (germany_ba(DE) sorts last for profile.countries=[pl]); `brave`/`jobspy` under Unavailable with reasons. ✓
  - `./yoke sources brave` → `✗ BRAVE_API_KEY not set` + full HELP with exact `export`/URL. ✓
  - `./yoke sources hn --json` → `{name,geo:"intl",cost,available,reason,enabled:true,roles_last_run:18,help}`. ✓
  - `./yoke sources --json` → `{"sources":[…]}`, each item the 7-key contract; `enabled` bool, `roles_last_run` null when absent. ✓
  - `./yoke sources bogus` → stderr `unknown source: bogus`, **exit 2**. ✓

No `discovery.md` (krukit-discovery not run) → no Validation plan to execute.

## Reality-check (design.md + plan.md vs code)
- All plan file paths exist: `src/yoke.py`, `tests/test_yoke.py`, `tests/test_invariants.py`, 12 `src/sources/*.py`, `README.md`. ✓
- All new symbols resolve and are wired (live run is proof): `_subcommands`, `_render_help`, `_cmd_help`, `_last_run_counts`, `_sources_meta`, `_source_help`, `_source_json`, `_render_sources_report`, `_render_source_page`, `_cmd_sources`; `COMMANDS` += `sources,help`; subparsers + dispatch present. ✓
- DoD 1–6 all implemented and live-proven. ✓
- Constitution MUST still holds: #1 local/read-only ✓, #2 stable tested `--json` ✓, #3 no new store ✓, #4 no new module ✓, #5 HELP co-located per plugin ✓, #6 test-first ✓, #7 cost shown, no fetch/spend ✓. ✓
- No TODO/placeholder in new code; no terminology drift. ✓

## Findings
| ID | Severity | Location | Summary | Recommendation |
|---|---|---|---|---|
| V1 | LOW | `src/yoke.py` `_cmd_sources` | On the `<name>` path `collect.load_sources()` runs twice (once via `_sources_meta`, once to build `mods`). | Build `mods` from a single load or fetch the module lazily; harmless (modules are cached), record for stage 7. |
| V2 | LOW | `_render_sources_report` | An enabled source absent from the newest scan shows `—`, indistinguishable from "ran, matched 0". | Accepted design (grill Q3: `—`, not `0`, because the source wasn't in the last run; scans carry no run-mode marker — YAGNI). Optional doc note. |

## Metrics
Requirements: 6 total / 6 implemented · Findings: 2 (0 CRITICAL / 0 HIGH / 0 MEDIUM / 2 LOW).

Zero CRITICAL, zero HIGH → gate clear. Both LOW recorded for stage 7 (krukit-review).

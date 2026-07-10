# Recon: sources-help

## Goal
Add `yoke help` (command surface for humans + LLMs), `yoke sources` (doctor report: geo/cost/status/enabled/roles-last-run), and `yoke sources <name>` (per-source setup page from an inline per-plugin `HELP` constant), with a stable `--json` contract — so an agent (Claude Code) can discover the CLI and self-configure a source.

## Affected map
| file | role | who depends on it |
|---|---|---|
| `src/yoke.py:17` `COMMANDS = ("run","board","apply","drop")` | allow-list gating auto-`run` insertion | `main()` :452 — **must add `"help"`,`"sources"`** |
| `src/yoke.py:429` `_build_parser` | argparse subparser registry (`add_subparsers(dest="cmd")` :431) | `main()` :454 — **add `help`/`sources` subparsers** |
| `src/yoke.py:450` `main(argv, input_fn)` | dispatch; branches :456-462, `drop` is bare `return` fallthrough | entrypoint — **add `help`/`sources` branches before `drop`** |
| `src/yoke.py:344-350` sources_meta loop | builds `{name,cost,available,reason,tags}` from `load_sources()` + `available()` | `_run`; **reuse for `yoke sources`** |
| `src/yoke.py:95-109` `_is_recommended`/`_recommended_names` | country-relevance sectioning (needs `profile.countries`) | menu; reusable for grouped listing |
| `src/yoke.py:56` menu status render | `COST`/reason display precedent | consent menu |
| `src/paths.py:17` `home()` / `:25` `ensure_home()` / `:47` `load_profile()` | `$YOKE_HOME` resolve; profile load (raises `ProfileError`) | `_run` :341, `_cmd_board` :406 |
| `src/collect.py:221` `load_sources()` | plugin discovery + `REQUIRED_ATTRS` validation | yoke.py:345, collect.py:329 |
| `src/collect.py:20` `REQUIRED_ATTRS=("NAME","TAGS","COST","available","fetch")` | source contract (presence check, extra attrs ignored) | `load_sources` :233 |
| `src/collect.py:365-368` scan snapshot | `home()/scans/<ts>.json` = matched jobs, each with `source` | roles-last-run source |
| `src/sources/*.py` (12 plugins) | `NAME/TAGS/COST/available()/fetch()`; optional `bypass_lane` (hn.py:16, read via `getattr` collect.py:350) | `load_sources` |

## Patterns to follow
- **Testability seam** (I authored these this session): pure renderers return strings, I/O injected. `select_sources_tui(sources_meta, preselected, read_key, out=print, recommended=None, viewport=…)`; `_render_menu(rows,…) -> str`; `_row_text(row,…) -> str`. New renderers `_render_help` / `_render_sources_report` / `_render_source_page` mirror this: pure, string-returning, tested directly; a thin `_cmd_*` prints.
- **Color helper** `_paint(text, code)` (`src/yoke.py`) + isatty gate `_interactive()` — for `yoke sources`, gate color on `sys.stdout.isatty()` so pipes/agents get clean text.
- **Optional plugin attr** precedent `bypass_lane` → read `HELP` as `getattr(mod, "HELP", None)`; fallback chain `HELP → __doc__ → "No setup needed — works out of the box"`.
- **Test style** `tests/test_yoke.py`: `unittest` TestCase classes; `test_*` methods; `_meta(name, available=True, reason="", cost="cost")` fixture builder; assert on rendered substrings. `$YOKE_HOME` set to a `TemporaryDirectory` in `setUp` (`:255-258`); scan glob precedent `tests/test_collect.py:312`.
- **No new store** — roles-last-run derived from newest `scans/*.json` grouped by `source`; `enabled` from `profile.sources.enabled` (`:304`). Drive source list off `load_sources()`, never `config/sources.json`.

## Invariants (must not break)
1. **COMMANDS gate** — new subcommand names MUST be added to `src/yoke.py:17`, or `main()` prepends `"run"` and mis-parses. Add a dispatch test (none exists).
2. **Source contract is a presence check** — extra attrs ignored; `HELP` on some plugins but not others breaks nothing (`test_invariants.py:64-80` asserts presence, not equality).
3. **COST vocabulary is `{free, key, paid}`** (`test_invariants.py:78`) — reuse existing `COST`/`_geo_badge`, do not invent labels (consent consistency, CONTEXT.md:16).
4. **No live network in tests** (constitution #6) — renderers read scans from `$YOKE_HOME`; test by writing a `scans/<ts>.json` under a tmp home, never real `~/.yoke`.
5. **`yoke sources` is read-only** (constitution #7) — must NOT fetch or spend; only display.
6. Constitution binds: **#5** sources-as-plugins (HELP co-located, no central help framework), **#4** concrete-with-seams (minimal branches, no new module/abstraction), **#2** stable/auditable output (`--json` = stable machine contract), **#6** test-first.

## Risks
- **[HIGH]** Forgetting `COMMANDS` edit → both new commands silently rewrite to `run`; current suite won't catch it → self-add a dispatch test.
- **[MED]** `--json` layout: existing tests pass flags *after* the subcommand; use **per-subcommand `--json`** (not root flag) so `yoke sources --json` and `yoke run …` both parse.
- **[MED]** Empty/first-run `scans/` (fresh home) → renderer must degrade gracefully ("no scans yet"), not crash. Cover with empty-tmp-home test.
- **[LOW]** `run`-path exact-stdout tests (`test_pipeline.py:144-145`, `test_yoke.py:318`) only bind `run`; safe as long as `_run`/`_print_summary` untouched — adding subparsers alone is safe.
- **[LOW]** README.md:66 documents public flags; new commands/`--json` extend the surface → update README (doc constraint, not a test).

## Open questions (→ grill)
1. **Profile-optional?** `yoke sources` needs `profile.sources.enabled` (enabled col) + `profile.countries` (recommended grouping). If no profile exists, degrade gracefully (enabled="—", no grouping) or raise `ProfileError` like `run`? Agent-facing leans graceful.
2. **`--json` exact schema** (stable contract): list-item shape for `yoke sources` (`{name, geo, cost, available, reason, enabled, roles_last_run}`?) and `yoke sources <name>` (`{name, available, reason, help}`?). Does `yoke help` need `--json` too?
3. **roles-last-run semantics** — newest scan is post-gate matched count; source absent from last run → `—` (not `0`). Confirm labeling; ignore `--mock`/`--dry-run` scans or not?
4. **`yoke help` source of truth** — derive from argparse subparsers vs a separate registry; sync guaranteed by a test either way. Which?
5. **Unknown source name** — `yoke sources bogus` → error text + nonzero exit? which code?
6. **HELP authoring scope now** — brave, jobspy, eures, germany_ba, justjoin get rich HELP; rest fall back. Confirm the 5, confirm actual `COST` values (which are `key` vs `paid`).

# Plan: sources-help

## Header
**Goal:** self-documenting, agent-operable source setup — `yoke help`, `yoke sources` (doctor report), `yoke sources <name>` (setup page from per-plugin `HELP`), stable `--json` contract.
**Architecture:** all in `src/yoke.py` (pure string-returning renderers + thin `_cmd_*`), plus a `HELP` constant per source module. No new module (constitution #4/#5).
**Stack:** Python 3.14, stdlib-only, `unittest`. Tests offline with a tmp `$YOKE_HOME`.
**Global constraints:** read-only (no fetch/spend); no new persistence; `--json` is a fixed tested shape; color gated on `isatty()`.

### MUST NOT break (invariants from context.md)
1. **COMMANDS gate** (`src/yoke.py:17`) — new names `help`,`sources` MUST be added, or `main()` prepends `run` and mis-parses. No existing test covers this — add one.
2. **Source contract is presence-only** (`collect.py:20,233`) — `HELP` on some plugins but not all breaks nothing; read via `getattr`.
3. **COST vocabulary `{free, key, paid}`** — reuse `COST`/`_geo_badge`, invent no labels.
4. **No live network in tests** (constitution #6) — write a `scans/<ts>.json` under a tmp home; never touch real `~/.yoke`.
5. **`yoke sources` read-only** (constitution #7) — display only.
6. **Run-path stdout tests** (`test_pipeline.py:144-145`, `test_yoke.py:318`) bind `run` only — `_sources_meta` extraction MUST preserve `_run` behavior; don't touch `_print_summary`.

---

## Tasks

### T1 — `yoke help` renderer (pure)
- **Files:** modify `src/yoke.py`; test `tests/test_yoke.py`.
- **Produces:**
  - `_subcommands(parser) -> list[tuple[str, str]]` — walk `parser._actions`, find the `argparse._SubParsersAction`, return `[(a.dest, a.help or "") for a in action._choices_actions]`.
  - `_render_help(commands: list[tuple[str,str]]) -> str` — header `Yoke — job-search harness. Commands:`, then aligned `  {name:<9} {purpose}` per command, then footer `Run \`yoke <command> -h\` for flags.`
- **Contract:** `_render_help` lists every `(name,purpose)` in order, name column left-padded to the longest name. `_subcommands(_build_parser())` returns all registered subcommands incl. `help` and `sources` (after T7 wires them).
- **Tests (`TestHelpCommand`):**
  - `test_render_help_lists_all_names` — build `[("run","collect…"),("board","…")]`, assert each name + purpose substring present and footer present.
  - `test_subcommands_reads_parser` — `names = [n for n,_ in _subcommands(_build_parser())]`; assert `"run"` and `"board"` in names (extended to `help`/`sources` in T7's sync test).

### T2 — `_last_run_counts` (newest-scan grouping)
- **Files:** modify `src/yoke.py` (uses `home` already imported `:15`, `json`); test `tests/test_yoke.py`.
- **Produces:** `_last_run_counts() -> dict[str, int]` — `scans = sorted((home()/"scans").glob("*.json"))`; if none → `{}`; read newest, `json.loads`; count records by `j.get("source")` (skip falsy); on `OSError`/`JSONDecodeError` → `{}`.
- **Contract:** newest file wins (lexical sort of `YYYY-MM-DD-HH-MM-SS.json` = chronological); missing/empty/malformed → `{}` (no raise).
- **Tests (`TestLastRunCounts`, tmp `$YOKE_HOME` in `setUp`):**
  - `test_counts_group_by_source` — write `scans/2026-01-01-00-00-00.json` = `[{"source":"hn"},{"source":"hn"},{"source":"vc"}]` → `{"hn":2,"vc":1}`.
  - `test_newest_scan_wins` — two scan files, newer has different counts → newer returned.
  - `test_empty_home_returns_empty` — no scans dir/file → `{}`.
  - `test_malformed_scan_returns_empty` — write non-JSON → `{}`.

### T3 — extract `_sources_meta` from `_run`
- **Files:** modify `src/yoke.py` (`_run:344-350` → call); test `tests/test_yoke.py`.
- **Produces:** `_sources_meta() -> list[dict]` — the loop from `_run`: for `mod in collect.load_sources()`, `ok,reason = mod.available()`, append `{"name":mod.NAME,"cost":mod.COST,"available":bool(ok),"reason":reason,"tags":mod.TAGS}`. `_run` replaces its inline loop with `sources_meta = _sources_meta()`.
- **Contract:** identical shape/order to the old inline loop; `_run` behavior unchanged (invariant #6).
- **Tests (`TestSourcesMeta`):**
  - `test_sources_meta_shape` — `meta = _sources_meta()`; assert non-empty, every item has keys `{name,cost,available,reason,tags}`, and `"hn"` present with `cost=="free"`.
  - Regression: existing pipeline/`_run` tests still green (no new test needed; suite covers it).

### T4a — per-source `HELP` constants [P]
- **Files:** modify all 12 `src/sources/*.py` (`ats, brave, eures, germany_ba, hn, jobspy_src, justjoin, remoteok, remotive, vc, workingnomads, wwr`). Disjoint from `yoke.py` → parallel-safe.
- **Produces:** module-level `HELP = """..."""` next to `NAME/TAGS/COST`.
  - **Full setup** (`brave`, `jobspy_src`): what it is · what it returns · Setup with the **exact** command (`export BRAVE_API_KEY=<key>` + key URL; `pip install python-jobspy` + the LinkedIn/Indeed ToS caveat) · notes.
  - **Concise** (other 10): 2–3 lines — what it is · what it returns · `Setup: none — works out of the box.` (brave/jobspy excluded).
- **Contract:** `HELP` is a non-empty `str`. Content is actionable (concrete commands, not just links) per the agent-operability goal.
- **Tests:** covered by T4b's contract test (every plugin resolves non-empty help).

### T4b — `_source_help` fallback (pure)
- **Files:** modify `src/yoke.py`; test `tests/test_yoke.py` + extend `tests/test_invariants.py`.
- **Produces:** `_source_help(mod) -> str` — `getattr(mod,"HELP",None) or (getattr(mod,"__doc__",None) or "").strip() or "No setup needed — works out of the box."`
- **Contract:** never returns empty; prefers `HELP`, then module docstring, then the default sentence.
- **Tests (`TestSourceHelp`):**
  - `test_help_prefers_constant` — fake module obj with `HELP="X"` → `"X"`.
  - `test_help_falls_back_to_doc` — obj with no `HELP`, `__doc__="doc"` → `"doc"`.
  - `test_help_default_sentence` — obj with neither → default sentence.
  - `test_every_plugin_has_help` (in `test_invariants.py`) — for each `collect.load_sources()` mod, `_source_help(mod)` is a non-empty `str`.

### T5 — `_render_sources_report` + `_source_json` (pure)
- **Files:** modify `src/yoke.py`; test `tests/test_yoke.py`.
- **Produces:**
  - `_source_json(row: dict, enabled, count) -> dict` → `{"name":row["name"], "geo":(row["tags"] or {}).get("country","any"), "cost":row["cost"], "available":bool(row["available"]), "reason":row["reason"], "enabled":enabled, "roles_last_run":count}` where `enabled` is `bool|None`, `count` is `int|None`.
  - `_render_sources_report(meta, enabled_names, counts, recommended, use_color=False) -> str` — split `meta` into available / unavailable; within available, order recommended-first then the rest (stable). Header `Sources`, group labels `Available` / `Unavailable`. Available row: `{name} {geo_badge}  {cost}  ✓  {enabled|disabled|—}  {N roles|—}`; unavailable row: `{name} {geo_badge}  {cost}  ✗  {reason}`. `enabled` = `enabled` if `name in enabled_names`, `disabled` if `enabled_names` set and not in, `—` if `enabled_names is None`. Roles from `counts.get(name)` → `N roles last run` or `—`. Aligned name column. Color (`_paint`) only when `use_color`. Footer `→ yoke sources <name> for setup`.
- **Contract:** deterministic; `use_color=False` yields plain ASCII+badge text with no escape codes; unavailable sources never show enabled/roles; ordering is recommended-first within Available.
- **Tests (`TestSourcesReport`, `use_color=False`):**
  - `test_report_splits_available_unavailable` — meta with one available + one unavailable → both group labels present, unavailable row shows its reason, not a roles count.
  - `test_report_enabled_and_roles` — available `hn` in `enabled_names`, `counts={"hn":5}` → row contains `enabled` and `5 roles`.
  - `test_report_enabled_none_shows_dash` — `enabled_names=None` → available row shows `—` where enabled would be.
  - `test_report_recommended_first` — two available, one in `recommended` → it precedes the other.
  - `test_report_no_color_has_no_escapes` — `"\x1b[" not in output`.
  - `test_source_json_shape` — assert exact key set `{name,geo,cost,available,reason,enabled,roles_last_run}` and `enabled=None`,`roles_last_run=None` pass through as JSON `null` via `json.dumps`.

### T6 — `_render_source_page` (pure)
- **Files:** modify `src/yoke.py`; test `tests/test_yoke.py`.
- **Produces:** `_render_source_page(row: dict, help_text: str, use_color=False) -> str` — line 1 status: `{name} — ✓ available` or `{name} — ✗ {reason}`; blank line; `help_text`. Color status glyph only when `use_color`.
- **Contract:** available → `✓ available`; unavailable → `✗ {reason}`; help body appended verbatim.
- **Tests (`TestSourcePage`):**
  - `test_page_available` — available row → contains `✓ available` and the help text.
  - `test_page_unavailable_shows_reason` — unavailable row with `reason="BRAVE_API_KEY not set"` → contains `✗ BRAVE_API_KEY not set`.

### T7 — wire `help` + `sources` commands + `_cmd_help`/`_cmd_sources`
- **Files:** modify `src/yoke.py` (`:17` COMMANDS, `_build_parser`, `main`); test `tests/test_yoke.py`.
- **Produces:**
  - `COMMANDS = ("run","board","apply","drop","sources","help")`.
  - In `_build_parser`: `sub.add_parser("help", help="list all commands and what they do")`; `srcp = sub.add_parser("sources", help="show source status + setup pages"); srcp.add_argument("name", nargs="?", default=None, help="show one source's setup page"); srcp.add_argument("--json", action="store_true", help="machine-readable output")`.
  - In `main`, before the `drop` fallthrough: `if args.cmd=="help": return _cmd_help(parser)` and `if args.cmd=="sources": return _cmd_sources(args.name, args.json)`. (`parser` = the object built at `main`'s top.)
  - `_cmd_help(parser) -> int` — `print(_render_help(_subcommands(parser)))`; return 0.
  - `_cmd_sources(name, as_json) -> int` — gather: `meta=_sources_meta()`; `try: profile=load_profile() except ProfileError: profile=None`; `enabled=set(profile.get("sources",{}).get("enabled",[])) if profile else None`; `recommended=_recommended_names(meta, profile.get("countries",[])) if profile else set()`; `counts=_last_run_counts()`. Registry `by_name={m["name"]:m for m in meta}` and module map `mods={mod.NAME:mod for mod in collect.load_sources()}` for help text.
    - **name given:** if `name not in by_name` → `print(f"unknown source: {name}", file=sys.stderr); return 2`. Else `row=by_name[name]`, `help_text=_source_help(mods[name])`; `as_json` → `print(json.dumps({**_source_json(row, _enabled_of(name), counts.get(name)), "help":help_text}))`; else `print(_render_source_page(row, help_text, use_color=sys.stdout.isatty()))`. return 0.
    - **no name:** `as_json` → `print(json.dumps({"sources":[_source_json(m,_enabled_of(m["name"]),counts.get(m["name"])) for m in meta]}))`; else `print(_render_sources_report(meta, enabled, counts, recommended, use_color=sys.stdout.isatty()))`. return 0.
    - helper `_enabled_of(nm)` = `None if enabled is None else (nm in enabled)`.
- **Contract:** bare `yoke sources`/`yoke help` dispatch correctly (COMMANDS gate); unknown source → exit 2; `--json` emits the T5 contract; no profile → runs fine with `enabled=None`.
- **Tests (`TestCliDispatch`, tmp `$YOKE_HOME`):**
  - `test_dispatch_help_returns_zero` — `main(["help"])` → 0 (COMMANDS-gate coverage).
  - `test_dispatch_sources_returns_zero` — `main(["sources"])` → 0 even with no profile in tmp home.
  - `test_help_lists_help_and_sources` — capture stdout of `main(["help"])`; assert `"help"` and `"sources"` both listed (sync test).
  - `test_sources_unknown_name_exit_2` — `main(["sources","bogus"])` → 2.
  - `test_sources_json_has_sources_key` — capture `main(["sources","--json"])` stdout; `json.loads` → has `"sources"` list; each item has the T5 key set.
  - `test_sources_name_json_has_help` — `main(["sources","hn","--json"])` → object with `"help"` non-empty.

### T8 — README: document new commands [mechanical]
- **Files:** modify `README.md` (near `:66` flags block).
- **Produces:** a short "Commands" note: `yoke help`, `yoke sources`, `yoke sources <name>`, and the `--json` flag on `sources`.
- **Contract:** doc consistency only; no code. Not test-covered.

---

## Self-review
- **Spec coverage:** DoD1→T1,T7 · DoD2→T5,T7 · DoD3→T6,T7 · DoD4→T5,T7 · DoD5→T4a,T4b · DoD6→each task's tests · README→T8. All design requirements mapped.
- **Placeholder scan:** no TODO/TBD/`...`; code blocks are signatures/contracts only. No unresolved decision slots (all resolved in grill/design).
- **Type consistency:** `enabled` is `bool|None` and `roles_last_run` is `int|None` across `_source_json`/`_cmd_sources`/tests; `_render_*` return `str`; `_cmd_*` return `int`.
- **Parallel/mechanical:** T4a `[P]` (disjoint source files); T8 `[mechanical]`. T1,T2,T3,T4b,T5,T6,T7 share `src/yoke.py` → sequential.
- **Suggested order:** T1 → T2 → T3 → T4a → T4b → T5 → T6 → T7 → T8.

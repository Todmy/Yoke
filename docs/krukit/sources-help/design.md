# Design: sources-help

## Goal & Definition of Done
Make Yoke's source setup self-documenting and agent-operable. An LLM (Claude Code) or a human can discover the CLI, see every source's status, and read concrete setup steps in the terminal — no external links required to act.

**Done when:**
1. `yoke help` lists every subcommand + one-line purpose, derived from the built argparse (single source of truth, sync-tested).
2. `yoke sources` prints an **Available** / **Unavailable** report — per source: geo · cost · status · enabled · roles-last-run. Works **with and without** a profile; no crash on empty `scans/`.
3. `yoke sources <name>` prints a status line + the source's `HELP` body. Unknown name → stderr `unknown source: <name>`, exit 2.
4. `--json` on both `sources` forms emits the agreed stable shape (contract, tested).
5. Every source module exposes a `HELP` constant — full setup for `brave`/`jobspy`, concise for the other 10; fallback chain works for any without one.
6. New logic fully unit-tested (renderers, json, empty-home, unknown-source, dispatch, help-sync); no network; full suite green. README updated.

## Approaches considered
- **A — three thin subcommands + pure renderers + per-plugin `HELP` via `getattr` (CHOSEN).** Minimal branches in `yoke.py`, no new module; help text co-located in each plugin. Honors #4 (concrete-with-seams) and #5 (sources-as-plugins).
- **B — a `src/help.py` module owning a help registry.** Rejected: new core module not tied to a ROADMAP milestone (#4 violation) + central framework instead of plugin-owned docs (#5).
- **C — reuse the interactive TUI to navigate sources with a details pane.** Rejected: TTY-only, breaks the agent/pipe goal (mode-2). A report must be plain stdout.

## Architecture & components
All in `src/yoke.py` (pure renderers + thin `_cmd_*`), plus a `HELP` constant per source module.

**Wiring (invariant #1 — the HIGH risk):**
- `COMMANDS` (`:17`) += `"help"`, `"sources"`.
- `_build_parser` (`:429`): `sub.add_parser("help", help="list all commands and what they do")`; `srcp = sub.add_parser("sources", help="show source status + setup pages")` with `srcp.add_argument("name", nargs="?", default=None)` and `srcp.add_argument("--json", action="store_true")` (per-subcommand, not root — invariant #MED).
- `main` (`:456-462`): add `if args.cmd == "help": return _cmd_help(parser)` and `if args.cmd == "sources": return _cmd_sources(args.name, args.json)` **before** the `drop` fallthrough.

**Pure functions (testable, string-returning):**
- `_subcommands(parser) -> [(name, help)]` — reads the `argparse._SubParsersAction` `_choices_actions` (dest+help). Single source of truth.
- `_render_help(commands) -> str` — aligned `name  purpose` list + `Run \`yoke <command> -h\` for flags.` footer.
- `_sources_meta() -> [ {name,cost,available,reason,tags} ]` — extracted from `_run`'s inline loop (`:344-350`); `_run` calls it too (DRY; behavior preserved).
- `_last_run_counts() -> {source: int}` — newest `home()/scans/*.json` grouped by `source`; `{}` on no-scans / malformed (guarded).
- `_source_help(mod) -> str` — `getattr(mod,"HELP",None) or (mod.__doc__ or "").strip() or "No setup needed — works out of the box."`
- `_render_sources_report(meta, enabled_names, counts, recommended, use_color=False) -> str` — Available/Unavailable groups; within Available, recommended-first ordering; aligned columns; color via `_paint` gated on `use_color`.
- `_render_source_page(row, help_text, use_color=False) -> str` — status line + help body.
- `_source_json(row, enabled, count) -> dict` — `{name, geo(raw tag), cost, available(bool), reason, enabled(bool|null), roles_last_run(int|null)}`.

**Thin commands (I/O):**
- `_cmd_help(parser)` → `print(_render_help(_subcommands(parser)))`; return 0.
- `_cmd_sources(name, as_json)`:
  1. `meta = _sources_meta()`.
  2. `try: profile = load_profile() except ProfileError: profile = None`.
  3. `enabled = set(profile["sources"]["enabled"]) if profile else None`; `recommended = _recommended_names(meta, profile.get("countries",[])) if profile else set()`; `counts = _last_run_counts()`.
  4. If `name`: locate row; unknown → `print("unknown source: "+name, file=sys.stderr); return 2`. Else render page (or `_source_json + help` when `as_json`).
  5. No name: `--json` → `print(json.dumps({"sources":[_source_json(...)...]}))`; else `print(_render_sources_report(..., use_color=sys.stdout.isatty()))`. return 0.

## Data flow
`load_sources()` → per-module `available()`/`TAGS`/`COST` → `meta`. `profile.sources.enabled` → enabled set (or None). newest `scans/*.json` → per-source counts. Renderers combine → stdout. Read-only throughout; no fetch, no network, no new persistence (invariant #5, constitution #7).

## Error handling / edge cases
- No profile → `enabled=None` → display `—`, json `null`; no recommended grouping (grill Q1).
- Empty/missing `scans/` → `counts={}` → roles `—` / json `null`; no crash (risk #MED).
- Malformed scan JSON → caught → `{}`.
- Unknown source name → stderr + exit 2 (grill Q5).
- `use_color=False` when piped (`isatty()` false) → clean text for agents.

## Testing
Test-first (constitution #6), all offline with tmp `$YOKE_HOME`:
- `_render_help` contains every name from `_subcommands(_build_parser())` (help-sync + risk #HIGH covered).
- `main(["help"])` and `main(["sources"])` return 0 — the COMMANDS-gate dispatch test (none exists today).
- `_render_sources_report` fixture → asserts Available/Unavailable split, geo badge, cost, enabled, roles ordering.
- `_last_run_counts`: write a `scans/<ts>.json` under tmp home → correct counts; empty home → `{}`.
- `_render_source_page` + `_source_help` fallback (HELP → __doc__ → default).
- `_source_json` exact keys/shape (contract lock).
- `_cmd_sources("bogus", False)` → 2 (stderr captured).
- Extend the source-contract test: `_source_help(mod)` is a non-empty str for every plugin.

## Constitution check
| Principle (MUST) | Verdict |
|---|---|
| #1 Local-first | pass — read-only, nothing leaves the machine |
| #2 Deterministic core, thin AI surface / auditable stable output | pass — `--json` is a fixed, tested shape; no model involved |
| #3 Flat files | pass — reads existing flat state (`scans/`, profile); no new store |
| #4 Concrete with seams | pass — minimal branches, no new module; `HELP` via `getattr` seam |
| #5 Sources are plugins | pass — `HELP` co-located per plugin; core stays lean, no central help framework |
| #6 Core test-first, fetchers on fixtures | pass — deterministic renderers written test-first; no live network |
| #7 No paid call without consent | pass — `yoke sources` is read-only display; surfaces `COST` ({free,key}), never fetches/spends |
| #8 Moat barrier & small commits | pass — no secrets committed; discrete commits per unit |
| #9 Competitor ban-list | pass — no TUI heaviness added (report is plain stdout), no banned pattern |
| #10 Live-run verification | pass — verify stage will include a real `yoke sources`/`yoke help` run + fresh-eyes review |

Zero violations.

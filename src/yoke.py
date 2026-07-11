"""Yoke CLI: subcommands, consent gates, run orchestration.

Two consent points guard every run: the sources menu (no source is fetched
unless selected) and the analyze line (no model call without a yes). `--yes`
skips both using the remembered selection; `--mock` swaps the backend for a
deterministic fake so nothing real is ever constructed or spent.
"""

import argparse
import json
import sys
from datetime import datetime, timezone

from src import analyze, board, collect, eval, labels, llm, prepare, tune
from src.paths import ProfileError, home, load_profile, load_state, save_state

COMMANDS = ("run", "board", "apply", "drop", "sources", "help", "eval", "tune")


class MockBackend:
    """--mock backend: analyze.mock_fill behind the LLMBackend surface.

    complete() re-derives the card identity fields from the prompt lines that
    build_card_prompt emits, so scores stay deterministic per job key.
    """

    def __init__(self, feature_names):
        self.feature_names = list(feature_names)

    def describe(self):
        return "mock (no model call)"

    def complete(self, prompt, schema=None, system=None):
        fields = {}
        for line in prompt.splitlines():
            for f in ("company", "title", "url"):
                if f not in fields and line.startswith(f"{f}: "):
                    fields[f] = line[len(f) + 2:]
        return analyze.mock_fill(fields, self.feature_names)


def select_sources(sources_meta, preselected, input_fn=input):
    """Numbered toggle menu; pure over its inputs (I/O via print/input_fn).

    sources_meta: [{name, cost, available, reason}]. Empty input confirms and
    returns the selection in menu order. Unavailable sources cannot be enabled
    (a preselected-but-unavailable source is silently dropped).
    """
    wanted = set(preselected)
    selected = {m["name"] for m in sources_meta if m["available"] and m["name"] in wanted}
    while True:
        print("Sources:")
        for i, m in enumerate(sources_meta, 1):
            mark = "x" if m["name"] in selected else " "
            status = "available" if m["available"] else f"unavailable: {m['reason']}"
            print(f"  [{mark}] {i}. {m['name']} ({m['cost']}, {status})")
        raw = (input_fn("Toggle a number, empty input to start: ") or "").strip()
        if raw == "":
            return [m["name"] for m in sources_meta if m["name"] in selected]
        if not raw.isdigit() or not 1 <= int(raw) <= len(sources_meta):
            print(f"  enter a number 1-{len(sources_meta)}, or empty to confirm")
            continue
        m = sources_meta[int(raw) - 1]
        if m["name"] in selected:
            selected.discard(m["name"])
        elif m["available"]:
            selected.add(m["name"])
        else:
            print(f"  {m['name']} is unavailable ({m['reason']}) — cannot enable")


_ARROW_KEYS = {"[A": "up", "[B": "down", "[C": "right",
               "OA": "up", "OB": "down", "OC": "right"}


def _decode_key(getch):
    """Map one keypress (getch() → one char) to a semantic token.

    Returns 'up' | 'down' | 'right' | 'space' | 'enter' | None (key ignored). Ctrl-C
    raises KeyboardInterrupt so the menu cancels like any other prompt. Split
    from terminal I/O so the mapping is unit-testable without a TTY.
    """
    ch = getch()
    if ch in ("\r", "\n"):
        return "enter"
    if ch == " ":
        return "space"
    if ch == "\x03":
        raise KeyboardInterrupt
    if ch == "\x1b":  # CSI/SS3 arrow: ESC + two more bytes
        return _ARROW_KEYS.get(getch() + getch())
    return None


def _is_recommended(tags, countries):
    """Country-relevance gate for menu sectioning: global (any) and remote
    (intl) sources are always recommended; a country-pinned source only when
    its ISO-2 is in profile.countries. 'all-eu' is not expanded to member
    states here — a country board you didn't list sits in Other, still
    selectable, just not surfaced first.
    """
    country = (tags or {}).get("country", "any")
    return country in ("any", "intl") or country in countries


def _recommended_names(sources_meta, countries):
    """Names of sources whose TAGS clear _is_recommended for profile.countries."""
    cset = set(countries or [])
    return {m["name"] for m in sources_meta if _is_recommended(m.get("tags"), cset)}


_MENU_HINT = " ↑/↓ move · space toggle · enter start"

_GEO_LABEL = {"intl": "remote", "any": "any"}


def _geo_badge(tags):
    """Short geo label from a source's country tag: ISO-2 upper for a
    country-pinned board (PL, DE), else 'remote'/'any' for global sources.
    A single scalar can't express a multi-country board (PL+UA) — that would
    need a geo-list re-model; today every source has one dominant orientation.
    """
    country = str((tags or {}).get("country") or "any")
    return _GEO_LABEL.get(country, country.upper())


def _paint(text, code):
    return f"\x1b[{code}m{text}\x1b[0m"


def _badge_colored(tags):
    """Geo badge with an ANSI hue by kind: country=green, remote=cyan, any=dim."""
    label = _geo_badge(tags)
    return _paint(label, {"remote": "36", "any": "2"}.get(label, "32"))


def _menu_rows(rec, oth, unavail, expanded, selected):
    """Flat navigable-row model: recommended sources, then collapsible 'Other'
    and 'Unavailable' controls. `expanded` is {'other': bool, 'unavail': bool}.
    Row kinds: 'src' (selectable), 'more' (control), 'unavail' (read-only).
    """
    rows = [{"kind": "src", "meta": m, "indent": 0} for m in rec]
    if oth:
        rows.append({"kind": "more", "which": "other", "label": "Other",
                     "count": len(oth), "open": expanded["other"],
                     "on": sum(1 for m in oth if m["name"] in selected)})
        if expanded["other"]:
            rows += [{"kind": "src", "meta": m, "indent": 1} for m in oth]
    if unavail:
        rows.append({"kind": "more", "which": "unavail", "label": "Unavailable",
                     "count": len(unavail), "open": expanded["unavail"], "on": 0})
        if expanded["unavail"]:
            rows += [{"kind": "unavail", "meta": m, "indent": 1} for m in unavail]
    return rows


def _row_text(row, is_cursor, selected):
    pointer = "❯" if is_cursor else " "
    kind = row["kind"]
    if kind == "more":
        tri = "▾" if row["open"] else "▸"
        tail = f" · {row['on']} on" if (not row["open"] and row["on"]) else ""
        return f" {pointer} {tri} {row['label']} ({row['count']}{tail})"
    m = row["meta"]
    pad = "  " * row["indent"]
    if kind == "unavail":  # read-only, dim, carries the why — no checkbox
        line = (f" {pointer} {pad}{m['name']} "
                f"({_geo_badge(m.get('tags'))}, {m['cost']}) — {m['reason']}")
        return _paint(line, "2")
    mark = "x" if m["name"] in selected else " "
    return (f" {pointer} {pad}[{mark}] {m['name']} "
            f"({_badge_colored(m.get('tags'))}, {m['cost']})")


def _render_menu(rows, selected, cursor, top, viewport):
    """One frame: title, a `viewport`-tall window of rows around the cursor,
    and a hint that carries a position readout only while windowed.
    """
    end = min(top + viewport, len(rows))
    lines = ["Sources:"]
    lines += [_row_text(rows[i], i == cursor, selected) for i in range(top, end)]
    hint = _MENU_HINT
    if len(rows) > viewport:
        hint += f"   [{cursor + 1}/{len(rows)}]"
    lines.append(hint)
    return "\n".join(lines)


def select_sources_tui(sources_meta, preselected, read_key, out=print,
                       recommended=None, viewport=1000):
    """Arrow-key checkbox menu: up/down move, space toggles, enter confirms.

    Pure over read_key/out — read_key() yields _decode_key tokens and out()
    renders a frame; the real terminal wiring lives in _interactive_select.
    Available sources split into a recommended section and a collapsed 'Other'
    (via the `recommended` name set; None keeps them all recommended);
    unavailable sources collapse under a read-only 'Unavailable' control.
    space or → works a collapse control; → is a no-op on a source row.
    `viewport` caps visible rows, windowing around the cursor for long lists.
    Returns the selection with recommended sources first, then Other.
    """
    if not sources_meta:
        return []
    avail = [m for m in sources_meta if m["available"]]
    unavail = [m for m in sources_meta if not m["available"]]
    if recommended is None:
        rec, oth = avail, []
    else:
        rec = [m for m in avail if m["name"] in recommended]
        oth = [m for m in avail if m["name"] not in recommended]
    order = rec + oth
    wanted = set(preselected)
    selected = {m["name"] for m in order if m["name"] in wanted}
    expanded = {"other": not rec, "unavail": False}
    cursor = 0
    top = 0
    rows = _menu_rows(rec, oth, unavail, expanded, selected)
    prev = 0

    def draw(first):
        nonlocal top, prev
        if cursor < top:
            top = cursor
        elif cursor >= top + viewport:
            top = cursor - viewport + 1
        top = max(0, min(top, max(0, len(rows) - viewport)))
        text = _render_menu(rows, selected, cursor, top, viewport)
        out(text if first else f"\x1b[{prev}A\x1b[J" + text)
        prev = text.count("\n") + 1

    draw(first=True)
    while True:
        key = read_key()
        if key == "enter":
            out("")  # drop below the menu block before run output
            return [m["name"] for m in order if m["name"] in selected]
        if key == "up":
            cursor = (cursor - 1) % len(rows)
        elif key == "down":
            cursor = (cursor + 1) % len(rows)
        elif key in ("space", "right"):
            row = rows[cursor]
            if row["kind"] == "more":
                expanded[row["which"]] = not expanded[row["which"]]  # space or →
            elif key == "space" and row["kind"] == "src":  # → is a no-op here
                name = row["meta"]["name"]
                selected.discard(name) if name in selected else selected.add(name)
        rows = _menu_rows(rec, oth, unavail, expanded, selected)
        cursor = min(cursor, len(rows) - 1)
        draw(first=False)


def _interactive():
    """True when a real TTY is on both ends and raw-mode is importable — the
    gate for the arrow-key menu. Pipes, CI, and Windows fall to the numbered one.
    """
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    try:
        import termios  # noqa: F401
        import tty  # noqa: F401
    except ImportError:
        return False
    return True


def _interactive_select(sources_meta, preselected, recommended):
    """Production wiring for select_sources_tui: cbreak + hidden cursor for the
    life of the menu, restored on exit; reads one key at a time from stdin. The
    visible window tracks terminal height so long source lists scroll.
    """
    import shutil
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    sys.stdout.write("\x1b[?25l")  # hide cursor
    sys.stdout.flush()
    try:
        tty.setcbreak(fd)
        viewport = max(8, shutil.get_terminal_size((80, 24)).lines - 4)
        return select_sources_tui(
            sources_meta, preselected,
            read_key=lambda: _decode_key(lambda: sys.stdin.read(1)),
            recommended=recommended, viewport=viewport,
        )
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\x1b[?25h")  # show cursor
        sys.stdout.flush()


def _default_selection(sources_meta, state, profile):
    """Consent-backed default: saved selection → profile sources.enabled
    (explicit config counts as consent, filtered to available) → available
    FREE sources only. A cost!="free" source never enters by mere availability.
    """
    saved = state.get("last_selection")
    if saved:
        return saved
    available = {m["name"] for m in sources_meta if m["available"]}
    enabled = [
        s for s in profile.get("sources", {}).get("enabled", []) if s in available
    ]
    if enabled:
        return enabled
    return [m["name"] for m in sources_meta
            if m["available"] and m["cost"] == "free"]


def _load_index():
    path = home() / "_index.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _print_summary(records, stats, shortlist_path):
    ranked = sorted(
        (r for r in records if r.get("tier") in ("A", "B")),
        key=lambda r: -int(r.get("fit", 0)),
    )[:10]
    if ranked:
        print(f"\n{'tier':<4} {'fit':>3}  {'company':<20} {'title':<32} comp")
        for r in ranked:
            print(
                f"{r['tier']:<4} {r['fit']:>3}  {r['company'][:20]:<20} "
                f"{r['title'][:32]:<32} {r['comp_display']}"
            )
    print(f"board: +{stats['added']} added / {stats['refreshed']} refreshed / "
          f"{stats['pruned']} pruned")
    print(f"SHORTLIST: {shortlist_path}")
    failed = sum(1 for r in records if r.get("analysis_failed"))
    if failed:
        print(f"failed analyses: {failed} (kept as tier C)")


def _source_help(mod):
    """Setup text for a source: its `HELP` constant, else the module docstring,
    else a default. Optional-by-construction — a plugin without HELP still
    resolves to usable text (mirrors the `bypass_lane` getattr precedent).
    """
    return (getattr(mod, "HELP", None)
            or (getattr(mod, "__doc__", None) or "").strip()
            or "No setup needed — works out of the box.")


def _sources_meta(modules=None):
    """Status row per registered source: {name, cost, available, reason, tags}.

    Shared by `_run` (menu/consent) and `yoke sources` (doctor report); calls
    each plugin's available() but nothing that fetches or spends. `modules`
    lets a caller pass an already-loaded plugin list to avoid a second load.
    """
    meta = []
    for mod in (modules if modules is not None else collect.load_sources()):
        ok, reason = mod.available()
        meta.append(
            {"name": mod.NAME, "cost": mod.COST, "available": bool(ok),
             "reason": reason, "tags": mod.TAGS}
        )
    return meta


def _source_json(row, enabled, count):
    """Stable machine shape for one source (agent-facing contract). `enabled` is
    bool|None (None = no profile), `count` is int|None (None = absent last run).
    """
    return {
        "name": row["name"],
        "geo": (row.get("tags") or {}).get("country") or "any",  # mirror _geo_badge
        "cost": row["cost"],
        "available": bool(row["available"]),
        "reason": row["reason"],
        "enabled": enabled,
        "roles_last_run": count,
    }


def _render_sources_report(meta, enabled_names, counts, recommended, use_color=False):
    """Doctor report: Available (recommended-first) then Unavailable. Available
    rows carry enabled-state + roles-last-run; unavailable rows carry the reason.
    `enabled_names` None → enabled column shows '—'. Color gated on use_color so
    piped/agent output stays clean.
    """
    width = max((len(m["name"]) for m in meta), default=0)
    avail = [m for m in meta if m["available"]]
    unavail = [m for m in meta if not m["available"]]
    avail.sort(key=lambda m: m["name"] not in recommended)  # recommended first, stable

    def paint(text, code):
        return _paint(text, code) if use_color else text

    lines = ["Sources", ""]
    if avail:
        lines.append("Available")
        for m in avail:
            nm = m["name"]
            if enabled_names is None:
                en = "—"
            else:
                en = "enabled" if nm in enabled_names else "disabled"
            roles = f"{counts[nm]} roles last run" if nm in counts else "—"
            lines.append(
                f"  {nm:<{width}}  {_geo_badge(m.get('tags')):<6}  "
                f"{m['cost']:<4}  {paint('✓', '32')}  {en:<8}  {roles}"
            )
    if unavail:
        lines.append("Unavailable")
        for m in unavail:
            nm = m["name"]
            lines.append(
                f"  {nm:<{width}}  {_geo_badge(m.get('tags')):<6}  "
                f"{m['cost']:<4}  {paint('✗', '31')}  {m['reason']}"
            )
    lines += ["", "→ yoke sources <name> for setup"]
    return "\n".join(lines)


def _render_source_page(row, help_text, use_color=False):
    """One source's setup page: a live status line + its HELP body."""
    def paint(text, code):
        return _paint(text, code) if use_color else text

    if row["available"]:
        status = f"{paint('✓', '32')} available"
    else:
        status = f"{paint('✗', '31')} {row['reason']}"
    return f"{row['name']} — {status}\n\n{help_text}"


def _cmd_sources(name, as_json):
    """`yoke sources` (report) / `yoke sources <name>` (setup page). Read-only,
    profile-optional (degrades to enabled='—' when no profile), agent-facing
    via --json. Unknown name → stderr + exit 2.
    """
    modules = collect.load_sources()
    meta = _sources_meta(modules)
    try:
        profile = load_profile()
    except ProfileError:
        profile = None
    enabled = set(profile.get("sources", {}).get("enabled", [])) if profile else None
    recommended = (_recommended_names(meta, profile.get("countries", []))
                   if profile else set())
    counts = _last_run_counts()

    def enabled_of(nm):
        return None if enabled is None else (nm in enabled)

    if name is not None:
        row = next((m for m in meta if m["name"] == name), None)
        if row is None:
            print(f"unknown source: {name}", file=sys.stderr)
            return 2
        mod = next(m for m in modules if m.NAME == name)
        help_text = _source_help(mod)
        if as_json:
            obj = _source_json(row, enabled_of(name), counts.get(name))
            obj["help"] = help_text
            print(json.dumps(obj))
        else:
            print(_render_source_page(row, help_text, use_color=sys.stdout.isatty()))
        return 0

    if as_json:
        print(json.dumps({"sources": [
            _source_json(m, enabled_of(m["name"]), counts.get(m["name"])) for m in meta
        ]}))
    else:
        print(_render_sources_report(meta, enabled, counts, recommended,
                                     use_color=sys.stdout.isatty()))
    return 0


def _cmd_eval(record, as_json):
    """`yoke eval` scores frozen model outputs vs the golden set (zero model
    calls); `yoke eval --record` first runs the current backend over the golden
    roles (the only model op). Missing golden / run → stderr + exit 2.
    """
    golden = eval.load_golden()
    if not golden:
        print("no golden set: create $YOKE_HOME/_golden.json", file=sys.stderr)
        return 2
    if record:
        log = (lambda *a: None) if as_json else print  # keep --json output clean
        run = eval.record(golden, llm.get_backend(), log)
        if as_json:
            print(json.dumps({"recorded": len(run["roles"]), "backend": run["backend"]}))
        else:
            print(f"recorded {len(run['roles'])} roles via {run['backend']} → _eval_run.json")
        return 0
    run_path = home() / eval.EVAL_RUN_FILE
    if not run_path.is_file():
        print("no eval run: `yoke eval --record` first", file=sys.stderr)
        return 2
    try:
        run = json.loads(run_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("eval run file is unreadable: re-run `yoke eval --record`", file=sys.stderr)
        return 2
    card = eval.score(run, golden)
    if as_json:
        print(json.dumps(eval.scorecard_json(card)))
    else:
        print(eval.render_scorecard(card, use_color=sys.stdout.isatty()))
    return 0


def _cmd_tune(as_json):
    """`yoke tune` refits additive weights to apply/drop labels and PROPOSES
    (diff + _tuned_weights.json); never mutates profile.yml. Zero model calls.
    """
    scoring_cfg = load_profile().get("scoring", {})
    weights = {f["name"]: f["weight"]
               for f in scoring_cfg.get("features", []) + scoring_cfg.get("deterministic", [])}
    pairs = []
    for rec in labels.load_labels():
        if rec.get("label") not in ("applied", "dropped"):
            continue
        scores = {n: fv.get("score", 0)
                  for n, fv in (rec.get("features") or {}).items()
                  if isinstance(fv, dict)}
        if scores:  # feature-less labels can't inform the additive fit — skip them
            pairs.append((scores, rec["label"]))
    result = tune.refit(pairs, weights)
    tune.write_proposal(result)
    if as_json:
        print(json.dumps(tune.proposal_json(result)))
    else:
        print(tune.render_proposal(result, use_color=sys.stdout.isatty()))
    return 0


def _run(args, input_fn):
    profile = load_profile()
    state = load_state()

    sources_meta = _sources_meta()
    if args.sources:
        selected = [s.strip() for s in args.sources.split(",") if s.strip()]
    elif args.yes:
        selected = _default_selection(sources_meta, state, profile)
    else:
        default = _default_selection(sources_meta, state, profile)
        if _interactive():
            recommended = _recommended_names(sources_meta, profile.get("countries", []))
            try:
                selected = _interactive_select(sources_meta, default, recommended)
            except KeyboardInterrupt:
                print("\ncancelled — nothing fetched")
                return 130
        else:
            selected = select_sources(sources_meta, default, input_fn)

    print("Collecting:")
    collect.run_collect(profile, selected, print)
    if args.dry_run:
        print("dry run — stopped after collect")
        return 0

    cards = prepare.build_cards(profile, _load_index(), state)
    # Only in-window cards may reach analyze/board: out-of-window roles keep
    # their earlier board records instead of being re-emitted as C/0 skeletons.
    in_window = [c for c in cards if c.get("in_window")]
    needy = [c for c in in_window if c.get("needs_ai")]
    if not needy:
        print("nothing new in window")
        return 0

    feature_names = [f["name"] for f in profile.get("scoring", {}).get("features", [])]
    backend = MockBackend(feature_names) if args.mock else llm.get_backend()

    if not args.yes:
        answer = input_fn(
            f"{len(needy)} new roles → analyze via {backend.describe()} — "
            "free on subscription / est if metered. Proceed? [Y/n] "
        )
        if (answer or "").strip().lower().startswith("n"):
            print("analysis declined — nothing spent")
            return 0

    records = analyze.analyze_cards(in_window, profile, backend, print)
    stats = board.upsert(records)
    shortlist_path = board.render(profile)
    _print_summary(records, stats, shortlist_path)

    state["last_run"] = datetime.now(timezone.utc).isoformat()
    state["last_selection"] = selected
    save_state(state)
    return 0


def _cmd_board():
    path = board.render(load_profile())
    print(path.read_text(encoding="utf-8"))
    return 0


def _cmd_apply(match):
    removed = board.mark_applied(match)
    if removed:
        print(f"applied — removed from board: {', '.join(removed)}")
    else:
        print(f"applied — no board hit, '{match}' ledgered so it never resurfaces")
    return 0


def _cmd_drop(match, reason):
    removed = board.drop(match, reason)
    if removed:
        print(f"dropped: {', '.join(removed)}")
    else:
        print(f"no board role matches '{match}'")
    return 0


def _last_run_counts():
    """Per-source role counts from the newest scan snapshot, grouped by `source`.

    The count is the post-gate matched slice that actually landed that run — a
    source absent from the last run has no entry (caller renders it as '—', not
    0). Missing/empty/malformed scans degrade to {} without raising.
    """
    scans = sorted((home() / "scans").glob("*.json"))
    if not scans:
        return {}
    try:
        jobs = json.loads(scans[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(jobs, list):  # a hand-/agent-written file need not be a job list
        return {}
    counts = {}
    for j in jobs:
        src = j.get("source") if isinstance(j, dict) else None
        if src:
            counts[src] = counts.get(src, 0) + 1
    return counts


def _subcommands(parser):
    """(name, help) for every registered subcommand, read off the built parser
    so `yoke help` can never drift from what argparse actually accepts.

    Couples to argparse internals (`_SubParsersAction`, `_choices_actions`) —
    the conventional stdlib-only idiom; if that private shape is ever renamed
    this raises rather than degrading, but the alternative is a hand-kept list
    that silently drifts.
    """
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return [(a.dest, a.help or "") for a in action._choices_actions]
    return []


def _render_help(commands):
    """Aligned `name  purpose` list — the command surface an agent reads to
    discover what Yoke can do. `yoke <command> -h` still owns per-command flags.
    """
    width = max((len(n) for n, _ in commands), default=0)
    lines = ["Yoke — job-search harness. Commands:", ""]
    lines += [f"  {n:<{width}}  {h}" for n, h in commands]
    lines += ["", "Run `yoke <command> -h` for flags."]
    return "\n".join(lines)


def _cmd_help(parser):
    print(_render_help(_subcommands(parser)))
    return 0


def _build_parser():
    p = argparse.ArgumentParser(prog="yoke", description="job scan → scored shortlist")
    sub = p.add_subparsers(dest="cmd")

    run = sub.add_parser("run", help="collect → prepare → analyze → board (default)")
    run.add_argument("--yes", action="store_true",
                     help="skip menu and consent; reuse remembered selection")
    run.add_argument("--dry-run", action="store_true", help="stop after collect")
    run.add_argument("--mock", action="store_true",
                     help="deterministic fake analysis, no model call")
    run.add_argument("--sources", default=None, help="comma-separated source names")

    sub.add_parser("board", help="re-render and print the shortlist")
    ap = sub.add_parser("apply", help="mark a role applied (prunes reposts too)")
    ap.add_argument("match")
    dr = sub.add_parser("drop", help="remove a role from the board")
    dr.add_argument("match")
    dr.add_argument("--reason", default=None)

    srcp = sub.add_parser("sources", help="show source status + setup pages")
    srcp.add_argument("name", nargs="?", default=None,
                      help="show one source's setup page")
    srcp.add_argument("--json", action="store_true", help="machine-readable output")
    sub.add_parser("help", help="list all commands and what they do")

    evp = sub.add_parser("eval", help="score the model vs the frozen golden set")
    evp.add_argument("--record", action="store_true",
                     help="run the current model over the golden set first")
    evp.add_argument("--json", action="store_true", help="machine-readable output")
    tnp = sub.add_parser("tune", help="propose refit weights from apply/drop labels")
    tnp.add_argument("--json", action="store_true", help="machine-readable output")
    return p


def main(argv=None, input_fn=input):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in COMMANDS:
        argv.insert(0, "run")  # `yoke --yes` == `yoke run --yes`
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "run":
            return _run(args, input_fn)
        if args.cmd == "help":
            return _cmd_help(parser)
        if args.cmd == "sources":
            return _cmd_sources(args.name, args.json)
        if args.cmd == "eval":
            return _cmd_eval(args.record, args.json)
        if args.cmd == "tune":
            return _cmd_tune(args.json)
        if args.cmd == "board":
            return _cmd_board()
        if args.cmd == "apply":
            return _cmd_apply(args.match)
        return _cmd_drop(args.match, args.reason)
    except ProfileError as e:
        print(f"profile error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

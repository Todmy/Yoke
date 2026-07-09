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

from src import analyze, board, collect, llm, prepare
from src.paths import ProfileError, home, load_profile, load_state, save_state

COMMANDS = ("run", "board", "apply", "drop")


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


def _menu_rows(rec, oth, expanded, selected):
    """Flat navigable-row model: recommended sources, then an 'Other (N)'
    control that reveals the rest when expanded. Every row is a cursor stop.
    """
    rows = [{"kind": "src", "meta": m, "indent": 0} for m in rec]
    if oth:
        on = sum(1 for m in oth if m["name"] in selected)
        rows.append({"kind": "more", "count": len(oth), "on": on})
        if expanded:
            rows += [{"kind": "src", "meta": m, "indent": 1} for m in oth]
    return rows


def _row_text(row, is_cursor, selected, expanded):
    pointer = "❯" if is_cursor else " "
    if row["kind"] == "more":
        tri = "▾" if expanded else "▸"
        tail = f" · {row['on']} on" if (not expanded and row["on"]) else ""
        return f" {pointer} {tri} Other ({row['count']}{tail})"
    m = row["meta"]
    mark = "x" if m["name"] in selected else " "
    status = "available" if m["available"] else f"unavailable: {m['reason']}"
    return (f" {pointer} {'  ' * row['indent']}[{mark}] "
            f"{m['name']} ({m['cost']}, {status})")


def _render_menu(rows, selected, cursor, top, viewport, expanded):
    """One frame: title, a `viewport`-tall window of rows around the cursor,
    and a hint that carries a position readout only while windowed.
    """
    end = min(top + viewport, len(rows))
    lines = ["Sources:"]
    lines += [_row_text(rows[i], i == cursor, selected, expanded)
              for i in range(top, end)]
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
    `recommended` (a set of names) splits the list into a recommended section
    and a collapsed 'Other'; None keeps every source recommended (flat list).
    `viewport` caps visible rows, windowing around the cursor for long lists.
    Unavailable sources cannot be enabled; returns the selection with
    recommended sources first, then Other, each in menu order.
    """
    if not sources_meta:
        return []
    if recommended is None:
        rec, oth = list(sources_meta), []
    else:
        rec = [m for m in sources_meta if m["name"] in recommended]
        oth = [m for m in sources_meta if m["name"] not in recommended]
    order = rec + oth
    wanted = set(preselected)
    selected = {m["name"] for m in order if m["available"] and m["name"] in wanted}
    expanded = not rec  # nothing recommended → open Other so the list isn't empty
    cursor = 0
    top = 0
    rows = _menu_rows(rec, oth, expanded, selected)
    prev = 0

    def draw(first):
        nonlocal top, prev
        if cursor < top:
            top = cursor
        elif cursor >= top + viewport:
            top = cursor - viewport + 1
        top = max(0, min(top, max(0, len(rows) - viewport)))
        text = _render_menu(rows, selected, cursor, top, viewport, expanded)
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
                expanded = not expanded  # space or → works the collapse control
            elif key == "space":  # → is a no-op on a source row; space toggles it
                m = row["meta"]
                if m["name"] in selected:
                    selected.discard(m["name"])
                elif m["available"]:
                    selected.add(m["name"])
        rows = _menu_rows(rec, oth, expanded, selected)
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


def _run(args, input_fn):
    profile = load_profile()
    state = load_state()

    sources_meta = []
    for mod in collect.load_sources():
        ok, reason = mod.available()
        sources_meta.append(
            {"name": mod.NAME, "cost": mod.COST, "available": bool(ok),
             "reason": reason, "tags": mod.TAGS}
        )
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
    return p


def main(argv=None, input_fn=input):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in COMMANDS:
        argv.insert(0, "run")  # `yoke --yes` == `yoke run --yes`
    args = _build_parser().parse_args(argv)
    try:
        if args.cmd == "run":
            return _run(args, input_fn)
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

#!/usr/bin/env python3
"""Persistent job-search shortlist board.

Single source of truth = ~/PBaaS/job-scans/board.json (structured, machine-owned).
Human view      = ~/PBaaS/personal/job-search/SHORTLIST.md (rendered, read-only).
Dedup ledger    = ~/PBaaS/job-scans/.review-state.json (applied[] is authoritative).

The board ACCUMULATES qualifying roles across /jobsearch runs (each carries a
date_added so old vs new is visible) and SELF-PRUNES: any role whose key or
role_key lands in applied[] is removed on the next sync, so an applied role can
never resurface and can't be applied to twice.

Subcommands:
  add      < roles.json     # merge new roles (stdin = JSON list), then sync+render
  apply    <substr|key> ... # mark matching roles applied, prune, render (works
                            #   even if the role isn't on the board: records the
                            #   key in applied[] so /jobsearch won't resurface it)
  drop     <substr|key> ... # remove roles; add --reason <tag> to log a REJECTION
                            #   label (off-lane/geo/comp/...) for the flywheel;
                            #   without --reason = silent drop (dead/filled posting)
  sync-folders              # derive labels from application folders (STATUS.md):
                            #   APPLIED/SENT/SUBMITTED -> applied; APPLY...TODO -> draft
  render                    # re-render SHORTLIST.md from board.json
  sync                      # prune applied roles from board, then render
  list                      # print current board (debug)

A role dict: {key, role_key, company, title, url, fit, label, geo, comp,
              lane, note, tier, date_added}
key = canonical URL. role_key = "company|normalized title" (repost-proof).
"""
import json
import re
import sys
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store  # canonical SQLite store (board roles + decision labels)
from paths import STATE, SHORTLIST, APPS_DIR as JOBSEARCH_DIR  # noqa: E402

# decision labels (apply from a folder / reject from drop --reason) live in the
# SQLite store (store.record_decision) — the flywheel's ground-truth signal.
# Application folders under APPS_DIR are the apply signal; nothing to skip there.
_SKIP_DIRS = {"__pycache__"}
# completed-submission markers in a STATUS.md timeline (vs the template "APPLY ... via TODO")
_DONE_RE = re.compile(r"\b(APPLIED|SUBMITTED|EMAIL SENT|FORM SUBMITTED|SENT)\b")


def _today():
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def load_board():
    return store.load()  # canonical store = jobsearch.db (migrates board.json on first run)


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"last_review": None, "reviewed": [], "applied": []}


def save_board(b):
    store.save(b)


def save_state(st):
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2))


def _applied_set(st):
    return set(st.get("applied", []))


def prune_applied(b, st):
    """Drop any board role already in applied[] (by key OR role_key)."""
    applied = _applied_set(st)
    kept, dropped = [], []
    for r in b["roles"]:
        if r.get("key") in applied or r.get("role_key") in applied:
            dropped.append(r)
        else:
            kept.append(r)
    b["roles"] = kept
    return dropped


_TIER_ORDER = {"A": 0, "B": 1, "C": 2}


def render(b):
    roles = sorted(
        b["roles"],
        key=lambda r: (_TIER_ORDER.get(r.get("tier", "B"), 1), -int(r.get("fit", 0))),
    )
    today = _today()
    lines = [
        "# Job-search shortlist — live board",
        "",
        f"_Оновлено: {b.get('updated', '')[:10]} · {len(roles)} живих ролей · "
        "накопичується щопрогону `/jobsearch`, зникає на apply._",
        "",
        "**Як читати:** `Added` = коли роль зайшла на дошку (старі внизу свого тіру — "
        "якщо сидить давно і не подався, це сигнал). Подався → роль зникає звідси назавжди.",
        "",
    ]
    for tier, header in (("A", "## Tier A — подавати"), ("B", "## Tier B — варто глянути"), ("C", "## Tier C")):
        chunk = [r for r in roles if r.get("tier") == tier]
        if not chunk:
            continue
        lines += [header, ""]
        lines.append("| Added | Fit | Geo | Роль | Компанія | Comp net/mo | Нюанс | URL |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in chunk:
            age = ""
            try:
                d = datetime.date.fromisoformat(r.get("date_added", today))
                days = (datetime.date.fromisoformat(today) - d).days
                age = f" ({days}d)" if days > 0 else " (new)"
            except Exception:
                pass
            lines.append(
                f"| {r.get('date_added','')}{age} | {r.get('fit','')} {r.get('label','')} | "
                f"{r.get('geo','')} | {r.get('title','')} | {r.get('company','')} | "
                f"{r.get('comp','')} | {r.get('note','')} | {r.get('url','')} |"
            )
        lines.append("")
    log = b.get("applied_log", [])
    if log:
        lines += ["---", "", "## Подано (не подаватися повторно)", ""]
        lines.append("| Дата | Роль | Компанія |")
        lines.append("|---|---|---|")
        for e in log[-30:]:
            lines.append(f"| {e.get('date','')} | {e.get('title','')} | {e.get('company','')} |")
        lines.append("")
    SHORTLIST.write_text("\n".join(lines))


def cmd_sync():
    b, st = load_board(), load_state()
    dropped = prune_applied(b, st)
    save_board(b)
    render(b)
    print(f"sync: {len(b['roles'])} live, pruned {len(dropped)} applied")


def cmd_render():
    b = load_board()
    render(b)
    print(f"render: {len(b['roles'])} roles -> {SHORTLIST}")


def cmd_add():
    """stdin = JSON list of role dicts. Merge (dedup by key/role_key vs board+applied)."""
    payload = json.loads(sys.stdin.read())
    if isinstance(payload, dict):
        payload = payload.get("roles", [])
    b, st = load_board(), load_state()
    applied = _applied_set(st)
    by_key = {r.get("key"): r for r in b["roles"]}
    by_rk = {r.get("role_key"): r for r in b["roles"] if r.get("role_key")}
    added, refreshed, skipped = 0, 0, 0
    for r in payload:
        k, rk = r.get("key"), r.get("role_key")
        if k in applied or rk in applied:
            skipped += 1
            continue
        existing = by_key.get(k) or (by_rk.get(rk) if rk else None)
        if existing:  # refresh mutable fields, keep original date_added
            for f in ("fit", "label", "geo", "comp", "lane", "note", "tier", "title", "company", "url"):
                if r.get(f) not in (None, ""):
                    existing[f] = r[f]
            refreshed += 1
        else:
            r.setdefault("date_added", _today())
            b["roles"].append(r)
            by_key[k] = r
            if rk:
                by_rk[rk] = r
            added += 1
    prune_applied(b, st)
    save_board(b)
    render(b)
    print(f"add: +{added} new, ~{refreshed} refreshed, {skipped} skipped (already applied), "
          f"{len(b['roles'])} live")


def cmd_apply(args):
    """Mark board roles matching any arg (substring of key/url/company/title OR exact key) as applied."""
    if not args:
        print("usage: board.py apply <substr|key> ...", file=sys.stderr)
        sys.exit(1)
    b, st = load_board(), load_state()
    needles = [a.lower() for a in args]
    hit = []
    for r in list(b["roles"]):
        hay = " ".join(str(r.get(f, "")) for f in ("key", "url", "company", "title", "role_key")).lower()
        if any(n in hay for n in needles):
            hit.append(r)
    applied = set(st.get("applied", []))
    if not hit:
        # Applied straight from analysis (not on the board) — still record so
        # /jobsearch and the board dedup it forever. Use the raw args as keys.
        for a in args:
            applied.add(a)
            b.setdefault("applied_log", []).append(
                {"date": _today(), "company": "(off-board)", "title": a, "key": a}
            )
        st["applied"] = sorted(applied)
        save_state(st)
        prune_applied(b, st)
        save_board(b)
        render(b)
        print(f"apply: no role was on the board — recorded {len(args)} key(s) in applied[] anyway "
              "(so /jobsearch won't resurface them). Pass the exact URL if you want clean dedup.")
        return
    for r in hit:
        for kk in (r.get("key"), r.get("role_key")):
            if kk:
                applied.add(kk)
        b.setdefault("applied_log", []).append(
            {"date": _today(), "company": r.get("company"), "title": r.get("title"), "key": r.get("key")}
        )
    st["applied"] = sorted(applied)
    save_state(st)
    prune_applied(b, st)
    save_board(b)
    render(b)
    print("applied + pruned:")
    for r in hit:
        print(f"  ✓ {r.get('company')} | {r.get('title')}")
    print(f"{len(b['roles'])} live remain")


# ── self-improvement flywheel: labels from real decisions ────────────────────
def _raw_feats(role):
    """Raw model features for a label (what tune.py needs), parsing the role's
    features JSON; falls back to the output snapshot for legacy roles."""
    if not role:
        return None
    raw = role.get("features")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    if isinstance(raw, dict):
        return raw
    return {k: role.get(k) for k in ("fit", "label", "geo", "comp", "lane", "tier")}


def _role_key(company, title):
    """Match job-scan.py's role_key normalization (company|normalized-title)."""
    t = re.sub(r"[^a-z0-9 ]", "", (title or "").lower())
    t = re.sub(r"\s+", " ", t).strip()
    return f"{(company or '').lower()}|{t}"


def _status_field(text, name):
    m = re.search(rf"^- \*\*{name}\*\*:\s*(.+)$", text, re.M)
    if not m:
        return ""
    return re.sub(r"\s*\(.*", "", m.group(1)).strip()  # drop trailing "(...)"


def _parse_status(path):
    try:
        t = path.read_text()
    except OSError:
        return None
    company, title = _status_field(t, "Company"), _status_field(t, "Title")
    # only timeline rows count for the done-marker (avoid matching the role header)
    timeline = t.split("## Timeline", 1)[-1]
    decision = "applied" if _DONE_RE.search(timeline) else "interested"
    return {"company": company, "title": title, "decision": decision}


def write_label(rec):
    """Record an ML label in the store; idempotent on (slug, role_key, decision)."""
    return store.record_decision(rec)


def cmd_sync_folders():
    """Derive labels from application folders: STATUS.md 'APPLIED/SENT/SUBMITTED'
    -> applied (strong+); template 'APPLY...TODO' -> interested/draft (weak+).
    Applied folders are also promoted to applied[] + pruned off the board."""
    b, st = load_board(), load_state()
    applied = set(st.get("applied", []))
    by_rk = {r.get("role_key"): r for r in b["roles"] if r.get("role_key")}
    n_app = n_int = n_new = 0
    for d in sorted(p for p in JOBSEARCH_DIR.iterdir() if p.is_dir() and p.name not in _SKIP_DIRS):
        status = d / "STATUS.md"
        if not status.exists():
            continue
        info = _parse_status(status)
        if not info:
            continue
        company, title = info["company"], info["title"]
        rk = _role_key(company, title) if (company and title and "TODO" not in company) else None
        role = by_rk.get(rk) if rk else None
        feats = _raw_feats(role)
        if write_label({"date": _today(), "slug": d.name, "company": company, "title": title,
                        "decision": info["decision"], "reason": "", "role_key": rk,
                        "features": feats, "source": "folder"}):
            n_new += 1
        if info["decision"] == "applied":
            n_app += 1
            if rk:
                applied.add(rk)
            if role:
                b["roles"] = [r for r in b["roles"] if r.get("role_key") != rk]
                b.setdefault("applied_log", []).append(
                    {"date": _today(), "company": company, "title": title, "key": role.get("key")})
        else:
            n_int += 1
    st["applied"] = sorted(applied)
    save_state(st)
    save_board(b)
    render(b)
    print(f"sync-folders: {n_app} applied, {n_int} interested/draft  "
          f"({n_new} new labels -> labels.jsonl, {len(b['roles'])} live on board)")


def cmd_drop(args):
    """Remove board roles matching any arg WITHOUT marking applied (dead/filled),
    OR record a rejection with a reason for the flywheel: --reason <tag>."""
    reason = ""
    if "--reason" in args:
        i = args.index("--reason")
        reason = args[i + 1] if i + 1 < len(args) else ""
        args = args[:i] + args[i + 2:]
    if not args:
        print("usage: board.py drop <substr|key> ... [--reason off-lane|geo|comp|not-interesting]", file=sys.stderr)
        sys.exit(1)
    b = load_board()
    needles = [a.lower() for a in args]
    kept, dropped = [], []
    for r in b["roles"]:
        hay = " ".join(str(r.get(f, "")) for f in ("key", "url", "company", "title", "role_key")).lower()
        (dropped if any(n in hay for n in needles) else kept).append(r)
    if not dropped:
        print(f"drop: no board role matched {args}", file=sys.stderr)
        sys.exit(2)
    b["roles"] = kept
    save_board(b)
    render(b)
    tag = f"rejected ({reason})" if reason else "dropped (dead/filled, no label)"
    print(f"{tag}:")
    for r in dropped:
        if reason:  # negative training example
            write_label({"date": _today(), "slug": None, "company": r.get("company"),
                         "title": r.get("title"), "decision": "rejected", "reason": reason,
                         "role_key": r.get("role_key"), "features": _raw_feats(r),
                         "source": "drop"})
        print(f"  ✗ {r.get('company')} | {r.get('title')}")
    print(f"{len(b['roles'])} live remain" + (f"  (+{len(dropped)} rejected labels)" if reason else ""))


def cmd_list():
    b = load_board()
    for r in sorted(b["roles"], key=lambda r: (_TIER_ORDER.get(r.get("tier", "B"), 1), -int(r.get("fit", 0)))):
        print(f"[{r.get('tier')}] {r.get('fit')} {r.get('geo')} | {r.get('company')} | {r.get('title')} | {r.get('key')}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "render"
    if cmd == "add":
        cmd_add()
    elif cmd == "apply":
        cmd_apply(sys.argv[2:])
    elif cmd == "drop":
        cmd_drop(sys.argv[2:])
    elif cmd == "sync-folders":
        cmd_sync_folders()
    elif cmd == "render":
        cmd_render()
    elif cmd == "sync":
        cmd_sync()
    elif cmd == "list":
        cmd_list()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()

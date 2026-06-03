#!/usr/bin/env python3
"""SQLite store — canonical home for the Yoke board + decision labels.

Holds live roles, the applied log, decision labels (the self-improvement signal),
and the tunable fit weights. board.py is a thin CLI over this; analyze.py feeds
roles in via `board.py add`; the local web UI reads/writes here too. The index
dedup ledger (review-state.json) stays a file — a different concern.

Single source of truth, WAL mode for concurrent cron + UI access, stdlib only
(sqlite3) so it stays cross-platform and zero-dependency. Data lives under
$YOKE_HOME (see paths.py), never in the repo.

Public API (used by board.py):
  load() -> {"roles":[...], "applied_log":[...]}
  save(b)                                          # upsert live roles + applied_log
  record_decision(rec) -> bool                     # ML label; idempotent
  label_counts() -> {"applied","interested","rejected","with_features","both_classes"}
"""
import json
import sqlite3
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import DB, ensure_home  # noqa: E402

ROLE_COLS = ["role_key", "key", "company", "title", "url", "fit", "label",
             "geo", "comp", "lane", "note", "tier", "date_added", "features"]

# fit-formula weights — externalized so the Improve tuner can refit them to the
# user's real decisions. score_fit (analyze.py), eval.py and tune.py read these.
DEFAULT_WEIGHTS = {"lane_in": 50, "lane_adjacent": 30, "diff_per_hit": 7, "diff_cap": 5,
                   "seniority_ok": 10, "seniority_no": -5, "lang_ok": 5, "lang_no": -20,
                   "emp_no": -20}


def _conn():
    ensure_home()
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    _init(c)
    return c


def _init(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS roles(
      role_key TEXT PRIMARY KEY, key TEXT, company TEXT, title TEXT, url TEXT,
      fit INTEGER, label TEXT, geo TEXT, comp TEXT, lane TEXT, note TEXT,
      tier TEXT, date_added TEXT, features TEXT, status TEXT DEFAULT 'live');
    CREATE TABLE IF NOT EXISTS applied_log(
      id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, company TEXT, title TEXT, key TEXT);
    CREATE TABLE IF NOT EXISTS decisions(
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, slug TEXT, role_key TEXT,
      company TEXT, title TEXT, decision TEXT, reason TEXT, comment TEXT,
      features TEXT, source TEXT, status TEXT, status_note TEXT, updated TEXT, url TEXT);
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
    """)
    rcols = [r[1] for r in c.execute("PRAGMA table_info(roles)").fetchall()]
    if "features" not in rcols:
        c.execute("ALTER TABLE roles ADD COLUMN features TEXT")
    # application-tracking columns on decisions (added after first ship)
    dcols = [r[1] for r in c.execute("PRAGMA table_info(decisions)").fetchall()]
    for col in ("status", "status_note", "updated", "url", "resume"):
        if col not in dcols:
            c.execute(f"ALTER TABLE decisions ADD COLUMN {col} TEXT")
    c.commit()


# application pipeline (Applied tab)
APP_STATUSES = ["applied", "screening", "interview", "offer", "accepted", "rejected", "ghosted"]


def get_weights():
    c = _conn()
    row = c.execute("SELECT value FROM meta WHERE key='fit_weights'").fetchone()
    c.close()
    w = dict(DEFAULT_WEIGHTS)
    if row:
        try:
            w.update(json.loads(row["value"]))
        except json.JSONDecodeError:
            pass
    return w


def set_weights(w):
    c = _conn()
    c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('fit_weights',?)",
              (json.dumps(w), ))
    c.commit()
    c.close()


def get_meta(key, default=None):
    """Generic JSON-valued meta read (e.g. the tuner gate thresholds)."""
    c = _conn()
    row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    c.close()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return default


def _upsert_role(c, r, status="live"):
    vals = [r.get(col) for col in ROLE_COLS] + [status]
    ph = ",".join("?" * (len(ROLE_COLS) + 1))
    c.execute(f"INSERT OR REPLACE INTO roles({','.join(ROLE_COLS)},status) VALUES({ph})", vals)


# ── public API ───────────────────────────────────────────────────────────────
def load():
    c = _conn()
    roles = [dict(row) for row in c.execute(
        "SELECT * FROM roles WHERE status='live'").fetchall()]
    for r in roles:
        r.pop("status", None)
    log = [{"date": row["date"], "company": row["company"], "title": row["title"], "key": row["key"]}
           for row in c.execute("SELECT * FROM applied_log ORDER BY date").fetchall()]
    c.close()
    return {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "roles": roles, "applied_log": log}


def save(b):
    """Replace the live role set with b['roles']; sync applied_log."""
    c = _conn()
    c.execute("DELETE FROM roles WHERE status='live'")
    for r in b.get("roles", []):
        _upsert_role(c, r, status="live")
    c.execute("DELETE FROM applied_log")
    for e in b.get("applied_log", []):
        c.execute("INSERT INTO applied_log(date,company,title,key) VALUES(?,?,?,?)",
                  (e.get("date"), e.get("company"), e.get("title"), e.get("key")))
    c.commit()
    c.close()


def record_decision(rec):
    """Insert an ML label; idempotent on (slug, role_key, decision)."""
    c = _conn()
    dup = c.execute("""SELECT 1 FROM decisions WHERE
                       IFNULL(slug,'')=IFNULL(?,'') AND IFNULL(role_key,'')=IFNULL(?,'')
                       AND decision=?""",
                    (rec.get("slug"), rec.get("role_key"), rec.get("decision"))).fetchone()
    if dup:
        c.close()
        return False
    c.execute("""INSERT INTO decisions(ts,slug,role_key,company,title,decision,reason,
                 comment,features,source) VALUES(?,?,?,?,?,?,?,?,?,?)""",
              (rec.get("date") or datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
               rec.get("slug"), rec.get("role_key"), rec.get("company"), rec.get("title"),
               rec.get("decision"), rec.get("reason", ""), rec.get("comment", ""),
               json.dumps(rec.get("features")), rec.get("source")))
    c.commit()
    c.close()
    return True


def get_role(role_key):
    """Fetch a single role (any status) as a dict, or None."""
    c = _conn()
    row = c.execute("SELECT * FROM roles WHERE role_key=?", (role_key,)).fetchone()
    c.close()
    return dict(row) if row else None


def star(role_key):
    """Flag a board role as 'interested' — a bookmark that STAYS on the live board
    (the user filters to it later, not a separate list). Recorded in the decisions
    registry so it survives re-runs; never a tuner positive. Idempotent.
    Returns True if newly starred."""
    r = get_role(role_key) or {}
    return record_decision({"role_key": role_key, "company": r.get("company"),
                            "title": r.get("title"), "decision": "interested", "source": "ui"})


def unstar(role_key):
    """Remove the 'interested' bookmark. Returns True if something was removed."""
    c = _conn()
    n = c.execute("DELETE FROM decisions WHERE IFNULL(role_key,'')=? AND decision='interested'",
                  (role_key or "",)).rowcount
    c.commit()
    c.close()
    return n > 0


def starred_keys():
    """Set of role_keys currently bookmarked 'interested' — used to flag + filter the board."""
    c = _conn()
    rows = c.execute("SELECT DISTINCT role_key FROM decisions WHERE decision='interested'").fetchall()
    c.close()
    return {r["role_key"] for r in rows}


def mark(role_key, decision, reason="", comment="", source="ui", resume=""):
    """Record a decision on a board role + move it off the live board.
    decision: applied | rejected (interested is a stay-on-board bookmark — see star()).
    Returns the role dict or None."""
    c = _conn()
    row = c.execute("SELECT * FROM roles WHERE role_key=?", (role_key,)).fetchone()
    if not row:
        c.close()
        return None
    r = dict(row)
    # prefer the RAW model features (lane_match etc.) the tuner needs; fall back
    # to the output snapshot for legacy rows that lack them.
    feats_json = r.get("features") or json.dumps(
        {k: r.get(k) for k in ("fit", "label", "geo", "comp", "lane", "tier")})
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    # dedup label on (role_key, decision)
    dup = c.execute("SELECT 1 FROM decisions WHERE IFNULL(role_key,'')=? AND decision=?",
                    (role_key or "", decision)).fetchone()
    if not dup:
        # applied roles enter the tracker pipeline at status 'applied'
        st = "applied" if decision == "applied" else None
        c.execute("""INSERT INTO decisions(ts,slug,role_key,company,title,decision,reason,
                     comment,features,source,status,updated,url,resume) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (today, None, role_key, r.get("company"), r.get("title"), decision,
                   reason, comment, feats_json, source, st, today, r.get("key"), resume))
    c.execute("UPDATE roles SET status=? WHERE role_key=?", (decision, role_key))
    if decision == "applied":
        c.execute("INSERT INTO applied_log(date,company,title,key) VALUES(?,?,?,?)",
                  (today, r.get("company"), r.get("title"), r.get("key")))
    c.commit()
    c.close()
    return r


# ── application tracker (Applied tab) ────────────────────────────────────────
def applications():
    """Applied roles with their pipeline status, newest first."""
    c = _conn()
    rows = c.execute("""SELECT id, ts, company, title, url, status, status_note, updated, resume
                        FROM decisions WHERE decision='applied' ORDER BY ts DESC, id DESC""").fetchall()
    c.close()
    return [dict(r) for r in rows]


def unapply(decision_id):
    """Undo an application (e.g. an accidental Apply): the role returns to the live
    board and the applied label + log entry are removed. Returns True if reverted."""
    try:
        decision_id = int(decision_id)
    except (TypeError, ValueError):
        return False
    c = _conn()
    row = c.execute("SELECT role_key, url FROM decisions WHERE id=? AND decision='applied'",
                    (decision_id,)).fetchone()
    if not row:
        c.close()
        return False
    if row["role_key"]:
        c.execute("UPDATE roles SET status='live' WHERE role_key=?", (row["role_key"],))
    c.execute("DELETE FROM applied_log WHERE key=?", (row["url"],))
    c.execute("DELETE FROM decisions WHERE id=?", (decision_id,))
    c.commit()
    c.close()
    return True


def set_status(decision_id, status, note):
    c = _conn()
    c.execute("UPDATE decisions SET status=?, status_note=?, updated=? WHERE id=? AND decision='applied'",
              (status, note, datetime.datetime.now(datetime.timezone.utc).date().isoformat(), decision_id))
    c.commit()
    c.close()


def application_stats():
    c = _conn()
    rows = c.execute("SELECT COALESCE(status,'applied') s, COUNT(*) n FROM decisions "
                     "WHERE decision='applied' GROUP BY s").fetchall()
    c.close()
    by = {r["s"]: r["n"] for r in rows}
    total = sum(by.values())
    advanced = sum(by.get(s, 0) for s in ("screening", "interview", "offer", "accepted"))
    interviews = sum(by.get(s, 0) for s in ("interview", "offer", "accepted"))
    offers = sum(by.get(s, 0) for s in ("offer", "accepted"))
    pct = lambda x: f"{round(100 * x / total)}%" if total else "—"
    return {"by": by, "total": total, "response_rate": pct(advanced),
            "interview_rate": pct(interviews), "offers": offers}


def labeled_decisions(require_raw=True):
    """Decisions usable for tuning: those whose features hold RAW model features
    (lane_match etc., persisted by analyze.py), not just output snapshots."""
    c = _conn()
    rows = c.execute("SELECT role_key, decision, reason, features FROM decisions "
                     "WHERE features IS NOT NULL AND features!='null'").fetchall()
    c.close()
    out = []
    for r in rows:
        try:
            feats = json.loads(r["features"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(feats, dict):
            continue
        if require_raw and "lane_match" not in feats:
            continue
        out.append({"role_key": r["role_key"], "decision": r["decision"],
                    "reason": r["reason"], "features": feats})
    return out


def label_counts():
    c = _conn()
    rows = c.execute("SELECT decision, COUNT(*) n, SUM(features IS NOT NULL AND features!='null') wf "
                     "FROM decisions GROUP BY decision").fetchall()
    c.close()
    d = {row["decision"]: row["n"] for row in rows}
    wf = sum(row["wf"] or 0 for row in rows)
    # Δ1: the tuner's positive class is `applied` ONLY — `interested` is a bookmark,
    # not a training label. both_classes reflects what the tuner can actually fit.
    return {"applied": d.get("applied", 0), "interested": d.get("interested", 0),
            "rejected": d.get("rejected", 0), "with_features": wf,
            "both_classes": d.get("applied", 0) > 0 and d.get("rejected", 0) > 0,
            "total": sum(d.values())}


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        b = load()
        print(f"DB: {DB}")
        print(f"live roles: {len(b['roles'])}  applied_log: {len(b['applied_log'])}")
        print(f"labels: {label_counts()}")

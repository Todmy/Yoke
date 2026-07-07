"""Flat-file job board: `_board.json` + `SHORTLIST.md` render.

State is a single flat JSON file under home():
`{"roles": {job_key: record}, "applied": [keys+role_keys], "dropped": [entries]}`.
Applied is a forever-ledger: any role whose key OR role_key lands there is
pruned from the board and never resurfaces.
"""

import datetime
import json
from pathlib import Path

from .paths import ensure_home, home

BOARD_FILE = "_board.json"
SHORTLIST_FILE = "SHORTLIST.md"

# Fields refreshed on re-upsert of an existing key; date_added is preserved.
_MUTABLE = (
    "fit", "tier", "features", "note", "comp_display", "geo_certainty",
    "red_flags", "url", "title", "company", "location", "last_refreshed",
)

_TIER_ORDER = {"A": 0, "B": 1}

_LABELS = {
    "en": {
        "title": "Yoke shortlist",
        "generated": "Generated",
        "counts": "{a} tier A · {b} tier B",
        "columns": ["Tier", "Fit", "Company", "Title", "Comp", "Geo", "Note", "URL"],
    },
    "uk": {
        "title": "Шортліст Yoke",
        "generated": "Згенеровано",
        "counts": "{a} тір A · {b} тір B",
        "columns": ["Тір", "Фіт", "Компанія", "Роль", "Комп", "Гео", "Нотатка", "URL"],
    },
}


def _today() -> str:
    return datetime.date.today().isoformat()


def load_board() -> dict:
    """Read home()/_board.json; missing file -> empty board."""
    path = home() / BOARD_FILE
    if path.is_file():
        b = json.loads(path.read_text(encoding="utf-8"))
    else:
        b = {}
    b.setdefault("roles", {})
    b.setdefault("applied", [])
    b.setdefault("dropped", [])
    return b


def _save_board(b: dict) -> None:
    ensure_home()
    path = home() / BOARD_FILE
    path.write_text(json.dumps(b, ensure_ascii=False, indent=2), encoding="utf-8")


def _prune(b: dict) -> list[str]:
    """Drop roles whose key OR role_key is in applied[]; return removed keys."""
    applied = set(b["applied"])
    removed = [
        k for k, r in b["roles"].items()
        if k in applied or r.get("role_key") in applied
    ]
    for k in removed:
        del b["roles"][k]
    return removed


def upsert(records: list[dict]) -> dict:
    """Merge analyze records into the board; returns {added, refreshed, pruned}.

    Existing keys keep their date_added and get mutable fields refreshed.
    After the merge, applied roles are pruned (repost dedup via role_key).
    """
    b = load_board()
    added = refreshed = 0
    today = _today()
    for rec in records:
        key = rec["key"]
        existing = b["roles"].get(key)
        if existing:
            for f in _MUTABLE:
                if rec.get(f) not in (None, ""):
                    existing[f] = rec[f]
            refreshed += 1
        else:
            rec.setdefault("date_added", today)
            b["roles"][key] = rec
            added += 1
    pruned = _prune(b)
    _save_board(b)
    return {"added": added, "refreshed": refreshed, "pruned": len(pruned)}


def mark_applied(match: str) -> list[str]:
    """Mark roles matching `match` as applied; returns removed board keys.

    Substring match (case-insensitive) on key OR company+title. Both job_key
    and role_key go into the applied ledger. No board hit -> the match string
    itself is ledgered so the role never resurfaces.
    """
    b = load_board()
    needle = match.lower()
    applied = set(b["applied"])
    hit = [
        r for r in b["roles"].values()
        if needle in r.get("key", "").lower()
        or needle in f"{r.get('company', '')} {r.get('title', '')}".lower()
    ]
    if hit:
        for r in hit:
            for k in (r.get("key"), r.get("role_key")):
                if k:
                    applied.add(k)
    else:
        applied.add(match)
    b["applied"] = sorted(applied)
    removed = _prune(b)
    _save_board(b)
    return removed


def drop(match: str, reason: str | None = None) -> list[str]:
    """Remove matching roles; keep {key, reason, date} in dropped[] (training signal)."""
    b = load_board()
    needle = match.lower()
    removed = []
    for key, r in list(b["roles"].items()):
        if (
            needle in r.get("key", "").lower()
            or needle in f"{r.get('company', '')} {r.get('title', '')}".lower()
        ):
            del b["roles"][key]
            b["dropped"].append({"key": key, "reason": reason, "date": _today()})
            removed.append(key)
    _save_board(b)
    return removed


def prune_applied() -> list[str]:
    """Drop any board role already applied (by key OR role_key); return removed keys."""
    b = load_board()
    removed = _prune(b)
    _save_board(b)
    return removed


def render(profile: dict) -> Path:
    """Write home()/SHORTLIST.md: tier A then B, fit desc within tier, C excluded."""
    b = load_board()
    lang = profile.get("output_language", "en")
    labels = _LABELS.get(lang, _LABELS["en"])
    roles = sorted(
        (r for r in b["roles"].values() if r.get("tier") in _TIER_ORDER),
        key=lambda r: (_TIER_ORDER[r["tier"]], -int(r.get("fit", 0))),
    )
    n_a = sum(1 for r in roles if r["tier"] == "A")
    n_b = len(roles) - n_a
    lines = [
        f"# {labels['title']}",
        "",
        f"_{labels['generated']}: {_today()} · {labels['counts'].format(a=n_a, b=n_b)}_",
        "",
        "| " + " | ".join(labels["columns"]) + " |",
        "|" + "---|" * len(labels["columns"]),
    ]
    for r in roles:
        cells = [
            r.get("tier", ""),
            str(r.get("fit", "")),
            r.get("company", ""),
            r.get("title", ""),
            r.get("comp_display", ""),
            r.get("geo_certainty", ""),
            r.get("note", ""),
            r.get("url", ""),
        ]
        lines.append("| " + " | ".join(str(c).replace("|", "/") for c in cells) + " |")
    ensure_home()
    path = home() / SHORTLIST_FILE
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

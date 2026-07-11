"""The labels store — decision snapshots that feed the M3 tuner.

At apply/drop, board snapshots the decided role's feature vector here *before*
pruning it from the board (the features live nowhere else). 100% deterministic:
no network, no LLM. The tuner's ground truth. Only decisions made after M3
carry features (cold-start).
"""

import datetime
import json

from src.paths import ensure_home, home

LABELS_FILE = "_labels.json"

# Fields copied straight off the analyzed board record.
_SNAPSHOT_KEYS = (
    "key", "role_key", "company", "title",
    "features", "fit", "tier", "geo_certainty", "red_flags",
)


def record(role: dict, label: str, reason: str | None = None) -> dict:
    """Snapshot a decided role to home()/_labels.json; append and return it.

    `label` is "applied" or "dropped"; `reason` is the drop reason (None for
    applied). Feature vector and audit fields are copied from `role`.
    """
    rec = {k: role.get(k) for k in _SNAPSHOT_KEYS}
    rec["label"] = label
    rec["reason"] = reason
    rec["date"] = datetime.date.today().isoformat()

    stored = load_labels()
    stored.append(rec)
    ensure_home()
    (home() / LABELS_FILE).write_text(
        json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return rec


def load_labels() -> list[dict]:
    """Read home()/_labels.json; fail open. Missing/malformed/non-list -> [];
    non-dict entries skipped."""
    path = home() / LABELS_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [e for e in data if isinstance(e, dict)]

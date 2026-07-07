"""$YOKE_HOME layout and persistent state.

All Yoke state lives under $YOKE_HOME (default ~/.yoke), flat files only.
"""

import json
import os
from pathlib import Path

STATE_FILE = "_state.json"


def home() -> Path:
    """Yoke home directory: $YOKE_HOME if set, else ~/.yoke."""
    env = os.environ.get("YOKE_HOME")
    if env:
        return Path(env)
    return Path.home() / ".yoke"


def ensure_home() -> Path:
    """Create home() and home()/scans if missing; return home()."""
    root = home()
    (root / "scans").mkdir(parents=True, exist_ok=True)
    return root


def load_state() -> dict:
    """Read home()/_state.json; missing file -> {}."""
    path = home() / STATE_FILE
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(d: dict) -> None:
    """Write d to home()/_state.json (creating home() if needed)."""
    ensure_home()
    path = home() / STATE_FILE
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

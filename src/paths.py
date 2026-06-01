"""Central paths + config loading for Yoke. Everything user-specific lives under
$YOKE_HOME (default ~/.yoke), never in the repo. Import these instead of
hard-coding locations."""
import json
import os
from pathlib import Path

YOKE_HOME = Path(os.environ.get("YOKE_HOME", Path.home() / ".yoke")).expanduser()

DB = YOKE_HOME / "yoke.db"
INDEX = YOKE_HOME / "index.json"
STATE = YOKE_HOME / "review-state.json"          # collect/analyze dedup ledger
JD_CACHE = YOKE_HOME / "jd-cache"
SHORTLIST = YOKE_HOME / "SHORTLIST.md"
SCANS_DIR = YOKE_HOME / "scans"                  # dated raw scan snapshots
APPS_DIR = Path(os.environ.get("YOKE_APPS", YOKE_HOME / "applications")).expanduser()
CONFIG_DIR = Path(os.environ.get("YOKE_CONFIG", YOKE_HOME / "config")).expanduser()
PROFILE_FILE = CONFIG_DIR / "profile.json"
SOURCES_FILE = CONFIG_DIR / "sources.json"

# repo-bundled examples, used as fallback so a fresh checkout runs before the
# user has written their own config
_REPO = Path(__file__).resolve().parent.parent
_EX_PROFILE = _REPO / "config" / "profile.example.json"
_EX_SOURCES = _REPO / "config" / "sources.example.json"


def ensure_home():
    YOKE_HOME.mkdir(parents=True, exist_ok=True)


def _load(primary, fallback):
    for p in (primary, fallback):
        if p.exists():
            try:
                return json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                continue
    return {}


def load_profile():
    """User profile (CV + constraints). Falls back to the bundled example."""
    return _load(PROFILE_FILE, _EX_PROFILE)


def load_sources():
    """Source config (companies, dork queries, source toggles)."""
    return _load(SOURCES_FILE, _EX_SOURCES)

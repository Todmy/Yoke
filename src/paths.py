"""$YOKE_HOME layout and persistent state.

All Yoke state lives under $YOKE_HOME (default ~/.yoke), flat files only.
"""

import json
import os
from pathlib import Path

STATE_FILE = "_state.json"


class ProfileError(Exception):
    """Profile missing, unparseable, or failing validation."""


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


def load_profile(path: Path | str | None = None) -> dict:
    """Load and validate the user profile.

    Default lookup: home()/profile.yml, then home()/profile.json.
    Raises ProfileError on missing file, missing PyYAML, or failed validation.
    """
    if path is not None:
        candidates = [Path(path)]
    else:
        candidates = [home() / "profile.yml", home() / "profile.json"]

    for candidate in candidates:
        if candidate.is_file():
            profile = _parse_profile(candidate)
            _validate_profile(profile, candidate)
            return profile

    looked = ", ".join(str(c) for c in candidates)
    raise ProfileError(
        f"No profile found (looked at: {looked}). "
        "Copy profile.example.yml to $YOKE_HOME/profile.yml and fill it in."
    )


def _parse_profile(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yml", ".yaml"):
        try:
            import yaml  # lazy: third-party imports stay out of module level
        except ImportError:
            raise ProfileError(
                f"{path} is YAML but PyYAML is not installed. "
                "Fix: `pip install pyyaml`, or use a profile.json instead."
            ) from None
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ProfileError(f"{path}: profile must be a mapping, got {type(data).__name__}")
    return data


def _validate_profile(profile: dict, path: Path) -> None:
    scoring = profile.get("scoring", {})
    weights = [
        entry.get("weight", 0)
        for entry in scoring.get("features", []) + scoring.get("deterministic", [])
    ]
    total = sum(weights)
    if total != 100:
        raise ProfileError(
            f"{path}: scoring weights (features + deterministic) must sum to 100, got {total}"
        )
    floor = profile.get("comp", {}).get("floor_net_usd_mo")
    if not isinstance(floor, int) or isinstance(floor, bool):
        raise ProfileError(
            f"{path}: comp.floor_net_usd_mo must be an integer, got {floor!r}"
        )

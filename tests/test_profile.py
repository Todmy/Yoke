import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="yoke-test-profile-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src import paths  # noqa: E402


def _profile_dict(feature_weights=(40, 30), det_weights=(30,)):
    return {
        "name": "Test User",
        "output_language": "en",
        "lane": {"keywords": ["engineer"], "anti": ["intern"]},
        "comp": {"floor_net_usd_mo": 10000},
        "geo": {"allow": ["remote-eu"], "block": ["ru"]},
        "tech": {"primary": ["python"], "avoid_primary": ["php"]},
        "language_levels": {"en": "b2"},
        "stage_rules": [],
        "scoring": {
            "features": [
                {"name": f"f{i}", "weight": w, "desc": "d"}
                for i, w in enumerate(feature_weights)
            ],
            "deterministic": [
                {"name": f"det{i}", "weight": w}
                for i, w in enumerate(det_weights)
            ],
        },
        "sources": {"enabled": [], "companies": []},
    }


def _yaml_profile_text():
    return (
        "name: Test User\n"
        "output_language: en\n"
        "lane:\n"
        "  keywords: [engineer]\n"
        "  anti: [intern]\n"
        "comp:\n"
        "  floor_net_usd_mo: 10000\n"
        "geo:\n"
        "  allow: [remote-eu]\n"
        "  block: [ru]\n"
        "tech:\n"
        "  primary: [python]\n"
        "  avoid_primary: [php]\n"
        "language_levels:\n"
        "  en: b2\n"
        "stage_rules: []\n"
        "scoring:\n"
        "  features:\n"
        "    - {name: f0, weight: 40, desc: d}\n"
        "    - {name: f1, weight: 30, desc: d}\n"
        "  deterministic:\n"
        "    - {name: det0, weight: 30}\n"
        "sources:\n"
        "  enabled: []\n"
        "  companies: []\n"
    )


class TestProfile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["YOKE_HOME"] = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()
        os.environ["YOKE_HOME"] = _TMP

    def test_yaml_profile_loads(self):
        home = paths.ensure_home()
        (home / "profile.yml").write_text(_yaml_profile_text(), encoding="utf-8")
        profile = paths.load_profile()
        self.assertEqual(profile["name"], "Test User")
        self.assertEqual(profile["comp"]["floor_net_usd_mo"], 10000)
        self.assertEqual(len(profile["scoring"]["features"]), 2)

    def test_json_fallback(self):
        home = paths.ensure_home()
        # no profile.yml present -> falls back to profile.json
        (home / "profile.json").write_text(
            json.dumps(_profile_dict()), encoding="utf-8"
        )
        profile = paths.load_profile()
        self.assertEqual(profile["name"], "Test User")
        self.assertEqual(profile["lane"]["keywords"], ["engineer"])

    def test_weights_must_sum_100(self):
        home = paths.ensure_home()
        bad = _profile_dict(feature_weights=(40, 30), det_weights=(20,))  # sums 90
        (home / "profile.json").write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaises(paths.ProfileError) as ctx:
            paths.load_profile()
        self.assertIn("100", str(ctx.exception))

    def test_missing_profile_message(self):
        paths.ensure_home()  # empty home, no profile files
        with self.assertRaises(paths.ProfileError) as ctx:
            paths.load_profile()
        self.assertIn("profile.example.yml", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="yoke-test-paths-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src import paths  # noqa: E402


class TestPaths(unittest.TestCase):
    def test_home_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["YOKE_HOME"] = tmp
            try:
                self.assertEqual(paths.home(), Path(tmp))
                ensured = paths.ensure_home()
                self.assertEqual(ensured, Path(tmp))
                self.assertTrue((Path(tmp) / "scans").is_dir())
            finally:
                os.environ["YOKE_HOME"] = _TMP

    def test_state_roundtrip(self):
        paths.ensure_home()
        data = {"last_run": "2026-07-07T00:00:00", "selection": ["hn", "remoteok"]}
        paths.save_state(data)
        state_file = paths.home() / "_state.json"
        self.assertTrue(state_file.is_file())
        self.assertEqual(paths.load_state(), data)
        # file content is real JSON
        self.assertEqual(json.loads(state_file.read_text()), data)

    def test_missing_state_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["YOKE_HOME"] = tmp
            try:
                self.assertEqual(paths.load_state(), {})
            finally:
                os.environ["YOKE_HOME"] = _TMP


if __name__ == "__main__":
    unittest.main()

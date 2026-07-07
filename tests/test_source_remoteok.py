import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="yoke-test-remoteok-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.sources import remoteok  # noqa: E402

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "remoteok.json"


class TestRemoteokSource(unittest.TestCase):
    def test_plugin_contract(self):
        self.assertEqual(remoteok.NAME, "remoteok")
        self.assertEqual(remoteok.TAGS, {"domain": "it", "country": "intl"})
        self.assertEqual(remoteok.COST, "free")
        self.assertEqual(remoteok.available(), (True, ""))

    def test_parse_fixture(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        jobs = remoteok._parse(payload, {})
        # first element of the API list is a legal notice — must be skipped
        self.assertEqual(len(jobs), 2)
        self.assertEqual(
            jobs[0],
            {
                "title": "Senior AI Engineer",
                "company": "Acme AI",
                "location": "Remote - Europe",
                "url": "https://remoteok.com/remote-jobs/123456",
                "source": "remoteok",
                "posted_at": "2026-07-05T10:00:00+00:00",
                "comp": None,
            },
        )

    def test_parse_non_list_payload(self):
        self.assertEqual(remoteok._parse(None, {}), [])
        self.assertEqual(remoteok._parse({"error": "rate limited"}, {}), [])


if __name__ == "__main__":
    unittest.main()

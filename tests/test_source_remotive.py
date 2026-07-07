import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="yoke-test-remotive-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.sources import remotive  # noqa: E402

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "remotive.json"


class TestRemotiveSource(unittest.TestCase):
    def test_plugin_contract(self):
        self.assertEqual(remotive.NAME, "remotive")
        self.assertEqual(remotive.TAGS, {"domain": "it", "country": "intl"})
        self.assertEqual(remotive.COST, "free")
        self.assertEqual(remotive.available(), (True, ""))

    def test_parse_fixture(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        jobs = remotive._parse(payload, {})
        self.assertEqual(len(jobs), 2)
        self.assertEqual(
            jobs[0],
            {
                "title": "Machine Learning Engineer",
                "company": "Nimbus Labs",
                "location": "Europe",
                "url": "https://remotive.com/remote-jobs/software-dev/machine-learning-engineer-1902938",
                "source": "remotive",
                "posted_at": "2026-07-04T09:30:00",
                "comp": None,
            },
        )
        # second job omits candidate_required_location — defaults to Remote
        self.assertEqual(jobs[1]["location"], "Remote")

    def test_parse_bad_payload(self):
        self.assertEqual(remotive._parse(None, {}), [])
        self.assertEqual(remotive._parse({"job-count": 0}, {}), [])


if __name__ == "__main__":
    unittest.main()

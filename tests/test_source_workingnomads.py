import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="yoke-test-workingnomads-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.sources import workingnomads  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "workingnomads.json"


class TestWorkingNomads(unittest.TestCase):
    def test_module_contract(self):
        self.assertEqual(workingnomads.NAME, "workingnomads")
        self.assertEqual(workingnomads.TAGS, {"domain": "it", "country": "intl"})
        self.assertEqual(workingnomads.COST, "free")
        self.assertEqual(workingnomads.available(), (True, ""))

    def test_parse_fixture(self):
        payload = FIXTURE.read_text(encoding="utf-8")
        jobs = workingnomads._parse(payload, {})
        # third fixture entry has no title -> skipped
        self.assertEqual(len(jobs), 2)
        self.assertEqual(
            jobs[0],
            {
                "title": "Senior Backend Engineer",
                "company": "Acme Robotics",
                "location": "Europe",
                "url": "https://www.workingnomads.com/jobs/senior-backend-engineer-acme-robotics",
                "source": "workingnomads",
                "posted_at": "2026-07-05T10:00:00",
                "comp": None,
                "jd": "Build APIs in Python for our logistics platform.",
            },
        )
        # description HTML tag-stripped into plain-text jd
        for j in jobs:
            self.assertTrue(j["jd"])
            self.assertNotIn("<", j["jd"])

    def test_parse_garbage_payload(self):
        self.assertEqual(workingnomads._parse("not json at all", {}), [])
        self.assertEqual(workingnomads._parse('{"detail": "rate limited"}', {}), [])


if __name__ == "__main__":
    unittest.main()

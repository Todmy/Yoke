import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="yoke-test-wwr-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.sources import wwr  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "wwr.xml"


class TestWWR(unittest.TestCase):
    def test_module_contract(self):
        self.assertEqual(wwr.NAME, "wwr")
        self.assertEqual(wwr.TAGS, {"domain": "it", "country": "intl"})
        self.assertEqual(wwr.COST, "free")
        self.assertEqual(wwr.available(), (True, ""))

    def test_parse_fixture(self):
        payload = FIXTURE.read_text(encoding="utf-8")
        jobs = wwr._parse(payload, {})
        self.assertEqual(len(jobs), 3)
        # CDATA title split on "Company: Role"
        self.assertEqual(
            jobs[0],
            {
                "title": "Senior Backend Engineer",
                "company": "Acme Robotics",
                "location": "Anywhere in the World",
                "url": "https://weworkremotely.com/remote-jobs/acme-robotics-senior-backend-engineer",
                "source": "wwr",
                "posted_at": "Sat, 05 Jul 2026 10:00:00 +0000",
                "comp": None,
                "jd": "Build APIs in Python for our logistics platform.",
            },
        )
        # CDATA description HTML tag-stripped into plain-text jd
        self.assertNotIn("<", jobs[0]["jd"])
        self.assertEqual(jobs[1]["jd"], "LLM fine-tuning and evaluation pipelines.")
        # plain (non-CDATA) tags parse too
        self.assertEqual(jobs[1]["company"], "Globex")
        self.assertEqual(jobs[1]["location"], "Europe Only")
        # no "Company:" prefix -> whole title is the role, empty company,
        # missing <region> defaults to Remote
        self.assertEqual(jobs[2]["title"], "Standalone Role Without Company Prefix")
        self.assertEqual(jobs[2]["company"], "")
        self.assertEqual(jobs[2]["location"], "Remote")
        # missing <description> → jd stays ""
        self.assertEqual(jobs[2]["jd"], "")

    def test_parse_empty_payload(self):
        self.assertEqual(wwr._parse("", {}), [])
        self.assertEqual(wwr._parse(None, {}), [])


if __name__ == "__main__":
    unittest.main()

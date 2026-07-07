import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="yoke-test-brave-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.sources import brave  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "brave.json"


class TestBraveSource(unittest.TestCase):
    def test_module_contract(self):
        self.assertEqual(brave.NAME, "brave")
        self.assertEqual(brave.TAGS, {"domain": "any", "country": "any"})
        self.assertEqual(brave.COST, "key")

    def test_brave_unavailable_without_key(self):
        env = {k: v for k, v in os.environ.items() if k != "BRAVE_API_KEY"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(brave.available(), (False, "BRAVE_API_KEY not set"))
        with mock.patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
            self.assertEqual(brave.available(), (True, ""))

    def test_brave_parse(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        jobs = brave._parse(payload, 'site:job-boards.greenhouse.io ("ai engineer") remote')

        # blog result on a non-ATS, non-aggregator host is dropped
        self.assertEqual(len(jobs), 2)

        # ATS host: company attributed from the URL slug, loc from description
        self.assertEqual(
            jobs[0],
            {
                "title": "AI Engineer",
                "company": "Acmeai",
                "location": "Europe",
                "url": "https://job-boards.greenhouse.io/acmeai/jobs/4012345",
                "source": "dork:job-boards.greenhouse.io",
                "posted_at": "",
                "comp": None,
            },
        )

        # soft aggregator host: company attributed from the title, kept either way
        self.assertEqual(jobs[1]["company"], "Nofluff Corp")
        self.assertEqual(jobs[1]["location"], "Poland")
        self.assertEqual(jobs[1]["source"], "dork:nofluffjobs.com")

    def test_dork_queries_from_profile_lane(self):
        profile = {"lane": {"keywords": ["ai engineer", "forward deployed"]}}
        queries = brave._dork_queries(profile)
        self.assertTrue(queries)
        # every query is a site: dork carrying the lane keywords OR-joined
        for q in queries:
            self.assertTrue(q.startswith("site:"))
            self.assertIn('"ai engineer" OR "forward deployed"', q)
        # PL aggregator dorks present (nofluffjobs has no usable API)
        hosts = " ".join(queries)
        self.assertIn("site:nofluffjobs.com", hosts)
        self.assertIn("site:justjoin.it", hosts)


if __name__ == "__main__":
    unittest.main()

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="yoke-test-ats-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.sources import ats  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestAtsSource(unittest.TestCase):
    def test_module_contract(self):
        self.assertEqual(ats.NAME, "ats")
        self.assertEqual(ats.TAGS, {"domain": "it", "country": "any"})
        self.assertEqual(ats.COST, "free")
        self.assertEqual(ats.available(), (True, ""))

    def test_ats_greenhouse_parse(self):
        company = {"slug": "acme", "ats": "greenhouse"}
        jobs = ats._parse_greenhouse(_fixture("ats_greenhouse.json"), company)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(
            jobs[0],
            {
                "title": "Senior Backend Engineer",
                "company": "acme",
                "location": "Remote - Europe",
                "url": "https://boards.greenhouse.io/acme/jobs/100",
                "source": "ats:greenhouse:acme",
                "posted_at": "2026-07-01T10:00:00Z",
                "comp": None,
                "jd": "Build backend systems.",
            },
        )
        # jd is plain text: escaped HTML unwrapped, no tags survive
        self.assertNotIn("<", jobs[0]["jd"])
        # empty content field → jd stays ""
        self.assertEqual(jobs[1]["jd"], "")
        # malformed payload → empty list, never a raise
        self.assertEqual(ats._parse_greenhouse({}, company), [])
        self.assertEqual(ats._parse_greenhouse(None, company), [])

    def test_ats_lever_parse(self):
        company = {"slug": "acme", "ats": "lever"}
        jobs = ats._parse_lever(_fixture("ats_lever.json"), company)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(
            jobs[0],
            {
                "title": "Platform Engineer",
                "company": "acme",
                "location": "Remote - EU",
                "url": "https://jobs.lever.co/acme/abc123",
                "source": "ats:lever:acme",
                "posted_at": "1750000000000",
                "comp": "USD90000-120000",
                "jd": "Build the platform.",
            },
        )
        # salaryDescriptionPlain fallback when no structured range
        self.assertEqual(jobs[1]["comp"], "EUR 80k-100k per year")
        # descriptionPlain preferred; HTML description falls back tag-stripped
        self.assertEqual(jobs[1]["jd"], "Train models.")
        self.assertNotIn("<", jobs[1]["jd"])
        # lever payload is a list — anything else parses to empty
        self.assertEqual(ats._parse_lever({"error": "nope"}, company), [])

    def test_ats_ashby_parse(self):
        company = {"slug": "acme", "ats": "ashby"}
        jobs = ats._parse_ashby(_fixture("ats_ashby.json"), company)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(
            jobs[0],
            {
                "title": "Staff Engineer",
                "company": "acme",
                "location": "Remote Europe",
                "url": "https://jobs.ashbyhq.com/acme/xyz-789",
                "source": "ats:ashby:acme",
                "posted_at": "2026-06-15T00:00:00Z",
                "comp": "$150K – $180K • Offers Equity",
                "jd": "Own the architecture.",
            },
        )
        # job without compensation block → comp None
        self.assertIsNone(jobs[1]["comp"])
        # descriptionHtml fallback comes out tag-stripped
        self.assertEqual(jobs[1]["jd"], "Keep it up.")
        self.assertNotIn("<", jobs[1]["jd"])
        self.assertEqual(ats._parse_ashby({}, company), [])


class TestFetchIsolation(unittest.TestCase):
    def test_one_dead_slug_does_not_kill_the_source(self):
        import io
        import json as _json
        from contextlib import redirect_stderr
        from unittest import mock

        good_payload = {"jobs": [{"title": "AI Engineer",
                                  "absolute_url": "https://boards.greenhouse.io/good/1",
                                  "location": {"name": "Remote"},
                                  "updated_at": "2026-07-01"}]}

        def fake_get(url):
            if "dead" in url:
                raise OSError("HTTP Error 404: Not Found")
            return good_payload

        profile = {"sources": {"companies": [
            {"slug": "dead", "ats": "greenhouse"},
            {"slug": "good", "ats": "greenhouse"},
        ]}}
        with mock.patch.object(ats, "_get_json", side_effect=fake_get):
            with redirect_stderr(io.StringIO()):
                jobs = ats.fetch(profile)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["company"], "good")


if __name__ == "__main__":
    unittest.main()

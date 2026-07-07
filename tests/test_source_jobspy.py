import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="yoke-test-jobspy-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.sources import jobspy_src  # noqa: E402


def _profile():
    return {
        "lane": {"keywords": ["engineer", "backend"], "anti": []},
        "geo": {"allow": ["remote-eu"], "block": []},
        "search": {"keywords": ["backend engineer"], "location": "European Union"},
    }


def _rows():
    return [
        {
            "site": "indeed",
            "title": "Senior Backend Engineer",
            "company": "Acme Corp",
            "city": "Warsaw",
            "state": "Mazowieckie",
            "country": "Poland",
            "is_remote": False,
            "job_url": "https://indeed.com/viewjob?jk=abc123",
            "date_posted": "2026-07-01",
            "min_amount": 50.0,
            "max_amount": 60.0,
            "interval": "hourly",
            "currency": "USD",
            "job_type": "contract",
        },
        {
            "site": "linkedin",
            "title": "Staff Engineer",
            "company": "Globex",
            "city": float("nan"),
            "state": None,
            "country": "nan",
            "is_remote": True,
            "job_url": "https://linkedin.com/jobs/view/999",
            "date_posted": "2026-07-02",
            "min_amount": 120000,
            "max_amount": 150000,
            "interval": "yearly",
            "currency": "USD",
            "job_type": "fulltime",
        },
        {
            "site": "google",
            "title": "Platform Engineer",
            "company": "Initech",
            "city": "Krakow",
            "state": "",
            "country": "Poland",
            "is_remote": False,
            "job_url": "https://example.com/job/3",
            "date_posted": None,
            "min_amount": None,
            "max_amount": None,
            "interval": None,
            "currency": None,
            "job_type": "fulltime",
        },
    ]


class TestJobspySource(unittest.TestCase):
    def test_module_contract(self):
        self.assertEqual(jobspy_src.NAME, "jobspy")
        self.assertEqual(jobspy_src.TAGS, {"domain": "any", "country": "any"})
        self.assertEqual(jobspy_src.COST, "free")

    def test_available_false_without_lib(self):
        ok, reason = jobspy_src.available()
        self.assertFalse(ok)
        self.assertEqual(reason, "python-jobspy not installed")

    def test_rows_to_norms_maps_comp(self):
        norms = jobspy_src._rows_to_norms(_rows(), _profile())
        self.assertEqual(len(norms), 3)

        # Fully-checked record: hourly salary → unit "hour".
        j = norms[0]
        self.assertEqual(j["title"], "Senior Backend Engineer")
        self.assertEqual(j["company"], "Acme Corp")
        self.assertEqual(j["location"], "Warsaw, Mazowieckie, Poland")
        self.assertEqual(j["url"], "https://indeed.com/viewjob?jk=abc123")
        self.assertEqual(j["source"], "jobspy:indeed")
        self.assertEqual(j["posted_at"], "2026-07-01")
        self.assertEqual(
            j["comp"],
            {
                "min": 50.0,
                "max": 60.0,
                "currency": "usd",
                "unit": "hour",
                "type": "contract",
            },
        )

        # Yearly interval → unit "year"; nan/None location parts dropped,
        # is_remote fallback kicks in.
        j2 = norms[1]
        self.assertEqual(j2["location"], "Remote")
        self.assertEqual(j2["source"], "jobspy:linkedin")
        self.assertEqual(j2["comp"]["unit"], "year")
        self.assertEqual(j2["comp"]["min"], 120000)
        self.assertEqual(j2["comp"]["max"], 150000)

        # No salary data → comp is None (never an empty dict/string).
        self.assertIsNone(norms[2]["comp"])
        self.assertEqual(norms[2]["posted_at"], "")


if __name__ == "__main__":
    unittest.main()

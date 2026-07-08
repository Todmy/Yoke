import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="yoke-test-germany-ba-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src import http  # noqa: E402
from src.collect import JD_MAX_CHARS  # noqa: E402
from src.sources import germany_ba  # noqa: E402

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "germany_ba.json"


class TestGermanyBaSource(unittest.TestCase):
    def test_module_contract(self):
        self.assertEqual(germany_ba.NAME, "germany_ba")
        self.assertEqual(germany_ba.TAGS, {"domain": "any", "country": "de"})
        self.assertEqual(germany_ba.COST, "free")
        self.assertEqual(germany_ba.available(), (True, ""))

    def test_parse_fixture(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        jobs = germany_ba._parse(payload, {})
        self.assertEqual(len(jobs), 4)
        self.assertEqual(
            jobs[0],
            {
                "title": "Python Entwickler (m/w/d)",
                "company": "R+V Allgemeine Versicherung AG",
                "location": "Wiesbaden, Deutschland",
                "url": "https://www.arbeitsagentur.de/jobsuche/jobdetail/19301-952981419-S",
                "source": "germany_ba",
                "posted_at": "2026-06-22",
                "comp": None,
                "jd": "",
            },
        )
        # an entry carrying externeUrl uses it verbatim instead of the built link
        self.assertEqual(
            jobs[1]["url"],
            "https://www.get-in-it.de/jobsuche/p265788?utm_source=arbeitsagentur"
            "&utm_medium=organic&utm_campaign=launch-basic",
        )
        # every role is the full 8-key shape, jd tag-free and capped
        for j in jobs:
            self.assertEqual(
                set(j),
                {"title", "company", "location", "url", "source", "posted_at", "comp", "jd"},
            )
            self.assertNotIn("<", j["jd"])
            self.assertLessEqual(len(j["jd"]), JD_MAX_CHARS)
        # malformed / missing stellenangebote → [], never a raise
        self.assertEqual(germany_ba._parse({}, {}), [])
        self.assertEqual(germany_ba._parse(None, {}), [])

    def test_fetch_returns_empty_when_de_not_selected(self):
        profile = {"countries": ["uk"], "lane": {"keywords": ["python"]}}
        with mock.patch.object(http, "fetch_bytes") as fake:
            jobs = germany_ba.fetch(profile)
        fake.assert_not_called()
        self.assertEqual(jobs, [])

    def test_fetch_queries_when_de_selected(self):
        profile = {"countries": ["de"], "lane": {"keywords": ["python"]}}
        payload_bytes = _FIXTURE.read_bytes()
        with mock.patch.object(http, "fetch_bytes", return_value=payload_bytes) as fake:
            jobs = germany_ba.fetch(profile)
        self.assertTrue(fake.called)
        self.assertEqual(len(jobs), 4)
        self.assertEqual(jobs[0]["source"], "germany_ba")

    def test_fetch_returns_empty_on_blocked(self):
        # Contract: never raises past its own fetch — a cooled-down host → [].
        profile = {"countries": ["de"], "lane": {"keywords": ["python"]}}
        with mock.patch.object(http, "fetch_bytes", side_effect=http.Blocked("cooldown")):
            self.assertEqual(germany_ba.fetch(profile), [])


if __name__ == "__main__":
    unittest.main()

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="yoke-test-eures-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.collect import JD_MAX_CHARS  # noqa: E402
from src.sources import eures  # noqa: E402

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "eures_search.json"

_EIGHT_KEYS = {
    "title", "company", "location", "url",
    "source", "posted_at", "comp", "jd",
}


class TestEuresSource(unittest.TestCase):
    def test_module_contract(self):
        self.assertEqual(eures.NAME, "eures")
        self.assertEqual(eures.TAGS, {"domain": "any", "country": "any"})
        self.assertEqual(eures.COST, "free")
        self.assertEqual(eures.available(), (True, ""))

    def test_parse_fixture(self):
        payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
        jobs = eures._parse(payload, {})
        self.assertGreaterEqual(len(jobs), 1)

        j0 = jobs[0]
        self.assertEqual(set(j0), _EIGHT_KEYS)
        self.assertEqual(j0["title"], "Technischer Produktdesigner (m/w/d) (IT-Tester/in)")
        self.assertEqual(j0["company"], "Guldberg GmbH")
        self.assertEqual(j0["location"], "DE")
        self.assertEqual(
            j0["url"],
            "https://europa.eu/eures/portal/jv-se/jv-details/MTM0MTAtazEzNTcyLjE1ODA3LVMgMQ",
        )
        self.assertEqual(j0["source"], "eures")
        self.assertTrue(j0["posted_at"].startswith("2026-07"))

        # EURES search carries no structured salary → comp is None for every hit
        for j in jobs:
            self.assertIsNone(j["comp"])
            # jd is plain text, tag-free, capped
            self.assertNotIn("<", j["jd"])
            self.assertLessEqual(len(j["jd"]), JD_MAX_CHARS)
        # the first hit actually carried a description
        self.assertTrue(j0["jd"])

    def test_parse_malformed(self):
        self.assertEqual(eures._parse(None, {}), [])
        self.assertEqual(eures._parse({}, {}), [])
        self.assertEqual(eures._parse({"jvs": "x"}, {}), [])
        self.assertEqual(eures._parse({"jvs": [None, 1]}, {}), [])

    def test_fetch_builds_body_from_profile(self):
        captured = {}

        def fake_fetch_bytes(url, *, data=None, headers=None, timeout=20):
            captured["url"] = url
            captured["headers"] = headers
            captured["body"] = json.loads(data)
            return _FIXTURE.read_bytes()

        profile = {"countries": ["de"], "lane": {"keywords": ["ai engineer", "ml"]}}
        with mock.patch.object(eures.http, "fetch_bytes", fake_fetch_bytes):
            jobs = eures.fetch(profile)

        self.assertEqual(captured["url"], eures.SEARCH_URL)
        self.assertEqual(captured["headers"]["Content-Type"], "application/json")
        self.assertEqual(captured["body"]["locationCodes"], ["de"])
        self.assertEqual(
            [k["keyword"] for k in captured["body"]["keywords"]],
            ["ai engineer", "ml"],
        )
        self.assertEqual(len(jobs), 3)

    def test_fetch_all_eu_sends_no_country_filter(self):
        captured = {}

        def fake_fetch_bytes(url, *, data=None, headers=None, timeout=20):
            captured["body"] = json.loads(data)
            return b'{"jvs": []}'

        with mock.patch.object(eures.http, "fetch_bytes", fake_fetch_bytes):
            eures.fetch({"countries": ["all-eu"], "lane": {"keywords": ["x"]}})
        self.assertEqual(captured["body"]["locationCodes"], [])

    def test_fetch_returns_empty_on_blocked(self):
        # Contract: a fetcher never raises past its own fetch — a cooled-down
        # host degrades to [] (run_collect's outer isolation is only a backstop).
        profile = {"countries": ["de"], "lane": {"keywords": ["x"]}}
        with mock.patch.object(
            eures.http, "fetch_bytes", side_effect=eures.http.Blocked("cooldown")
        ):
            self.assertEqual(eures.fetch(profile), [])

    def test_fetch_returns_empty_on_bad_json(self):
        with mock.patch.object(
            eures.http, "fetch_bytes", return_value=b"<html>not json</html>"
        ):
            self.assertEqual(eures.fetch({"lane": {"keywords": ["x"]}}), [])


if __name__ == "__main__":
    unittest.main()

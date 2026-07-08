import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="yoke-test-justjoin-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src import collect, http  # noqa: E402
from src.sources import justjoin  # noqa: E402

_FIXTURE = Path(__file__).parent / "fixtures" / "justjoin.json"
_OFFER_HTML = (Path(__file__).parent / "fixtures" / "justjoin_offer.html").read_bytes()


def _payload():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


class _FakeResp:
    """Minimal stand-in for urlopen's context-manager response."""

    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# One remote offer so JD enrichment fetches exactly one URL.
_LIST_ONE = {
    "data": [
        {
            "title": "Senior Python Engineer",
            "companyName": "Acme",
            "workplaceType": "remote",
            "city": "Warszawa",
            "slug": "acme-senior-python-engineer",
            "publishedAt": "2026-07-01T10:00:00.000Z",
            "employmentTypes": [],
        }
    ]
}
_OFFER_URL = "https://justjoin.it/job-offer/acme-senior-python-engineer"


class TestJustjoin(unittest.TestCase):
    def test_module_contract(self):
        self.assertEqual(justjoin.NAME, "justjoin")
        self.assertEqual(justjoin.TAGS, {"domain": "it", "country": "pl"})
        self.assertEqual(justjoin.COST, "free")
        self.assertEqual(justjoin.available(), (True, ""))

    def test_justjoin_parse(self):
        jobs = justjoin._parse(_payload(), {})
        # 3 offers in fixture, the "office" one is hard-gated out
        self.assertEqual(len(jobs), 2)
        self.assertEqual(
            jobs[0],
            {
                "title": "Senior Python Engineer",
                "company": "Acme Sp. z o.o.",
                "location": "Remote (Poland)",
                "url": "https://justjoin.it/job-offer/acme-senior-python-engineer",
                "source": "justjoin",
                "posted_at": "2026-07-01T10:00:00.000Z",
                "comp": {
                    "min": 6200,
                    "max": 7900,
                    "currency": "usd",
                    "unit": "month",
                    "type": "b2b",
                },
                # list payload has no full text — full JD needs per-offer fetch (M1)
                "jd": "",
            },
        )

    def test_justjoin_comp_is_structured_never_string(self):
        # Regression guard on the _jj_comp bug class: comp must never be
        # a preformatted "$X-Y/mo" string.
        for job in justjoin._parse(_payload(), {}):
            self.assertNotIsInstance(job["comp"], str)
            if job["comp"] is not None:
                self.assertEqual(
                    set(job["comp"]), {"min", "max", "currency", "unit", "type"}
                )

    def test_justjoin_hourly_unit(self):
        # The prototype's _jj_comp formatted hourly B2B rates as "$50-62/mo".
        # A per-hour offer MUST come out with unit == "hour".
        jobs = justjoin._parse(_payload(), {})
        hourly = [j for j in jobs if j["company"] == "HourlyWorks"]
        self.assertEqual(len(hourly), 1)
        comp = hourly[0]["comp"]
        self.assertEqual(comp["unit"], "hour")
        self.assertEqual(comp["min"], 50)
        self.assertEqual(comp["max"], 62)
        self.assertEqual(comp["currency"], "usd")
        self.assertEqual(comp["type"], "b2b")
        self.assertEqual(hourly[0]["location"], "Wrocław, Poland")

    def test_parse_fixture(self):
        # _parse stays pure: every record still ships jd == "" (full JD is a
        # fetch-time enrichment, never built inside _parse).
        for job in justjoin._parse(_payload(), {}):
            self.assertEqual(job["jd"], "")


class TestJustjoinFetch(unittest.TestCase):
    """fetch() enriches _parse records with per-offer JD over HTTP + cache."""

    def setUp(self):
        # Isolated home per test so jd_cache.json never leaks across tests.
        self._prev_home = os.environ.get("YOKE_HOME")
        self._home = tempfile.mkdtemp(prefix="yoke-test-justjoin-fetch-")
        os.environ["YOKE_HOME"] = self._home

    def tearDown(self):
        if self._prev_home is not None:
            os.environ["YOKE_HOME"] = self._prev_home

    @staticmethod
    def _fake_urlopen(req, timeout=None):
        return _FakeResp(json.dumps(_LIST_ONE).encode("utf-8"))

    def test_fetch_fills_jd_from_http(self):
        calls = []

        def fake_fetch_bytes(url, **kwargs):
            calls.append(url)
            return _OFFER_HTML

        with mock.patch.object(justjoin, "CATEGORIES", (5,)), \
                mock.patch("urllib.request.urlopen", self._fake_urlopen), \
                mock.patch.object(http, "fetch_bytes", fake_fetch_bytes):
            out = justjoin.fetch({})

        self.assertEqual(len(out), 1)
        jd = out[0]["jd"]
        self.assertTrue(jd, "jd should be populated from the offer page")
        self.assertNotIn("<", jd)  # tag-free after strip_html
        self.assertLessEqual(len(jd), collect.JD_MAX_CHARS)
        self.assertIn("FastAPI", jd)  # real content pulled from JSON-LD
        self.assertEqual(calls, [_OFFER_URL])

    def test_second_run_reads_cache_no_refetch(self):
        calls = []

        def fake_fetch_bytes(url, **kwargs):
            calls.append(url)
            return _OFFER_HTML

        with mock.patch.object(justjoin, "CATEGORIES", (5,)), \
                mock.patch("urllib.request.urlopen", self._fake_urlopen), \
                mock.patch.object(http, "fetch_bytes", fake_fetch_bytes):
            justjoin.fetch({})
            second = justjoin.fetch({})

        # JD fetched once ever: the second run serves it from jd_cache.json.
        self.assertEqual(len(calls), 1)
        self.assertTrue(second[0]["jd"])

    def test_jd_fetch_error_leaves_jd_empty_but_role_kept(self):
        def boom(url, **kwargs):
            raise http.Blocked("host in cooldown")

        with mock.patch.object(justjoin, "CATEGORIES", (5,)), \
                mock.patch("urllib.request.urlopen", self._fake_urlopen), \
                mock.patch.object(http, "fetch_bytes", boom):
            out = justjoin.fetch({})

        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["jd"], "")  # jd stays empty
        self.assertEqual(out[0]["title"], "Senior Python Engineer")  # role kept


if __name__ == "__main__":
    unittest.main()

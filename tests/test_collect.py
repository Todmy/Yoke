import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="yoke-test-collect-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src import collect, paths  # noqa: E402


def _profile():
    return {
        "lane": {"keywords": ["engineer", "backend"], "anti": ["intern"]},
        "geo": {"allow": ["remote-eu"], "block": ["russia", "belarus"]},
        "tech": {"primary": ["python", "llm"], "avoid_primary": []},
    }


class TestCollect(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["YOKE_HOME"] = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()
        os.environ["YOKE_HOME"] = _TMP

    def test_norm_shape(self):
        j = collect.norm("  Engineer ", " Acme ", " Remote ", " https://x.com/1 ", "fake")
        self.assertEqual(
            j,
            {
                "title": "Engineer",
                "company": "Acme",
                "location": "Remote",
                "url": "https://x.com/1",
                "source": "fake",
                "posted_at": "",
                "comp": None,
                "jd": "",
            },
        )
        # comp passes through untouched: dict or str
        comp = {"min": 50, "max": 60, "currency": "usd", "unit": "hour"}
        self.assertEqual(collect.norm("t", "c", "l", "u", "s", comp=comp)["comp"], comp)
        self.assertEqual(collect.norm("t", "c", "l", "u", "s", comp="$5k/mo")["comp"], "$5k/mo")
        # jd is optional plain text; defaults "" and passes through
        self.assertEqual(collect.norm("t", "c", "l", "u", "s", jd="Build things.")["jd"], "Build things.")
        self.assertEqual(collect.norm("t", "c", "l", "u", "s", jd=None)["jd"], "")

    def test_strip_html_and_jd_cap(self):
        # tags stripped, entities unescaped, whitespace collapsed
        self.assertEqual(
            collect.strip_html("<p>Build   <b>APIs</b> &amp; pipelines.</p>"),
            "Build APIs & pipelines.",
        )
        # greenhouse ships HTML-escaped HTML — unescape happens BEFORE tag-strip
        self.assertEqual(
            collect.strip_html("&lt;p&gt;Build backend systems.&lt;/p&gt;"),
            "Build backend systems.",
        )
        self.assertEqual(collect.strip_html(None), "")
        self.assertEqual(collect.strip_html(""), "")
        # convention: plugins cap jd at JD_MAX_CHARS to keep _index.json bounded
        self.assertEqual(collect.JD_MAX_CHARS, 8000)
        capped = collect.strip_html("<p>" + "x" * 9000 + "</p>")[: collect.JD_MAX_CHARS]
        self.assertEqual(len(capped), 8000)

    def test_update_index_carries_jd(self):
        j = collect.norm("Backend Engineer", "Acme", "Remote, Europe",
                         "https://x.com/1", "s", jd="Build backend systems.")
        index = collect.update_index([j], {})
        entry = index[collect.job_key(j)]
        self.assertEqual(entry["jd"], "Build backend systems.")
        # a later jd-less sighting must not wipe the stored jd
        bare = collect.norm("Backend Engineer", "Acme", "Remote, Europe",
                            "https://x.com/1", "s")
        index = collect.update_index([bare], index)
        self.assertEqual(index[collect.job_key(j)]["jd"], "Build backend systems.")

    def test_job_key_url_and_fallback(self):
        j = collect.norm("T", "C", "L", "https://X.com/Job-1", "s")
        self.assertEqual(collect.job_key(j), "https://x.com/job-1")
        j2 = collect.norm("Engineer", "Acme", "", "", "s")
        self.assertEqual(collect.job_key(j2), "acme|engineer")

    def test_role_key_collapses_reposts(self):
        a = collect.norm("Senior Engineer (Remote)", "Acme", "Berlin", "u1", "s")
        b = collect.norm("Senior Engineer - Remote", "Acme", "Warsaw", "u2", "s")
        self.assertEqual(collect.role_key(a), collect.role_key(b))
        self.assertEqual(collect.role_key(a), "acme|senior engineer remote")

    def test_matches_profile_geo_block(self):
        j = collect.norm("Backend Engineer", "Acme", "Moscow, Russia", "u", "s")
        ok, score = collect.matches_profile(j, _profile())
        self.assertFalse(ok)
        self.assertEqual(score, 0)

    def test_matches_profile_ukraine_not_uk(self):
        # " uk" marker must not fire inside "ukraine" (word-boundary matching)
        p = _profile()
        for loc in ("Kyiv, Ukraine", "Remote, Ukraine"):
            j = collect.norm("Backend Engineer", "Acme", loc, "u://" + loc, "s")
            self.assertTrue(collect.matches_profile(j, p)[0], loc)
        # real UK-only stays rejected
        uk = collect.norm("Backend Engineer", "Acme", "London, UK", "u2", "s")
        self.assertFalse(collect.matches_profile(uk, p)[0])

    def test_matches_profile_country_unblocks_uk(self):
        # a London/UK role is rejected today (non-EU marker, no EU term alongside)
        uk = collect.norm("Backend Engineer", "Acme", "London, UK", "u", "s")
        self.assertFalse(collect.matches_profile(uk, _profile())[0])
        # selecting countries=["uk"] un-blocks the same role
        p = _profile()
        p["countries"] = ["uk"]
        ok, score = collect.matches_profile(uk, p)
        self.assertTrue(ok)
        self.assertGreaterEqual(score, 2)

    def test_matches_profile_empty_countries_unchanged(self):
        # no countries key -> a US role is still rejected (identical to today)
        us = collect.norm("Backend Engineer", "Acme", "San Francisco, US", "u", "s")
        self.assertFalse(collect.matches_profile(us, _profile())[0])
        # explicit empty list behaves the same
        p = _profile()
        p["countries"] = []
        self.assertFalse(collect.matches_profile(us, p)[0])
        # the "uk" target marker must not fire inside "ukraine" (word-boundary)
        self.assertFalse(
            collect._has_geo_marker("kyiv, ukraine", collect.COUNTRY_MARKERS["uk"])
        )
        # and selecting uk does not spuriously reject a real Ukraine (EU) role
        p["countries"] = ["uk"]
        ua = collect.norm("Backend Engineer", "Acme", "Kyiv, Ukraine", "u", "s")
        self.assertTrue(collect.matches_profile(ua, p)[0])

    def test_country_markers_cover_queryable_countries(self):
        markers = collect.COUNTRY_MARKERS
        for code, terms in markers.items():
            self.assertIsInstance(terms, list)
            self.assertTrue(terms, code)  # non-empty
            self.assertEqual(code, code.lower())  # lowercase
            self.assertEqual(len(code), 2)  # ISO-2
        self.assertIn("de", markers)  # M1 sources route on "de"
        self.assertIn("uk", markers)  # relocation target

    def test_matches_profile_lane_required(self):
        p = _profile()
        miss = collect.norm("Accountant", "Acme", "Remote, Europe", "u", "s")
        self.assertFalse(collect.matches_profile(miss, p)[0])

        hit = collect.norm("Backend Engineer", "Acme", "Remote, Europe", "u", "s")
        ok, score = collect.matches_profile(hit, p)
        self.assertTrue(ok)
        self.assertGreaterEqual(score, 2)  # 2 per lane keyword hit

        # bypass_lane: no lane keyword in title, but a tech hit keeps it
        hn = collect.norm("Python wizard wanted", "Acme", "Remote, Europe", "u", "hn")
        self.assertFalse(collect.matches_profile(hn, p)[0])
        ok_b, score_b = collect.matches_profile(hn, p, bypass_lane=True)
        self.assertTrue(ok_b)
        self.assertGreaterEqual(score_b, 1)

    def test_anti_lane_rejects(self):
        j = collect.norm("Backend Engineer Intern", "Acme", "Remote, Europe", "u", "s")
        ok, score = collect.matches_profile(j, _profile())
        self.assertFalse(ok)

    def test_update_index_stamps_and_prunes(self):
        j = collect.norm("Backend Engineer", "Acme", "Remote, Europe", "https://x.com/1", "s")
        j["_score"] = 3
        index = collect.update_index([j], {})
        k = collect.job_key(j)
        entry = index[k]
        self.assertEqual(entry["first_seen"], entry["last_seen"])
        datetime.fromisoformat(entry["first_seen"])  # valid ISO
        self.assertEqual(entry["role_key"], collect.role_key(j))

        # earliest first_seen is kept on re-scan; last_seen refreshed
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        index[k]["first_seen"] = old
        index[k]["last_seen"] = old
        index = collect.update_index([j], index)
        self.assertEqual(index[k]["first_seen"], old)
        self.assertGreater(index[k]["last_seen"], old)

        # entries unseen for >45 days get pruned
        stale = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        index["stale-key"] = {"first_seen": stale, "last_seen": stale}
        index = collect.update_index([], index)
        self.assertNotIn("stale-key", index)
        self.assertIn(k, index)

    def test_run_collect_source_error_isolated(self):
        good_jobs = [
            collect.norm("Backend Engineer", "Acme", "Remote, Europe", "https://x.com/1", "good")
        ]
        good = SimpleNamespace(
            NAME="good", TAGS={"domain": "it", "country": "any"}, COST="free",
            available=lambda: (True, ""), fetch=lambda profile: good_jobs,
        )

        def _boom(profile):
            raise RuntimeError("boom")

        bad = SimpleNamespace(
            NAME="bad", TAGS={"domain": "it", "country": "any"}, COST="free",
            available=lambda: (True, ""), fetch=_boom,
        )
        logged = []
        with mock.patch.object(collect, "load_sources", return_value=[good, bad]):
            results = collect.run_collect(_profile(), ["good", "bad"], logged.append)

        self.assertEqual(results["good"], "1 roles")
        self.assertTrue(results["bad"].startswith("ERROR"))
        self.assertIn("boom", results["bad"])

        index = json.loads((paths.home() / "_index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(index), 1)
        snapshots = list((paths.home() / "scans").glob("*.json"))
        self.assertEqual(len(snapshots), 1)


if __name__ == "__main__":
    unittest.main()

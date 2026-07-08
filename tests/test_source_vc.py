import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="yoke-test-vc-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.sources import ats, vc  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestVcContract(unittest.TestCase):
    def test_module_contract(self):
        self.assertEqual(vc.NAME, "vc")
        self.assertEqual(vc.TAGS, {"domain": "any", "country": "any"})
        self.assertEqual(vc.COST, "free")
        self.assertEqual(vc.available(), (True, ""))
        self.assertEqual(vc.CAP, 40)


class TestVcProbe(unittest.TestCase):
    def test_probe_returns_first_valid_provider(self):
        # greenhouse (first in _URLS) is down; lever answers with a parseable
        # list -> the first provider that yields >=1 role wins.
        jobs_list = _fixture("vc_probe.json")["jobs"]  # a list -> lever parser bites

        def fake_get_json(url):
            if "greenhouse" in url:
                raise ats.http.Blocked("429")
            if "lever" in url:
                return jobs_list
            raise OSError("no board here")

        with mock.patch.object(ats, "_get_json", side_effect=fake_get_json):
            self.assertEqual(vc._probe("stripe"), "lever")

    def test_probe_none_when_all_fail(self):
        def boom(url):
            raise OSError("dead")

        with mock.patch.object(ats, "_get_json", side_effect=boom), \
                mock.patch.object(ats, "_get_xml", side_effect=boom):
            self.assertEqual(vc._probe("nobody"), "none")


class TestVcFetch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="yoke-test-vc-fetch-")
        os.environ["YOKE_HOME"] = self._tmp

    def tearDown(self):
        os.environ["YOKE_HOME"] = _TMP
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_cache_short_circuits_reprobe(self):
        companies = [{"slug": "a", "name": "A"}, {"slug": "b", "name": "B"}]
        calls = []

        def counting_probe(slug):
            calls.append(slug)
            return "none"

        with mock.patch.object(vc, "_load_yc", return_value=companies), \
                mock.patch.object(vc, "_load_a16z", return_value=[]), \
                mock.patch.object(vc, "_probe", side_effect=counting_probe):
            vc.fetch({})
            vc.fetch({})  # second run reads the persisted cache

        self.assertEqual(sorted(calls), ["a", "b"])  # each slug probed exactly once
        self.assertEqual(vc._cache_load(), {"a": "none", "b": "none"})

    def test_none_slugs_skipped_on_fetch(self):
        vc._cache_save({"deadco": "none"})
        companies = [{"slug": "deadco", "name": "Dead"}]
        calls = []

        with mock.patch.object(vc, "_load_yc", return_value=companies), \
                mock.patch.object(vc, "_load_a16z", return_value=[]), \
                mock.patch.object(vc, "_probe", side_effect=lambda s: calls.append(s)):
            roles = vc.fetch({})

        self.assertEqual(calls, [])   # cached "none" slug is not re-probed
        self.assertEqual(roles, [])   # and it emits no roles

    def test_emits_roles_via_ats_parser(self):
        vc._cache_save({"stripe": "greenhouse"})
        probe_fixture = _fixture("vc_probe.json")  # real greenhouse {jobs, meta}
        companies = [{"slug": "stripe", "name": "Stripe"}]

        with mock.patch.object(vc, "_load_yc", return_value=companies), \
                mock.patch.object(vc, "_load_a16z", return_value=[]), \
                mock.patch.object(ats, "_get_json", return_value=probe_fixture):
            roles = vc.fetch({})

        self.assertTrue(roles)
        role = roles[0]
        self.assertEqual(role["source"], "ats:greenhouse:stripe")
        self.assertEqual(role["company"], "Stripe")
        self.assertEqual(
            set(role),
            {"title", "company", "location", "url", "source", "posted_at", "comp", "jd"},
        )


if __name__ == "__main__":
    unittest.main()

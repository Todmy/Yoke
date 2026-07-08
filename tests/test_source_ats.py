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


def _xml_fixture(name):
    from defusedxml.ElementTree import fromstring
    return fromstring((FIXTURES / name).read_bytes())


def _xml_fixture_from(text):
    from defusedxml.ElementTree import fromstring
    return fromstring(text)


def _assert_comp_shape(case, comp):
    """comp is either None or the canonical structured dict — never a string."""
    if comp is not None:
        case.assertIsInstance(comp, dict)
        case.assertEqual(set(comp), {"min", "max", "currency", "unit", "type"})


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


class TestNewAtsProviders(unittest.TestCase):
    def test_ats_personio_parse(self):
        company = {"slug": "getquin"}
        jobs = ats._parse_personio(_xml_fixture("ats_personio.xml"), company)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(
            jobs[0],
            {
                "title": "Business Development Manager (f/m/d)",
                "company": "getquin",
                "location": "Berlin",
                "url": "https://getquin.jobs.personio.de/job/2334688",
                "source": "ats:personio:getquin",
                "posted_at": "2025-09-12T18:32:55+00:00",
                "comp": None,
                "jd": "At getquin, we’re on a mission to empower everyone to build wealth.",
            },
        )
        _assert_comp_shape(self, jobs[0]["comp"])
        # jd came out of CDATA'd HTML tag-stripped, and the second role is populated too
        self.assertNotIn("<", jobs[0]["jd"])
        self.assertTrue(jobs[1]["jd"])
        self.assertNotIn("<", jobs[1]["jd"])
        # a <position> with no jobDescriptions → jd stays ""
        empty = _xml_fixture_from(
            "<workzag-jobs><position><id>9</id><office>Berlin</office>"
            "<name>Role</name><createdAt>2026</createdAt></position></workzag-jobs>"
        )
        self.assertEqual(ats._parse_personio(empty, company)[0]["jd"], "")
        # malformed root → empty list, never a raise
        self.assertEqual(ats._parse_personio(None, company), [])
        self.assertEqual(
            ats._parse_personio(_xml_fixture_from("<empty/>"), company), []
        )

    def test_ats_smartrecruiters_parse(self):
        company = {"slug": "Visa"}
        jobs = ats._parse_smartrecruiters(_fixture("ats_smartrecruiters.json"), company)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(
            jobs[0],
            {
                "title": "Sr. Manager",
                "company": "Visa",
                "location": "Austin, TX, United States",
                "url": "https://jobs.smartrecruiters.com/Visa/744000133907678",
                "source": "ats:smartrecruiters:Visa",
                "posted_at": "2026-06-24T10:00:11.853Z",
                "comp": None,
                "jd": "",
            },
        )
        _assert_comp_shape(self, jobs[0]["comp"])
        # the postings-list endpoint carries no description → jd is empty
        self.assertEqual(jobs[1]["jd"], "")
        # malformed payload → empty list, never a raise
        self.assertEqual(ats._parse_smartrecruiters({}, company), [])
        self.assertEqual(ats._parse_smartrecruiters(None, company), [])

    def test_ats_workable_parse(self):
        company = {"slug": "zego"}
        jobs = ats._parse_workable(_fixture("ats_workable.json"), company)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(
            jobs[0],
            {
                "title": "Claims Data Analyst",
                "company": "zego",
                "location": "London, United Kingdom",
                "url": "https://apply.workable.com/j/2446BEA4E2",
                "source": "ats:workable:zego",
                "posted_at": "2026-07-06",
                "comp": None,
                "jd": "",
            },
        )
        _assert_comp_shape(self, jobs[0]["comp"])
        # widget feed carries neither salary nor description
        self.assertIsNone(jobs[1]["comp"])
        self.assertEqual(jobs[1]["jd"], "")
        # a non-dict / wrong-key payload → empty list
        self.assertEqual(ats._parse_workable({"error": "nope"}, company), [])
        self.assertEqual(ats._parse_workable([], company), [])

    def test_ats_recruitee_parse(self):
        company = {"slug": "bunq"}
        jobs = ats._parse_recruitee(_fixture("ats_recruitee.json"), company)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(
            jobs[0],
            {
                "title": "Head of Trust & Transparency",
                "company": "bunq",
                "location": "Amsterdam, Noord-Holland, Netherlands",
                "url": "https://careers.bunq.com/o/head-of-trust-transparency",
                "source": "ats:recruitee:bunq",
                "posted_at": "2026-07-03 16:23:27 UTC",
                "comp": None,
                "jd": "At bunq \U0001f308, users trust us with her money across 30+ countries.",
            },
        )
        _assert_comp_shape(self, jobs[0]["comp"])
        # description came out of HTML tag-stripped
        self.assertNotIn("<", jobs[0]["jd"])
        # null-valued salary object → comp None (not an empty dict)
        self.assertIsNone(jobs[1]["comp"])
        # malformed payload → empty list, never a raise
        self.assertEqual(ats._parse_recruitee({}, company), [])
        self.assertEqual(ats._parse_recruitee([], company), [])

    def test_ats_recruitee_comp_is_structured_dict_when_salary_present(self):
        # a real recruitee salary object → the canonical {min,max,currency,unit,type}
        payload = {"offers": [{
            "title": "Data Engineer",
            "careers_url": "https://acme.recruitee.com/o/data-engineer",
            "location": "Berlin, Germany",
            "published_at": "2026-07-01 09:00:00 UTC",
            "employment_type_code": "fulltime_permanent",
            "salary": {"min": 70000, "max": 90000, "period": "yearly", "currency": "EUR"},
            "description": "<p>Own the pipelines.</p>",
        }]}
        jobs = ats._parse_recruitee(payload, {"slug": "acme"})
        self.assertEqual(
            jobs[0]["comp"],
            {"min": 70000, "max": 90000, "currency": "eur",
             "unit": "year", "type": "fulltime_permanent"},
        )
        _assert_comp_shape(self, jobs[0]["comp"])

    def test_ats_personio_rejects_entity_expansion(self):
        from unittest import mock

        from defusedxml.common import EntitiesForbidden

        bomb = (FIXTURES / "ats_personio_billionlaughs.xml").read_bytes()
        # _get_xml parses untrusted network bytes with defusedxml → expansion refused
        with mock.patch.object(ats.http, "fetch_bytes", return_value=bomb):
            with self.assertRaises(EntitiesForbidden):
                ats._get_xml("https://evil.jobs.personio.de/xml")
        # and through fetch() the company SKIPs rather than expanding / crashing
        import io
        from contextlib import redirect_stderr
        profile = {"sources": {"companies": [{"slug": "evil", "ats": "personio"}]}}
        with mock.patch.object(ats.http, "fetch_bytes", return_value=bomb):
            with redirect_stderr(io.StringIO()):
                jobs = ats.fetch(profile)
        self.assertEqual(jobs, [])


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

    def test_new_providers_dead_company_does_not_kill_the_source(self):
        import io
        from contextlib import redirect_stderr
        from unittest import mock

        good_offers = {"offers": [{"title": "Backend Engineer",
                                   "careers_url": "https://live.recruitee.com/o/be",
                                   "location": "Amsterdam", "published_at": "2026-07-01"}]}
        root = _xml_fixture_from(
            "<workzag-jobs><position><id>7</id><office>Berlin</office>"
            "<name>Platform Engineer</name><createdAt>2026-07-01</createdAt>"
            "</position></workzag-jobs>"
        )

        def fake_json(url):  # recruitee getter
            if "dead" in url:
                raise OSError("HTTP Error 404: Not Found")
            return good_offers

        def fake_xml(url):   # personio getter
            return root

        profile = {"sources": {"companies": [
            {"slug": "dead", "ats": "recruitee"},   # raises → SKIP
            {"slug": "live", "ats": "recruitee"},   # via _get_json
            {"slug": "getquin", "ats": "personio"},  # via _get_xml
        ]}}
        with mock.patch.object(ats, "_get_json", side_effect=fake_json), \
                mock.patch.object(ats, "_get_xml", side_effect=fake_xml):
            with redirect_stderr(io.StringIO()):
                jobs = ats.fetch(profile)
        self.assertEqual(len(jobs), 2)
        self.assertEqual({j["company"] for j in jobs}, {"live", "getquin"})


if __name__ == "__main__":
    unittest.main()

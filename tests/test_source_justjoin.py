import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="yoke-test-justjoin-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.sources import justjoin  # noqa: E402

_FIXTURE = Path(__file__).parent / "fixtures" / "justjoin.json"


def _payload():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


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


if __name__ == "__main__":
    unittest.main()

import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="yoke-test-comp-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src import comp  # noqa: E402


class TestNormalize(unittest.TestCase):
    def test_hourly_b2b_usd(self):
        out = comp.normalize(
            {"min": 50, "max": 60, "currency": "usd", "unit": "hour", "type": "b2b"}
        )
        self.assertEqual(out["usd_min_mo"], 50 * comp.HOURS_PER_MO)  # 8400
        self.assertEqual(out["usd_max_mo"], 60 * comp.HOURS_PER_MO)  # 10080
        self.assertEqual(out["unit_detected"], "hour")

    def test_yearly_permanent_eur_net_factor(self):
        out = comp.normalize(
            {"min": 120000, "max": 180000, "currency": "eur", "unit": "year",
             "type": "permanent"}
        )
        # 120000/12 * 1.08 * 0.72 = 7776 ; 180000/12 * 1.08 * 0.72 = 11664
        self.assertEqual(out["usd_min_mo"], round(120000 / 12 * 1.08 * 0.72))
        self.assertEqual(out["usd_max_mo"], round(180000 / 12 * 1.08 * 0.72))

    def test_pln_month(self):
        out = comp.normalize(
            {"min": 20000, "max": 30000, "currency": "pln", "unit": "month",
             "type": "b2b"}
        )
        self.assertEqual(out["usd_min_mo"], 5000)
        self.assertEqual(out["usd_max_mo"], 7500)
        self.assertEqual(out["unit_detected"], "month")

    def test_raw_string_parse(self):
        out = comp.normalize({"raw": "150 - 200 PLN/h net B2B"})
        # 150 * 168 * 0.25 = 6300 ; 200 * 168 * 0.25 = 8400
        self.assertEqual(out["unit_detected"], "hour")
        self.assertEqual(out["usd_min_mo"], 6300)
        self.assertEqual(out["usd_max_mo"], 8400)

    def test_raw_b2b_suffix_not_max(self):
        # digits embedded in words ("b2b") must not be read as the max
        out = comp.normalize({"raw": "12 000 USD/month B2B"})
        self.assertEqual(out["usd_min_mo"], 12000)
        self.assertEqual(out["usd_max_mo"], 12000)
        self.assertEqual(out["floor_verdict"], "above")

    def test_floor_verdicts(self):
        # above: both ends >= floor
        above = comp.normalize(
            {"min": 12000, "max": 15000, "currency": "usd", "unit": "month",
             "type": "b2b"}
        )
        self.assertEqual(above["floor_verdict"], "above")
        # straddles: min below floor, max above
        straddles = comp.normalize(
            {"min": 8000, "max": 12000, "currency": "usd", "unit": "month",
             "type": "b2b"}
        )
        self.assertEqual(straddles["floor_verdict"], "straddles")
        # below: both ends under floor
        below = comp.normalize(
            {"min": 4000, "max": 6000, "currency": "usd", "unit": "month",
             "type": "b2b"}
        )
        self.assertEqual(below["floor_verdict"], "below")
        # unknown: no salary figure at all
        unknown = comp.normalize({"currency": "usd"})
        self.assertEqual(unknown["floor_verdict"], "unknown")
        self.assertIsNone(unknown["usd_min_mo"])

    def test_justjoin_hourly_regression(self):
        # The _jj_comp bug class: an hourly 50-60 USD offer must NOT be read
        # as $50-60/month. Unit-aware conversion must land in thousands.
        out = comp.normalize(
            {"min": 50, "max": 60, "currency": "usd", "unit": "hour", "type": "b2b"}
        )
        self.assertNotEqual(out["usd_min_mo"], 50)
        self.assertNotEqual(out["usd_max_mo"], 60)
        self.assertGreaterEqual(out["usd_min_mo"], 8000)
        # 50-60/h straddles the $10k floor, it is not "below"
        self.assertNotEqual(out["floor_verdict"], "below")


if __name__ == "__main__":
    unittest.main()

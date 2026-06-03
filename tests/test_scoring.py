"""T006 — cutline single-source + score_fit/tier_of boundaries (spec Δ3, FR-004).

Run: python3 -m unittest discover -s tests
Stdlib unittest only (zero-dependency, per constitution VII / research R1).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("YOKE_HOME", tempfile.mkdtemp(prefix="yoke-test-"))
SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import scoring  # noqa: E402
from analyze import tier_of, score_fit, label_of, comp_display  # noqa: E402
from analyze import THRESHOLD as ANALYZE_THRESHOLD, TIER_A as ANALYZE_TIER_A  # noqa: E402

# representative weights (mirror store.DEFAULT_WEIGHTS) so score_fit needs no DB
W = {"lane_in": 50, "lane_adjacent": 30, "diff_per_hit": 7, "diff_cap": 5,
     "seniority_ok": 10, "seniority_no": -5, "lang_ok": 5, "lang_no": -20, "emp_no": -20}


class TestCutlineSingleSource(unittest.TestCase):
    """The board (analyze.tier_of) and the tuner (tune) must read the SAME cutlines."""

    def test_analyze_uses_scoring_constants(self):
        self.assertEqual(ANALYZE_THRESHOLD, scoring.THRESHOLD)
        self.assertEqual(ANALYZE_TIER_A, scoring.TIER_A)

    def test_tune_uses_scoring_threshold(self):
        import tune
        self.assertEqual(tune.THRESHOLD, scoring.THRESHOLD)


class TestTierBoundaries(unittest.TestCase):
    def test_a_requires_threshold_and_remote(self):
        self.assertEqual(tier_of(scoring.TIER_A, "remote", False), "A")
        self.assertEqual(tier_of(scoring.TIER_A, "verify", False), "B")  # 70 + verify → B, not A

    def test_b_at_threshold(self):
        self.assertEqual(tier_of(scoring.THRESHOLD, "verify", False), "B")
        self.assertEqual(tier_of(scoring.THRESHOLD - 1, "verify", False), "C")  # below worth-pursuing
        self.assertEqual(tier_of(scoring.TIER_A - 1, "remote", False), "B")     # strong but <A

    def test_gates_force_c(self):
        self.assertEqual(tier_of(99, "blocked", False), "C")   # geo gate dominates
        self.assertEqual(tier_of(99, "remote", True), "C")     # comp-floor gate dominates


class TestLabelHonoursGeoGate(unittest.TestCase):
    """The fit-band label must never overstate a role the geo gate hasn't cleared
    (truthfulness, FR-014): a high-fit but geo=verify role is tier B, so its label
    is demoted from 'Top candidate' to 'Strong'. The verify state is carried by the
    adjacent geo cell, so the label itself stays free of a redundant suffix."""
    def test_top_candidate_requires_remote(self):
        self.assertEqual(label_of(93, "remote"), "🟢 Top candidate")
        self.assertEqual(label_of(93, "verify"), "🟢 Strong")   # demoted, no "Top candidate"

    def test_lower_bands_geo_agnostic(self):
        self.assertEqual(label_of(60, "verify"), "🟡 Good")
        self.assertEqual(label_of(60, "remote"), "🟡 Good")

    def test_remote_bands_unchanged(self):
        self.assertEqual(label_of(72, "remote"), "🟢 Strong")
        self.assertEqual(label_of(60, "remote"), "🟡 Good")


class TestCompDisplayFlagsEstimate(unittest.TestCase):
    """A model-estimated comp must be flagged 'est', never shown as a scraped fact
    (ed66a591). Scraped comp shows bare; below-floor adds the gate marker."""
    def test_estimate_flagged(self):
        self.assertEqual(comp_display("~$6-9k", True, False), "~$6-9k est")

    def test_scraped_bare(self):
        self.assertEqual(comp_display("$8k", False, False), "$8k")

    def test_missing_not_flagged(self):
        self.assertEqual(comp_display(None, True, False), "? [research]")  # no comp → no "est"

    def test_below_floor_marker(self):
        self.assertEqual(comp_display("$4k", False, True), "$4k ⛔<floor")


class TestScoreFit(unittest.TestCase):
    def test_bounds_0_100(self):
        worst = score_fit({"lane_match": "out", "differentiator_hits": 0, "seniority_ok": False,
                            "lang_ok": False, "employer_winnable": False}, W)
        best = score_fit({"lane_match": "in", "differentiator_hits": 5, "seniority_ok": True,
                          "lang_ok": True, "employer_winnable": True}, W)
        self.assertGreaterEqual(worst, 0)
        self.assertLessEqual(best, 100)
        self.assertGreater(best, worst)

    def test_lane_monotonic(self):
        base = {"differentiator_hits": 2, "seniority_ok": True, "lang_ok": True, "employer_winnable": True}
        self.assertGreater(score_fit({**base, "lane_match": "in"}, W),
                           score_fit({**base, "lane_match": "adjacent"}, W))


if __name__ == "__main__":
    unittest.main()

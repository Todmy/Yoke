import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="yoke-test-scoring-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src import scoring  # noqa: E402


class TestFit(unittest.TestCase):
    def test_fit_weighted_sum(self):
        weights = {"lane": 40, "tech": 30, "comp_vs_floor": 30}
        scores = {"lane": 100, "tech": 50, "comp_vs_floor": 0}
        # 40*100/100 + 30*50/100 + 30*0/100 = 40 + 15 + 0 = 55
        self.assertEqual(scoring.fit(scores, weights), 55)

    def test_fit_missing_feature_zero(self):
        weights = {"lane": 60, "tech": 40}
        scores = {"lane": 100}  # tech missing → contributes 0
        self.assertEqual(scoring.fit(scores, weights), 60)
        # extra score keys not in weights are ignored
        scores_extra = {"lane": 100, "rogue": 100}
        self.assertEqual(scoring.fit(scores_extra, weights), 60)

    def test_fit_clamped(self):
        weights = {"lane": 100}
        self.assertEqual(scoring.fit({"lane": 150}, weights), 100)
        self.assertEqual(scoring.fit({"lane": -50}, weights), 0)


class TestTier(unittest.TestCase):
    def test_tier_a_requires_geo_and_comp(self):
        self.assertEqual(scoring.tier_of(80, True, True, []), "A")
        self.assertEqual(scoring.tier_of(scoring.TIER_A, True, True, []), "A")
        # fit >= 70 but a hard condition off → not A
        self.assertNotEqual(scoring.tier_of(80, False, True, []), "A")
        self.assertNotEqual(scoring.tier_of(80, True, False, []), "A")

    def test_tier_b_friction_demotes_a(self):
        self.assertEqual(scoring.tier_of(80, True, True, ["verify geo"]), "B")
        # plain B band
        self.assertEqual(scoring.tier_of(60, True, True, []), "B")
        self.assertEqual(scoring.tier_of(scoring.TIER_B, True, True, []), "B")

    def test_tier_c_below_55(self):
        self.assertEqual(scoring.tier_of(54, True, True, []), "C")
        self.assertEqual(scoring.tier_of(0, True, True, []), "C")


if __name__ == "__main__":
    unittest.main()

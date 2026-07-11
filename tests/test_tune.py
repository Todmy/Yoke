import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="yoke-test-tune-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src import tune  # noqa: E402


def _pairs(applied, dropped):
    """applied/dropped are lists of score-dicts."""
    return [(s, "applied") for s in applied] + [(s, "dropped") for s in dropped]


class BalancedAccuracyTest(unittest.TestCase):
    def test_perfect_separation(self):
        pairs = _pairs([{"a": 90}], [{"a": 10}])
        self.assertEqual(tune.balanced_accuracy(pairs, {"a": 100}, 55), 1.0)

    def test_imbalance_predict_all_negative(self):
        # 2 applied, 10 dropped; weights push everything < 55 -> all predicted negative.
        pairs = _pairs([{"a": 10}] * 2, [{"a": 10}] * 10)
        # TPR=0 (both applied missed), TNR=1 -> BA 0.5, NOT the 0.83 plain accuracy would give.
        self.assertEqual(tune.balanced_accuracy(pairs, {"a": 100}, 55), 0.5)


class CompositionsTest(unittest.TestCase):
    def test_sum_and_step(self):
        comps = list(tune._compositions(["a", "b", "c"], 100, 25))
        self.assertTrue(comps)
        for c in comps:
            self.assertEqual(sum(c.values()), 100)
            for v in c.values():
                self.assertEqual(v % 25, 0)
        # count = C(4+2, 2) = 15
        self.assertEqual(len(comps), 15)


class RefitTest(unittest.TestCase):
    # applied: a-heavy; dropped: b-heavy. Base {a:50,b:50} can't separate; a-weight can.
    APPLIED = [{"a": 90, "b": 10}] * 5
    DROPPED = [{"a": 10, "b": 90}] * 5
    BASE = {"a": 50, "b": 50}

    def _pairs(self):
        return _pairs(self.APPLIED, self.DROPPED)

    def test_finds_known_optimum(self):
        res = tune.refit(self._pairs(), self.BASE)
        self.assertFalse(res["cold_start"])
        self.assertEqual(res["ba_before"], 0.5)
        self.assertEqual(res["ba_after"], 1.0)

    def test_tie_break_smallest_change(self):
        # a>=60 all reach BA 1.0; closest to base {50,50} is {a:60,b:40}.
        res = tune.refit(self._pairs(), self.BASE)
        self.assertEqual(res["after"], {"a": 60, "b": 40})

    def test_cold_start(self):
        pairs = _pairs([{"a": 90, "b": 10}] * 3, [{"a": 10, "b": 90}] * 5)
        res = tune.refit(pairs, self.BASE)
        self.assertTrue(res["cold_start"])
        self.assertEqual(res["after"], self.BASE)
        self.assertEqual(res["n"], {"applied": 3, "dropped": 5})

    def test_after_sums_100(self):
        res = tune.refit(self._pairs(), self.BASE)
        self.assertEqual(sum(res["after"].values()), 100)

    def test_deterministic(self):
        r1 = tune.refit(self._pairs(), self.BASE)
        r2 = tune.refit(self._pairs(), self.BASE)
        self.assertEqual(r1, r2)


if __name__ == "__main__":
    unittest.main()

"""T029 — tuner gate (Δ2) + applied-only positive class (Δ1), spec FR-017 / SC-004.

Stdlib unittest. Uses a throwaway YOKE_HOME so it never touches the real ~/.yoke.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("YOKE_HOME", tempfile.mkdtemp(prefix="yoke-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import tune  # noqa: E402

HI = {"lane_match": "in", "differentiator_hits": 5, "seniority_ok": True, "lang_ok": True, "employer_winnable": True}
LO = {"lane_match": "out", "differentiator_hits": 0, "seniority_ok": False, "lang_ok": False, "employer_winnable": False}


def labels(n_applied, n_rejected, n_interested=0):
    out = []
    out += [{"role_key": f"a{i}", "decision": "applied", "reason": "", "features": dict(HI)} for i in range(n_applied)]
    out += [{"role_key": f"r{i}", "decision": "rejected", "reason": "", "features": dict(LO)} for i in range(n_rejected)]
    out += [{"role_key": f"i{i}", "decision": "interested", "reason": "", "features": dict(HI)} for i in range(n_interested)]
    return out


class TestGate(unittest.TestCase):
    def test_declines_below_gate(self):
        res = tune.tune(labels(4, 4))
        self.assertFalse(res["ok"])
        self.assertIn("not enough", res["reason"])

    def test_accepts_at_gate(self):
        res = tune.tune(labels(10, 10))
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertEqual(res["n_pos"], 10)
        self.assertEqual(res["n_neg"], 10)
        # tuner never worsens the objective (only replaces on strict improvement)
        self.assertGreaterEqual(res["objective_after"], res["objective_before"])

    def test_total_counts_usable_labels_only(self):
        # 10 applied + 10 rejected meets total>=20; interested must NOT count toward it
        res = tune.tune(labels(6, 6, n_interested=50))
        self.assertFalse(res["ok"])  # 12 usable < 20 total, despite 50 interested


class TestPositiveClass(unittest.TestCase):
    def test_interested_excluded_from_positive(self):
        pos, neg = tune._split(labels(3, 3, n_interested=7))
        self.assertEqual(len(pos), 3)   # applied only — interested dropped
        self.assertEqual(len(neg), 3)


if __name__ == "__main__":
    unittest.main()

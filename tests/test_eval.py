"""T030 — eval: scorecard always produced; a seeded geo false-positive forces FAIL
regardless of fit closeness (SC-003, FR-016). Grades against curated `expected`.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("YOKE_HOME", tempfile.mkdtemp(prefix="yoke-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import eval as evalmod  # noqa: E402

FEATS = {"lane_match": "in", "differentiator_hits": 3, "seniority_ok": True, "lang_ok": True, "employer_winnable": True}


def card(geo_verdict="remote"):
    return {"company": "Acme", "title": "AI Engineer",
            "geo": {"verdict": geo_verdict}, "lane": {"verdict": "in"}, "comp": {"found": False}}


def fill(geo="remote"):
    return {"fit_features": dict(FEATS), "geo_verdict": geo, "comp_est_net_mo": None}


class TestEvaluate(unittest.TestCase):
    def test_seeded_geo_fp_forces_fail(self):
        c = card()
        truth = evalmod._score(fill("blocked"), c)   # curated truth: this role is geo-blocked
        items = [{"card": c, "ref": truth, "expected": truth}]
        # candidate wrongly says remote → geo false-positive → must FAIL
        report = evalmod.evaluate(items, lambda _c: fill("remote"))
        self.assertEqual(report["verdict"], "FAIL")
        self.assertGreaterEqual(report["hard_gates"]["geo_false_positive"], 1)
        self.assertFalse(report["hard_gates"]["pass"])

    def test_scorecard_always_returned(self):
        c = card()
        truth = evalmod._score(fill("remote"), c)
        items = [{"card": c, "ref": truth, "expected": truth}]
        report = evalmod.evaluate(items, lambda _c: fill("remote"))
        # agreement on a clean item → no safety violation
        self.assertEqual(report["hard_gates"]["geo_false_positive"], 0)
        self.assertIn(report["verdict"], ("PASS", "FAIL"))
        self.assertEqual(report["n"], 1)

    def test_parse_failure_is_a_gate(self):
        c = card()
        truth = evalmod._score(fill("remote"), c)
        items = [{"card": c, "ref": truth, "expected": truth}]

        def boom(_c):
            raise ValueError("bad json")
        report = evalmod.evaluate(items, boom)
        self.assertEqual(report["hard_gates"]["parse_fail"], 1)
        self.assertEqual(report["verdict"], "FAIL")


if __name__ == "__main__":
    unittest.main()

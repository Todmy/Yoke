import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="yoke-test-eval-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src import eval as ev  # noqa: E402

_FIX = Path(__file__).resolve().parent / "fixtures"


def _golden():
    return json.loads((_FIX / "golden.json").read_text(encoding="utf-8"))


def _run():
    return json.loads((_FIX / "eval_run.json").read_text(encoding="utf-8"))


class ScoreTest(unittest.TestCase):
    def test_score_safety_clean_fixture(self):
        card = ev.score(_run(), _golden())
        self.assertEqual(card["verdict"], "safety-clean")
        self.assertEqual(card["safety"]["total"], 0)
        self.assertEqual(card["n"], 4)
        self.assertEqual(card["backend"], "mock")

    def test_geo_false_positive_flips_verdict(self):
        run = _run()
        # g2 truth is onsite; model now claims remote_confirmed -> false positive
        run["roles"][1]["geo"] = "remote_confirmed"
        card = ev.score(run, _golden())
        self.assertEqual(card["safety"]["geo_false_positive"], 1)
        self.assertEqual(card["verdict"], "safety-fail")

    def test_tier_over_promotion_counts(self):
        run = _run()
        run["roles"][1]["tier"] = "A"  # truth C -> over-promotion
        card = ev.score(run, _golden())
        self.assertGreaterEqual(card["safety"]["tier_over_promotion"], 1)
        self.assertEqual(card["verdict"], "safety-fail")

    def test_dimension_agreement_math(self):
        run = _run()
        run["roles"][0]["geo"] = "onsite"  # break 1 of 4 geo agreements
        card = ev.score(run, _golden())
        self.assertEqual(card["dimensions"]["geo"]["agreement"], 0.75)

    def test_red_flag_recall_precision(self):
        card = ev.score(_run(), _golden())
        rf = card["dimensions"]["red_flags"]
        self.assertEqual(rf["recall"], 1.0)
        self.assertEqual(rf["precision"], 1.0)

    def test_feature_mae_present_when_truth_features(self):
        card = ev.score(_run(), _golden())
        # g1 |80-80|=0, g4 |62-60|=2 -> mean 1.0
        self.assertEqual(card["dimensions"]["features"]["hire_probability"]["mae"], 1.0)

    def test_feature_block_absent_when_no_truth_features(self):
        golden = copy.deepcopy(_golden())
        for g in golden:
            g["truth"].pop("features", None)
        card = ev.score(_run(), golden)
        self.assertNotIn("features", card["dimensions"])

    def test_unparseable_when_model_role_missing(self):
        run = _run()
        run["roles"] = run["roles"][:3]  # drop g4's model output
        card = ev.score(run, _golden())
        self.assertEqual(card["safety"]["unparseable"], 1)

    def test_score_zero_model_calls(self):
        from src import yoke
        with mock.patch.object(yoke.llm, "get_backend",
                               side_effect=AssertionError("real backend constructed")):
            card = ev.score(_run(), _golden())
        self.assertEqual(card["verdict"], "safety-clean")

    def test_load_golden_reads_home(self):
        from src.paths import home
        os.environ["YOKE_HOME"] = tempfile.mkdtemp(prefix="yoke-test-eval-")
        (home() / ev.GOLDEN_FILE).write_text(json.dumps(_golden()), encoding="utf-8")
        self.assertEqual(len(ev.load_golden()), 4)


if __name__ == "__main__":
    unittest.main()

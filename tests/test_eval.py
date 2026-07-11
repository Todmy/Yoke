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

    def test_empty_geo_is_unparseable(self):
        # analysis-failed golden role: analyze emits geo="" — must count as a
        # safety hit, not read as clean (review M3).
        run = _run()
        run["roles"][3]["geo"] = ""
        card = ev.score(run, _golden())
        self.assertEqual(card["safety"]["unparseable"], 1)
        self.assertEqual(card["verdict"], "safety-fail")

    def test_score_skips_non_dict_golden(self):
        golden = _golden() + ["GARBAGE"]
        card = ev.score(_run(), golden)  # must not raise
        self.assertEqual(card["n"], 4)  # the string row excluded

    def test_score_skips_non_dict_model_role(self):
        run = _run()
        run["roles"].append("GARBAGE")
        card = ev.score(run, _golden())  # must not raise
        self.assertEqual(card["verdict"], "safety-clean")

    def test_load_golden_skips_non_dict(self):
        from src.paths import home
        os.environ["YOKE_HOME"] = tempfile.mkdtemp(prefix="yoke-test-eval-")
        (home() / ev.GOLDEN_FILE).write_text(
            json.dumps([{"key": "g1"}, "junk", 7]), encoding="utf-8")
        self.assertEqual(ev.load_golden(), [{"key": "g1"}])

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


_PROFILE = {
    "countries": ["pl"],
    "comp": {"floor_net_usd_mo": 5000},
    "scoring": {
        "features": [{"name": "hire_probability", "weight": 60, "desc": "will they hire"}],
        "deterministic": [{"name": "comp_vs_floor", "weight": 40}],
    },
}


class RecordRenderTest(unittest.TestCase):
    def setUp(self):
        from src.paths import home
        os.environ["YOKE_HOME"] = tempfile.mkdtemp(prefix="yoke-test-eval-")
        (home() / "profile.json").write_text(json.dumps(_PROFILE), encoding="utf-8")

    def _backend(self):
        from src.yoke import MockBackend
        return MockBackend(["hire_probability"])

    def test_record_via_mock_backend(self):
        from src.paths import home
        run = ev.record(_golden(), self._backend())
        self.assertEqual(len(run["roles"]), 4)
        self.assertTrue((home() / ev.EVAL_RUN_FILE).is_file())
        self.assertIn("key", run["roles"][0])
        self.assertIn("features", run["roles"][0])

    def test_record_sets_backend_describe(self):
        run = ev.record(_golden(), self._backend())
        self.assertEqual(run["backend"], "mock (no model call)")

    def test_render_scorecard_safety_before_fit(self):
        out = ev.render_scorecard(ev.score(_run(), _golden()))
        self.assertLess(out.lower().index("safety"), out.lower().index("fit"))

    def test_render_no_color(self):
        self.assertNotIn("\x1b[", ev.render_scorecard(ev.score(_run(), _golden())))

    def test_scorecard_json_key_set(self):
        obj = ev.scorecard_json(ev.score(_run(), _golden()))
        self.assertEqual(set(obj), {"n", "backend", "safety", "dimensions", "fit", "verdict"})


if __name__ == "__main__":
    unittest.main()

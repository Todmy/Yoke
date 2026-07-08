import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="yoke-test-parity-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tools import parity_check  # noqa: E402


def _rec(role_key, tier, fit):
    return {"role_key": role_key, "tier": tier, "fit": fit}


class TestParityCompare(unittest.TestCase):
    def test_perfect_agreement(self):
        recs = [_rec("acme|be", "A", 90), _rec("beta|fe", "B", 60)]
        report = parity_check.compare(recs, [dict(r) for r in recs])
        self.assertEqual(report["topN_overlap"], 1.0)
        self.assertEqual(report["divergences"], [])
        self.assertEqual(report["tier_agreement"][("A", "A")], 1)
        self.assertEqual(report["tier_agreement"][("B", "B")], 1)

    def test_tier_divergence_listed(self):
        report = parity_check.compare([_rec("acme|be", "A", 90)], [_rec("acme|be", "C", 40)])
        self.assertEqual(
            report["divergences"],
            [{"role_key": "acme|be", "yoke_tier": "A", "proto_tier": "C"}],
        )

    def test_topN_overlap_jaccard(self):
        # A/B sets: yoke {a,b}, proto {b,c}; ∩={b}=1, ∪={a,b,c}=3 → 1/3
        yoke = [_rec("a", "A", 90), _rec("b", "B", 60), _rec("x", "C", 10)]
        proto = [_rec("b", "A", 88), _rec("c", "B", 57), _rec("x", "C", 12)]
        report = parity_check.compare(yoke, proto)
        self.assertAlmostEqual(report["topN_overlap"], 1 / 3)

    def test_unmatched_role_reported(self):
        yoke = [_rec("a", "A", 90), _rec("only_y", "B", 60)]
        proto = [_rec("a", "A", 90), _rec("only_p", "B", 55)]
        report = parity_check.compare(yoke, proto)
        self.assertEqual(report["unmatched"]["yoke_only"], ["only_y"])
        self.assertEqual(report["unmatched"]["proto_only"], ["only_p"])


class TestParityCLI(unittest.TestCase):
    def test_cli_reads_and_reports(self):
        d = tempfile.mkdtemp()
        yp, pp = Path(d) / "yoke.json", Path(d) / "proto.json"
        yp.write_text(json.dumps([_rec("a", "A", 90)]), encoding="utf-8")
        pp.write_text(json.dumps([_rec("a", "B", 60)]), encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = parity_check.main([str(yp), str(pp)])
        self.assertEqual(rc, 0)
        self.assertIn("a", buf.getvalue())  # the divergent role surfaces

    def test_cli_bad_args_returns_2(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = parity_check.main(["only-one-arg"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()

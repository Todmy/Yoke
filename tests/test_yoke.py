import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="yoke-test-yoke-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src import collect, paths, yoke  # noqa: E402

PROFILE = {
    "lane": {"keywords": ["engineer"], "anti": []},
    "geo": {"allow": ["remote"], "block": []},
    "tech": {"primary": ["python"], "avoid_primary": []},
    "comp": {"floor_net_usd_mo": 5000},
    "scoring": {
        "features": [{"name": "lane_fit", "weight": 80, "desc": "role matches lane"}],
        "deterministic": [{"name": "comp_vs_floor", "weight": 20}],
    },
}


def _meta(name, available=True, reason="", cost="free"):
    return {"name": name, "cost": cost, "available": available, "reason": reason}


def _scripted(*answers):
    it = iter(answers)
    return lambda prompt="": next(it)


def _no_input(prompt=""):
    raise AssertionError(f"unexpected interactive prompt: {prompt!r}")


def _fake_source(name, jobs):
    """(module, fetch_calls) — SimpleNamespace source with a fetch spy."""
    calls = []

    def fetch(profile):
        calls.append(name)
        return jobs

    mod = SimpleNamespace(
        NAME=name, TAGS={"domain": "it", "country": "any"}, COST="free",
        available=lambda: (True, ""), fetch=fetch,
    )
    return mod, calls


class TestSelectSources(unittest.TestCase):
    def test_select_sources_toggle_and_confirm(self):
        meta = [_meta("alpha"), _meta("beta")]
        with redirect_stdout(io.StringIO()):
            got = yoke.select_sources(meta, ["alpha"], _scripted("2", ""))
        self.assertEqual(got, ["alpha", "beta"])
        # toggling an enabled source off, then empty input confirms
        with redirect_stdout(io.StringIO()):
            got = yoke.select_sources(meta, ["alpha"], _scripted("1", ""))
        self.assertEqual(got, [])

    def test_select_sources_cannot_enable_unavailable(self):
        meta = [
            _meta("alpha"),
            _meta("brave", available=False, reason="BRAVE_API_KEY missing", cost="key"),
        ]
        # preselected unavailable source is dropped; toggling it on is refused
        with redirect_stdout(io.StringIO()):
            got = yoke.select_sources(meta, ["alpha", "brave"], _scripted("2", ""))
        self.assertEqual(got, ["alpha"])


class TestRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["YOKE_HOME"] = self._tmp.name
        home = paths.ensure_home()
        (home / "profile.json").write_text(json.dumps(PROFILE), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()
        os.environ["YOKE_HOME"] = _TMP

    @staticmethod
    def _jobs(name, n=1):
        return [
            collect.norm(
                f"Backend Engineer {i}", "Acme", "Remote, Europe",
                f"https://x.com/{name}/{i}", name,
            )
            for i in range(1, n + 1)
        ]

    def test_run_dry_run_stops_after_collect(self):
        mod, calls = _fake_source("fake1", self._jobs("fake1"))
        with mock.patch.object(collect, "load_sources", return_value=[mod]), \
                mock.patch.object(yoke.llm, "get_backend",
                                  side_effect=AssertionError("real backend constructed")), \
                redirect_stdout(io.StringIO()):
            rc = yoke.main(["run", "--dry-run", "--sources", "fake1"], input_fn=_no_input)
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["fake1"])
        self.assertTrue((paths.home() / "_index.json").is_file())
        # dry run stops after collect: no cards, no board, no shortlist
        self.assertFalse((paths.home() / "_cards.json").exists())
        self.assertFalse((paths.home() / "_board.json").exists())
        self.assertFalse((paths.home() / "SHORTLIST.md").exists())

    def test_run_mock_end_to_end(self):
        mod, calls = _fake_source("fake1", self._jobs("fake1", n=2))
        buf = io.StringIO()
        with mock.patch.object(collect, "load_sources", return_value=[mod]), \
                mock.patch.object(yoke.llm, "get_backend",
                                  side_effect=AssertionError("real backend constructed")), \
                redirect_stdout(buf):
            rc = yoke.main(["run", "--mock", "--yes", "--sources", "fake1"],
                           input_fn=_no_input)
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["fake1"])

        self.assertTrue((paths.home() / "SHORTLIST.md").is_file())
        board_data = json.loads(
            (paths.home() / "_board.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(board_data["roles"]), 2)
        for rec in board_data["roles"].values():
            self.assertIn(rec["tier"], ("A", "B", "C"))
            self.assertIsInstance(rec["fit"], int)
            self.assertIn("lane_fit", rec["features"])

        state = paths.load_state()
        self.assertIn("last_run", state)
        self.assertEqual(state["last_selection"], ["fake1"])
        self.assertIn("SHORTLIST", buf.getvalue())

    def test_deselected_source_never_fetched(self):
        mod1, calls1 = _fake_source("fake1", self._jobs("fake1"))
        mod2, calls2 = _fake_source("fake2", self._jobs("fake2"))
        with mock.patch.object(collect, "load_sources", return_value=[mod1, mod2]), \
                mock.patch.object(yoke.llm, "get_backend",
                                  side_effect=AssertionError("real backend constructed")), \
                redirect_stdout(io.StringIO()):
            rc = yoke.main(["run", "--mock", "--yes", "--sources", "fake1"],
                           input_fn=_no_input)
        self.assertEqual(rc, 0)
        self.assertEqual(calls1, ["fake1"])
        self.assertEqual(calls2, [])  # DoD #3: deselected source never fetched
        index = json.loads((paths.home() / "_index.json").read_text(encoding="utf-8"))
        self.assertTrue(all("fake2" not in k for k in index))


if __name__ == "__main__":
    unittest.main()

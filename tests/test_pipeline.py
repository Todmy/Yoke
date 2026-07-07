"""T20 — end-to-end mock pipeline smoke.

Drives the real `yoke run` orchestration (collect → prepare → analyze → board)
against fake in-memory sources under a throwaway $YOKE_HOME. No network, no
model: --mock swaps in MockBackend, and llm.get_backend is booby-trapped so a
real backend can never be constructed.

Scenario per plan T20: fake1 emits a same-URL duplicate pair, one distinct
clean role, and one geo-blocked role (block-term hit); fake2 raises. The run
must dedup, filter, isolate the source error, produce the full artifact set,
and a second identical run must short-circuit on "nothing new in window"
leaving the board byte-identical.

Note: the plan's prose says "3 roles" but asserts 2 unique index keys — with
only a dup pair + a blocked role the index would hold 1 key. fake1 therefore
emits 4 raw roles (dup pair → 1 key, clean role → 1 key, blocked → 0 keys)
so the "exactly 2 unique keys" assertion tests both collapse and filtering.
"""

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

_TMP = tempfile.mkdtemp(prefix="yoke-test-pipeline-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src import collect, paths, yoke  # noqa: E402

PROFILE = {
    "lane": {"keywords": ["engineer"], "anti": []},
    "geo": {"allow": ["remote"], "block": ["moscow"]},
    "tech": {"primary": ["python"], "avoid_primary": []},
    "comp": {"floor_net_usd_mo": 5000},
    "scoring": {
        "features": [{"name": "lane_fit", "weight": 80, "desc": "role matches lane"}],
        "deterministic": [{"name": "comp_vs_floor", "weight": 20}],
    },
}

DUP_URL = "https://x.com/fake1/backend"
CLEAN_URL = "https://x.com/fake1/platform"
BLOCKED_URL = "https://x.com/fake1/blocked"

FAKE1_JOBS = [
    collect.norm("Backend Engineer", "Acme", "Remote, Europe", DUP_URL, "fake1"),
    # same URL posted twice -> must collapse to one index key
    collect.norm("Backend Engineer", "Acme", "Remote", DUP_URL, "fake1"),
    collect.norm("Platform Engineer", "Beta", "Remote, Europe", CLEAN_URL, "fake1"),
    # location hits profile geo.block ("moscow") -> matches_profile drops it
    collect.norm("Systems Engineer", "Gamma", "Moscow", BLOCKED_URL, "fake1"),
]


def _no_input(prompt=""):
    raise AssertionError(f"unexpected interactive prompt: {prompt!r}")


def _fake_ok_source(name, jobs):
    calls = []

    def fetch(profile):
        calls.append(name)
        return jobs

    mod = SimpleNamespace(
        NAME=name, TAGS={"domain": "it", "country": "any"}, COST="free",
        available=lambda: (True, ""), fetch=fetch,
    )
    return mod, calls


def _fake_raising_source(name):
    def fetch(profile):
        raise RuntimeError("boom")

    return SimpleNamespace(
        NAME=name, TAGS={"domain": "it", "country": "any"}, COST="free",
        available=lambda: (True, ""), fetch=fetch,
    )


class TestPipelineSmoke(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["YOKE_HOME"] = self._tmp.name
        home = paths.ensure_home()
        (home / "profile.json").write_text(json.dumps(PROFILE), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()
        os.environ["YOKE_HOME"] = _TMP

    def _run_once(self):
        """One `yoke run --mock --yes --sources fake1,fake2`; returns (rc, stdout)."""
        fake1, _ = _fake_ok_source("fake1", FAKE1_JOBS)
        fake2 = _fake_raising_source("fake2")
        buf = io.StringIO()
        with mock.patch.object(collect, "load_sources", return_value=[fake1, fake2]), \
                mock.patch.object(yoke.llm, "get_backend",
                                  side_effect=AssertionError("real backend constructed")), \
                redirect_stdout(buf):
            rc = yoke.main(["run", "--mock", "--yes", "--sources", "fake1,fake2"],
                           input_fn=_no_input)
        return rc, buf.getvalue()

    def test_first_run_full_pipeline(self):
        rc, out = self._run_once()
        self.assertEqual(rc, 0)  # raising source must not break the run

        # collect: dup URL collapsed, geo-blocked filtered -> exactly 2 keys
        index = json.loads((paths.home() / "_index.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(index), sorted([DUP_URL.lower(), CLEAN_URL.lower()]))

        # prepare: cards dump written, one card per surviving index key
        cards = json.loads((paths.home() / "_cards.json").read_text(encoding="utf-8"))
        self.assertEqual(len(cards), 2)

        # analyze + board: records carry int fit and a real tier
        board = json.loads((paths.home() / "_board.json").read_text(encoding="utf-8"))
        self.assertEqual(len(board["roles"]), 2)
        for rec in board["roles"].values():
            self.assertIsInstance(rec["fit"], int)
            self.assertNotIsInstance(rec["fit"], bool)
            self.assertIn(rec["tier"], ("A", "B", "C"))

        # render: shortlist exists and never shows a tier-C row
        shortlist = (paths.home() / "SHORTLIST.md").read_text(encoding="utf-8")
        for line in shortlist.splitlines():
            self.assertFalse(line.startswith("| C "),
                             f"tier-C row leaked into SHORTLIST: {line!r}")

        # the raising source is reported, isolated, and named
        self.assertIn("fake2: ERROR (boom)", out)
        self.assertIn("fake1: 3 roles", out)  # 4 raw - 1 geo-blocked

    def test_second_identical_run_nothing_new(self):
        rc1, _ = self._run_once()
        self.assertEqual(rc1, 0)
        board_before = (paths.home() / "_board.json").read_text(encoding="utf-8")

        rc2, out2 = self._run_once()
        self.assertEqual(rc2, 0)
        self.assertIn("nothing new in window", out2)
        # short-circuited before analyze/board: board is byte-identical
        board_after = (paths.home() / "_board.json").read_text(encoding="utf-8")
        self.assertEqual(board_before, board_after)


if __name__ == "__main__":
    unittest.main()

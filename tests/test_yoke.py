import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
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


class TestSourceRelevance(unittest.TestCase):
    def test_is_recommended_country_gate(self):
        self.assertTrue(yoke._is_recommended({"country": "any"}, {"pl"}))
        self.assertTrue(yoke._is_recommended({"country": "intl"}, set()))
        self.assertTrue(yoke._is_recommended({"country": "pl"}, {"pl"}))
        self.assertFalse(yoke._is_recommended({"country": "de"}, {"pl"}))
        self.assertTrue(yoke._is_recommended({}, {"pl"}))  # no tag → treat as any

    def test_recommended_names_splits_by_tags(self):
        meta = [
            {**_meta("hn"), "tags": {"country": "intl"}},
            {**_meta("justjoin"), "tags": {"country": "pl"}},
            {**_meta("germany_ba"), "tags": {"country": "de"}},
            {**_meta("eures"), "tags": {"country": "any"}},
        ]
        self.assertEqual(
            yoke._recommended_names(meta, ["pl"]),
            {"hn", "justjoin", "eures"},
        )

    def test_geo_badge_labels(self):
        self.assertEqual(yoke._geo_badge({"country": "pl"}), "PL")
        self.assertEqual(yoke._geo_badge({"country": "de"}), "DE")
        self.assertEqual(yoke._geo_badge({"country": "intl"}), "remote")
        self.assertEqual(yoke._geo_badge({"country": "any"}), "any")
        self.assertEqual(yoke._geo_badge(None), "any")  # no tags → any


class TestSelectSourcesTui(unittest.TestCase):
    @staticmethod
    def _keys(*tokens):
        it = iter(tokens)
        return lambda: next(it)

    def test_tui_navigate_toggle_confirm(self):
        meta = [_meta("alpha"), _meta("beta"), _meta("gamma")]
        # start on alpha (preselected); down to beta, space enables it, enter starts
        got = yoke.select_sources_tui(
            meta, ["alpha"], self._keys("down", "space", "enter"),
            out=lambda *a, **k: None,
        )
        self.assertEqual(got, ["alpha", "beta"])

    def test_tui_toggle_off_and_wrap(self):
        meta = [_meta("alpha"), _meta("beta")]
        # up wraps to beta, enable it; up to alpha, disable it → only beta
        got = yoke.select_sources_tui(
            meta, ["alpha"], self._keys("up", "space", "up", "space", "enter"),
            out=lambda *a, **k: None,
        )
        self.assertEqual(got, ["beta"])

    def test_tui_unavailable_not_selectable(self):
        meta = [
            _meta("alpha"),
            _meta("brave", available=False, reason="key missing", cost="key"),
        ]
        # brave lives in a collapsed Unavailable section: down→control, right
        # expands, down→brave, space is a no-op (unavailable). Only alpha returns.
        got = yoke.select_sources_tui(
            meta, ["alpha"], self._keys("down", "right", "down", "space", "enter"),
            out=lambda *a, **k: None,
        )
        self.assertEqual(got, ["alpha"])

    def test_tui_unavailable_hidden_until_expand(self):
        meta = [
            _meta("alpha"),
            _meta("brave", available=False, reason="BRAVE_API_KEY not set", cost="key"),
        ]
        frames = []
        yoke.select_sources_tui(
            meta, [], self._keys("enter"), out=lambda t="": frames.append(t),
        )
        self.assertIn("Unavailable (1)", frames[0])  # control shown
        self.assertNotIn("brave", frames[0])         # source hidden while collapsed

    def test_tui_row_shows_geo_badge(self):
        meta = [{**_meta("justjoin"), "tags": {"country": "pl"}}]
        frames = []
        yoke.select_sources_tui(
            meta, [], self._keys("enter"), out=lambda t="": frames.append(t),
        )
        self.assertIn("PL", frames[0])         # geo badge rendered
        self.assertIn("justjoin", frames[0])
        self.assertNotIn("available", frames[0])  # status noise dropped

    def test_tui_other_collapsed_hides_until_expand(self):
        meta = [_meta("hn"), _meta("germany_ba")]
        # germany_ba is Other, collapsed. rows = [hn, more]; down lands on the
        # 'more' control, enter without expanding → germany_ba never selectable.
        got = yoke.select_sources_tui(
            meta, [], self._keys("down", "enter"),
            out=lambda *a, **k: None, recommended={"hn"},
        )
        self.assertEqual(got, [])

    def test_tui_expand_other_then_select(self):
        meta = [_meta("hn"), _meta("germany_ba")]
        # down→'more', space expands, down→germany_ba, space selects, enter.
        got = yoke.select_sources_tui(
            meta, [], self._keys("down", "space", "down", "space", "enter"),
            out=lambda *a, **k: None, recommended={"hn"},
        )
        self.assertEqual(got, ["germany_ba"])

    def test_tui_right_arrow_expands_other(self):
        meta = [_meta("hn"), _meta("germany_ba")]
        # right also works the collapse control: down→'more', right expands,
        # down→germany_ba, space selects, enter.
        got = yoke.select_sources_tui(
            meta, [], self._keys("down", "right", "down", "space", "enter"),
            out=lambda *a, **k: None, recommended={"hn"},
        )
        self.assertEqual(got, ["germany_ba"])

    def test_tui_right_arrow_noop_on_source(self):
        meta = [_meta("alpha"), _meta("beta")]
        # right is a collapse-control key only — on a source row it does nothing
        # (space stays the toggle). alpha preselected, right, enter → still alpha.
        got = yoke.select_sources_tui(
            meta, ["alpha"], self._keys("right", "enter"),
            out=lambda *a, **k: None,
        )
        self.assertEqual(got, ["alpha"])

    def test_tui_return_order_recommended_then_other(self):
        meta = [_meta("germany_ba"), _meta("hn")]  # menu order ≠ section order
        # hn recommended, germany_ba Other. Preselect both; expand to reach it.
        # Returned order is recommended-first, then Other.
        got = yoke.select_sources_tui(
            meta, ["hn", "germany_ba"], self._keys("enter"),
            out=lambda *a, **k: None, recommended={"hn"},
        )
        self.assertEqual(got, ["hn", "germany_ba"])

    def test_tui_viewport_windows_long_list(self):
        meta = [_meta(f"s{i}") for i in range(8)]
        frames = []
        keys = self._keys("down", "down", "down", "down", "down", "enter")
        yoke.select_sources_tui(
            meta, [], keys, out=lambda t="": frames.append(t), viewport=3,
        )
        for f in frames:
            body = re.sub(r"^\x1b\[\d+A\x1b\[J", "", f)
            if not body.startswith("Sources:"):
                continue
            visible = [ln for ln in body.split("\n") if "[ ]" in ln or "[x]" in ln]
            self.assertLessEqual(len(visible), 3)  # never more than a window
        self.assertTrue(any("/8]" in f for f in frames))  # position indicator

    def test_decode_key_maps_sequences(self):
        def chars(*cs):
            it = iter(cs)
            return lambda: next(it)
        self.assertEqual(yoke._decode_key(chars("\x1b", "[", "A")), "up")
        self.assertEqual(yoke._decode_key(chars("\x1b", "[", "B")), "down")
        self.assertEqual(yoke._decode_key(chars("\x1b", "[", "C")), "right")
        self.assertEqual(yoke._decode_key(chars("\x1b", "O", "C")), "right")
        self.assertEqual(yoke._decode_key(chars("\x1b", "O", "A")), "up")
        self.assertEqual(yoke._decode_key(chars(" ")), "space")
        self.assertEqual(yoke._decode_key(chars("\r")), "enter")
        self.assertEqual(yoke._decode_key(chars("\n")), "enter")
        self.assertIsNone(yoke._decode_key(chars("x")))
        with self.assertRaises(KeyboardInterrupt):
            yoke._decode_key(chars("\x03"))


class TestRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["YOKE_HOME"] = self._tmp.name
        home = paths.ensure_home()
        (home / "profile.json").write_text(json.dumps(PROFILE), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()
        os.environ["YOKE_HOME"] = _TMP

    # Distinct engineer roles (all hit the "engineer" lane keyword) so n>1 emits
    # genuinely different roles — a numeric suffix would read as a WS4 near-dup.
    _TITLES = ["Backend Engineer", "Frontend Engineer", "Platform Engineer", "Data Engineer"]

    @staticmethod
    def _jobs(name, n=1):
        return [
            collect.norm(
                TestRun._TITLES[i - 1], "Acme", "Remote, Europe",
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

    def test_first_run_yes_never_selects_keyed_source(self):
        """I3: --yes with no saved selection and no profile.sources.enabled
        must fall back to FREE sources only — an available cost="key" source
        needs explicit consent (saved selection, profile, --sources, or menu)."""
        free_mod, free_calls = _fake_source("freefake", self._jobs("freefake"))
        key_mod, key_calls = _fake_source("keyfake", self._jobs("keyfake"))
        key_mod.COST = "key"  # available (key present) but never consented to
        with mock.patch.object(collect, "load_sources",
                               return_value=[free_mod, key_mod]), \
                mock.patch.object(yoke.llm, "get_backend",
                                  side_effect=AssertionError("real backend constructed")), \
                redirect_stdout(io.StringIO()):
            rc = yoke.main(["run", "--mock", "--yes"], input_fn=_no_input)
        self.assertEqual(rc, 0)
        self.assertEqual(free_calls, ["freefake"])
        self.assertEqual(key_calls, [])  # keyed source fetch never called

    def test_first_run_yes_profile_enabled_counts_as_consent(self):
        """Explicit profile.sources.enabled is consent: a keyed source listed
        there is selected on a first --yes run; unlisted sources are not."""
        profile = dict(PROFILE)
        profile["sources"] = {"enabled": ["keyfake"]}
        (paths.home() / "profile.json").write_text(
            json.dumps(profile), encoding="utf-8"
        )
        free_mod, free_calls = _fake_source("freefake", self._jobs("freefake"))
        key_mod, key_calls = _fake_source("keyfake", self._jobs("keyfake"))
        key_mod.COST = "key"
        with mock.patch.object(collect, "load_sources",
                               return_value=[free_mod, key_mod]), \
                mock.patch.object(yoke.llm, "get_backend",
                                  side_effect=AssertionError("real backend constructed")), \
                redirect_stdout(io.StringIO()):
            rc = yoke.main(["run", "--mock", "--yes"], input_fn=_no_input)
        self.assertEqual(rc, 0)
        self.assertEqual(key_calls, ["keyfake"])
        self.assertEqual(free_calls, [])  # profile list is authoritative

    def test_aged_out_scored_role_not_wiped(self):
        """C1 regression: a role scored A on an earlier run, now outside the
        14-day window, must keep its tier/fit when a later run brings new roles.
        Out-of-window cards must never reach analyze/board."""
        old_key = "https://x.com/fake1/old"
        old_iso = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        index = {
            old_key: {
                "title": "Backend Engineer Old", "company": "Acme",
                "location": "Remote, Europe", "url": old_key, "source": "fake1",
                "posted_at": "", "comp": None, "score": 2,
                "role_key": "acme|backend engineer old",
                "first_seen": old_iso, "last_seen": old_iso,
            }
        }
        (paths.home() / "_index.json").write_text(json.dumps(index), encoding="utf-8")
        board = {
            "roles": {
                old_key: {
                    "key": old_key, "role_key": "acme|backend engineer old",
                    "company": "Acme", "title": "Backend Engineer Old",
                    "url": old_key, "location": "Remote, Europe",
                    "source": "fake1", "fit": 88, "tier": "A", "features": {},
                    "geo_certainty": "remote_confirmed", "red_flags": [],
                    "note": "scored on an earlier run", "comp_display": "—",
                    "date_added": "2026-06-01", "last_refreshed": "2026-06-01",
                }
            },
            "applied": [], "dropped": [],
        }
        (paths.home() / "_board.json").write_text(json.dumps(board), encoding="utf-8")

        mod, calls = _fake_source("fake1", self._jobs("fake1"))
        with mock.patch.object(collect, "load_sources", return_value=[mod]), \
                mock.patch.object(yoke.llm, "get_backend",
                                  side_effect=AssertionError("real backend constructed")), \
                redirect_stdout(io.StringIO()):
            rc = yoke.main(["run", "--mock", "--yes", "--sources", "fake1"],
                           input_fn=_no_input)
        self.assertEqual(rc, 0)

        after = json.loads((paths.home() / "_board.json").read_text(encoding="utf-8"))
        rec = after["roles"][old_key]
        self.assertEqual(rec["tier"], "A")   # NOT wiped to C
        self.assertEqual(rec["fit"], 88)     # NOT wiped to 0
        self.assertEqual(rec["last_refreshed"], "2026-06-01")  # untouched
        # the genuinely new role still landed on the board
        self.assertIn("https://x.com/fake1/1", after["roles"])

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


class TestSourceHelp(unittest.TestCase):
    def test_help_prefers_constant(self):
        mod = SimpleNamespace(HELP="X", __doc__="doc")
        self.assertEqual(yoke._source_help(mod), "X")

    def test_help_falls_back_to_doc(self):
        mod = SimpleNamespace(__doc__="  doc here  ")  # no HELP attr
        self.assertEqual(yoke._source_help(mod), "doc here")

    def test_help_default_sentence(self):
        mod = SimpleNamespace(__doc__=None)  # neither HELP nor docstring
        self.assertEqual(yoke._source_help(mod),
                         "No setup needed — works out of the box.")


class TestSourcesMeta(unittest.TestCase):
    def test_sources_meta_shape(self):
        m1, _ = _fake_source("hn", [])
        m2 = SimpleNamespace(
            NAME="brave", TAGS={"domain": "it", "country": "any"}, COST="key",
            available=lambda: (False, "BRAVE_API_KEY not set"), fetch=lambda p: [],
        )
        with mock.patch.object(collect, "load_sources", return_value=[m1, m2]):
            meta = yoke._sources_meta()
        self.assertEqual({m["name"] for m in meta}, {"hn", "brave"})
        for m in meta:
            self.assertEqual(set(m), {"name", "cost", "available", "reason", "tags"})
        brave = next(m for m in meta if m["name"] == "brave")
        self.assertFalse(brave["available"])
        self.assertEqual(brave["reason"], "BRAVE_API_KEY not set")


class TestSourcesReport(unittest.TestCase):
    def _m(self, name, available=True, reason="", cost="free", country="any"):
        return {**_meta(name, available, reason, cost), "tags": {"country": country}}

    def test_report_splits_available_unavailable(self):
        meta = [self._m("hn"),
                self._m("brave", available=False,
                        reason="BRAVE_API_KEY not set", cost="key")]
        out = yoke._render_sources_report(meta, set(), {}, set())
        self.assertIn("Available", out)
        self.assertIn("Unavailable", out)
        self.assertIn("BRAVE_API_KEY not set", out)
        brave_line = next(l for l in out.splitlines() if "brave" in l)
        self.assertNotIn("roles", brave_line)  # unavailable carries reason, not a count

    def test_report_enabled_and_roles(self):
        out = yoke._render_sources_report([self._m("hn")], {"hn"}, {"hn": 5}, set())
        self.assertIn("enabled", out)
        self.assertIn("5 roles", out)

    def test_report_enabled_none_shows_dash(self):
        out = yoke._render_sources_report([self._m("hn")], None, {}, set())
        self.assertNotIn("enabled", out)
        self.assertNotIn("disabled", out)
        self.assertIn("—", out)

    def test_report_recommended_first(self):
        meta = [self._m("alpha"), self._m("beta")]
        out = yoke._render_sources_report(meta, set(), {}, {"beta"})
        self.assertLess(out.index("beta"), out.index("alpha"))

    def test_report_no_color_has_no_escapes(self):
        meta = [self._m("hn"),
                self._m("brave", available=False, reason="x", cost="key")]
        out = yoke._render_sources_report(meta, set(), {}, set(), use_color=False)
        self.assertNotIn("\x1b[", out)

    def test_source_json_shape(self):
        row = self._m("brave", available=False,
                      reason="BRAVE_API_KEY not set", cost="key")
        obj = yoke._source_json(row, None, None)
        self.assertEqual(set(obj), {"name", "geo", "cost", "available",
                                    "reason", "enabled", "roles_last_run"})
        self.assertEqual(obj["geo"], "any")
        self.assertFalse(obj["available"])
        self.assertIn('"enabled": null', json.dumps(obj))  # None → JSON null


class TestLastRunCounts(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["YOKE_HOME"] = self._tmp.name
        paths.ensure_home()

    def tearDown(self):
        self._tmp.cleanup()
        os.environ["YOKE_HOME"] = _TMP

    def _write_scan(self, ts, jobs):
        (paths.home() / "scans" / f"{ts}.json").write_text(
            json.dumps(jobs), encoding="utf-8")

    def test_counts_group_by_source(self):
        self._write_scan("2026-01-01-00-00-00",
                         [{"source": "hn"}, {"source": "hn"}, {"source": "vc"}])
        self.assertEqual(yoke._last_run_counts(), {"hn": 2, "vc": 1})

    def test_newest_scan_wins(self):
        self._write_scan("2026-01-01-00-00-00", [{"source": "hn"}])
        self._write_scan("2026-02-02-00-00-00", [{"source": "vc"}, {"source": "vc"}])
        self.assertEqual(yoke._last_run_counts(), {"vc": 2})

    def test_empty_home_returns_empty(self):
        self.assertEqual(yoke._last_run_counts(), {})

    def test_malformed_scan_returns_empty(self):
        (paths.home() / "scans" / "2026-01-01-00-00-00.json").write_text(
            "not json", encoding="utf-8")
        self.assertEqual(yoke._last_run_counts(), {})


class TestHelpCommand(unittest.TestCase):
    def test_render_help_lists_all_names(self):
        out = yoke._render_help([("run", "collect and score"),
                                 ("board", "print shortlist")])
        self.assertIn("run", out)
        self.assertIn("collect and score", out)
        self.assertIn("board", out)
        self.assertIn("yoke <command> -h", out)  # footer pointer to flags

    def test_subcommands_reads_parser(self):
        names = [n for n, _ in yoke._subcommands(yoke._build_parser())]
        self.assertIn("run", names)
        self.assertIn("board", names)


if __name__ == "__main__":
    unittest.main()

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="yoke-test-prepare-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src import paths, prepare  # noqa: E402


def _profile():
    return {
        "lane": {"keywords": ["engineer"], "anti": ["intern", "recruiter"]},
        "geo": {"allow": ["remote-eu", "pl"], "block": ["russia"]},
        "tech": {"primary": ["python"], "avoid_primary": ["cobol"]},
        "comp": {"floor_net_usd_mo": 5000},
        "language_levels": {"en": "b2"},
        "stage_rules": [],
    }


def _iso(dt):
    return dt.isoformat()


def _entry(
    title="Backend Engineer",
    company="Acme",
    location="Remote, EU",
    url="https://x.com/1",
    comp=None,
    first_seen=None,
):
    now = datetime.now(timezone.utc)
    fs = first_seen or _iso(now)
    return {
        "title": title,
        "company": company,
        "location": location,
        "url": url,
        "source": "fake",
        "posted_at": "",
        "comp": comp,
        "score": 2,
        "role_key": f"{company.lower()}|{title.lower()}",
        "first_seen": fs,
        "last_seen": fs,
    }


class TestPrepare(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["YOKE_HOME"] = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()
        os.environ["YOKE_HOME"] = _TMP

    def test_window_boundary(self):
        now = datetime.now(timezone.utc)
        index = {
            "old": _entry(url="https://x.com/old", first_seen=_iso(now - timedelta(days=15))),
            "edge": _entry(url="https://x.com/edge", first_seen=_iso(now - timedelta(days=14))),
            "fresh": _entry(url="https://x.com/fresh", first_seen=_iso(now - timedelta(days=13))),
        }
        keys = {e["key"] for e in prepare.window_slice(index, None, days=14)}
        self.assertEqual(keys, {"fresh"})  # strict >: exact boundary excluded

    def test_window_uses_last_run(self):
        now = datetime.now(timezone.utc)
        last_run = _iso(now - timedelta(days=2))
        index = {
            "before": _entry(url="https://x.com/b", first_seen=_iso(now - timedelta(days=3))),
            "after": _entry(url="https://x.com/a", first_seen=_iso(now - timedelta(days=1))),
        }
        keys = {e["key"] for e in prepare.window_slice(index, last_run, days=14)}
        self.assertEqual(keys, {"after"})  # last_run wins over now-14d

    def test_gate_geo_block(self):
        job = _entry(location="Moscow, Russia")
        self.assertIn("geo", prepare.apply_gates(job, _profile()))

    def test_gate_bare_city_is_friction_not_fail(self):
        index = {"k": _entry(location="Gdansk")}
        cards = prepare.build_cards(_profile(), index, {})
        card = cards[0]
        self.assertNotIn("geo", card["gates_failed"])
        self.assertIn("verify", card["frictions"])
        self.assertTrue(card["needs_ai"])  # friction never blocks analysis

    def test_gate_comp_below_floor(self):
        job = _entry(comp={"min": 2000, "max": 3000, "currency": "usd", "unit": "month", "type": "b2b"})
        self.assertIn("comp_floor", prepare.apply_gates(job, _profile()))
        # above-floor comp passes the gate
        job_ok = _entry(comp={"min": 8000, "max": 9000, "currency": "usd", "unit": "month", "type": "b2b"})
        self.assertNotIn("comp_floor", prepare.apply_gates(job_ok, _profile()))

    def test_gate_anti_lane(self):
        job = _entry(title="Engineer Intern")
        self.assertIn("lane", prepare.apply_gates(job, _profile()))

    def test_needs_ai_only_windowed_and_clean(self):
        now = datetime.now(timezone.utc)
        index = {
            "clean": _entry(url="https://x.com/c"),
            "gated": _entry(url="https://x.com/g", location="Moscow, Russia"),
            "stale": _entry(url="https://x.com/s", first_seen=_iso(now - timedelta(days=30))),
        }
        cards = {c["key"]: c for c in prepare.build_cards(_profile(), index, {})}
        self.assertTrue(cards["clean"]["needs_ai"])
        self.assertFalse(cards["gated"]["needs_ai"])
        self.assertEqual(cards["gated"]["tier"], "C")  # gated-out pre-assigned C
        self.assertFalse(cards["stale"]["needs_ai"])
        self.assertNotIn("tier", cards["stale"])  # stale-but-clean is not tier C

    def test_cards_dump_written(self):
        index = {
            "str-comp": _entry(url="https://x.com/sc", comp="12 000 USD/month"),
        }
        cards = prepare.build_cards(_profile(), index, {})
        dump = json.loads((paths.home() / "_cards.json").read_text(encoding="utf-8"))
        self.assertEqual(dump, cards)
        # string comp went through comp.normalize's raw path
        self.assertEqual(cards[0]["comp_norm"]["floor_verdict"], "above")


if __name__ == "__main__":
    unittest.main()

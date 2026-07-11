import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="yoke-test-board-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src import board, labels  # noqa: E402
from src.paths import home  # noqa: E402


def _record(key="https://x.com/1", role_key="acme|backendengineer", **over):
    rec = {
        "key": key,
        "role_key": role_key,
        "company": "Acme",
        "title": "Backend Engineer",
        "url": key,
        "location": "Remote, EU",
        "source": "fake",
        "fit": 80,
        "tier": "A",
        "features": {"hire_probability": {"score": 80, "evidence": "solid"}},
        "geo_certainty": "remote_confirmed",
        "red_flags": [],
        "note": "looks good",
        "comp_display": "$8.4-10.1k/mo",
        "date_added": "2026-07-01",
        "last_refreshed": "2026-07-01",
    }
    rec.update(over)
    return rec


class BoardTest(unittest.TestCase):
    def setUp(self):
        os.environ["YOKE_HOME"] = tempfile.mkdtemp(prefix="yoke-test-board-")

    def test_upsert_keeps_date_added(self):
        board.upsert([_record(date_added="2026-06-01", fit=70)])
        stats = board.upsert([_record(date_added="2026-07-07", fit=85, note="fresher")])
        self.assertEqual(stats["added"], 0)
        self.assertEqual(stats["refreshed"], 1)
        b = board.load_board()
        rec = b["roles"]["https://x.com/1"]
        self.assertEqual(rec["date_added"], "2026-06-01")
        self.assertEqual(rec["fit"], 85)
        self.assertEqual(rec["note"], "fresher")

    def test_prune_on_apply_by_role_key(self):
        board.upsert([_record(key="https://x.com/1", role_key="acme|backendengineer")])
        removed = board.mark_applied("x.com/1")
        self.assertIn("https://x.com/1", removed)
        b = board.load_board()
        self.assertIn("acme|backendengineer", b["applied"])
        # A repost: different job_key, same role_key -> pruned on upsert.
        stats = board.upsert(
            [_record(key="https://y.com/repost", role_key="acme|backendengineer")]
        )
        self.assertEqual(stats["pruned"], 1)
        b = board.load_board()
        self.assertNotIn("https://y.com/repost", b["roles"])
        self.assertEqual(b["roles"], {})

    def test_apply_offboard_still_ledgered(self):
        removed = board.mark_applied("https://never-seen.example/job")
        self.assertEqual(removed, [])
        b = board.load_board()
        self.assertIn("https://never-seen.example/job", b["applied"])

    def test_drop_with_reason(self):
        board.upsert([_record()])
        board.drop("x.com/1", reason="salary too low")
        b = board.load_board()
        self.assertEqual(b["roles"], {})
        self.assertEqual(len(b["dropped"]), 1)
        entry = b["dropped"][0]
        self.assertEqual(entry["key"], "https://x.com/1")
        self.assertEqual(entry["reason"], "salary too low")

    def test_render_orders_and_excludes_c(self):
        board.upsert([
            _record(key="u1", role_key="r1", company="Alpha", title="Eng A80",
                    fit=80, tier="A"),
            _record(key="u2", role_key="r2", company="Beta", title="Eng A90",
                    fit=90, tier="A"),
            _record(key="u3", role_key="r3", company="Gamma", title="Eng B60",
                    fit=60, tier="B"),
            _record(key="u4", role_key="r4", company="Delta", title="Eng C95",
                    fit=95, tier="C"),
        ])
        path = board.render({"output_language": "en"})
        self.assertEqual(path, home() / "SHORTLIST.md")
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("Eng C95", text)
        i_a90 = text.index("Eng A90")
        i_a80 = text.index("Eng A80")
        i_b60 = text.index("Eng B60")
        self.assertLess(i_a90, i_a80)
        self.assertLess(i_a80, i_b60)
        # header carries counts
        self.assertIn("3", text.split("\n")[0] + text)

    def test_render_uk_headers(self):
        board.upsert([_record()])
        path = board.render({"output_language": "uk"})
        text = path.read_text(encoding="utf-8")
        self.assertIn("Компанія", text)
        self.assertNotIn("| Company |", text)

    # --- M3: apply/drop snapshot the feature vector before prune (T2) ---

    def test_apply_snapshots_features_before_prune(self):
        board.upsert([_record()])
        board.mark_applied("x.com/1")
        stored = labels.load_labels()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["label"], "applied")
        self.assertIsNone(stored[0]["reason"])
        # the feature vector survived the prune
        self.assertEqual(
            stored[0]["features"],
            {"hire_probability": {"score": 80, "evidence": "solid"}},
        )

    def test_drop_snapshots_with_reason(self):
        board.upsert([_record()])
        board.drop("x.com/1", reason="salary too low")
        stored = labels.load_labels()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["label"], "dropped")
        self.assertEqual(stored[0]["reason"], "salary too low")
        self.assertEqual(stored[0]["fit"], 80)

    def test_apply_no_hit_no_snapshot(self):
        board.mark_applied("https://never-seen.example/job")
        self.assertEqual(labels.load_labels(), [])

    def test_apply_ledger_shape_unchanged(self):
        board.upsert([_record()])
        board.mark_applied("x.com/1")
        b = board.load_board()
        self.assertIn("acme|backendengineer", b["applied"])
        self.assertEqual(b["roles"], {})


if __name__ == "__main__":
    unittest.main()

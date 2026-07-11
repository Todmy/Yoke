import datetime
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="yoke-test-labels-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src import labels  # noqa: E402
from src.paths import home  # noqa: E402


def _role(**over):
    rec = {
        "key": "https://x.com/1",
        "role_key": "acme|backendengineer",
        "company": "Acme",
        "title": "Backend Engineer",
        "fit": 80,
        "tier": "A",
        "features": {"hire_probability": {"score": 80, "evidence": "solid"}},
        "geo_certainty": "remote_confirmed",
        "red_flags": [],
    }
    rec.update(over)
    return rec


class LabelsTest(unittest.TestCase):
    def setUp(self):
        os.environ["YOKE_HOME"] = tempfile.mkdtemp(prefix="yoke-test-labels-")

    def test_record_builds_snapshot_fields(self):
        rec = labels.record(_role(), "applied")
        self.assertEqual(rec["label"], "applied")
        self.assertIsNone(rec["reason"])
        self.assertEqual(rec["date"], datetime.date.today().isoformat())
        self.assertEqual(rec["key"], "https://x.com/1")
        self.assertEqual(rec["role_key"], "acme|backendengineer")
        self.assertEqual(rec["company"], "Acme")
        self.assertEqual(rec["title"], "Backend Engineer")
        self.assertEqual(rec["fit"], 80)
        self.assertEqual(rec["tier"], "A")
        self.assertEqual(rec["features"], {"hire_probability": {"score": 80, "evidence": "solid"}})
        self.assertEqual(rec["geo_certainty"], "remote_confirmed")
        # persisted
        stored = labels.load_labels()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["label"], "applied")

    def test_record_appends_to_list(self):
        labels.record(_role(), "applied")
        labels.record(_role(key="https://x.com/2"), "dropped", reason="onsite")
        stored = labels.load_labels()
        self.assertEqual(len(stored), 2)
        self.assertEqual(stored[1]["reason"], "onsite")
        self.assertEqual(stored[1]["label"], "dropped")

    def test_record_reason_null_for_applied(self):
        rec = labels.record(_role(), "applied")
        self.assertIsNone(rec["reason"])

    def test_load_missing_returns_empty(self):
        self.assertEqual(labels.load_labels(), [])

    def test_load_malformed_returns_empty(self):
        (home() / labels.LABELS_FILE).write_text("{not json", encoding="utf-8")
        self.assertEqual(labels.load_labels(), [])

    def test_load_non_list_returns_empty(self):
        (home() / labels.LABELS_FILE).write_text(json.dumps({"a": 1}), encoding="utf-8")
        self.assertEqual(labels.load_labels(), [])

    def test_load_skips_non_dict_entries(self):
        (home() / labels.LABELS_FILE).write_text(
            json.dumps([{"label": "applied"}, "junk", 42]), encoding="utf-8"
        )
        stored = labels.load_labels()
        self.assertEqual(stored, [{"label": "applied"}])


if __name__ == "__main__":
    unittest.main()

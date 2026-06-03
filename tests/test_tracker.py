"""T018 — tracker: immutable CV snapshot on apply (Δ4, FR-007); `interested` is a
bookmark not a training-positive (Δ1); funnel stats (FR-010). Uses temp YOKE_HOME.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("YOKE_HOME", tempfile.mkdtemp(prefix="yoke-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import store  # noqa: E402


def _seed_role(role_key, company="Acme", title="AI Engineer"):
    # key == url (canonical): store.mark records `key` as the decision's url column
    store.save({"roles": [{"role_key": role_key, "key": f"https://x/{role_key}", "company": company,
                           "title": title, "url": f"https://x/{role_key}", "fit": 80, "label": "",
                           "geo": "remote", "comp": "", "lane": "in", "note": "", "tier": "A",
                           "date_added": "2026-06-02",
                           "features": '{"lane_match":"in","differentiator_hits":3}'}],
                "applied_log": []})


class TestSnapshot(unittest.TestCase):
    def test_apply_stores_immutable_resume(self):
        _seed_role("r1")
        store.mark("r1", "applied", resume="CV-SENT-v1")
        apps = [a for a in store.applications() if a.get("url") == "https://x/r1"]
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["resume"], "CV-SENT-v1")
        # re-apply (idempotent on role_key+decision) must NOT overwrite the snapshot
        _seed_role("r1")
        store.mark("r1", "applied", resume="CV-CHANGED-LATER")
        apps2 = [a for a in store.applications() if a.get("url") == "https://x/r1"]
        self.assertEqual(apps2[0]["resume"], "CV-SENT-v1")  # frozen


class TestInterestedBookmark(unittest.TestCase):
    def test_interested_not_in_applications(self):
        _seed_role("r2")
        store.mark("r2", "interested")
        self.assertNotIn("https://x/r2", [a.get("url") for a in store.applications()])

    def test_interested_leaves_board_enters_shortlist(self):
        _seed_role("r2b")
        store.mark("r2b", "interested")
        # off the live board…
        self.assertNotIn("r2b", [r.get("role_key") for r in store.load()["roles"]])
        # …but on the starred shortlist (survives, look-later)
        self.assertIn("r2b", [r.get("role_key") for r in store.interested_roles()])

    def test_unstar_round_trip(self):
        _seed_role("r2c")
        store.mark("r2c", "interested")
        before = store.label_counts()["interested"]
        self.assertTrue(store.unstar("r2c"))
        self.assertIn("r2c", [r.get("role_key") for r in store.load()["roles"]])      # back on board
        self.assertNotIn("r2c", [r.get("role_key") for r in store.interested_roles()])  # off shortlist
        self.assertEqual(store.label_counts()["interested"], before - 1)              # its label removed
        self.assertFalse(store.unstar("r2c"))                                         # no-op second time

    def test_label_counts_both_classes_is_applied_vs_rejected(self):
        _seed_role("r3"); store.mark("r3", "interested")   # bookmark only
        _seed_role("r4"); store.mark("r4", "rejected", reason="off-lane")
        lc = store.label_counts()
        # interested+rejected present, but no `applied` → both_classes must be False
        self.assertFalse(lc["both_classes"])
        _seed_role("r5"); store.mark("r5", "applied", resume="cv")
        self.assertTrue(store.label_counts()["both_classes"])  # now applied AND rejected exist


class TestFunnel(unittest.TestCase):
    def test_stats_shape(self):
        s = store.application_stats()
        for k in ("total", "response_rate", "interview_rate", "offers"):
            self.assertIn(k, s)


if __name__ == "__main__":
    unittest.main()

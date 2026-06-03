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
    def test_star_keeps_role_on_board(self):
        _seed_role("r2b")
        store.star("r2b")
        # the star is a filter flag — the role STAYS on the live board (no separate tab)
        self.assertIn("r2b", [r.get("role_key") for r in store.load()["roles"]])
        self.assertIn("r2b", store.starred_keys())

    def test_star_not_in_applications(self):
        _seed_role("r2")
        store.star("r2")
        self.assertNotIn("https://x/r2", [a.get("url") for a in store.applications()])

    def test_unstar_round_trip(self):
        _seed_role("r2c")
        store.star("r2c")
        before = store.label_counts()["interested"]
        self.assertTrue(store.unstar("r2c"))
        self.assertIn("r2c", [r.get("role_key") for r in store.load()["roles"]])   # still on board
        self.assertNotIn("r2c", store.starred_keys())                              # flag cleared
        self.assertEqual(store.label_counts()["interested"], before - 1)           # bookmark removed
        self.assertFalse(store.unstar("r2c"))                                      # no-op second time

    def test_star_not_a_tuner_signal(self):
        _seed_role("r2d")
        store.star("r2d")
        # star() records no raw features → excluded from the tuner's labeled set
        self.assertNotIn("r2d", [l["role_key"] for l in store.labeled_decisions()])

    def test_label_counts_both_classes_is_applied_vs_rejected(self):
        _seed_role("r3"); store.star("r3")                 # bookmark only
        _seed_role("r4"); store.mark("r4", "rejected", reason="off-lane")
        lc = store.label_counts()
        # interested+rejected present, but no `applied` → both_classes must be False
        self.assertFalse(lc["both_classes"])
        _seed_role("r5"); store.mark("r5", "applied", resume="cv")
        self.assertTrue(store.label_counts()["both_classes"])  # now applied AND rejected exist


class TestUnapply(unittest.TestCase):
    def test_unapply_returns_role_to_board(self):
        _seed_role("u1")
        store.mark("u1", "applied", resume="cv")
        aid = [a for a in store.applications() if a.get("url") == "https://x/u1"][0]["id"]
        self.assertTrue(store.unapply(aid))
        self.assertIn("u1", [r.get("role_key") for r in store.load()["roles"]])      # back on board
        self.assertNotIn("https://x/u1", [a.get("url") for a in store.applications()])  # off applied
        self.assertFalse(store.unapply(999999))                                       # bad id → False

    def test_unapply_bad_id(self):
        self.assertFalse(store.unapply("not-an-int"))


class TestFunnel(unittest.TestCase):
    def test_stats_shape(self):
        s = store.application_stats()
        for k in ("total", "response_rate", "interview_rate", "offers"):
            self.assertIn(k, s)


if __name__ == "__main__":
    unittest.main()

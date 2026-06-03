"""T014 — dedup keys (FR-009, SC-005) + T012 manual import + T007 URL-liveness (FR-005).
All deterministic / stubbed — no network.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("YOKE_HOME", tempfile.mkdtemp(prefix="yoke-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import collect  # noqa: E402
import board  # noqa: E402


class TestDedupKeys(unittest.TestCase):
    def test_role_key_collapses_reposts(self):
        a = collect.norm("Senior AI Engineer", "Acme", "Remote", "https://x.com/jobs/1", "ats")
        b = collect.norm("Senior  AI   Engineer", "Acme", "Remote", "https://y.com/jobs/2", "ats")  # repost, new URL
        self.assertEqual(collect.role_key(a), collect.role_key(b))   # same company|normalized-title
        self.assertNotEqual(collect.job_key(a), collect.job_key(b))  # different URL

    def test_job_key_is_url(self):
        j = collect.norm("X", "Y", "Remote", "https://X.com/Jobs/1", "ats")
        self.assertEqual(collect.job_key(j), "https://x.com/jobs/1")


class TestManualImport(unittest.TestCase):
    def test_reads_import_file(self):
        home = Path(os.environ["YOKE_HOME"])
        home.mkdir(parents=True, exist_ok=True)
        (home / "import.json").write_text(json.dumps([
            {"title": "AI Engineer", "company": "Foo", "url": "https://foo/1"}]))
        rows = collect.scan_manual()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "manual")
        self.assertEqual(rows[0]["company"], "Foo")

    def test_returns_list(self):
        self.assertIsInstance(collect.scan_manual(), list)  # never raises, even if absent


class TestLiveness(unittest.TestCase):
    def test_404_410_are_dead(self):
        self.assertEqual(board.url_liveness("u", lambda _u: 404), "dead")
        self.assertEqual(board.url_liveness("u", lambda _u: 410), "dead")

    def test_2xx_alive(self):
        self.assertEqual(board.url_liveness("u", lambda _u: 200), "alive")

    def test_transient_and_5xx_do_not_prune(self):
        self.assertEqual(board.url_liveness("u", lambda _u: None), "unknown")  # timeout/URLError
        self.assertEqual(board.url_liveness("u", lambda _u: 503), "unknown")   # server error, keep
        self.assertEqual(board.url_liveness("", lambda _u: 404), "unknown")     # no URL, keep


if __name__ == "__main__":
    unittest.main()

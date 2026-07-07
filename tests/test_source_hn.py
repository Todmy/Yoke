import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="yoke-test-hn-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.sources import hn  # noqa: E402

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name):
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


class TestHNSource(unittest.TestCase):
    def test_module_contract(self):
        self.assertEqual(hn.NAME, "hn")
        self.assertEqual(hn.TAGS, {"domain": "it", "country": "intl"})
        self.assertEqual(hn.COST, "free")
        self.assertTrue(hn.bypass_lane)  # HN comments lack clean job titles
        self.assertEqual(hn.available(), (True, ""))

    def test_thread_search_parse(self):
        story_id = hn._parse_thread_search(_load("hn_thread_search.json"))
        self.assertEqual(story_id, "44000001")
        self.assertIsNone(hn._parse_thread_search({"hits": []}))
        self.assertIsNone(hn._parse_thread_search({}))

    def test_comments_parse(self):
        jobs = hn._parse_comments(_load("hn_comments.json"), {})
        # 3 comments in fixture; the onsite-only one (no "remote") is dropped
        self.assertEqual(len(jobs), 2)
        self.assertEqual(
            jobs[0],
            {
                "title": (
                    "Acme Corp | Senior Backend Engineer | Remote (EU) | "
                    "$8k-10k/mo Python, LLM pipelines. Apply: jobs@acme.example"
                ),
                "company": "(HN who-is-hiring)",
                "location": "see post",
                "url": "https://news.ycombinator.com/item?id=44001001",
                "source": "hn",
                "posted_at": "2026-06-02T15:01:00.000Z",
                "comp": None,
            },
        )

    def test_comments_parse_empty_payload(self):
        self.assertEqual(hn._parse_comments({}, {}), [])
        self.assertEqual(hn._parse_comments({"children": None}, {}), [])


if __name__ == "__main__":
    unittest.main()

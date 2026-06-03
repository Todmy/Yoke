"""T025 — gap analysis: deterministic match, ranked-missing, no-fabrication, and
the cover-letter prompt grounding (US3, FR-011/013/014, SC-006).

No model calls — only the deterministic taxonomy match + prompt assembly.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("YOKE_HOME", tempfile.mkdtemp(prefix="yoke-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import gap  # noqa: E402
import cover  # noqa: E402

TAX = gap.load_taxonomy()
JD = "We need Python and Kubernetes for our high-load distributed systems; RAG and agents a plus."
CV = "Senior engineer. Python, FastAPI, RAG pipelines. Built evaluation harnesses."


class TestExtract(unittest.TestCase):
    def test_aliases_match(self):
        sk = gap.extract_skills("k8s and golang on gcp", TAX)
        self.assertIn("Kubernetes", sk)
        self.assertIn("Go", sk)
        self.assertIn("GCP", sk)

    def test_no_false_substring(self):
        # 'java' must not fire on 'javascript' alone (JS has its own entry)
        sk = gap.extract_skills("javascript only", TAX)
        self.assertIn("JavaScript", sk)
        self.assertNotIn("Java", sk)


class TestGap(unittest.TestCase):
    def setUp(self):
        self.g = gap.compute_gap(JD, CV, TAX)

    def test_matched_and_missing(self):
        self.assertIn("Python", self.g["matched"])
        self.assertIn("RAG", self.g["matched"])
        missing = [m["skill"] for m in self.g["missing"]]
        self.assertIn("Kubernetes", missing)
        self.assertIn("High-load systems", missing)

    def test_no_fabrication(self):
        # SC-006: nothing reported as matched may be absent from the CV
        cv_skills = set(gap.extract_skills(CV, TAX))
        for m in self.g["matched"]:
            self.assertIn(m, cv_skills)
        # and nothing missing is actually in the CV
        for m in self.g["missing"]:
            self.assertNotIn(m["skill"], cv_skills)

    def test_indicator_is_relevance_not_ats(self):
        self.assertIn(self.g["match_band"], ("Strong", "Moderate", "Weak"))
        self.assertIn("not", self.g["indicator_note"].lower())  # disclaims ATS-beating
        self.assertIsInstance(self.g["match_score"], int)

    def test_missing_ranked_central_first(self):
        # JD mentions high-load/distributed twice-ish; ensure ordering is by centrality desc
        scores = [gap._centrality(gap.extract_skills(JD, TAX)[m["skill"]], JD) for m in self.g["missing"]]
        self.assertEqual(scores, sorted(scores, reverse=True))


class TestCoverPrompt(unittest.TestCase):
    def test_prompt_grounded_in_cv_and_jd(self):
        p = cover.build_prompt(CV, JD, "Acme", "Senior Engineer")
        self.assertIn(CV, p)
        self.assertIn("Kubernetes", p)  # from JD

    def test_system_forbids_fabrication(self):
        self.assertIn("NEVER invent", cover._SYSTEM)


if __name__ == "__main__":
    unittest.main()

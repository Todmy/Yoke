"""T015 — deterministic pipeline: prepare.build_card hard-gates off-lane roles with
ZERO model calls; in-lane roles flow to mock_fill → score_fit → tier_of (FR-006, SC-002).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("YOKE_HOME", tempfile.mkdtemp(prefix="yoke-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import prepare  # noqa: E402
import analyze  # noqa: E402


def entry(title, company="Acme", location="Remote", url="https://x/1"):
    return {"key": url, "url": url, "role_key": f"{company.lower()}|x", "title": title,
            "company": company, "location": location, "source": "ats:test"}


class TestHardGate(unittest.TestCase):
    def test_offlane_title_hard_gated_no_model(self):
        card = prepare.build_card(entry("Frontend Engineer"))
        self.assertTrue(card["hard_gate_fail"])      # decided by rules → Tier C, no model call

    def test_inlane_needs_model(self):
        card = prepare.build_card(entry("AI Engineer"))
        self.assertFalse(card["hard_gate_fail"])
        self.assertIn("fit_features", card["needs_ai"])


class TestDeterministicScore(unittest.TestCase):
    def test_mock_fill_to_tier_no_provider(self):
        card = prepare.build_card(entry("Applied AI Engineer"))
        fill = analyze.mock_fill(card)               # deterministic stub, no provider
        fit = analyze.score_fit(fill["fit_features"])
        tier = analyze.tier_of(fit, fill["geo_verdict"], False)
        self.assertIn(tier, ("A", "B", "C"))
        self.assertGreaterEqual(fit, 0)
        self.assertLessEqual(fit, 100)


if __name__ == "__main__":
    unittest.main()

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="yoke-test-llm-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.llm import build_prompt, extract_json, get_backend  # noqa: E402


class TestExtractJson(unittest.TestCase):
    def test_extract_json_fenced(self):
        text = '```json\n{"fit": 72, "tier": "A"}\n```'
        self.assertEqual(extract_json(text), {"fit": 72, "tier": "A"})

    def test_extract_json_prose(self):
        text = 'Sure, here is the result:\n{"fit": 55}\nHope that helps!'
        self.assertEqual(extract_json(text), {"fit": 55})

    def test_extract_json_raises(self):
        with self.assertRaises(ValueError):
            extract_json("no json here at all")
        with self.assertRaises(ValueError):
            extract_json(None)


class TestBuildPrompt(unittest.TestCase):
    def test_build_prompt_appends_schema(self):
        schema = {"type": "object", "properties": {"fit": {"type": "integer"}}}
        out = build_prompt("score this", schema)
        self.assertTrue(out.startswith("score this"))
        self.assertIn('"fit"', out)
        self.assertIn("ONLY valid JSON", out)
        # without schema: still pins JSON-only output
        bare = build_prompt("score this", None)
        self.assertTrue(bare.startswith("score this"))
        self.assertIn("ONLY valid JSON", bare)
        self.assertNotIn('"fit"', bare)


class TestGetBackend(unittest.TestCase):
    def test_get_backend_env_cascade(self):
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("YOKE_PROVIDER", "OPENROUTER_API_KEY",
                              "YOKE_MODEL", "YOKE_BASE_URL", "YOKE_API_KEY")}

        # 1. nothing set -> ClaudeCodeBackend, default model, describe()
        with mock.patch.dict(os.environ, clean, clear=True):
            be = get_backend()
            self.assertEqual(be.name, "claude_code")
            self.assertEqual(be.model, "claude-haiku-4-5")
            self.assertEqual(be.describe(), "claude-code:claude-haiku-4-5")

        # 2. OPENROUTER_API_KEY set -> openrouter backend
        with mock.patch.dict(os.environ, {**clean, "OPENROUTER_API_KEY": "sk-test"},
                             clear=True):
            be = get_backend()
            self.assertEqual(be.name, "openrouter")
            self.assertEqual(be.describe(), f"openrouter:{be.model}")

        # 3. YOKE_PROVIDER wins over OPENROUTER_API_KEY
        with mock.patch.dict(os.environ,
                             {**clean, "OPENROUTER_API_KEY": "sk-test",
                              "YOKE_PROVIDER": "ollama"}, clear=True):
            be = get_backend()
            self.assertEqual(be.name, "ollama")

        # 4. YOKE_PROVIDER=claude_code -> subprocess backend even with a key
        with mock.patch.dict(os.environ,
                             {**clean, "OPENROUTER_API_KEY": "sk-test",
                              "YOKE_PROVIDER": "claude_code"}, clear=True):
            be = get_backend(model="claude-sonnet-4-5")
            self.assertEqual(be.name, "claude_code")
            self.assertEqual(be.model, "claude-sonnet-4-5")

        # 5. force overrides env
        with mock.patch.dict(os.environ, {**clean, "YOKE_PROVIDER": "ollama"},
                             clear=True):
            be = get_backend(force="claude_code")
            self.assertEqual(be.name, "claude_code")


if __name__ == "__main__":
    unittest.main()

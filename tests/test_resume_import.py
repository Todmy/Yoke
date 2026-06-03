"""002 résumé import — autofill field mapping + no-fabrication (mock backend),
extract_text(.txt) deterministic, and the lib-absent / unsupported-format fallbacks
(FR-003/005/009, SC-003/SC-005). Stdlib unittest, no real model call.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("YOKE_HOME", tempfile.mkdtemp(prefix="yoke-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import resume_import  # noqa: E402
from resume_import import (autofill, extract_text, ExtractionUnavailable,  # noqa: E402
                           NoTextFound, MalformedOutput)


class _MockBackend:
    """Returns a fixed dict — stands in for get_backend().complete()."""
    def __init__(self, payload):
        self.payload = payload

    def complete(self, prompt, schema=None, system=None):
        return self.payload


class TestAutofillMapping(unittest.TestCase):
    def test_maps_fields_from_resume(self):
        be = _MockBackend({
            "basics": {"name": "Dana Lee", "label": "Staff ML Engineer",
                       "summary": "ML engineer with 8y in production systems."},
            "work": [{"company": "Acme", "position": "Staff ML Engineer"}],
            "skills": ["Python", "PyTorch", "MLOps"],
            "seniority": "staff",
        })
        out = autofill("irrelevant cv text", backend=be)
        self.assertEqual(out["name"], "Dana Lee")
        self.assertEqual(out["headline"], "Staff ML Engineer")
        self.assertIn("PyTorch", out["scoring_prompt"])
        self.assertIn("Staff ML Engineer", out["scoring_prompt"])
        self.assertEqual(out["_resume"], be.payload)

    def test_absent_field_is_empty_not_fabricated(self):
        # no basics.label in the model output → headline must be "", never guessed
        be = _MockBackend({"basics": {"name": "Sam"}, "skills": []})
        out = autofill("cv", backend=be)
        self.assertEqual(out["headline"], "")
        self.assertEqual(out["name"], "Sam")

    def test_empty_cv_no_call(self):
        # empty input returns empty fields without invoking the backend
        class Boom:
            def complete(self, *a, **k): raise AssertionError("should not be called")
        out = autofill("   ", backend=Boom())
        self.assertEqual(out, {"name": "", "headline": "", "scoring_prompt": "", "_resume": {}})

    def test_malformed_output_raises(self):
        be = _MockBackend(["not", "a", "dict"])
        with self.assertRaises(MalformedOutput):
            autofill("cv", backend=be)

    def test_empty_resume_yields_empty_prompt(self):
        out = autofill("cv", backend=_MockBackend({}))
        self.assertEqual(out["scoring_prompt"], "")


class TestExtractText(unittest.TestCase):
    def _write(self, name, content):
        p = Path(tempfile.mkdtemp(prefix="yoke-cv-")) / name
        p.write_text(content)
        return str(p)

    def test_txt_roundtrip(self):
        path = self._write("cv.txt", "Jane Doe\nSenior Engineer\nPython, Go")
        self.assertEqual(extract_text(path), "Jane Doe\nSenior Engineer\nPython, Go")

    def test_empty_file_raises_notextfound(self):
        path = self._write("empty.txt", "   \n  ")
        with self.assertRaises(NoTextFound):
            extract_text(path)

    def test_legacy_doc_unsupported(self):
        with self.assertRaises(ExtractionUnavailable) as cm:
            extract_text("/tmp/whatever.doc")
        self.assertIn("docx", str(cm.exception).lower())

    def test_pdf_without_lib_degrades(self):
        # force `import pypdf` to fail regardless of the environment
        saved = sys.modules.get("pypdf")
        sys.modules["pypdf"] = None  # makes `import pypdf` raise ImportError
        try:
            with self.assertRaises(ExtractionUnavailable) as cm:
                resume_import._extract_pdf("/tmp/x.pdf")
            self.assertIn("pip install pypdf", cm.exception.hint)
        finally:
            if saved is None:
                sys.modules.pop("pypdf", None)
            else:
                sys.modules["pypdf"] = saved


if __name__ == "__main__":
    unittest.main()

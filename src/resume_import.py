"""Résumé import + Profile auto-fill (feature 002).

CLI-first (Constitution I): the Profile web page calls these same functions.
Two jobs, both reusable:
  • extract_text(path)        — file → plain text. Deterministic, no model.
                                .txt/.md = stdlib; .pdf/.docx = lazy optional libs.
  • autofill(cv_text)         — text → {name, headline, scoring_prompt, _resume}
                                via ONE narrow model call (a JSON-Resume subset),
                                then a deterministic scoring-prompt assembly.

Truthfulness (Constitution VI / FR-003): the model extracts ONLY what is present;
absent fields come back empty, never invented. The scoring prompt is assembled in
code from extracted facts — not free-form embellishment.

Zero-dependency core (Constitution VII / FR-009): pypdf/python-docx are optional,
imported lazily inside the readers; their absence degrades to "paste the text".
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm import get_backend  # noqa: E402


class ExtractionUnavailable(Exception):
    """A file format can't be read here (optional lib missing, or unsupported)."""
    def __init__(self, fmt, hint):
        self.fmt, self.hint = fmt, hint
        super().__init__(f"cannot read {fmt}: {hint}")


class NoTextFound(Exception):
    """The file was read but yielded no usable text (e.g. a scanned PDF)."""


class MalformedOutput(Exception):
    """The model returned something that isn't a usable résumé object."""


# JSON-Resume subset — the narrow, fixed schema a weak/local model fills reliably.
RESUME_SCHEMA = {
    "type": "object",
    "properties": {
        "basics": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "label": {"type": "string", "description": "one-line headline"},
                "summary": {"type": "string", "description": "2-3 sentence profile, from the CV only"},
            },
        },
        "work": {
            "type": "array",
            "items": {"type": "object", "properties": {
                "company": {"type": "string"}, "position": {"type": "string"}}},
        },
        "skills": {"type": "array", "items": {"type": "string"}},
        "seniority": {"type": "string", "description": "e.g. senior/staff — only if stated or unambiguous"},
    },
}

_SYSTEM = (
    "You extract a structured résumé from the text the user provides. "
    "Extract ONLY what is present in the text. Never infer, guess, or invent a name, "
    "title, employer, skill, seniority, certification, or metric that is not explicitly there. "
    "If a field is not present, omit it or leave it empty — do not fill it with a plausible guess. "
    "Return only the requested JSON."
)


def _read_textfile(path):
    raw = Path(path).read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def _extract_pdf(path):
    try:
        import pypdf  # lazy, optional (BSD)
    except ImportError:
        raise ExtractionUnavailable("pdf", "pip install pypdf  (or paste the text)")
    reader = pypdf.PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_docx(path):
    try:
        import docx  # lazy, optional (python-docx, MIT)
    except ImportError:
        raise ExtractionUnavailable("docx", "pip install python-docx  (or paste the text)")
    return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)


def extract_text(path):
    """File → plain text. Raises ExtractionUnavailable (unreadable format / missing
    optional lib) or NoTextFound (empty result)."""
    ext = Path(path).suffix.lower()
    if ext in ("", ".txt", ".md", ".text"):
        text = _read_textfile(path)
    elif ext == ".pdf":
        text = _extract_pdf(path)
    elif ext == ".docx":
        text = _extract_docx(path)
    elif ext == ".doc":
        raise ExtractionUnavailable("doc", "legacy .doc isn't supported — save as .docx or paste the text")
    else:
        raise ExtractionUnavailable(ext or "file", "unsupported format — paste the text instead")
    if not text or not text.strip():
        raise NoTextFound(f"no readable text in {path}")
    return text


def _assemble_scoring_prompt(resume):
    """Build a draft scoring prompt from EXTRACTED facts only (no invention).
    The user edits it afterward; geo/comp aren't on a CV so they're left to add."""
    basics = resume.get("basics") or {}
    parts = []
    summary = (basics.get("summary") or "").strip()
    if summary:
        parts.append(summary)
    seniority = (resume.get("seniority") or "").strip()
    positions = [w.get("position", "").strip() for w in (resume.get("work") or []) if w.get("position")]
    if seniority or positions:
        roles = ", ".join(dict.fromkeys(positions))  # de-dup, keep order
        lead = seniority + " " if seniority else ""
        parts.append(f"Lane: {lead}{roles}".strip())
    skills = [s.strip() for s in (resume.get("skills") or []) if s.strip()]
    if skills:
        parts.append("Core skills / differentiators: " + ", ".join(skills))
    return "\n".join(parts)


def autofill(cv_text, backend=None):
    """Résumé text → {name, headline, scoring_prompt, _resume}. One model call.
    Absent info → empty fields (never fabricated). Raises MalformedOutput on junk."""
    if not cv_text or not cv_text.strip():
        return {"name": "", "headline": "", "scoring_prompt": "", "_resume": {}}
    backend = backend or get_backend()
    prompt = "Résumé text:\n\n" + cv_text.strip()
    data = backend.complete(prompt, schema=RESUME_SCHEMA, system=_SYSTEM)
    if not isinstance(data, dict):
        raise MalformedOutput(f"expected a JSON object, got {type(data).__name__}")
    basics = data.get("basics") or {}
    return {
        "name": (basics.get("name") or "").strip(),
        "headline": (basics.get("label") or "").strip(),
        "scoring_prompt": _assemble_scoring_prompt(data),
        "_resume": data,
    }


def _provider_is_local():
    return os.environ.get("YOKE_PROVIDER", "claude_code") in ("ollama", "lmstudio")


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: resume_import.py extract <path> | autofill <path|-> [--json]", file=sys.stderr)
        return 0
    cmd = argv[0]
    rest = [a for a in argv[1:] if a != "--json"]
    src = rest[0] if rest else "-"
    try:
        text = sys.stdin.read() if src == "-" else extract_text(src)
    except ExtractionUnavailable as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except NoTextFound as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    if cmd == "extract":
        print(text)
        return 0
    if cmd == "autofill":
        if not _provider_is_local():
            print(f"note: résumé text will be sent to your model provider "
                  f"({os.environ.get('YOKE_PROVIDER', 'claude_code')}).", file=sys.stderr)
        try:
            result = autofill(text)
        except MalformedOutput as e:
            print(f"error: {e}", file=sys.stderr)
            return 5
        except Exception as e:  # provider/network failures
            print(f"error: auto-fill failed: {type(e).__name__}: {e}", file=sys.stderr)
            return 4
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

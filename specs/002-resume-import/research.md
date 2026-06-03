# Research: Résumé Import & Profile Auto-fill

Phase 0 — resolve the technical unknowns. Most clarify-level decisions were settled
in discussion and recorded in spec Assumptions; this consolidates the library and
parsing choices with rationale.

## R1 — PDF text extraction library

**Decision**: `pypdf` (BSD-3), lazy-imported, venv-optional. Step-up to `pdfplumber` (MIT) only if real CVs extract poorly.

**Rationale**: Auto-fill feeds the extracted text to an LLM that re-structures it into JSON Resume, so we need **clean text**, not layout-preserving markdown. pypdf gives reliable text for digital (non-scanned) 1–2 page CVs, is pure-Python (no binary wheel), lightweight, and BSD-licensed — keeps Yoke's MIT license clean.

**Alternatives considered**:
- `pymupdf4llm` / PyMuPDF — best markdown, but **AGPL-3.0** (Artifex dual-license). Contaminates an MIT OSS project even as a hard dep; rejected. This is the library `interviewstreet/hiring-agent` uses; we take its *recipe*, not this dep.
- `pdfminer.six` (MIT) — good text, more control; heavier than pypdf, no advantage for our use.
- `pdfplumber` (MIT, on pdfminer) — great for tables/columns; pulls Pillow. Held as the fallback if pypdf text is messy.
- `markitdown` (MIT) — any-format→markdown; heavier dep tree than needed.

## R2 — Word (.docx) extraction

**Decision**: `python-docx` (MIT), lazy-imported, venv-optional.

**Rationale**: `.docx` is zip+XML; `python-docx` is the standard, MIT-licensed, lightweight reader. (A pure-stdlib `zipfile`+XML walk is possible but brittle across docx variants — not worth it.)

**Alternatives**: stdlib zipfile/XML (brittle); markitdown (heavier).

## R3 — Plain text / Markdown

**Decision**: stdlib only — read the file, decode UTF-8 (with latin-1 fallback). No dependency.

## R4 — Optional-dependency mechanism (Constitution VII)

**Decision**: lazy `import` **inside** `extract_text` per format; on `ImportError` raise a typed `ExtractionUnavailable` carrying the pip install hint. The core never imports these at module level (enforced by the existing `test_invariants` allowlist — add `pypdf`/`docx` to the OPTIONAL_LAZY set, NOT to module-level). Document installs in `requirements-optional.txt`.

**Rationale**: Exactly the `jobspy` carve-out the constitution already sanctions. Paste path (`.txt`/pasted text) needs nothing; PDF/docx degrade to a "install X or paste instead" message.

## R5 — File upload parsing in stdlib http.server (no `cgi`)

**Decision**: Parse `multipart/form-data` with the stdlib `email` module — feed `Content-Type` + body to `email.parser.BytesParser` and walk the parts. `.txt` uploads may alternatively be read client-side (FileReader) and posted as a urlencoded field, but binary (PDF/docx) bytes must reach the server, so server-side multipart is required.

**Rationale**: `cgi.FieldStorage` was removed in Python 3.13. The `email` BytesParser is the documented stdlib path for multipart and keeps the core dependency-free.

**Alternatives**: manual boundary splitting (works but fiddly/error-prone); a web framework (violates zero-dep core).

## R6 — Parsing recipe (stolen from hiring-agent, run on our backend)

**Decision**: extracted text → **one** `get_backend().complete(prompt, schema=…, system=…)` call that returns a JSON-Resume-subset dict (basics.name, basics.label/headline, work[], skills[]); from that we derive name, headline, and a drafted scoring prompt. One call per the spec; not section-wise.

**Rationale**: hiring-agent proves the JSON-Resume + structured-extraction recipe; we reuse the *recipe and schema* on Yoke's existing backend rather than its code/deps/provider layer. One call keeps latency/cost predictable and matches the user's stated "one LLM call". The fixed schema is the weak-model-friendly task Principle II wants.

**Truthfulness (Principle VI / FR-003)**: the system prompt instructs "extract only what is present; never infer or invent; leave fields absent if not stated". The scoring-prompt draft is assembled from extracted facts (titles, stack, seniority), not free-form embellishment.

## R7 — Privacy gate (FR-013)

**Decision**: before an auto-fill call, check the active provider; if it is not local (not `ollama`/`lmstudio`), show a one-time confirm: "Your résumé text will be sent to <provider>." Proceed on confirm; never block. Reuse the existing provider-detection in serve.py (`read_env`).

**Rationale**: Honest local-first. Cloud users (most) still get the feature; local-model users are unaffected.

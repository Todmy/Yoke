# Contracts: Résumé Import & Profile Auto-fill

Per Constitution I, the capability is a CLI module; the web panel is a thin client over it.

## CLI — `src/resume_import.py` (wired as `yoke resume`)

```
yoke resume extract <path>            # PDF/docx/txt → plain text on stdout
yoke resume autofill <path|->         # extract (or read stdin with -) → JSON proposal on stdout
        [--json]                      # machine-readable (default for autofill)
```

### `extract_text(path: str) -> str`
- Dispatches by extension: `.txt`/`.md` (stdlib), `.pdf` (lazy `pypdf`), `.docx` (lazy `python-docx`).
- Raises `ExtractionUnavailable(format, pip_hint)` if the optional lib is missing.
- Raises `NoTextFound` if the file yields no usable text (e.g., scanned PDF).
- Pure/deterministic; no model call. Unit-tested on `.txt` and on lib-absent path.

### `autofill(cv_text: str, backend=None) -> dict`
- `backend = backend or get_backend()`; one `complete(prompt, schema=RESUME_SCHEMA, system=_SYSTEM)` call.
- Returns `{"name", "headline", "scoring_prompt", "_resume": <JSON-Resume subset>}`.
- Absent source info → empty string for that field (never fabricated).
- Raises on malformed model output (caller surfaces "edit manually").
- CLI prints the dict as JSON. The cloud-warning gate (FR-013) is a UI/CLI concern, not in this pure function — CLI prints a stderr notice when provider is non-local.

### Exit codes
`0` ok · `2` extraction unavailable (lib missing) · `3` no text found · `4` no provider · `5` malformed model output. Errors → stderr.

## UI — `serve.py` Profile page

### Page additions (GET `/profile`)
- **⬆ Upload résumé** (file input: `.txt,.md,.pdf,.docx`) → posts to `/profile/upload`.
- **✨ Auto-fill from CV** button → posts current résumé text to `/profile/autofill`.
- A note line: which formats need `pip install` (opt-in), and that non-local providers send the CV out.

### POST `/profile/upload` (multipart/form-data)
- Parse with stdlib `email.parser.BytesParser`; size cap enforced before read.
- On success: extracted text rendered back into the résumé textarea (form pre-filled), nothing saved.
- On `ExtractionUnavailable`/`NoTextFound`: flash with the install hint / paste fallback; form intact.

### POST `/profile/autofill` (urlencoded: `resume_text`, `confirm_cloud?`)
- If no provider → flash "set a provider" (no call).
- If provider non-local AND `confirm_cloud` not set → re-render the form with a confirm prompt ("CV will be sent to <provider>"); no call yet.
- Else → `autofill(resume_text)`; re-render the Profile form with `name`/`headline`/`prompt` **replaced** by the proposal (editable, unsaved). On malformed output → flash "couldn't auto-fill; edit manually", form values preserved.

### POST `/profile` (existing, unchanged)
- Saves the form (including any auto-filled+edited values) to `profile.json`. This is the only write.

## Invariants (tie to constitution)
- No module-level import of `pypdf`/`python-docx` (test_invariants allowlist — OPTIONAL_LAZY).
- Web layer holds no parsing/auto-fill logic; it calls `resume_import`.
- Nothing persists until POST `/profile` (Save).

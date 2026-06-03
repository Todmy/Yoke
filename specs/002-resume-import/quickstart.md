# Quickstart: Résumé Import & Profile Auto-fill

## For the user

**Paste path (no install needed):**
1. Open **Profile**, paste your CV text into the résumé box.
2. Click **✨ Auto-fill from CV**. (On a cloud provider you'll confirm "CV will be sent to <provider>" once.)
3. Review the proposed name / headline / scoring prompt — edit anything off — click **Save**.

**File path (opt-in):**
```bash
pip install pypdf python-docx     # only needed for PDF / .docx upload
```
1. Open **Profile** → **⬆ Upload résumé** → pick a `.pdf` / `.docx` / `.txt`.
2. The extracted text lands in the résumé box → continue as above.

**CLI:**
```bash
yoke resume extract ~/cv.pdf                 # text to stdout
yoke resume autofill ~/cv.pdf --json         # proposal as JSON
cat cv.txt | yoke resume autofill - --json   # from stdin
```

## For the developer (tests)

```bash
python3 -m unittest tests.test_resume_import     # deterministic + mock-backend
python3 -m unittest discover -s tests            # full suite stays green
```

Test coverage:
- `extract_text` on a `.txt` fixture → exact text (deterministic, no model).
- lib-absent path → `ExtractionUnavailable` with a pip hint (simulate by import guard).
- `autofill` with a **mock backend** returning a JSON-Resume dict → correct field mapping;
  a dict missing `basics.label` → empty `headline` (no fabrication, FR-005).
- `test_invariants`: `pypdf`/`docx` never imported at module level.

## Acceptance walk-through (maps to spec)

| Spec | Check |
|------|-------|
| US1 / SC-001 | paste CV → autofill → save → reopen: prompt+headline persisted, < 2 min |
| FR-003/005 / SC-003 | proposal contains only CV-present facts; missing → empty |
| FR-013 | cloud provider → warning+confirm before the call; local → no warning |
| FR-004 | autofill replaces target form fields; nothing saved until Save |
| US2 / FR-009 | PDF upload works with libs; without libs → "install or paste", no crash |
| SC-004 | clean install (no pip extras): paste path works end-to-end |

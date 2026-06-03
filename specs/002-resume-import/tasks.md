# Tasks: Résumé Import & Profile Auto-fill

**Feature**: `002-resume-import` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Tests**: included (constitution: correctness-critical pure functions unit-tested; deterministic paths via `--mock`).

## Phase 1: Setup

- [ ] T001 Add `requirements-optional.txt` at repo root listing `pypdf` (BSD) and `python-docx` (MIT) with a comment that they are opt-in, venv-only, for PDF/.docx résumé upload (not needed for paste). Reference it from README quickstart.
- [ ] T002 Extend `tests/test_invariants.py`: add `pypdf`, `docx` to the `OPTIONAL_LAZY` set and assert neither appears as a module-level import in `src/` (only lazy, inside functions) — locks Constitution VII.

## Phase 2: Foundational (blocks US1 and US2)

- [ ] T003 Create `src/resume_import.py` skeleton: module docstring, `from __future__ import annotations`, exceptions `ExtractionUnavailable(format, pip_hint)` and `NoTextFound`, the `RESUME_SCHEMA` (JSON-Resume subset: basics.name, basics.label, work[], skills[]), and the `_SYSTEM` prompt enforcing "extract only what is present; never infer or invent; omit absent fields" (FR-003/005, Constitution VI).
- [ ] T004 In `src/resume_import.py` implement `extract_text(path)` dispatch by extension: `.txt`/`.md` via stdlib UTF-8 (latin-1 fallback); `.pdf`/`.docx` branches raise `ExtractionUnavailable` for now (real readers land in US2). Raise `NoTextFound` on empty result. Pure, no model call.

## Phase 3: User Story 1 — Auto-fill from résumé text (Priority: P1) 🎯 MVP

**Goal**: Paste CV text → Auto-fill proposes name/headline/scoring-prompt → review → Save.
**Independent test**: paste text → autofill → fields populated from text → edit → Save → reopen → persisted.

- [ ] T005 [P] [US1] In `src/resume_import.py` implement `autofill(cv_text, backend=None)`: `backend or get_backend()`; one `complete(prompt, schema=RESUME_SCHEMA, system=_SYSTEM)` call; map result → `{"name","headline","scoring_prompt","_resume"}`; empty string for absent fields (FR-005); raise on malformed output (FR-012).
- [ ] T006 [P] [US1] In `src/resume_import.py` add CLI `main`: `extract <path>` and `autofill <path|-> [--json]` (stdin via `-`); exit codes 0/2/3/4/5 per contract; non-local-provider notice to stderr.
- [ ] T007 [US1] Wire `resume` into the `yoke` dispatcher → `exec python3 "$S/resume_import.py" "$@"`; add the help line.
- [ ] T008 [US1] In `src/serve.py` add POST `/profile/autofill` (urlencoded `resume_text`, `confirm_cloud?`): no-provider → flash "set a provider"; non-local provider without `confirm_cloud` → re-render form with a confirm prompt (FR-013); else call `resume_import.autofill` and re-render Profile form with `name`/`headline`/`prompt` **replaced** by the proposal (editable, unsaved, FR-004); malformed → flash "couldn't auto-fill; edit manually", preserve form values.
- [ ] T009 [US1] In `src/serve.py` `profile_page`: add a **✨ Auto-fill from CV** button (posts résumé textarea to `/profile/autofill`) and a note line that non-local providers send the CV out; import `resume_import` (lazy in handler is fine).
- [ ] T010 [P] [US1] Add `tests/test_resume_import.py`: `autofill` with a **mock backend** returning a JSON-Resume dict → asserts name/headline/scoring_prompt mapping; a dict missing `basics.label` → empty `headline` (no fabrication, FR-005/SC-003); malformed output → raises.

**Checkpoint**: US1 is a usable MVP — paste→autofill→save works with zero optional deps.

## Phase 4: User Story 2 — Bring résumé as a file (Priority: P2)

**Goal**: Upload PDF/Word/txt → extracted text into the résumé field → same auto-fill.
**Independent test**: upload a text PDF, a .docx, a .txt → readable text appears in the field.

- [ ] T011 [P] [US2] In `src/resume_import.py` implement the `.pdf` reader: lazy `import pypdf` inside the function; extract text per page; on `ImportError` raise `ExtractionUnavailable("pdf", "pip install pypdf")`; on empty text raise `NoTextFound`.
- [ ] T012 [P] [US2] In `src/resume_import.py` implement the `.docx` reader: lazy `import docx`; join paragraph text; `ImportError` → `ExtractionUnavailable("docx", "pip install python-docx")`. Legacy `.doc` is out of scope — reject with a "convert to .docx or paste" message.
- [ ] T013 [US2] In `src/serve.py` add `_parse_multipart(headers, body)` using stdlib `email.parser.BytesParser` (no `cgi`); enforce a **5 MB** size cap (FR-007a) before reading the part, rejecting larger uploads with a clear message.
- [ ] T014 [US2] In `src/serve.py` add POST `/profile/upload` (multipart): parse file → `resume_import.extract_text` (write to a temp path or pass bytes) → render extracted text back into the résumé textarea (unsaved); `ExtractionUnavailable`/`NoTextFound` → flash install-hint / paste-fallback, form intact (FR-009).
- [ ] T015 [US2] In `src/serve.py` `profile_page`: add **⬆ Upload résumé** file input (`.txt,.md,.pdf,.docx`) posting to `/profile/upload`, with the opt-in install note.
- [ ] T016 [P] [US2] In `tests/test_resume_import.py`: `extract_text` on a `.txt` fixture → exact text; the `.pdf`/`.docx` branches with the lib import forced to fail → `ExtractionUnavailable` carrying the pip hint (lib-absent fallback, FR-009/SC-005).

**Checkpoint**: US2 adds file upload; absence of optional libs degrades to paste, never crashes.

## Phase 5: Polish & Cross-Cutting

- [ ] T017 [P] Update `README.md` providers/quickstart + `specs/002-resume-import/quickstart.md` reference: paste path is zero-dep; PDF/.docx need `pip install pypdf python-docx`.
- [ ] T018 Run `python3 -m unittest discover -s tests` — full suite green (existing 48 + new resume-import tests); confirm `test_invariants` passes with the new optional libs.
- [ ] T019 [P] Manual QA: add a "Résumé import" section to `docs/manual-qa-checklist.md` (paste→autofill→save; cloud-warning; upload with/without libs; no-text PDF fallback).

## Dependencies & Order

- **Setup (T001–T002)** → **Foundational (T003–T004)** → **US1 (T005–T010)** → **US2 (T011–T016)** → **Polish (T017–T019)**.
- US1 is independently shippable as the MVP without US2.
- US2 depends only on the Foundational skeleton (T003–T004), not on US1 — but ship US1 first (priority).

## Parallel Opportunities

- T005, T006, T010 (US1) touch different concerns (autofill fn / CLI / tests) — `[P]` where files differ; T005 & T006 share `resume_import.py` so sequence them, T010 is a separate test file `[P]`.
- T011, T012 (pdf/docx readers) are independent functions — `[P]`.
- T016 test `[P]` with T011/T012.
- T017, T019 docs `[P]`.

## MVP Scope

**Just Phase 1–3 (US1)** = a usable feature: paste your CV, auto-fill the hardest fields, review, save — zero optional dependencies. US2 (file upload) is an additive increment.

## Notes

- No persistence change: Profile already stores `resume_text` and `prompt`; auto-fill writes to the form, Save persists (existing POST `/profile`).
- Truthfulness (FR-003) lives in `_SYSTEM` + the empty-on-absent mapping, verified by T010.
- Cloud-warning (FR-013) is UI-layer (T008), not in the pure `autofill` fn.
- Truthfulness of the *generated* scoring_prompt (free text) is not unit-tested — it can't be checked deterministically; it relies on `_SYSTEM` (T003). T010 verifies no-fabrication on the structured fields (empty-on-absent). Accepted limitation (analyze C3).

# Implementation Plan: Résumé Import & Profile Auto-fill

**Branch**: `002-resume-import` | **Date**: 2026-06-03 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-resume-import/spec.md`

## Summary

Let a user bring an existing résumé (paste text, or upload PDF/Word/txt) and have Yoke **propose** the Profile fields — name, headline, and the scoring prompt — in one step, which the user reviews and edits before saving. The paste→auto-fill→save path runs on the zero-dependency core; file extraction for PDF/Word is an optional, opt-in, permissively-licensed venv add-on that degrades gracefully to paste. Auto-fill reuses the existing LLM backend; when the provider is non-local the user is warned the CV will leave the machine before it proceeds.

## Technical Context

**Language/Version**: Python 3.11+ (stdlib)
**Primary Dependencies**: Core — stdlib only (`http.server`, `urllib`, `json`, `email`/multipart parsing, existing `llm` backend). Optional venv add-on — `pypdf` (BSD) for PDF text, `python-docx` (MIT) for `.docx`. Both lazy-imported, never required by the core (mirrors the `jobspy` carve-out).
**Storage**: Existing profile store (`profile.json` under `$YOKE_HOME` via `load_profile`/save in serve.py). No schema change — Auto-fill writes nothing until the user saves the Profile form. The structured parse is in-memory only (not persisted in v1).
**Testing**: stdlib `unittest`; deterministic paths (`extract_text` on `.txt`, fallback when a lib is absent, truthfulness/field-mapping) tested with no model; auto-fill tested against a mock backend (`--mock`).
**Target Platform**: Local CLI + thin web panel (`serve.py`) on `127.0.0.1`.
**Project Type**: Single project (`src/`).
**Performance Goals**: One LLM call per auto-fill (per the spec); latency dominated by the chosen model, not by Yoke. Extraction of a 1–2 page CV is sub-second.
**Constraints**: Zero-dependency core (paste path stdlib-only); CV never sent off-machine without an explicit warning+confirm on non-local providers (FR-013); never fabricate (VI); file upload bounded by a size cap.
**Scale/Scope**: Single user; 1–2 page résumés; one Profile.

## Constitution Check

*GATE: evaluated against `.specify/memory/constitution.md` v1.0.0.*

| Principle | Verdict | Notes |
|-----------|---------|-------|
| I. CLI-First | ✅ PASS | Capability ships as a command (`src/resume_import.py`, wired as `yoke resume`): `extract_text(path)` + `autofill(cv_text)` → JSON to stdout. The Profile page calls the same module; no business logic in the web layer. |
| II. Determinize What You Can | ✅ PASS | File→text extraction is deterministic code. The model gets ONE narrow extraction task with a fixed JSON-Resume-subset schema — exactly the weak-model-friendly shape the principle wants. |
| III. Model proposes, code computes | ✅ N/A | No fit score involved; this feature touches Profile inputs, not scoring. |
| IV. Ground truth = user behavior | ✅ N/A | No labels/tuner involved. |
| V. Safety gates over fuzzy accuracy | ✅ N/A | No eval/golden-set surface. |
| VI. The Human Decides (truthfulness) | ✅ PASS | Auto-fill **proposes**; user reviews/edits/saves (FR-004). The prompt forbids inventing skills/titles/employers; absent info → empty field (FR-003/005). This is the principle's "assisted and truthful" stance applied to the profile. |
| VII. Pluggable, Zero-Dependency Core | ✅ PASS | `pypdf`/`python-docx` are optional venv add-ons, lazy-imported inside functions, never at module level; absence degrades to paste (FR-009). Permissive licenses only (FR-010) — explicitly NOT PyMuPDF (AGPL). |
| Local-first | ✅ PASS | File parsed on the user's machine; CV text reaches only the user's chosen model, and a non-local provider triggers a warning+confirm first (FR-013). |
| Bring-your-own model | ✅ PASS | Reuses `get_backend()`; no bundled inference; deterministic extraction needs no provider. |

**Result**: PASS, no violations. Complexity Tracking empty.

## Project Structure

### Documentation (this feature)

```text
specs/002-resume-import/
├── plan.md              # This file
├── research.md          # Phase 0 — library + parsing-recipe decisions
├── data-model.md        # Phase 1 — Résumé / Parsed-résumé / Profile shapes
├── quickstart.md        # Phase 1 — how to use (CLI + UI) and test
├── contracts/
│   └── cli-and-ui.md    # Phase 1 — resume_import CLI + serve.py routes
└── tasks.md             # Phase 2 (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
src/
├── resume_import.py     # NEW — extract_text(path) [lazy pypdf/python-docx/txt] ;
│                        #        autofill(cv_text, backend) -> {name,headline,scoring_prompt, _resume(JSON Resume)} ;
│                        #        CLI main (path|- , --autofill, --json)
├── serve.py             # MODIFY — Profile page: ⬆ Upload + ✨ Auto-fill button;
│                        #          POST /profile/upload (file→text into form),
│                        #          POST /profile/autofill (text→proposal into form, cloud-warning gate)
├── llm/                 # REUSE — get_backend().complete(prompt, schema, system)
└── (profile store)      # REUSE — existing load_profile / save (profile.json); no schema change

tests/
└── test_resume_import.py  # NEW — extract_text(.txt) deterministic; lib-absent fallback;
                           #        autofill field-mapping + no-fabrication (mock backend);
                           #        JSON Resume shape

yoke                     # MODIFY — add `resume` dispatcher case → resume_import.py
requirements-optional.txt # NEW (or extend) — pypdf, python-docx (venv-only, documented as opt-in)
```

**Structure Decision**: Single project, matches the existing `src/*.py` + thin `serve.py` + `yoke` dispatcher layout. One new module (`resume_import.py`) owns both extraction and auto-fill so the CLI and the web panel call the identical code path (Principle I). No new persistence — the Profile already stores `resume_text` and the scoring `prompt`.

## Complexity Tracking

> No constitution violations — section intentionally empty.

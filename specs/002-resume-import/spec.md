# Feature Specification: Résumé Import & Profile Auto-fill

**Feature Branch**: `002-resume-import`
**Created**: 2026-06-03
**Status**: Draft
**Input**: User description: "Upload or paste a resume and auto-fill the Profile (name, headline, scoring prompt) via one LLM call; user reviews and edits before saving"

## Overview

Today a new Yoke user must hand-type their Profile: name, headline, output language, comp floor, a free-form **scoring prompt** (the lane / differentiators / seniority text the model scores against), and paste their résumé text. The scoring prompt is the highest-leverage and hardest field — a blank box with no guidance. Manual entry is tedious and many users will fill it poorly or abandon onboarding.

This feature lets a user bring their existing résumé — by pasting its text or uploading a file — and have Yoke **propose** the Profile fields for them in one step. The user always reviews and edits the proposal before it is saved; nothing is auto-committed and nothing is invented beyond what the résumé actually contains.

## Clarifications

### Session 2026-06-03

- Q: Auto-fill sends résumé text to the chosen model; if the provider is cloud, the CV leaves the machine, against the local-first promise. How to handle? → A: Warn before auto-fill when the provider is non-local ("your CV will be sent to <provider>"); user confirms, but it is not blocked.
- Q: When the user triggers Auto-fill and the form's target fields already hold (unsaved) content, what happens to them? → A: Replace all target fields (name/headline/scoring-prompt) with the proposal; fields stay editable and nothing is saved until the user clicks Save.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Auto-fill my profile from my résumé text (Priority: P1)

A first-time user opens Profile, pastes the text of their CV into the résumé field, and clicks **Auto-fill from CV**. Yoke reads the text and pre-fills the name, a one-line headline, and a draft scoring prompt that captures their lane, differentiators, seniority, and stack. The user edits anything that's off and clicks Save.

**Why this priority**: This is the MVP and the core value — it removes the blank-box problem for the hardest field (the scoring prompt) and turns onboarding from "type six fields cold" into "review a draft". It works with zero new dependencies (text in, text out) and is the foundation the file-upload story builds on.

**Independent Test**: Paste any résumé text → Auto-fill → confirm name/headline/scoring-prompt fields are populated with content traceable to the pasted text → edit one field → Save → reopen Profile and confirm the saved values persist.

**Acceptance Scenarios**:

1. **Given** a user on the Profile page with résumé text pasted, **When** they trigger Auto-fill, **Then** the name, headline, and scoring-prompt fields are populated with a proposal derived only from that text, and the fields remain editable.
2. **Given** an auto-filled proposal, **When** the user edits a field and clicks Save, **Then** the edited values are persisted (the proposal is never saved without an explicit Save).
3. **Given** résumé text that omits a piece of information (e.g., no clear headline), **When** Auto-fill runs, **Then** that field is left empty or marked as "needs your input" rather than fabricated.
4. **Given** the user has not configured an AI provider, **When** they trigger Auto-fill, **Then** they get a clear message to set a provider first (the same gate as Run), not a silent failure.

---

### User Story 2 - Bring my résumé as a file (Priority: P2)

Instead of copy-pasting, the user uploads their résumé file (PDF, Word, or plain text). Yoke extracts the text into the résumé field, after which the same Auto-fill flow applies.

**Why this priority**: Most people have their CV as a PDF, not as plain text — pasting from a PDF often produces garbled text. File upload removes that friction. It is P2 because it depends on an optional text-extraction component and the paste path (US1) already delivers the core value without it.

**Independent Test**: Upload a text-based PDF (and a .docx, and a .txt) → confirm readable text appears in the résumé field → run Auto-fill as in US1.

**Acceptance Scenarios**:

1. **Given** a user selects a supported résumé file, **When** the upload completes, **Then** the extracted text appears in the résumé field for review before any auto-fill.
2. **Given** the optional extraction component for a format is not installed, **When** the user uploads that format, **Then** Yoke tells them how to enable it (or to paste the text instead) — it does not crash and the paste path still works.
3. **Given** a file with no extractable text (e.g., a scanned image PDF), **When** extraction runs, **Then** the user is told no text could be read and is offered the paste fallback.

---

### Edge Cases

- **No AI provider configured** → Auto-fill is blocked with the same guidance as Run ("set a provider in Settings").
- **Cloud provider selected** → before auto-fill, user is warned the résumé will be sent off-machine and must confirm (local-first promise stays honest); local models skip the warning.
- **Extraction component missing** for an uploaded format → clear "install to enable / or paste instead" message; paste path unaffected.
- **Scanned/encrypted PDF** with no text layer → "couldn't read text from this file" + paste fallback (OCR is out of scope).
- **Empty or junk résumé text** → Auto-fill returns empty/partial fields, never fabricated content.
- **Model returns malformed output** → the proposal is discarded with a "couldn't auto-fill, edit manually" message; existing field values are not destroyed.
- **Oversized file** (> 5 MB) → rejected with a size message before processing.
- **Existing profile already filled** → Auto-fill replaces the target fields in the form with the proposal for review; saved values are not overwritten until the user clicks Save.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to trigger an auto-fill of their Profile from résumé text they provide.
- **FR-002**: Auto-fill MUST propose, at minimum, a name, a one-line headline, and a draft scoring prompt derived from the résumé.
- **FR-003**: Every proposed value MUST be traceable to content in the résumé; the system MUST NOT invent experience, skills, employers, or titles not present in the source (truthfulness, consistent with the project's assisted-not-fabricated stance).
- **FR-004**: Proposed values MUST be presented in editable fields and MUST NOT be persisted until the user explicitly saves. Triggering Auto-fill MUST replace the target fields (name, headline, scoring prompt) with the proposal even if they already hold unsaved content; saved Profile values are untouched until Save.
- **FR-005**: When a piece of information is absent from the résumé, the corresponding field MUST be left empty rather than filled with a guess.
- **FR-006**: Users MUST be able to provide the résumé by pasting text (no upload required for the core flow).
- **FR-007**: Users MUST be able to provide the résumé by uploading a file in common formats: plain text/markdown, PDF, and Word `.docx`. Legacy binary `.doc` is out of scope.
- **FR-007a**: Uploads MUST be bounded by a size limit of 5 MB; a larger file is rejected with a clear message before processing.
- **FR-008**: Uploaded files MUST be converted to text and shown in the résumé field for review before auto-fill runs.
- **FR-009**: The paste-and-auto-fill path (FR-001, FR-006) MUST function using only the project's zero-dependency core; any component required to read non-text file formats MUST be optional and opt-in, and its absence MUST degrade gracefully to the paste path (never a crash).
- **FR-010**: Any third-party component introduced for file reading MUST carry a permissive (non-copyleft) license so the project's own license is unaffected.
- **FR-011**: Auto-fill MUST reuse the user's already-configured AI provider; when none is configured it MUST surface the same guidance as the Run action.
- **FR-012**: Failures (no provider, unreadable file, malformed model output) MUST be surfaced to the user with a clear next step and MUST NOT destroy existing Profile values.
- **FR-013**: When the configured provider is not a local model, Auto-fill MUST warn the user that their résumé text will be sent to that provider and require an explicit confirmation before proceeding; it MUST NOT block the action. Local providers (e.g., on-device models) proceed without the warning.

### Key Entities *(include if feature involves data)*

- **Résumé (raw)**: the user's CV as text — either pasted or extracted from an uploaded file. Transient input; the saved Profile already stores résumé text today.
- **Parsed résumé (structured)**: an intermediate, standard-shaped representation of the résumé (basics, experience, skills) produced by reading the raw text. Used to derive the proposed fields; not necessarily persisted in v1.
- **Profile**: the existing entity (name, headline, output language, comp floor, scoring prompt, résumé text). Auto-fill populates a subset of these for review; comp floor and language are left to the user (personal/preference, not derivable from a CV).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new user can produce a saved, non-empty scoring prompt and headline from an existing résumé in under 2 minutes, without writing the scoring prompt from scratch.
- **SC-002**: Auto-fill populates at least the 3 target fields (name, headline, scoring prompt) when the résumé contains the corresponding information.
- **SC-003**: Zero fabricated entries: in review, every proposed skill/role/employer is present in the source résumé (verified on a sample of real CVs).
- **SC-004**: The core paste→auto-fill→save flow works on a clean install with no extra packages installed (file upload for PDF/Word may require an opt-in package).
- **SC-005**: An unreadable or unsupported upload never crashes the app; the user can always fall back to pasting and complete the flow.

## Assumptions

- **Scope of auto-filled fields**: name, headline, and scoring prompt. Comp floor and output language are user choices, not inferred from the CV, and are left for the user to set.
- **Provider reuse**: auto-fill uses the existing LLM backend and provider selection; this feature adds no new provider configuration.
- **Truthfulness over completeness**: when in doubt the system leaves a field blank rather than guessing — consistent with how Yoke treats the board (assisted, never fabricated).
- **File formats v1**: plain text/markdown (handled by the core), plus PDF and Word `.docx` via an optional, permissively-licensed, opt-in text-extraction component installed alongside the existing optional scraping dependency. Legacy `.doc` and scanned-image OCR are out of scope.
- **Structured format**: the intermediate structured representation follows a common résumé schema (e.g., the JSON Resume shape) so it can be reused later (variant library, export) without redesign — but persisting/exporting it is out of scope for this feature.
- **Single user, local**: runs locally like the rest of Yoke; the uploaded file is processed on the user's machine and not sent anywhere except the user's chosen model for the auto-fill step.
- **Existing résumé field**: the Profile already has a résumé-text field and a scoring-prompt field; this feature populates them rather than introducing a parallel store.

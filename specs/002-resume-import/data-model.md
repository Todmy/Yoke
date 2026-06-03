# Data Model: Résumé Import & Profile Auto-fill

No persistent schema change. The Profile already exists; the structured parse is
transient (in-memory) for v1.

## Entities

### Résumé (raw) — transient
The CV as text. Produced by paste, by `.txt` decode, or by `extract_text()` over PDF/docx.
- `text: str` — the extracted/pasted plain text.
- Lifecycle: input only; lands in the Profile's existing `resume_text` field when the user saves the form. Not stored separately.

### Parsed résumé (structured) — transient, in-memory
A JSON-Resume-subset produced by the single auto-fill model call. Not persisted in v1.
- `basics.name: str | absent`
- `basics.label: str | absent` — the headline.
- `work: [{company, title, summary?}] | []`
- `skills: [str] | []`
- Validation: any field MAY be absent (FR-005 — absent ≠ fabricated). Shape follows the
  JSON Resume standard so a future variant-library/export feature can reuse it.

### Auto-fill proposal — transient
Derived from the parsed résumé; what the Profile form is pre-filled with.
- `name: str` (from basics.name; "" if absent)
- `headline: str` (from basics.label; "" if absent)
- `scoring_prompt: str` — drafted from work titles + skills + inferred seniority/lane,
  using ONLY extracted facts.
- Rule: empty string where the source lacks the info; never a guess.

### Profile — existing, persisted (`profile.json` under `$YOKE_HOME`)
Unchanged shape. Auto-fill writes into the *form*, not the store; save persists as today.
- `name, headline, output_language, comp_floor_net_mo_usd, prompt (scoring), resume_text`
- Auto-fill targets: `name`, `headline`, `prompt`. NOT touched: `output_language`,
  `comp_floor_net_mo_usd` (user choices, not CV-derivable), `resume_text` (set from the
  raw text/upload, not the proposal).

## State / flow

```
raw text (paste | .txt | extract_text(pdf|docx))
      │
      ▼  (FR-013 cloud-warning gate if provider non-local)
autofill(raw_text, backend)  ──1 LLM call──▶ Parsed résumé (JSON Resume subset)
      │
      ▼  derive
Auto-fill proposal {name, headline, scoring_prompt}
      │
      ▼  pre-fill into the editable Profile form (replaces target fields, FR-004)
user reviews / edits ──▶ Save ──▶ Profile (profile.json)
```

## Error states (map to FR-012)

- `no provider` → blocked, "set a provider in Settings".
- `ExtractionUnavailable` (lib absent) → "install pypdf/python-docx or paste text".
- `no text` (scanned/empty) → "couldn't read text; paste instead".
- `malformed model output` → discard proposal, "couldn't auto-fill; edit manually"; existing form values preserved.
- `oversize file` → rejected pre-processing.

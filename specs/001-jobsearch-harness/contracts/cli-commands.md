# CLI Command Contract — Yoke v1

The CLI is the public interface (FR-018); the web client calls the same modules. Every command: text in (args/stdin) → text out (stdout), errors → stderr, JSON where a machine/agent consumes it. Exit 0 = success, non-zero = failure (documented per command). Commands compose via pipes (`prepare | analyze`).

## Pipeline

### `collect` (`src/collect.py`)
Pull + normalize + dedup roles from pluggable scraper adapters into the index.
- **In**: source config; `--dry-run` (print, no save).
- **Sources (v1)**: existing ATS/RSS/HN adapters **+ new**: Hiring Cafe (urllib JSON), Djinni/DOU (urllib+html.parser, polite), LinkedIn (jobspy venv-optional, read-only), manual paste/CSV import.
- **Out**: index updated (`first_seen`/`last_seen`); dedup on `role_key` + normalized `company|title`.
- **Δ5**: prune live board entries whose posting URL returns 404/410 on re-collect; transient errors do not prune.

### `prepare` (`src/prepare.py`)
Deterministic feature cards. **In**: roles (stdin/index). **Out**: cards JSON (geo/lane/comp + `needs_ai`, `hard_gate_fail`). **No model call.**

### `analyze` (`src/analyze.py`)
Thin LLM fill → `score_fit` → tier → board.
- **Flags**: `--mock` (no model, deterministic stub), `--limit N`, `--no-board`, `--cards FILE`.
- **In**: cards (stdin/`--cards`). **Out**: tier counts to stderr; Tier A/B roles to `board.py add` (or JSON with `--no-board`).
- **Contract**: model fills the fixed feature schema for one role per call; the fit number comes only from the formula. `--mock` MUST run with no provider configured (SC-002).
- **Δ3**: tier cutlines imported from `scoring.py`.

## Board & tracker

### `board` (`src/board.py`)
- `board add` — ingest scored roles (stdin JSON) onto the live board.
- `board apply <role_key>` — **assisted flow** (review → record CV/notes → confirm); records an `applied` decision; **Δ4**: writes an immutable `resume` snapshot (base + accepted tailoring edits).
- `board drop <role_key> --reason <r>` — immediate reject + reason.
- `board render` — human-readable board (Tier, fit band + number, one-line reason).
- `board status` / `store status` — DB path, live/applied counts, label counts.
- **Guarantee**: an applied/rejected role never reappears (FR-009).

### `track` (via `store` / `serve`)
Application pipeline (`applied→screening→interview→offer→accepted/rejected/ghosted`) + funnel rates (`application_stats`). `interested` is a board bookmark (not a training label — Δ1).

## Gap, tailoring, cover

### `gap <role_key>` (gap analysis)
- **Out**: matched + ranked-missing skills (taxonomy+alias, no required model call), honest match band + number, accept/reject learning/tuning suggestions.
- Per-vacancy tailored CV copy produced at apply (v1). Semantic augmentation + variant library = v2.
- **Guard**: never fabricates a skill/metric/seniority absent from the CV (FR-013/014).

### `cover <role_key>` (`src/cover.py`, NEW — FR-026)
- **In**: role + base/tailored CV; model required.
- **Out**: cover-letter draft in `profile.output_language`, grounded only in CV+JD, to stdout/file.
- **Contract**: accept/reject/edit by the human, never auto-sent, never fabricated. Exit 2 if no provider configured.

## Harness

### `eval` (`src/eval.py`)
Grade the candidate model against the frozen golden set's curated labels. **Out**: saved scorecard (safety-gate results + agreement + pass/fail). Any single safety violation → fail. Zero reference-model calls at run time (FR-015/016).

### `tune` (`src/tune.py`)
Refit `score_fit` weights to `applied` vs `rejected` labels (Δ1), zero model calls.
- `tune` (report current vs proposed + objective before/after), `tune --json`, `tune --apply`.
- **Δ2**: declines (exit 2) with an explanation below ≥5 applied / ≥5 rejected / ≥20 total.
- **Δ3**: objective threshold imported from `scoring.py` (same cutline the board uses).

## Web client

### `serve` (`src/serve.py`) — thin client, 127.0.0.1
Pages: `/` board+triage, `/settings` provider/key+sources, `/profile` CV+prompt. Buttons: Run now, Schedule/Unschedule (cron), Improve (calls `tune`). **No business logic of its own** (FR-018).

## Cross-cutting contracts
- **No provider configured** → deterministic stages still run; model-scored stages explain a provider is required (FR-006).
- **Local-first** → all reads/writes under `$YOKE_HOME`; no personal data in args/URLs or the repo (FR-020).
- **No auto-apply / no auto-send / no auto-rewrite** (FR-021): every irreversible step is human-confirmed.

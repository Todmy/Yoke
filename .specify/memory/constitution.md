# Yoke Constitution

## Core Principles

### I. CLI-First
Every capability is a `yoke`/`python3 src/*.py` command a person can run and an agent can drive: text in (args/stdin) → text out (stdout), errors → stderr, JSON where a machine consumes it. The web panel is a thin client over the same modules and holds no business logic of its own. A feature is a command before it is a screen.

### II. Determinize What You Can
Any decision reducible to a rule, regex, or formula is code, not a prompt. The model gets only a narrow extraction task with a fixed schema — the kind a weak or local model does reliably. Roughly a quarter of roles are decided by rules with zero model calls.

### III. The Model Proposes Features; Code Computes the Score (NON-NEGOTIABLE)
The fit score is a transparent weighted formula over model-supplied features. The model never emits the number. Tier cutlines are fixed, defined in a single shared source, and the tuner moves weights only — never cutlines. Auditability beats cleverness.

### IV. Ground Truth Is the User's Behavior
Self-improvement optimizes against the user's real applied-vs-rejected decisions, not another model's opinion. `interested` is a bookmark, not a training label. The tuner makes zero model calls and declines, with an explanation, below its decision-count gate rather than producing misleading weights.

### V. Safety Gates Over Fuzzy Accuracy
The eval grades a candidate against a frozen, human-reviewed golden set; a single safety violation (geo false-positive, tier overreach, parse failure) forces a fail regardless of fit closeness. Safety-gate detection is deterministic against the labels, not a model judgment.

### VI. The Human Decides
Yoke scores and triages; it never applies on the user's behalf and never auto-rewrites a CV. Suggestions are accept/reject and truthfulness-guarded: never fabricate a skill, tool, certification, metric, or seniority the CV does not contain. Per-vacancy CV tailoring is assisted and truthful — surfacing genuine relevance, not gaming screening.

### VII. Pluggable Everywhere, Zero-Dependency Core
Sources and LLM backends are drop-in; the pipeline doesn't change when you add either. The core is stdlib-only (sqlite3, http.server, urllib, fcntl) — no third-party runtime dependency. Heavier needs (e.g. `jobspy` for JS-heavy scraping) are confined to an optional venv, never required by the core.

## Additional Constraints

- **Local-first.** All user data (CV, decisions, tokens, board) stays on the user's machine under `$YOKE_HOME`; no personal data in the public repo, in args, or in URLs.
- **Storage.** SQLite in WAL mode is the single source of truth; concurrent cron + UI access must not corrupt state.
- **Bring-your-own model.** A Claude subscription (`claude -p`), an OpenAI-compatible API key, or a fully local model — the user chooses; the tool ships no bundled paid inference. The deterministic path runs with no provider configured.

## Development Workflow

- Spec → plan → tasks → analyze → implement (Spec Kit). Clarify before plan.
- Tests are stdlib `unittest`; correctness-critical pure functions (score_fit, tier_of, tuner, dedup) are unit-tested. The deterministic pipeline is exercised with `--mock` (no model).
- Surgical changes on a retrofit codebase: every changed line traces to the requirement; don't refactor working code adjacent to a delta.

## Governance

This constitution codifies the principles in `docs/architecture.md` and supersedes ad-hoc practice where they conflict. Amendments require an explicit edit here with a version bump and rationale; principle changes are out of scope for `/speckit-analyze` (which treats these as non-negotiable). Complexity that violates a principle must be justified in the plan's Complexity Tracking or removed.

**Version**: 1.0.0 | **Ratified**: 2026-06-02 | **Last Amended**: 2026-06-02

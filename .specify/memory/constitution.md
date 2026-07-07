# Constitution: Yoke
Version: 1.0.0 | Ratified: 2026-07-07

## Principles

1. **Local-first** — MUST: the user's CV, labels, and decisions never leave their machine; the tool works with local models too. Trust is the product's stance.
2. **Deterministic core, thin AI surface** — MUST: the model only fills a fixed feature schema in `analyze`; a readable formula computes the score; anything decidable by rules never calls a model. The score must be auditable and stable.
3. **Flat files** — MUST: state lives in flat, inspectable files (`_index.json`, `SHORTLIST`); no SQLite/DB. The old Yoke died of heaviness; the README's SQLite mention is stale.
4. **Concrete with seams** — MUST: code is written for today's case (IT+PL, one profile.yml); extension happens only through seams (tags, registry, plugins), never speculative abstraction; a new core module only if it belongs to a ROADMAP milestone. Fourteen modules was exactly that mistake.
5. **Sources are plugins** — MUST: each source is a self-contained plugin ("tool search over a site") in an appendable registry, easy for outsiders to add; heavy dependencies live at the plugin edge, the core stays stdlib-lean. The source list grows forever — the core must not.
6. **Core test-first, fetchers on fixtures** — MUST: deterministic logic is written test-first; fetchers get contract tests on recorded fixtures; no live network call in tests. The core is provable; the web is not.
7. **No paid call without consent** — MUST: paid sources/LLM run only after explicit per-run selection in a menu showing the price; `analyze` scores only the new-in-window slice, never the whole index. The user's money; DoD check #3 punishes violations.
8. **Moat barrier & small commits** — MUST: `.private/`, the profile, and labels are never committed; commits are small and discrete (one logical change each); push only with explicit permission. A public OSS repo sits next to private strategy.
9. **Competitor ban-list** — MUST NOT: WebSearch-only collection, keyword tier-classifier, LaTeX CV pipeline, headless-loop LinkedIn apply, SQLite/TUI heaviness. Consensus failure modes from the 6-repo analysis.

## Amendment log
- 1.0.0 (2026-07-07) — initial ratification (grilled setup, feature: yoke-v0)

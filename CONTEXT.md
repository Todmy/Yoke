# Yoke — Domain Glossary

Canonical terms. Design docs, code, and reviews use these exact words.

- **source plugin** — a self-contained fetcher auto-discovered by `load_sources()` from `src/sources/`: a module exposing `NAME, TAGS{domain,country}, COST, available(), fetch(profile)` (no registration call); emits `norm()` dicts; carries `{domain, country}` tags so sources can be activated per the profile's countries. Adding one never touches the core.
- **norm record** — the single 8-key contract every source plugin emits: `title, company, location, url, source, posted_at, comp, jd`.
- **job_key / role_key** — exact-dedup key (url, else `company|title`) / repost-collapsing key (`company|normalized-title`).
- **match score** — collect's cheap deterministic keyword/geo gate score (`matches_profile`); a noise filter, NOT the fit score.
- **fit score** — analyze's 0–100 additive weighted sum `Σ wᵢ·featureᵢ` over scoring features; the AI-assisted "fits ME" judgment. Readable formula, weights are data.
- **scoring feature** — one input to the fit formula. Two kinds: *profile-declared* (name + description-for-model + weight, judged by the model per role) and *deterministic* (computed by code, e.g. comp-vs-floor). The set is personal, not hardcoded.
- **feature card** — prepare's deterministic per-role bundle handed to analyze: norm record + gate results + normalized comp + the new-in-window flag.
- **new-in-window** — `first_seen > max(last_run, now − 14d)`; stamped by collect (`first_seen`/`last_seen`), filtered by prepare. Analyze only ever scores this slice.
- **hard gate** — a deterministic pass/fail rule (geo/remote, lane, comp floor, tech-spine, legal, language, stage). Any fail → Tier C without spending a model call.
- **tier** — A = fit ≥ 70 ∧ geo ✅ ∧ comp floor cleared; B = 55–69 or ≥ 70 with named friction; C = < 55 or gate fail. Cutlines live in one shared constant.
- **board** — flat `_board.json` (roles + `applied[]` ledger) plus its read-only render `SHORTLIST.md`; self-prunes by job_key/role_key on apply.
- **cost consent** — the interactive per-run menu on `yoke run`: sources listed with price class (free / key / paid) and a priced confirmation before the analyze stage; no paid call ever fires without it.
- **red flag** — a score-reducing signal on a role, from two sources: *model-classified* (the model sorts JD-text concerns into a fixed enum) and *code-detected* (ghost/liveness signals from card metadata). Both feed the red-flag penalty; never a keyword→tier classifier.
- **red-flag penalty** — the clamped multiplier applied *after* the additive `fit_base`: `fit_final = round(fit_base × (1 − min(Σpenalty, cap)))`. Penalty numbers are profile data (`scoring.red_flags`), the `cap` (modifier-floor) bounds the hit so red flags can never zero a strong role. `fit_base` stays additive (ADR-0001, ADR-0003).
- **ghost / liveness signal** — a deterministic, code-detected red flag computed from card metadata alone (posting age, repost frequency, apply-domain trust, confidential company); never a network probe, never a hard gate — it lowers the score, it does not drop the role.
- **comp estimate** — a model-estimated comp band (from company + target-market context, a flagged feature in analyze's fixed schema), used only when both source and JD comp are absent; *soft* — fills the `comp_vs_floor` score + `comp_display` and adds an "estimated comp" friction, never fires the hard comp-floor gate, never assumes zero (ADR-0001, spec FR-002/FR-004).
- **near-duplicate** — two postings for the same role at the *same company* with fuzzy-similar titles, collapsed by deterministic stdlib text similarity; augments `role_key`, never merges across companies (ADR-0004).

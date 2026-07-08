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

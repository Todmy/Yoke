# ADR-0002: National employment-service coverage via the EURES aggregator, not per-country scrapers

Date: 2026-07-08 · Status: accepted (feature: m1-thicken-collection)

## Context

The user wants job coverage across European national public employment services (Germany's Bundesagentur für Arbeit, France's France Travail, Poland's służba zatrudnienia, …) because they are relocation-open across the EU. The naive reading — "a source plugin per country" — implies ~27 fragile, individually-maintained scrapers and directly threatens the "core must not grow" and "concrete with seams" principles.

Live research settled the API reality:
- **EURES** (`europa.eu/eures/api`) exposes a keyless public JSON API (reverse-engineered, `security: []`, live-verified HTTP 200 with no key) that **aggregates national employment-service vacancies across all EU/EEA/EFTA** (~2.94M postings) and is relocation/cross-border oriented by construction. One source ≈ multi-country. Caveat: undocumented (grey ToS, no SLA) and per-country completeness is uneven — national services feed EURES a subset.
- **Germany BA Jobsuche** (`rest.arbeitsagentur.de/jobboerse/jobsuche-service`) is keyless via a static public `X-API-Key`, JSON, and materially deeper for Germany than EURES's German slice. ToS grey/hostile (BA fought the reverse-engineering).
- **France Travail** requires OAuth2 client credentials → keyed. **Poland CBOP** requires a ministry-registered SOAP partner + returns zipped XML → keyed and high-friction. **Netherlands/Spain** expose no keyless vacancy API.

## Decision

- **Cover national PES breadth with EURES as the single all-EU aggregator source**, plus **Germany BA as one dedicated keyless booster** where its own database beats EURES's German feed. Do NOT build a scraper per country.
- Both land as ordinary **source plugins** (constitution #5) — auto-discovered, `COST="free"`, network isolated at the plugin edge, routed through the M1 anti-bot mixin.
- **Keyed national services (France Travail OAuth, Poland CBOP SOAP+registration) and non-keyless countries are deferred**, added later one-by-one as their own plugins when their incremental coverage over EURES justifies the auth/transport cost. Recorded as a standing backlog item.
- Country targeting is driven by a new `profile.countries` list (see the feature's grill decisions), which parameterizes the EURES/BA queries and feeds the geo gate.

## Consequences

- The source registry stays small: national-PES breadth costs ~2 plugins now, not ~27. Adding a country later is an isolated, appendable plugin — the seam does its job.
- **Yoke depends on two undocumented, reverse-engineered endpoints** (EURES, BA) with no stability guarantee and, for BA, an operator hostile to the interface. Both must be mixin-paced, degrade gracefully on block (return `[]`, never crash the scan), and be commented as unofficial. Acceptable for a personal-use tool; a productized/OSS distribution must revisit this (a shipped tool hitting BA's undocumented API at scale is a different risk profile).
- Coverage is broad but **not per-country complete** — EURES receives only a subset from some national services. Deep coverage for a specific country is what a dedicated national plugin (like BA) buys; that is the trigger for promoting a country off the backlog.
- Keyed sources (France/Poland) will need the `COST="key"` consent path (constitution #7) when added — they must never auto-run under `--yes`.

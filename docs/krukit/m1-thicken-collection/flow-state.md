# Krukit Flow: m1-thicken-collection
Started: 2026-07-08 | Route: full
Task: M1 "thicken collection" — 5 collect units in one flow (anti-bot HTTP mixin, justjoin full-JD fetch, +4 EU-HQ ATS, LinkedIn jobs-guest fetcher, VC-portfolio auto-discovery). Goal: more roles, fewer bans; same output format. No issue ref.
- [x] 1 recon — done 2026-07-08, artifact: context.md
- [x] 2 grill — done 2026-07-08, artifact: flow-state.md
- [x] 3 design — done 2026-07-08, artifact: design.md
- [x] 4 plan — done 2026-07-08, artifact: plan.md
- [x] 5 act — done 2026-07-08, artifact: plan.md (7 commits 1586b04..f8fb91e; full suite 142 OK)
- [x] 6 verify — done 2026-07-08, artifact: verify.md (143 tests OK; live dry-run all free sources; 1 HIGH a16z-marker fixed in 12a019d; 0 CRITICAL)
- [x] 7 review — done 2026-07-08, artifact: flow-state.md (fresh-eyes review; 2 IMPORTANT fixed under TDD; merged to main; 147 tests OK)

## Review summary (2026-07-08)

Independent fresh-eyes review (subagent, no session context) of the full
16-commit feature diff vs design/plan/constitution. Verdict: solid, disciplined
implementation — plugin boundaries, fetch/parse splits, norm()-only records, and
the defusedxml XXE mitigation all correct; tests genuinely fixture-driven.

**Findings: 0 CRITICAL, 2 IMPORTANT (both FIXED under TDD), 1 MINOR (deferred).**
- **R1 (IMPORTANT, fixed `ca8ce30`)** — `http.py` pacing self-disabled after any
  failed request: `state["last"]` was set only on success, so a non-429/403
  failure left it stale and the next same-host call skipped throttling (worst in
  the vc probe fan-out, mostly 404s). Moved the assignment into `finally` so a
  failed attempt still counts. Regression test added (red→green).
- **R2 (IMPORTANT, fixed `00c7844`)** — `eures`/`germany_ba` `fetch()` let
  Blocked/decode errors escape, breaking design's "never raises past its own
  fetch" contract (run_collect was the only backstop). Wrapped fetch+decode
  (not `_parse`) in graceful `[]`, matching the ats/vc precedent. Tests added.
- **R3 (MINOR, deferred)** — `tests/fixtures/vc_yc.json` is an orphan (same class
  as V5's `vc_a16z.json`); candidate for a `_load_yc` extraction test or removal.

Carried MEDIUM/LOW from verify: **V2** (vc slug-probe real-yield is structurally
low), **V3/V4** (stale design prose), **V5/R3** (orphan fixtures), **V6**
(test_http ResourceWarning cleanup). None blocking; backlog for follow-ups.

**Branch outcome:** merged into `main` (fast-forward, 16 commits), full suite
re-run on merged result (147 OK), feature branch deleted. Knowledge captured to
Valis (a16z-marker lesson + review-value lesson, both proposed).

## Route gate evidence (2026-07-08)
Task selection + structure decided across two AskUserQuestion rounds:
> "Так, давай зробимо всі." — 2026-07-08 (do all M1 units)
> "Один флоу, 5 одиниць" — 2026-07-08 (one flow, 5 units)

Scope = the 5 collect units of roadmap milestone M1. Build order (infra-first):
anti-bot HTTP mixin → source units (justjoin-JD, EU-ATS, LinkedIn-guest) →
VC-portfolio auto-discovery. M1 is still v0.x (parity with the jobsearch
prototype lands at M2, not here).

## Grill summary (2026-07-08)

**Reshaped scope — 7 work items** (supersedes the header's original 5-unit framing):
mixin · justjoin-JD · +4 EU-ATS · VC-discovery · EURES · Germany BA · country model.
**Dropped:** LinkedIn-guest (fragile, ban-hostile, low marginal value once EURES+BA+ATS
provide breadth). Build order infra-first: mixin → sources → VC-discovery.

**Resolved decisions:**
1. **Anti-bot mixin** — pace + jitter + burst-cooldown, NO retry; 429/403 → per-host
   cooldown for the run; fail → isolate (return []). (Q4)
2. **justjoin full-JD** — sidecar JD cache keyed by url; fetch once ever, incremental,
   mixin-paced; respects don't-clobber-jd-on-re-sighting. (Q6)
3. **Cost class** — all in-scope sources `COST="free"`; existing consent gating untouched. (Q8)
4. **Country routing** — ADD now via new `profile.countries` list (relocation-aware):
   parameterizes EURES/BA queries + feeds the geo gate; existing sources still all-run +
   geo-gate-filter; `TAGS.country` is the activation seam. (Q1, reshaped)
5. **National PES** — EURES (all-EU keyless aggregator) + Germany BA (keyless static-key
   booster) as source plugins now; per-country PES = follow-up plugins added
   country-by-country later. (new — ADR-0002)
6. **EU-ATS** — extend `ats.py` `_URLS`/`_PARSERS` with Personio(XML)/SmartRecruiters/
   Workable/Recruitee; slugs from `profile.sources.companies` + VC-discovery. (Q2)
7. **VC-discovery** — source plugin: YC/a16z portfolio → probe candidate ATS by slug →
   reuse `ats` parsers → emit roles; sidecar `{slug,ats}` cache (not profile mutation). (Q3)

**Sharpened terms (CONTEXT.md inline):** `norm record` 7-key → 8-key (added `jd`);
`source plugin` `register_source(...)` → auto-scan via `load_sources()`. Both were drift.

**ADR created:** ADR-0002 — national PES via EURES aggregator + BA booster, per-country as
pluggable follow-ups.

**Deferred (with reason):**
- LinkedIn-guest — dropped (fragility + EURES/BA/ATS cover the breadth). Q5 dies with it.
- France Travail (OAuth key), Poland CBOP (SOAP+ministry registration), NL/ES (no keyless
  API), Norway NAV (keyless unverified) — **backlog**: added as individual plugins later.

**Accepted risks:** EURES + BA are undocumented/reverse-engineered (grey ToS; BA operator
hostile) — mitigated by mixin-pacing + graceful-on-block + no-SLA assumption; acceptable
for personal use, revisit for OSS/productized distribution.

**Gate evidence (user, verbatim):**
> "Так, давай зробимо всі." / "Один флоу, 5 одиниць" — 2026-07-08 (scope+structure)
> "Greenlight — proceed to design" — 2026-07-08 (grill gate)
Plus the three grill Q&A rounds' selections recorded above.

# Krukit Flow: m1-thicken-collection
Started: 2026-07-08 | Route: full
Task: M1 "thicken collection" — 5 collect units in one flow (anti-bot HTTP mixin, justjoin full-JD fetch, +4 EU-HQ ATS, LinkedIn jobs-guest fetcher, VC-portfolio auto-discovery). Goal: more roles, fewer bans; same output format. No issue ref.
- [x] 1 recon — done 2026-07-08, artifact: context.md
- [x] 2 grill — done 2026-07-08, artifact: flow-state.md
- [x] 3 design — done 2026-07-08, artifact: design.md
- [ ] 4 plan
- [ ] 5 act
- [ ] 6 verify
- [ ] 7 review

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

# Verify — m1-thicken-collection

Stage 6 of 7. Evidence-based verification + read-only reality-check of the
7-unit collection thickening. Date: 2026-07-08.

## Metrics

- **DoD requirements:** 7 total / 7 addressed — 5 full PASS (#1,2,3,4,7), 2 PASS-with-noted-caveat (#5 live-proven on 3/4 new ATS providers; #6 mechanism proven + a16z marker fixed, real-yield tuning deferred).
- **Tests:** 143 pass / 0 fail (`python -m unittest discover -s tests`, exit 0). +1 vs act (new a16z coverage test).
- **Findings:** 6 total — 1 HIGH (**fixed this stage**), 1 MEDIUM (accepted design limitation), 4 LOW (for review). **CRITICAL: 0.**

## Test-run evidence (fresh, not from memory)

```
$ .venv/bin/python -m unittest discover -s tests
Ran 143 tests in 0.110s — OK   (exit 0)
```
Two `ResourceWarning: HTTPError 403/429` lines print (pre-existing mocked-double
noise from `test_http.py`, documented plan.md:127) — harmless, suite exits OK.

## Live-run evidence (constitution #10 — real network, free sources, isolated `$YOKE_HOME`)

Isolated temp home, `profile.countries=[pl,de]`, VC `cap=5`. All runs `yoke run --dry-run`, exit 0, no traceback, no ban.

| Source | Live result | Notes |
|---|---|---|
| eures | **14 roles** | live POST OK; `jd` from summary (~2.7k chars, tag-free); `comp=None` |
| germany_ba | **44 roles** | live GET OK; DE country-gate active; `jd=""`, `comp=None` (detail GET deferred — as designed) |
| justjoin | **106 roles, 101 with `jd`** | ld+json JobPosting selector **live-verified**; `jd` capped at 8000, 0 residual HTML tags; **2nd run 42s vs several min ⇒ `jd_cache.json` short-circuit confirmed** (DoD #4) |
| ats (seeded) | personio `getquin` **8**, recruitee `bunq` **14**, smartrecruiters `Visa` **2**, workable `Zego` 404 | 3/4 new providers return live roles end-to-end via the mixin; personio XML→defusedxml path live-OK; workable 404 → graceful per-company SKIP (documented flaky widget); comp/jd match plan.md:119 learnings exactly |
| ats (empty companies) | **0 roles**, clean | no crash on empty `profile.sources.companies` |
| vc | probe cache filled (5 entries); a16z **0→849** after fix | see V1 |

## Findings

| ID | Severity | Location | Summary | Recommendation |
|---|---|---|---|---|
| V1 | **HIGH — FIXED** | `src/sources/vc.py:36` | a16z marker was a documented GUESS `data-portfolio-companies="` — **absent from the live page**; real attribute is `data-companies="`. `_load_a16z` silently returned `[]`, so the a16z half of VC-discovery was dead. The marker→extraction path had **zero test coverage** (every vc test mocked `_load_a16z → []`). | **Fixed in `12a019d`**: corrected the constant + added a fixture-driven `_load_a16z` test (`tests/fixtures/vc_a16z_page.html`, red→green). Live-confirmed **849 companies** post-fix. |
| V2 | MEDIUM | `src/sources/vc.py:135` (`_probe`) | VC real-yield is structurally low: the probe slug is the company's domain label, which rarely equals its ATS board token, so most probes → `"none"` (0 roles in the capped live sample even post-fix). The *mechanism* is proven (offline `test_emits_roles_via_ats_parser` + the live ATS spot-check share the same `ats._PARSERS` path). | Accepted slug-probe limitation of the approved design. Follow-up (backlog): website→ATS-token resolution or a curated seed list. **Not a code defect.** |
| V3 | LOW | `design.md:76` | Stale prose: claims SmartRecruiters/Workable expose salary → structured comp. Live inverts it (both `comp=None`; Recruitee is the only new provider with salary). | Already reconciled in `plan.md:119` learnings. Correct the design prose in review, or keep as a historical record. |
| V4 | LOW | `design.md:122` | References a `_country_markers(profile)` helper that doesn't exist — the mapping is inlined in `matches_profile`. | Cosmetic naming drift; align in review. |
| V5 | LOW | `tests/fixtures/vc_a16z.json` | Orphan fixture (13k), referenced nowhere at runtime (used only to hand-generate `vc_a16z_page.html`). | Remove or wire into a test in review. |
| V6 | LOW | `tests/test_http.py` | Pre-existing `ResourceWarning` from mocked `HTTPError(fp=None)` doubles. | One-line cleanup (`BytesIO` fp / `addCleanup(err.close)`) in review. |

## Reality-check pass (read-only, fresh-eyes subagent)

Design/plan vs. actual code — **clean, zero CRITICAL/HIGH drift**:
- **Files:** every path in `plan.md` exists (all sources, tests, fixtures incl. bonus `ats_personio_billionlaughs.xml`, `justjoin_offer.html`).
- **Symbols:** all resolve (`http.fetch_bytes`/`Blocked`, `collect.{strip_html,JD_MAX_CHARS=8000,load_sources,run_collect,matches_profile,update_index,COUNTRY_MARKERS}`, `paths.{home,ensure_home}`, `ats.{_URLS,_PARSERS,_XML_ATS,_get_json,_get_xml,_parse_*}`, each new source's `NAME/TAGS/COST/available/fetch/_parse`).
- **Requirements:** 4 new ATS providers in `_URLS`+`_PARSERS`(+personio in `_XML_ATS`); `_get_*` route through the mixin; new sources `COST="free"`; germany_ba country-gate in `fetch()` not `available()`; vc reuses `ats._PARSERS`; `matches_profile` non-EU reject = `has_non_eu and not has_eu and not has_target`.
- **Constitution MUST:** no module-level third-party import in `src/**` (`defusedxml`/`yaml` lazy); no DB; all new sources free. Only deltas: V3/V4 stale design prose (already reconciled by plan learnings) and vc's intentional parser reuse.
- **Hygiene:** no TODO/FIXME/placeholder/NotImplementedError in new code.
- **Terminology:** `collect.norm` produces exactly the 8 keys; no source hand-builds records bypassing `norm`.

## Gate

- [x] Full test suite ran; output read, all 143 passing.
- [x] No confirmed `discovery.md` for this feature (glob empty) — no Validation plan to execute; DoD verified against `design.md` §Definition of Done instead.
- [x] `verify.md` exists with findings table + metrics line.
- [x] Zero CRITICAL findings.
- [x] The one HIGH (V1) **fixed** this stage (`12a019d`), not merely accepted.

**Gate: PASS.** MEDIUM/LOW (V2–V6) carried into stage 7 (review).

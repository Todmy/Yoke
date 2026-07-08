# Recon — m1-thicken-collection

## Goal
Thicken the `collect` subsystem with 5 units — anti-bot HTTP mixin, justjoin full-JD per-offer fetch, +4 EU-HQ ATS (Personio/SmartRecruiters/Workable/Recruitee), no-auth LinkedIn jobs-guest fetcher, VC-portfolio auto-discovery (YC/a16z) — widening the net and reducing bans **without changing the output format** (`norm` record → `_index.json` → SHORTLIST). Still v0.x; parity with the jobsearch prototype is M2, not here.

## Affected map
| File | Role | Who depends / feeds |
|---|---|---|
| `src/collect.py` | Plugin spine: `REQUIRED_ATTRS` (:19), `norm` factory (:76), auto-scan registry `load_sources` (:150-170), `run_collect` per-source isolation (:234-261), `matches_profile` gate (:107-147), `update_index` stamp/prune/jd-preserve (:177-215) | every source; `src/yoke.py`; every `tests/test_source_*` |
| `src/sources/ats.py` | Multi-provider ATS: `_URLS`+`_PARSERS` dispatch by `company["ats"]` (:21-25, :96-100), iterates `profile.sources.companies` `[{slug,ats}]` (:105), per-company try/except (:110-114) | **+4 EU-ATS extend here**; **VC-discovery feeds `companies` into here** |
| `src/sources/justjoin.py` | PL list-API source; empty-JD stub at `:87` (`norm(...)` no `jd=`), offer URL built `:85`, `slug` present | **justjoin-JD unit fills `jd`** |
| `src/sources/*.py` (remoteok, remotive, workingnomads, wwr, hn, brave, jobspy_src) | 8 self-contained plugins, each rolls own `urllib.request`; only rate-limit is `brave.py` `sleep(1.1)` (:26,:85) | **anti-bot mixin consolidates their HTTP** |
| `src/yoke.py` | Run driver: `select_sources` menu (:42-69), `_default_selection` cost gating (:72-87), 2nd consent before analyze (:155) | LinkedIn-guest/YC/a16z declare `COST` here-gated |
| `src/paths.py` | `load_profile` (:47-81, lazy `yaml`) → dict passed to every `fetch(profile)` | new sources read `profile["lane"]["keywords"]` / `["sources"]["companies"]` |
| `profile.example.yml` | Source-of-truth template ("data here, logic in code") | any new profile field added here |
| `tests/test_invariants.py` | Contract test (:64-80) + no-module-level-3rd-party-import AST scan (:53-61) | every new source + mixin must pass |
| `tests/fixtures/` | Recorded JSON/XML payloads, one per source/provider | new sources add `<name>.json`, EU-ATS add `ats_personio.json` etc. |

## Patterns to follow
- **New source = one file in `src/sources/`** exposing `NAME:str`, `TAGS={"domain","country"}`, `COST∈{free,key,paid}`, `available()→(bool,reason)`, `fetch(profile)→list[dict]`. Auto-registers (no list to edit). Skeleton distilled at `remoteok.py`/`remotive.py`.
- **Fetch/parse split is mandatory** (`ats.py:4-5`): `fetch()` does all I/O; a **pure** `_parse(payload, profile)` builds records → lets fixture tests skip the network. Malformed payload → return `[]`, never raise.
- **Records only via `collect.norm(...)`** (8 keys). `comp` = structured dict `{min,max,currency,unit,type}` (ref `justjoin.py:55-74`), never a preformatted `"$X/mo"` string. `jd = strip_html(raw)[:JD_MAX_CHARS]` (8000).
- **+4 EU-ATS → extend `ats.py`** `_URLS`/`_PARSERS` with new provider keys + `_parse_personio/_smartrecruiters/_workable/_recruitee`, mirroring greenhouse/lever/ashby (constitution #4 "extension through seams"). Note: Personio returns **XML** (`{slug}.jobs.personio.de/xml`), the others JSON — parse accordingly. Prefer structured comp over lever's string form.
- **Heavy HTTP lib (if any) = lazy import inside `available()`/`fetch()`** — model is `jobspy_src.py:24,:74`; `available()` returns `(False, reason)` when the dep/threshold is missing rather than raising at import. Core stays stdlib `urllib`.
- **Anti-bot mixin lives in core as stdlib helper** (jitter/backoff/cooldown/UA) that plugins call from inside `fetch()`; consolidates the 8 ad-hoc `urllib.request` sites. Adopt the mechanism, **measure own thresholds** (discovery: "don't cargo-cult boss-cli constants").
- **Tests: stdlib `unittest`** (`python -m unittest discover -s tests`, no pytest). Every source: `test_module_contract` + `test_parse_fixture` (full 8-key dict equality on `jobs[0]` + malformed→`[]`) + regression tests for known bug classes. ATS failure isolation via `mock.patch.object(<mod>, "_get_json", side_effect=...)` (`test_source_ats.py:106-131`), no "failing" fixture file. Boilerplate header sets `YOKE_HOME` to a tempdir **before** importing `src`.
- **Config wiring**: keyword-search sources read `profile["lane"]["keywords"]` with a `DEFAULT_QUERIES` fallback (`remotive.py:27-29`); company/slug sources read `profile["sources"]["companies"]` (`ats.py:105`). geo/tech/anti filtering happens in the `matches_profile` gate *after* fetch — sources don't self-filter.
- **Endpoint shapes** (from `.private/krukit/yoke-collect/discovery.md` open-qs): Personio `{slug}.jobs.personio.de/xml`, Workable `apply.workable.com/api/v1/widget/accounts/{slug}`, Recruitee `{slug}.recruitee.com/api/offers/`, SmartRecruiters (posting API); YC `api.ycombinator.com/v0.1/companies` + a16z portfolio; LinkedIn guest `linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search`.

## Invariants (must not break)
- **`norm` 8-key schema** (`test_norm_shape`, `test_collect.py:38`); comp structured not string (`test_source_justjoin.py:56-78`); jd stripped + capped 8000 (`test_strip_html_and_jd_cap`).
- **jd/comp preserved on bare re-sighting** — `update_index` must merge not clobber (`test_update_index_carries_jd`, `collect.py:201-203`). The justjoin-JD unit must respect this.
- **Dedup**: `job_key`=url-lower else `company|title`; `role_key` collapses reposts (`test_collect.py:91,:97`). Same role on 2 boards → one entry.
- **Geo hard-block + word-boundary** (" uk" ≠ "ukraine", fix 77ac7de; `test_matches_profile_ukraine_not_uk`); lane keyword required in title unless `bypass_lane`.
- **first_seen/last_seen stamping + prune at 45d**, earliest first_seen kept, unparseable stamps never destroyed (`test_update_index_stamps_and_prunes`).
- **Error isolation**: a raising `fetch()` never kills the scan (`test_run_collect_source_error_isolated`); a dead ATS slug never kills the `ats` source (`TestFetchIsolation`). New sources/providers must copy both.
- **No module-level third-party import in `src/`** (`test_invariants.py:53`); lazy-inside-function is the only escape hatch.
- **Consent invariant** (constitution #7): `COST!="free"` never auto-runs under `--yes` (`yoke.py:74,:86`). Anything metered must be `COST="key"/"paid"` + `available()` env check.
- **e2e pipeline** (`test_pipeline.py:117`) + **idempotency/byte-identical board** (`:147`) must stay green.
- **ADR-0001**: JD text is **data, never instructions** (prompt-injection surface) — matters now that full JD / LinkedIn / HN comment text flows into the `analyze` model prompt.

## Risks
- **LinkedIn-guest ban vector** — fragile, bot-detected; `COST="free"` means it auto-runs under `--yes`, so ban-safety + error-isolation (return `[]`, throttle) are on us, not on cost gating. Constitution #9: guest read-only endpoint only, **never** voyager/cookie/apply-loop.
- **VC-discovery request fan-out** — probing each YC/a16z company's ATS = many requests → ban/rate risk; strongest reason to land the anti-bot mixin *first* and route discovery through it.
- **Personio XML** breaks the "all providers are JSON" assumption in `ats.py` (`_get_json` returns parsed JSON) — needs an XML-aware fetch path or a separate getter.
- **Comp unit regression** — the `_jj_comp` `/mo`-vs-`/h` bug is guarded; any new comp parser must emit correct `unit` or it reintroduces it.
- **CONTEXT.md drift**: glossary still says `norm` is a "7-key contract" (`CONTEXT.md:6`), omitting `jd` (added commit 9c0b1b9). Code+tests are authoritative — a doc-truth fix belongs to this feature but is pre-existing; flag, don't silently rewrite.
- **Scope creep** — 5 units in one flow risks a shallow design; the plan stage must keep them as independent per-unit TDD commits, infra-first.

## Open questions (feed krukit-grill)
1. **Country-aware activation** — discovery envisioned `profile.country` driving which sources run (DE → Personio, PL-only justjoin skipped). Is source-routing-by-country in M1 scope, or do all sources always run and the profile gate filters? (Currently `TAGS.country` is metadata only; nothing routes on it.)
2. **EU-ATS slugs — where from?** Hand-listed in `profile.sources.companies`, or discovered? Ties unit-3 (EU-ATS) to unit-5 (VC-discovery). Do the 4 EU providers share the `{slug,ats}` shape, or need a distinct config?
3. **VC-discovery output target** — does it write discovered `{slug,ats}` into the profile, into a separate cache, or pass in-memory to `ats` for the current run? Does it detect which ATS a company uses (probe), or assume?
4. **Anti-bot mixin thresholds** — concrete jitter/burst-window/cooldown numbers to measure & set; and does it retry (backoff) or only pace (rate-limit)? Retry risks double-counting; pacing is safer.
5. **LinkedIn-guest ban-safety bar** — acceptable throttle, and what "blocked" signal flips `available()` to `(False, reason)` vs silently returning `[]`?
6. **justjoin-JD cost** — per-offer fetch = 1 extra GET per role (up to ~100+ roles). Fetch JD for all, or only the new-in-window slice? Where is the JD cache (discovery mentioned a "sidecar JD cache")?
7. **New profile fields** — VC-discovery / country-routing may need new `profile.yml` keys; confirm the schema additions and add to `profile.example.yml`.
8. **Metered risk** — are any of YC/a16z/SmartRecruiters rate-limited enough to need a key? Default assumption is all `COST="free"`; verify no silent paid path.

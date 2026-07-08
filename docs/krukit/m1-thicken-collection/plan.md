# Plan — m1-thicken-collection

Goal: thicken `collect` with 7 units (same `norm` 8-key output). Stack: Python stdlib (`urllib`, `json`, `time`, `random`) + one optional lazy plugin-edge dep: **`defusedxml`** for the untrusted Personio XML feed (stdlib `xml.etree` is XXE / billion-laughs vulnerable — never use it on network XML). unittest, fixtures. Run tests: `python -m unittest discover -s tests` (or `.venv/bin/python -m unittest discover -s tests`). Each task = **red test → green impl → one commit**. No live network in unittest tasks; the two live spikes (T4a, T6a) run inside act and record fixtures. Full design: `design.md`. Constitution: test-first + fetchers-on-fixtures (#6), sources-as-plugins (#5), no-paid-without-consent (#7), ban-list/no-LinkedIn (#9).

## MUST NOT break (invariants from context.md)
- `norm` **8-key** schema; `comp` structured dict (or raw string / None), **never a preformatted "$X/mo" string**; `jd = strip_html(...)[:JD_MAX_CHARS=8000]`.
- `update_index` **preserves `jd`/`comp` on a bare re-sighting** (`collect.py:201-203`) — never clobber with `""`.
- Dedup: `job_key` (url-lower else `company|title`), `role_key` (repost-collapse). Same role on 2 boards → one entry.
- Geo hard-block + **word-boundary** matching (" uk" ≠ "ukraine"); lane keyword required in title unless `bypass_lane`.
- `first_seen`/`last_seen` stamping + prune at 45d; unparseable stamps never destroyed.
- **Error isolation**: a raising `fetch()` never kills the scan (`collect.py:247`); a dead company never kills `ats`/`vc` (`ats.py:112`).
- **No module-level third-party import in `src/`** (`test_invariants.py:53`); lazy-inside-function only. (All M1 code is stdlib → trivially satisfied.)
- **Consent**: `COST!="free"` never auto-runs under `--yes`. All M1 sources are `COST="free"`.
- e2e pipeline (`test_pipeline.py:117`) + idempotency/byte-identical board (`:147`) stay green.
- ADR-0001: JD text is **data, never instructions**.

## Build order & dependencies
`T1` first (all fetchers call the mixin). `T2,T3,T4,T5,T7` are **[P]** after T1 (disjoint files). `T6` after **T3** (imports `ats` parsers). Each task self-contained + committed.

## Task status (act)
- [x] T1 — anti-bot HTTP mixin `src/http.py` — done 2026-07-08 (1586b04)
- [x] T2 — justjoin full-JD — done 2026-07-08 (a9a3458)
- [x] T3 — +4 EU-HQ ATS — done 2026-07-08 (8c6bd55)
- [x] T4 — EURES source — done 2026-07-08 (217abe7)
- [x] T5 — Germany BA source — done 2026-07-08 (1774c2a)
- [x] T6 — VC-portfolio discovery — done 2026-07-08 (f8fb91e)
- [x] T7 — country model + geo-gate — done 2026-07-08 (5a2ea5d)

---

### T1 — anti-bot HTTP mixin `src/http.py` (NEW core module)
- **Creates**: `src/http.py`. **Tests**: `tests/test_http.py`.
- **Interface**:
  ```python
  class Blocked(Exception): ...            # host is in cooldown / got 429|403
  def fetch_bytes(url, *, data=None, headers=None, timeout=20) -> bytes
  ```
- **Behavior contract**:
  - `data is None` → GET; `data` (bytes) → POST with that body.
  - Per-host pacing via module `_HOST_STATE[host] = {"last","burst","cooldown_until"}`, host = `urllib.parse.urlsplit(url).netloc`. Before a request: if `_now() < cooldown_until` → raise `Blocked`. Else `_sleep(BASE_DELAY + _rand_jitter())` throttling since `last`; `burst += 1`; when `burst >= BURST_CAP` → `_sleep(COOLDOWN)` + reset burst.
  - On `urllib.error.HTTPError` with code in `{429, 403}` → set `cooldown_until = _now() + COOLDOWN_LONG` for the host, then raise (as `Blocked` or re-raise HTTPError — caller isolates). **No retry** on any error.
  - Time/jitter are indirection hooks (`_now = time.monotonic`, `_sleep = time.sleep`, `_rand_jitter` uses `random.uniform`) so tests monkeypatch them → deterministic + offline.
  - Constants conservative: `BASE_DELAY≈0.5`, jitter `0..1.0`, `BURST_CAP≈20`, `COOLDOWN≈5`, `COOLDOWN_LONG≈60` (tune in act; do not cargo-cult).
- **Test cases**: `test_get_when_no_data`; `test_post_when_data`; `test_paces_between_same_host_calls` (asserts `_sleep` called ≥ BASE); `test_burst_cap_triggers_cooldown`; `test_429_sets_cooldown_then_next_call_blocked`; `test_403_sets_cooldown`; `test_distinct_hosts_independent_state`. All with monkeypatched `_now/_sleep/_rand_jitter` + a fake urlopen; zero real network.

### T2 [P] — justjoin full-JD `src/sources/justjoin.py`
- **Modifies**: `src/sources/justjoin.py`. **Tests**: `tests/test_source_justjoin.py` (+ fixture reuse).
- **Interface** (module-local helpers): `_jd_cache_load() -> dict`, `_jd_cache_save(cache: dict) -> None`, `_extract_jd(html_text: str) -> str`.
- **Behavior contract**:
  - `_parse` stays **pure and unchanged** — still emits `jd=""`.
  - `fetch(profile)`: build records via `_parse` (as today), then enrich: `cache = _jd_cache_load()` (`home()/jd_cache.json`, `{url: jd_text}`). For each record: if `record["url"] in cache` → `record["jd"] = cache[url]`; else `try: raw = http.fetch_bytes(record["url"], headers={"User-Agent": _UA})` — on any exception `continue` (jd stays `""`); `jd = collect.strip_html(_extract_jd(raw.decode("utf-8", "replace")))[:collect.JD_MAX_CHARS]`; set `record["jd"]`, `cache[url]=jd`. `_jd_cache_save(cache)` once at end.
  - `_extract_jd`: pull the offer description block from the justjoin offer HTML (act-time detail; degrade to `""` if not found).
- **Test cases**: `test_parse_fixture` (jd still `""`, unchanged); `test_fetch_fills_jd_from_http` (monkeypatch `http.fetch_bytes` → returns offer HTML; jd populated, tag-free, ≤8000); `test_second_run_reads_cache_no_refetch` (two `fetch` calls, same url → `fetch_bytes` called once; call-count assert); `test_jd_fetch_error_leaves_jd_empty_but_role_kept`.

### T3 [P] — +4 EU-HQ ATS in `src/sources/ats.py`
- **Modifies**: `src/sources/ats.py`. **Tests**: `tests/test_source_ats.py`. **Creates fixtures**: `tests/fixtures/ats_personio.xml`, `ats_smartrecruiters.json`, `ats_workable.json`, `ats_recruitee.json`.
- **Interface**: extend `_URLS` (+4), `_PARSERS` (+4); add `_XML_ATS = {"personio"}`; add `_get_xml(url) -> Element`; add `_parse_personio(root, company)`, `_parse_smartrecruiters(payload, company)`, `_parse_workable(payload, company)`, `_parse_recruitee(payload, company)`.
  - **XML safety**: `_get_xml` parses with **`defusedxml`** (lazy: `from defusedxml.ElementTree import fromstring` *inside* the function — plugin-edge dep, passes `test_invariants.py:53`; never stdlib `xml.etree` on network XML — XXE / billion-laughs). If `defusedxml` is not installed, raise a clear `RuntimeError("personio needs defusedxml: pip install defusedxml")` → caught by the per-company `try/except → SKIP` so it degrades to skipping personio companies, never crashes the scan. Document the optional dep in the module docstring.
  ```
  _URLS += {
    "personio":        "https://{slug}.jobs.personio.de/xml",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings",
    "workable":        "https://apply.workable.com/api/v1/widget/accounts/{slug}",
    "recruitee":       "https://{slug}.recruitee.com/api/offers/",
  }
  ```
- **Behavior contract**:
  - Migrate `_get_json`/new `_get_xml` to call `http.fetch_bytes` (mixin) instead of raw `urllib` (the one existing-code migration; `ats` fans out per-company). `_get_json` = `json.loads(fetch_bytes(url, headers={"User-Agent": UA}))`; `_get_xml` = `defusedxml.ElementTree.fromstring(fetch_bytes(url, headers=...))` (lazy import, see XML safety above).
  - `fetch()` picks getter: `payload = _get_xml(url) if ats in _XML_ATS else _get_json(url)`; per-company `try/except → SKIP` isolation unchanged.
  - Each `_parse_*`: shape-guard (`isinstance`/expected key/root) → else `return []`; build `norm(title, _name(company), location, url, f"ats:{provider}:{slug}", posted_at, comp, jd=strip_html(desc)[:JD_MAX_CHARS])`. **comp structured** `{min,max,currency,unit,type}` where the provider exposes salary (SmartRecruiters/Workable), else `None`. Personio parses `<position>` elements (XML); Recruitee reads `offers[]`; SmartRecruiters reads `content[]`; Workable reads `jobs[]`.
- **Test cases** (per provider): `test_ats_personio_parse`, `test_ats_smartrecruiters_parse`, `test_ats_workable_parse`, `test_ats_recruitee_parse` — full **8-key dict equality** on `jobs[0]`, comp shape assertion, malformed-payload→`[]`. `test_ats_personio_rejects_entity_expansion` — a billion-laughs XML payload raises (defusedxml `EntitiesForbidden`) and the company SKIPs rather than expanding. `TestFetchIsolation` extended to cover a new provider via monkeypatched `_get_json`/`_get_xml`. Existing greenhouse/lever/ashby tests stay green.

### T4 [P] — EURES source `src/sources/eures.py` (NEW plugin)
- **T4a [spike — live, act-only]**: fetch the search-body schema from `rorar/EURES-API-Documentation` `openapi.yaml`; POST live to `https://europa.eu/eures/api/jv-searchengine/public/jv-search/search` until a `200`; **save the real response to `tests/fixtures/eures_search.json`**. (Keyless confirmed by recon; only the winning body is unknown.)
- **Creates**: `src/sources/eures.py`. **Tests**: `tests/test_source_eures.py`. **Fixture**: `tests/fixtures/eures_search.json` (from T4a).
- **Interface**: `NAME="eures"`, `TAGS={"domain":"any","country":"any"}`, `COST="free"`, `available()->(True,"")`, `fetch(profile)`, `_parse(payload, profile)`.
- **Behavior contract**: `fetch` builds a JSON body from `profile.get("countries", [])` (empty/`all-eu` → no country filter) + `profile["lane"]["keywords"]`; `http.fetch_bytes(SEARCH_URL, data=json.dumps(body).encode(), headers={"Content-Type":"application/json"})`; hands the parsed payload to `_parse`. `_parse` → one `norm(...)` per hit: `source="eures"`, `location` from the hit's country/location, `url`=detail link, `comp` if the payload carries structured pay else `None`, `jd = strip_html(summary)[:JD_MAX_CHARS]` (full-JD detail GET deferred — bound volume). Malformed/empty → `[]`.
- **Test cases**: `test_module_contract`; `test_parse_fixture` (≥1 role, 8-key shape, jd tag-free/capped, malformed→`[]`). No live network in the unittest.

### T5 [P] — Germany BA source `src/sources/germany_ba.py` (NEW plugin)
- **T5a [spike — live, act-only]**: GET `https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/app/jobs?was=<kw>&wo=Deutschland&size=…` with header `X-API-Key: jobboerse-jobsuche`; **save the real response to `tests/fixtures/germany_ba.json`**.
- **Creates**: `src/sources/germany_ba.py`. **Tests**: `tests/test_source_germany_ba.py`. **Fixture**: `tests/fixtures/germany_ba.json`.
- **Interface**: `NAME="germany_ba"`, `TAGS={"domain":"any","country":"de"}`, `COST="free"`, `available()->(True,"")`, `fetch(profile)`, `_parse(payload, profile)`.
- **Behavior contract** (design correction: `available()` has **no** `profile` arg, so country-gating lives in `fetch`): `fetch(profile)`: if `{"de","all-eu"}.isdisjoint(set(profile.get("countries", [])))` → **return `[]`** (no HTTP call). Else `http.fetch_bytes(url_with_params, headers={"X-API-Key":"jobboerse-jobsuche"})`; `_parse` → `norm(..., source="germany_ba")`, jd from the search entry (detail GET deferred), comp `None` unless present. Malformed→`[]`.
- **Test cases**: `test_module_contract`; `test_parse_fixture` (8-key, malformed→`[]`); `test_fetch_returns_empty_when_de_not_selected` (monkeypatch `http.fetch_bytes`, assert not called); `test_fetch_queries_when_de_selected` (assert called + roles parsed).

### T6 — VC-portfolio discovery `src/sources/vc.py` (NEW plugin) — depends on T3
- **T6a [spike — live, act-only]**: determine the a16z portfolio data source (JSON endpoint vs HTML scrape); record a fixture (`tests/fixtures/vc_a16z.json` or `.html`). YC list = `https://api.ycombinator.com/v0.1/companies` (record `tests/fixtures/vc_yc.json`).
- **Creates**: `src/sources/vc.py`. **Tests**: `tests/test_source_vc.py`. **Fixtures**: `vc_yc.json`, a16z fixture, one probe-response fixture.
- **Interface**: `NAME="vc"`, `TAGS={"domain":"any","country":"any"}`, `COST="free"`, `available()->(True,"")`, `fetch(profile)`; helpers `_cache_load()`, `_cache_save(cache)`, `_probe(slug) -> str`, `CAP = 40`. Reuse via `from src.sources import ats` → `ats._get_json`, `ats._get_xml`, `ats._URLS`, `ats._PARSERS`, `ats._XML_ATS`.
- **Behavior contract**:
  - `fetch(profile)`: load YC + a16z company lists (I/O). `cache = _cache_load()` (`home()/vc_companies.json`, `{slug: provider|"none"}`). `new = [c for c in companies if c.slug not in cache][:CAP]`; for each: `provider = _probe(slug)`; `cache[slug]=provider`. `_cache_save(cache)`.
  - `_probe(slug)`: for `provider in ats._URLS`: try `ats._get_xml/_get_json(url.format(slug=slug))`; if it yields ≥1 parsed role via `ats._PARSERS[provider]` → return `provider`. All fail/`Blocked` → `"none"`.
  - Emit roles: for `slug,provider in cache` where `provider != "none"`: `payload = ats._get_*(...)`; `out += ats._PARSERS[provider](payload, {"slug":slug, "name":name})`. Per-company `try/except → continue` (isolation). Return `out`. Roles keep `source="ats:{provider}:{slug}"`.
  - Optional `profile["sources"]["vc"]` = `{enabled, cap, portfolios}` with defaults; absent → defaults.
- **Test cases**: `test_module_contract`; `test_probe_returns_first_valid_provider` (monkeypatch `ats._get_json`: greenhouse raises, lever returns jobs → `"lever"`); `test_probe_none_when_all_fail`; `test_cache_short_circuits_reprobe` (two `fetch` runs → each slug probed once; call-count); `test_none_slugs_skipped_on_fetch`; `test_emits_roles_via_ats_parser`. No live network in unittest.

### T7 [P] — country model: `profile.countries` + geo-gate
- **Modifies**: `src/collect.py` (`matches_profile` + a `COUNTRY_MARKERS` map), `profile.example.yml`. **Tests**: `tests/test_collect.py` (new cases).
- **Interface**: `COUNTRY_MARKERS = {"uk": ["united kingdom","uk","london",…], "de": ["germany","berlin",…], "ca": [...], …}` (ISO-2 → location terms); `matches_profile(job, profile, bypass_lane=False)` gains country awareness (signature unchanged).
- **Behavior contract**:
  - Build `target_markers` from `profile.get("countries", [])` via `COUNTRY_MARKERS` (`all-eu` → `[]`, EU already covered by `EU_TERMS`). `has_target = _has_geo_marker(geo, target_markers)`. Change the non-EU reject to: reject only if `has_non_eu and not has_eu and not has_target`. Everything else in the gate unchanged.
  - Empty `countries` → `target_markers == []` → **identical behavior to today** (all existing gate tests stay green).
  - Add `countries:` to `profile.example.yml` with a comment (`# ISO-2 codes you'd work in / relocate to; 'all-eu' = whole EU. Drives EURES/BA + un-blocks non-EU targets.`).
- **Test cases**: `test_matches_profile_country_unblocks_uk` (`countries=["uk"]` → a London/UK role now **passes**, was rejected); `test_matches_profile_empty_countries_unchanged` (a US role still rejected; existing geo tests green); `test_country_markers_cover_queryable_countries`.

---

## Notes for act
- **T4a, T5a, T6a are live spikes** — run them inside act (real network, one-shot) to record fixtures; then write the `_parse` tests test-first against the recorded fixtures. This is the only live network in act; everything else is offline TDD.
- **Live-network dry-run of all new free sources is NOT here** — it belongs to stage 6 (krukit-verify), per constitution #10.
- Every task ends with its own commit (`feat: <unit>` / `test: <unit>`), one logical change apiece (constitution #8).
- After T1, tasks T2/T3/T4/T5/T7 may run as parallel subagents (disjoint files); T6 waits for T3.

## Learnings
- `home()` lives in `src.paths` (not `src.collect`); write-side must call `paths.ensure_home()` first (mirrors `paths.save_state`).
- justjoin's full JD is only in the offer page's server-rendered `<script type="application/ld+json">` JobPosting `description` — the body is client-rendered React (no `__NEXT_DATA__`, no SSR div). Re-verify this selector live in stage 6.
- justjoin's list GET was NOT migrated to the http mixin (plan migrates only `ats` getters), so offline `fetch()` tests must stub `urllib.request.urlopen` in addition to `http.fetch_bytes`.
- **ATS comp/jd reality inverts the plan's guess:** SmartRecruiters postings-list + Workable widget carry neither salary nor description → `comp=None, jd=""`. **Recruitee** is the only new provider with structured `salary`; Personio + Recruitee are the only two with descriptions. No speculative salary/JD extraction added for fields providers never return.
- Personio (`{slug}.jobs.personio.de/xml`) and SmartRecruiters postings-list carry **no job URL** → built from id (`.../job/{id}`, `jobs.smartrecruiters.com/{ident}/{id}`), both verified 200.
- `defusedxml.common.EntitiesForbidden` (a `ValueError` subclass) is what `fromstring` raises on the billion-laughs DOCTYPE; the per-company `try/except` turns it into a SKIP.
- **Stage-6 live caveats:** Workable widget returns empty `jobs:[]` for most accounts (only widget-embedding tenants populate; probing hits 429 fast); Personio `.de` 307-redirects to `.com` for many slugs (urllib follows, curl -L needed); Recruitee 404s unless the exact careers subdomain exists; empty Personio `jobDescriptions` / empty content is a valid real `jd=""`.
- **EURES** search payload carries no structured salary and no job URL → comp `None`, detail link built from `hit.id` (`.../jv-details/{id}`); full JD needs a second detail GET (deferred). Working POST body confirmed live; `locationCodes` is the country filter, `keywords[].keyword` the query.
- **Germany BA** search entries carry no description → `jd=""` (detail GET deferred); URL built from `refnr` (`arbeitsagentur.de/jobsuche/jobdetail/{refnr}`) when no `externeUrl`. Country-gate is in `fetch` (not `available`, which takes no profile).
- **a16z has no JSON API** — the `/portfolio/` page (~3.5MB) embeds the company array as an entity-escaped attribute; the extraction marker `data-portfolio-companies="` is **a GUESS, unverified — MUST be confirmed live in stage 6**. Miss → `[]` (zero a16z companies), never a crash.
- **VC probe fan-out:** `_probe` fires up to `len(ats._URLS)=7` GETs per NEW company; `CAP=40` new/scan → ≤280 probe GETs worst case (first scan), all http-mixin-paced; cache makes it one-time per slug. Emit re-GETs every cached non-`"none"` slug each scan — a growing per-scan cost worth watching live.
- **Pre-existing test noise:** the full suite prints `ResourceWarning: Implicitly cleaning up <HTTPError 403/429>` from T1's mocked `HTTPError(fp=None)` doubles in `test_http.py`. Harmless (suite exits OK); candidate for a one-line cleanup in review — construct the doubles with a `BytesIO` fp or `addCleanup(err.close)`.

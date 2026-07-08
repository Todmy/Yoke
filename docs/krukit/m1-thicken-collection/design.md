# Design — m1-thicken-collection

Thicken `collect` with 7 units, same output (`norm` 8-key record → `_index.json` → SHORTLIST). Build order infra-first: **http mixin → justjoin-JD → EU-ATS → EURES → Germany BA → VC-discovery → country model**. All units emit the 8-key record; comp structured, never a preformatted string. All `COST="free"`.

## Architecture at a glance

- **One new core module**: `src/http.py` — the anti-bot transport mixin (stdlib `urllib`). Everything else either extends an existing module (`ats.py`, `collect.py`, `paths`/`profile`) or is a new **source plugin** under `src/sources/` (the registry is expected to grow — constitution #5). No other new core modules (constitution #4: "14 modules was the mistake").
- **Sidecar state** stays flat JSON under `home()` (`$YOKE_HOME`): `jd_cache.json` (justjoin), `vc_companies.json` (VC probe results). No DB (constitution #3).
- **Fetch/parse split preserved everywhere** (constitution #6): `fetch()` does all I/O (via the mixin); a pure `_parse(payload, profile)` builds records and is the only thing fixture tests touch.

---

## 1. Anti-bot HTTP mixin — `src/http.py` (NEW core module)

**Chosen over** a helper inside `collect.py` (keeps the spine focused; transport is a distinct responsibility).

Single public function, stdlib only:

```python
def fetch_bytes(url, *, data=None, headers=None, timeout=20) -> bytes
```
- `data` set → POST (JSON body already encoded by caller); else GET.
- **Pacing**: module-level `_HOST_STATE = {host: {"last": monotonic, "burst": int, "cooldown_until": monotonic}}`. Before each request: derive host from url; if `now < cooldown_until` → raise `Blocked(host)` (caller isolates). Else `sleep(BASE + random_jitter)` since `last`; increment `burst`; when `burst >= BURST_CAP` → `sleep(COOLDOWN)` and reset burst.
- **No retry**: on `HTTPError` 429/403 → set `cooldown_until = now + COOLDOWN_LONG` for that host, re-raise (source catches → returns `[]`/continues). On other errors → re-raise (isolated upstream). Pacing only, never a retry loop (grill Q4).
- Constants (`BASE`, jitter range, `BURST_CAP`, `COOLDOWN`, `COOLDOWN_LONG`) are **measured in act, not cargo-culted** (grill note); start conservative (~0.5–1.5 s base, burst ~20, long cooldown ~60 s).
- `Blocked(Exception)` — a small typed signal so a source can tell "host cooled down" from a genuine parse error.

**Adoption (surgical):** the mixin is used by the fan-out / new sources — `ats.py`, `justjoin.py` (per-offer JD), `vc.py`, `eures.py`, `germany_ba.py`. The existing **single-shot** RSS/API sources (remoteok, remotive, workingnomads, wwr, hn, brave) keep their own `urllib` in M1 — migrating working low-ban-risk fetchers is out of scope (constitution: surgical changes); noted as a later cleanup.

**Import discipline**: `src/http.py` imports only stdlib (`urllib`, `time`, `random`, `urllib.parse`) → passes `test_invariants.py:53`.

**Tests (test-first)**: pacing sleeps between calls, burst → cooldown, 429/403 → `cooldown_until` set + `Blocked` on next call to that host, GET vs POST selection. `time`/`sleep`/`random` are injected or monkeypatched so tests are deterministic and offline.

---

## 2. justjoin full-JD — extend `src/sources/justjoin.py`

`_parse` stays pure and still emits `jd=""`. **JD enrichment is I/O → lives in `fetch()`** after `_parse`:

```
fetch(profile):
  records = _parse(payload, profile)  # per category, as today
  cache = _jd_cache_load()            # home()/jd_cache.json : {url: jd_text}
  for r in records:
      if r["url"] in cache: r["jd"] = cache[r["url"]]
      else:
          try: html_ = http.fetch_bytes(offer_url_for(r), headers=...)   # mixin-paced
          except Exception: continue                                      # graceful, jd stays ""
          jd = collect.strip_html(_extract_jd(html_))[:collect.JD_MAX_CHARS]
          r["jd"] = jd; cache[r["url"]] = jd
  _jd_cache_save(cache)
  return records
```
- **Cache = flat `home()/jd_cache.json`**, keyed by role url → fetched once ever (grill Q6); re-runs skip cached urls; steady state fetches only new offers. Cache helpers are **local to justjoin** (no new core module — YAGNI; extract only if EURES/BA/brave later need it).
- Respects the invariant: `update_index` already preserves `jd` on a bare re-sighting (`collect.py:203`); the cache means we never re-clobber with `""`.
- `_extract_jd(html_)` parses the justjoin offer page for the description block (act-time detail; the offer URL is already built at `justjoin.py:85`).

**Tests**: `_parse` fixture test unchanged (jd still ""); new test that `fetch` fills `jd` from a mock `http.fetch_bytes` and a second run reads the cache without re-fetching (mock asserts call count). No live network.

---

## 3. +4 EU-HQ ATS — extend `src/sources/ats.py`

Add four providers to the existing dispatch tables (constitution #4 "extension through seams"):

| Provider | Endpoint | Transport |
|---|---|---|
| personio | `https://{slug}.jobs.personio.de/xml` | **XML** |
| smartrecruiters | `https://api.smartrecruiters.com/v1/companies/{slug}/postings` | JSON |
| workable | `https://apply.workable.com/api/v1/widget/accounts/{slug}` | JSON |
| recruitee | `https://{slug}.recruitee.com/api/offers/` | JSON |

- `_URLS` gains 4 entries; `_PARSERS` gains `_parse_personio/_parse_smartrecruiters/_parse_workable/_parse_recruitee`; add `_XML_ATS = {"personio"}`.
- **XML path**: add `_get_xml(url)` using `xml.etree.ElementTree`; `fetch()` picks `_get_xml if company["ats"] in _XML_ATS else _get_json`. Both getters route through `http.fetch_bytes` (mixin) instead of raw `urllib` — this is the one migration of existing code, justified because `ats` fans out per-company.
- Per-company `try/except → SKIP` isolation reused unchanged (`ats.py:110-114`).
- **comp structured where available** (SmartRecruiters/Workable expose salary fields → emit `{min,max,currency,unit,type}`; Personio/Recruitee often none → `None`). Never a preformatted string.
- Slugs come from `profile.sources.companies` `[{slug, ats}]` (hand-seeded) **and** from VC-discovery (unit 6). All 4 fit the existing `{slug, ats}` shape — no schema change.

**Tests**: 4 recorded fixtures (`ats_personio.xml`, `ats_smartrecruiters.json`, `ats_workable.json`, `ats_recruitee.json`) + one `_parse_*` test each (full 8-key equality on `jobs[0]`, comp shape, malformed→`[]`). Existing `TestFetchIsolation` covers the new providers too.

---

## 4. EURES — `src/sources/eures.py` (NEW plugin, COST=free)

All-EU keyless aggregator (ADR-0002).
- `available()` → `(True, "")`.
- `fetch(profile)`: build a JSON search body from `profile["countries"]` + `profile["lane"]["keywords"]`; `http.fetch_bytes(SEARCH_URL, data=body_json, headers={"Content-Type":"application/json"})`; `_parse(payload, profile)` → `norm(...)` per hit, `source="eures"`, comp if the payload carries it, `jd` from the hit summary (full-JD via the detail GET is deferred to keep request volume bounded — noted).
- `SEARCH_URL = https://europa.eu/eures/api/jv-searchengine/public/jv-search/search`.
- **Act-time spike**: the exact request-body field set for a 200 is pulled from `rorar/EURES-API-Documentation` `openapi.yaml` (research confirmed keyless; not the winning body). First act sub-task = nail the body against the live endpoint, record a fixture from the real response, then write `_parse` test-first against it.

**Tests**: `_parse` on a recorded EURES search fixture → 8-key records; malformed→`[]`. No live network in tests.

---

## 5. Germany BA — `src/sources/germany_ba.py` (NEW plugin, COST=free)

Deep DE booster (ADR-0002), keyless via static key.
- `fetch(profile)`: `GET https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/app/jobs` with header `X-API-Key: jobboerse-jobsuche` + params (`was`=keywords, `wo`=DE/city, `size`), via `http.fetch_bytes`; `_parse` → `norm(..., source="germany_ba")`, jd from the search entry (detail GET `/pc/v4/jobdetails/{base64(refnr)}` deferred to bound volume).
- Active when `de` or `all-eu` ∈ `profile.countries` (country model), else `available()` → `(False, "germany not in profile.countries")`.

**Tests**: `_parse` on a recorded BA fixture; contract test; malformed→`[]`.

---

## 6. VC-portfolio discovery — `src/sources/vc.py` (NEW plugin, COST=free)

**Capped incremental + permanent cache** (grill/clarify decision).
- **Company lists**: YC `https://api.ycombinator.com/v0.1/companies` + a16z portfolio (a16z has no clean API → scrape the portfolio page; **act-time spike**, same treatment as the EURES body).
- **Probe cache** = flat `home()/vc_companies.json` : `{slug: "greenhouse"|"lever"|...|"none"}`. Permanent — a slug is probed once ever.
- **Per-run bound**: take up to `CAP` (default 40) companies not yet in the cache; for each, probe candidate ATS by trying `ats._URLS[provider].format(slug=...)` (via the mixin) until one returns valid jobs → record provider; none → `"none"`.
- **Fetch roles by reusing `ats`** (no duplication): `from src.sources import ats`; for every cached slug with a real provider, call `ats._get_json`/`_get_xml` + `ats._PARSERS[provider](payload, {"slug":slug,"name":name})`. Roles keep the ats parser's `source="ats:{provider}:{slug}"` (the role genuinely comes from that ATS; VC is just how the company was found).
- Optional profile knob `profile.sources.vc = {enabled: true, cap: 40, portfolios: [yc, a16z]}` with defaults; absent → sensible defaults.

**Tests**: `_parse`/probe logic against fixtures with a mock `http.fetch_bytes` (probe picks the first provider that returns jobs; cache short-circuits re-probing; `"none"` slugs skipped). Reuses `ats` parser tests transitively. No live network.

---

## 7. Country model — `profile.countries` + geo-gate integration

- **New profile field** `countries: [pl, de, ...]` or `[all-eu]` (ISO-2). Added to `profile.example.yml`. `load_profile` needs no new validation (optional list; default empty → current behavior).
- **Drives source querying** (required use): EURES search body country filter; Germany BA activation; any future per-country source. `all-eu` = no country filter (broadest).
- **Geo-gate integration** (chosen: *the gate reads `profile.countries`*, over expanding `geo.allow` at load — keeps "data in profile, logic in code", `profile.example.yml` ethos). In `matches_profile` (`collect.py:107-147`): the EU marker set already permits every EU country, so EU targets need no change. For a **non-EU relocation target** (e.g. `uk`, `ca`) in `countries`, add its markers to the allowed set so the `NON_EU` reject doesn't fire: reject only if `has_non_eu and not has_eu and not has_target_country`. `_country_markers(profile)` maps ISO → terms; EU codes are redundant-but-harmless, non-EU codes are the ones that matter.
- Concrete-with-seams: for the current user (PL + EU), default behavior is unchanged; the field is the seam that also serves M5 generalization.

**Tests**: `matches_profile` with `countries=[uk]` lets a UK role pass (today rejected); empty `countries` leaves every existing gate test green; EURES/BA build the right country param from the field.

---

## Data flow (unchanged shape)

`yoke run` → `load_profile` (now carries `countries`) → source select menu (new free sources listed, nothing keyed) → `run_collect` → each `fetch(profile)` (mixin-paced) → `matches_profile` gate (now country-aware) → `update_index` (jd/comp preserved) → board render. Identical `_index.json`/SHORTLIST format.

## Error handling

Every new fetcher returns `[]` on malformed payload or `Blocked` (never raises past its own `fetch`). `run_collect` isolates a raising source (`collect.py:247`); `ats`/VC isolate per-company (`ats.py:112`). A cooled-down host is skipped for the rest of the run. No partial write corrupts `_index.json` (written once at end).

## Testing strategy

Unittest, fixtures, **no live network** (constitution #6): mixin logic (mocked time/sleep/random), each source `_parse` on a recorded fixture (8-key equality + malformed→`[]`), justjoin/VC cache behavior via mock `http.fetch_bytes` + call-count asserts, country-gate un-block test. Live-network dry-run of the new free collectors + zero-context diff review happen at **verify** (constitution #10).

## Definition of Done

1. All 7 units implemented, **one commit per unit**, full unittest suite green with **no live network in tests**.
2. `yoke run --dry-run` over the new free sources returns roles or a clear per-source reason; no traceback, no ban/crash.
3. `profile.countries=[pl,de]` → EURES + BA return PL+DE roles; adding a non-EU country lets its roles pass the gate; empty `countries` = unchanged behavior.
4. justjoin roles now carry `jd`; a second identical run re-uses `jd_cache.json` (no re-fetch) and the board stays idempotent/byte-identical.
5. At least one Personio/SmartRecruiters/Workable/Recruitee slug returns parsed roles (fixture-proven; live-spot-checked at verify).
6. VC-discovery: a capped probe fills `vc_companies.json`; resolved companies' roles appear; re-run skips re-probing.
7. No new paid/keyed path; consent menu + `--yes` free-default unchanged.

## Constitution check

| Principle (MUST) | Verdict |
|---|---|
| 1. Local-first | pass — all state (caches, index) stays under `$YOKE_HOME`; no CV/labels leave the machine; new sources are read-only fetch. |
| 2. Deterministic core, thin AI surface | pass — collect stays zero-LLM; no model call added; sources are deterministic parsers. |
| 3. Flat files | pass — `jd_cache.json`, `vc_companies.json`, `_index.json` are flat JSON; no DB. |
| 4. Concrete with seams | pass — M1 roadmap milestone; exactly one new core module (`src/http.py`, the mixin unit); JD cache kept local to justjoin; sources added via the plugin seam; no speculative abstraction. |
| 5. Sources are plugins | pass — vc/eures/germany_ba are self-contained plugins; EU-ATS extends the `ats` provider table; all deps stdlib (`urllib`/`xml.etree`/`json`) — nothing heavy at module level. |
| 6. Core test-first, fetchers on fixtures | pass — mixin + gate logic test-first; every fetcher keeps fetch/parse split with fixture parse-tests; no live network in tests. |
| 7. No paid call without consent | pass — all in-scope sources `COST="free"`; France/Poland deferred as `key`; analyze new-in-window slice untouched. |
| 8. Moat barrier & small commits | pass — one commit per unit; `.private`/profile/labels/caches never committed (caches live under `$YOKE_HOME`); push only with permission. |
| 9. Competitor ban-list | pass — structured APIs (not WebSearch-only); no keyword tier-classifier; no LaTeX; **LinkedIn dropped entirely** (no headless-loop apply); no SQLite/TUI. |
| 10. Live-run verification | pass — verify stage will dry-run the new free collectors on real network + independent zero-context diff review (planned in DoD + Testing). |

Zero unresolved violations.

# Verify — v1 live-validation

Date: 2026-07-08 · Route: fix · Oracle: docs/manual-qa-checklist.pdf (scoped)

## Scope correction (recorded at act)
The checklist targets a full **web** product (`./yoke serve` control panel;
Settings/Profile/Board/Apply/Reject/Applied/Improve/Schedule pages; `collect/
status/gap/cover/tune/eval` CLI). Built v1 is **CLI-only**: `run` (collect→
prepare→analyze→board→SHORTLIST.md), `board`, `apply`, `drop`; flat-file state.
~1.5 of 14 sections map to reality. Validation was scoped to the built slice
(user decision: "validate CLI slice live + fix docs to reality").

## Evidence (live)
- **Baseline**: 105 tests green before changes; **106 green** after (unittest, no pytest).
- **§3.2 collect (real network)**: `./yoke run --dry-run` over 7 free sources returned
  clean per-source counts, no traceback. hn 64 / justjoin 43 / wwr 2 / workingnomads 2
  / remoteok 0 / remotive 0 / ats 0 → 111 index keys. Zero encoding corruption in
  persisted `_index.json` across contributing sources.
- **§3.3–3.5, §4 pipeline (--mock)**: full run rendered SHORTLIST.md (tier/fit/comp/
  geo/note/URL) + `_board.json` {roles, applied, dropped}; run summary printed
  added/refreshed/pruned + shortlist path.
- **§14 idempotency**: two identical `--mock` runs → run #2 "nothing new in window",
  `_board.json` **byte-identical** (same md5). Dedup/window/prune path holds.
- **🔌 real LLM path**: single live `claude_code` (claude -p, haiku-4-5) call from
  inside this session **exited 1** — nested claude-in-claude artifact, not a Yoke
  defect. The backend's **error path validated**: it isolated the failure and raised
  RuntimeError → analyze would ship the card as `analysis_failed`/tier C (graceful,
  per design). Real-model success path NOT exercised this session (needs a
  non-nested run).

## Defect found + fixed (TDD)
**HN source served a 2020 thread.** `src/sources/hn.py` searched Algolia `/search`
(relevance-sorted, `hitsPerPage=1`) → `hits[0]` = a highly-ranked 2020 "who is hiring"
thread. 64 of 111 board roles (58%) were 6-year-old junk. Root cause: relevance sort,
no recency, no canonical-author pin. Fix: `search_by_date` + `tags=story,author_
whoishiring`. Live after fix: "Ask HN: Who is hiring? (July 2026)", current postings.
- Red→green test: `test_search_url_targets_latest_canonical_thread` (pins endpoint +
  author contract; a fixture-only parse test could not have caught a wrong URL — the
  exact "fixture-only masks integration defects" lesson).

## Surfaced, NOT defects (documented)
- **justjoin jd=0**: deliberate M1 deferral — code comment `# jd stays empty: full JD
  needs per-offer fetch — M1`. List API carries no full JD. Primary PL source scores
  from title/company/location/comp only until M1.
- **remoteok/remotive 0 roles**: legitimate profile-gate filter (raw 100/56 fetched;
  US-remote + narrow lane keywords → 0 kept). Scrapers work.
- **remoteok upstream mojibake** (`St Johnâ€™s`): upstream data corruption on
  roles that are filtered out entirely — never reaches state.
- **HN US roles on the mock board**: mock artifact — `mock_fill` never emits `onsite`
  (by design, so mock data reaches the board). Real model sets geo_certainty from the
  comment JD → onsite ⇒ tier C. Not validatable under --mock.

## Doc-truth fixes
- `README.md`: removed false "local web board" / "local web UI to triage" claims →
  CLI reality (`yoke apply`/`drop`, SHORTLIST.md); tagged tuner as roadmap.
- `manual-qa-checklist.pdf`: left as the **roadmap web-product** QA spec; this
  verify.md is the honest v1 (CLI) validation record. CONTEXT.md was already clean.

## Gate
- [x] Live evidence gathered (collect real, pipeline mock, idempotency).
- [x] One defect found → root-caused → TDD-fixed → re-verified live.
- [x] Full suite green (106).
- [x] Known-limits documented; no outstanding HIGH finding.
- [ ] Real-model success path — deferred (nested-session limitation).

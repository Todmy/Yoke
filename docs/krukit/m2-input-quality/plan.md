# Plan: m2-input-quality

## Header

**Goal.** Four deterministic workstreams closing v1.0 parity: WS1 red-flag penalty multiplier, WS2 model-estimated comp band, WS3 ghost/liveness as code-detected red flags, WS4 stdlib fuzzy dedup. Plus a parity harness (DoD).

**Architecture.** Pipeline `collect → prepare → analyze → board` unchanged. One penalty seam (`analyze` applies a clamped multiplier to the additive `fit_base` from two sources: model-classified red flags + code-detected ghost signals). Comp precedence source→JD-parsed→model-estimate (estimate soft). Dedup at ingest in `collect`, same-company-scoped.

**Stack.** Python stdlib only in `src/` (no third-party module-level imports). `unittest`; tests set `YOKE_HOME` to a tmpdir and import `src.*`; fixtures under `tests/fixtures/` drive the real path.

**North star.** Model judges/classifies (non-deterministic); code owns every number (deterministic); tunables are profile data.

**MUST NOT break (invariants from context.md):**
- `fit` stays the pure additive weighted sum, clamped 0-100 (`scoring.fit`); tier cutlines live only in `scoring.py` (`TIER_A=70/TIER_B=55`).
- Model never does arithmetic; `comp_vs_floor` deterministic (`COMP_SCORE`). `onsite`/`lane off` → hard C, independent of penalties.
- Comp: unit read from source field, never inferred; output-dict keys are a consumed contract.
- `prepare` stays pure (no network/LLM/IO beyond index/state read + `_cards.json`); `needs_ai = in_window AND not gates_failed`; window `first_seen > max(last_run, now−14d)`.
- Collect `norm` 8-key contract; `role_key` repost-collapse load-bearing for the board; **applied is a forever-ledger** — WS4 must not touch `role_key`/applied-prune.
- No module-level third-party import in `src/**` (`test_invariants`); `analyze` scores only the new-in-window slice; no new paid surface.

**Scope note.** WS4 (`collect`) is independent of WS1-3 (`analyze`/`scoring`/`prepare`); kept in one plan per the whole-M2 decision, but WS1+WS3 form a natural first commit-batch (the scoring core) with a `/clear` checkpoint after.

---

## Tasks (execution order)

### Progress
- [x] T1.1 penalized_fit (WS1)
- [x] T1.2 classified red-flag schema + enum (WS1)
- [x] T1.3 apply penalty in analyze_cards (WS1)
- [x] T1.4 profile red-flag config (WS1) [mechanical]
- [x] T3.1 prepare.ghost_flags (WS3)
- [x] T3.2 attach ghost_flags in build_cards (WS3)
- [x] T3.3 ghost penalty flows through analyze (WS3) [P]
- [ ] T2.1 comp_estimated schema + market-aware prompt (WS2)
- [ ] T2.2 comp precedence + soft estimate (WS2)
- [ ] T4.1 title normalization + similarity (WS4) [P]
- [ ] T4.2 update_index attaches dupe_of (WS4)
- [ ] T4.3 profile dedup config (WS4) [mechanical]
- [ ] T4.4 build_cards skips dupe_of entries (WS4)
- [ ] T5.1 parity harness tools/parity_check.py (DoD)

### T1.1 — `scoring.penalized_fit` (WS1)
- **Files:** modify `src/scoring.py`; test `tests/test_scoring.py`.
- **Signature:** `def penalized_fit(fit_base: int, penalties: list[float], cap: float) -> int`
- **Contract:** returns `round(fit_base * (1 - min(sum(p for p in penalties if p > 0), cap)))`, then clamped to 0-100. Empty/all-zero penalties → returns `fit_base` unchanged. `sum` is capped at `cap` before applying (the modifier-floor clamp). Pure, no I/O. Lives in `scoring.py` (single home of the fit arithmetic).
- **Test cases:** `no_penalties_identity` (80,[],0.5→80); `single_penalty` (80,[0.5],0.5→40); `summed_capped` (80,[0.4,0.4],0.5→40, not 16); `cap_zero_identity` (80,[0.5],0.0→80); `rounding` (81,[0.1],0.5→73); `clamp` (result never <0 or >100).

### T1.2 — Classified red-flag schema + enum (WS1)
- **Files:** modify `src/analyze.py`; test `tests/test_analyze.py`.
- **Add:** `RED_FLAG_CATEGORIES = ("scam_signal","unrealistic_requirements","legal_risk","comp_opacity","culture_flag","stale_posting","repost_churn","untrusted_apply_domain","confidential_employer")` and `ANALYSIS_SCHEMA_VERSION = 2`.
- **Change:** `ANALYSIS_SCHEMA` `red_flags` items from `{type:string}` to `{type:object, properties:{category:{enum:list(RED_FLAG_CATEGORIES)}, evidence:{type:string}}, required:[category, evidence]}`. Update `_SYSTEM` prompt: "classify each concern into exactly one red-flag category with one line of evidence; use only the listed categories." Update `mock_fill` to keep `red_flags: []` (still valid).
- **Contract:** schema validates classified objects; unknown category rejected by the enum. `red_flags` stays `required`. Empty list still valid.
- **Test cases:** `schema_accepts_classified_red_flags`; `schema_rejects_unknown_category`; `version_is_2`; `mock_fill_still_valid` (empty red_flags passes `_schema_ok`).

### T1.3 — Apply penalty in `analyze_cards` (WS1)
- **Files:** modify `src/analyze.py` (`analyze_cards`); test `tests/test_analyze.py`.
- **Consumes:** profile `scoring.red_flags: {category: penalty}` map + `scoring.red_flag_cap` (default `0.5`); model `result["red_flags"]` (classified objects); `card.get("ghost_flags", [])` (category strings — empty until WS3, read defensively now so WS3 needs no analyze change).
- **Contract:** build `penalties = [red_flag_map.get(rf["category"], 0.0) for rf in model_red_flags] + [red_flag_map.get(cat, 0.0) for cat in card.get("ghost_flags", [])]`. Unknown category → `0.0` + one `log()` line (fail-open). `fit_base = scoring.fit(scores, weights)` (unchanged); `fit_final = scoring.penalized_fit(fit_base, penalties, cap)`; pass `fit_final` to `tier_of`. Store `red_flags` on the record as the merged list of `{category, evidence}` (model flags + ghost flags rendered as `{category, evidence: "detected: <cat>"}`).
- **Contract (regression):** with no red flags and no ghost flags, `fit_final == fit_base` — existing exact-fit locks (fit 92, 77) stay valid.
- **Test cases:** `penalty_lowers_fit_and_tier` (scam_signal@0.5 turns a fit-92 A into fit-46 C-or-B per tiers); `unknown_category_ignored`; `cap_bounds_stacked_penalties`; `no_flags_is_identity` (existing 92/77 unchanged); `ghost_flags_field_penalizes` (card ghost_flags=["untrusted_apply_domain"] penalizes even with clean model output).
- **Note:** update any existing `test_analyze` fixture that returned `red_flags` as bare strings to the new `{category, evidence}` shape.

### T1.4 — [mechanical] Profile red-flag config (WS1)
- **Files:** modify `profile.example.yml`; test `tests/test_analyze.py` (or `test_prepare.py`) asserting the example profile carries the map.
- **Add** under `scoring:`: `red_flag_cap: 0.5` and a `red_flags:` map with the 9 categories and starter penalties (scam_signal 0.5, unrealistic_requirements 0.15, legal_risk 0.3, comp_opacity 0.1, culture_flag 0.1, stale_posting 0.15, repost_churn 0.2, untrusted_apply_domain 0.4, confidential_employer 0.1).
- **Contract:** `features`+`deterministic` weights STILL sum to 100 (red_flags are outside the additive sum). Loading the example profile exposes `scoring.red_flags` as a dict.
- **Test case:** `example_profile_has_red_flag_map` (dict present, cap==0.5, weights still sum 100).

### T3.1 — `prepare.ghost_flags` (WS3)
- **Files:** modify `src/prepare.py` (add fn + constants); test `tests/test_prepare.py`.
- **Signature:** `def ghost_flags(entry: dict, now: datetime | None = None) -> list[str]` → subset of `{stale_posting, repost_churn, untrusted_apply_domain, confidential_employer}`.
- **Constants:** `SHORTENER_HOSTS = {"bit.ly","tinyurl.com","forms.gle","goo.gl","t.co","rb.gy"}`; `STALE_DAYS = 30`; `EVERGREEN_DAYS = 30`; `CONFIDENTIAL_MARKERS = {"", "confidential", "undisclosed", "stealth", "n/a"}`.
- **Contract (pure, no network/IO):**
  - `stale_posting` if `posted_at` parses and is older than `STALE_DAYS` before `now`.
  - `repost_churn` if `last_seen − first_seen > EVERGREEN_DAYS` (kept reappearing).
  - `untrusted_apply_domain` if `urllib.parse.urlparse(url).netloc.lower()` (strip leading `www.`) ∈ `SHORTENER_HOSTS`.
  - `confidential_employer` if `company.strip().lower()` ∈ `CONFIDENTIAL_MARKERS`.
  - Unparseable/missing fields contribute nothing (no crash). `now` defaults to `datetime.now(timezone.utc)`; injectable for tests.
- **Test cases:** each of the four fires on a crafted entry and is absent on a clean one; `clean_entry_no_flags`; `stale_uses_injected_now`; `shortener_matched_case_insensitive`; `www_prefix_stripped`.

### T3.2 — Attach `ghost_flags` in `build_cards` (WS3)
- **Files:** modify `src/prepare.py` (`build_cards`); test `tests/test_prepare.py`.
- **Contract:** each card gets `"ghost_flags": ghost_flags(entry)` (computed for all entries, like `gates_failed`). No other field changes; purity preserved.
- **Test cases:** `card_carries_ghost_flags`; `stale_entry_card_has_stale_posting`; existing `build_cards` tests still pass (new key additive).

### T3.3 — [P] Ghost penalty flows through analyze (WS3, integration)
- **Files:** test only — `tests/test_analyze.py` (or `tests/test_pipeline.py`).
- **Contract:** no production change (T1.3 already reads `card["ghost_flags"]`). Prove end-to-end: a card with `ghost_flags=["untrusted_apply_domain"]` and a clean model result gets `fit_final < fit_base` by the mapped penalty; a card with empty ghost_flags is unaffected.
- **Test cases:** `ghost_flag_penalizes_via_seam`; `no_ghost_flags_identity`.

### T2.1 — `comp_estimated` schema + market-aware prompt (WS2)
- **Files:** modify `src/analyze.py` (`ANALYSIS_SCHEMA`, `_SYSTEM`, `build_card_prompt`); test `tests/test_analyze.py`.
- **Change:** add optional (NOT required) nullable `comp_estimated` with the same shape as `comp_parsed` (`{min,max,currency,unit,type} | null`). `_SYSTEM`: "if the posting states pay, fill `comp_parsed` verbatim and leave `comp_estimated` null; if pay is absent, leave `comp_parsed` null and fill `comp_estimated` with your best band for THIS company in the candidate's target market — never both." `build_card_prompt` adds a line with the target market from `profile.get("countries", [])` (and `comp.floor_net_usd_mo` as the reference floor) so the model estimates in-market.
- **Contract:** schema still valid when `comp_estimated` omitted (backward-compatible — existing mocks unaffected); model instructed to estimate only when pay absent; code still owns all comp arithmetic.
- **Test cases:** `schema_accepts_comp_estimated`; `schema_valid_without_comp_estimated`; `prompt_includes_target_market`.

### T2.2 — Comp precedence + soft estimate in `analyze_cards` (WS2)
- **Files:** modify `src/analyze.py` (`analyze_cards`, `comp_display`); test `tests/test_analyze.py`.
- **Contract (precedence):** resolve comp as `card.comp_norm` (source) → else `comp.normalize(comp_parsed, floor)` → else `comp.normalize(comp_estimated, floor)` with `is_estimated=True`. First present wins.
- **Contract (soft, when `is_estimated`):**
  - `comp_vs_floor` score = `COMP_SCORE[verdict]` (as usual).
  - friction = `"estimated comp"` (not `"comp unknown"`).
  - tiering: pass `comp_ok=True` **regardless of verdict** (an estimate never sets comp_ok False → never forces Tier C; never assumes zero).
  - `comp_display` prefixes `"≈ "` for estimates.
- **Contract (regression):** source/JD-parsed paths and the no-comp unknown path unchanged; existing exact-fit tests (92 source-comp, 77 unknown) hold because their mocks omit `comp_estimated`.
- **Test cases:** `precedence_source_over_parsed_over_estimated`; `estimated_below_not_tier_c` (below estimate → A/B with friction, comp_ok stays True); `estimated_sets_friction_and_display` (`≈` prefix, "estimated comp" friction); `unknown_still_50_when_no_estimate`.

### T4.1 — [P] Title normalization + similarity (WS4)
- **Files:** modify `src/collect.py` (add helpers); test `tests/test_collect.py`.
- **Signatures:** `def _normalize_title(title: str) -> str`; `def _title_similar(a: str, b: str, ratio: float) -> bool`.
- **Contract:** `_normalize_title` lowercases, strips seniority tokens `{senior,sr,junior,jr,mid,middle,lead,staff,principal}`, unifies `javascript`↔`js` and `node.js`↔`nodejs`, removes punctuation, collapses whitespace. `_title_similar` = `difflib.SequenceMatcher(None, _normalize_title(a), _normalize_title(b)).ratio() >= ratio`. Pure, stdlib `difflib` + `re`.
- **Test cases:** `normalize_strips_seniority` ("Senior Node.js Engineer" ~ "Node Engineer"); `js_javascript_unified`; `similar_true_above_ratio`; `dissimilar_false` ("Backend Engineer" vs "Data Scientist" @0.9).

### T4.2 — `update_index` attaches `dupe_of` (WS4)
- **Files:** modify `src/collect.py` (`update_index` + caller `run_collect`); test `tests/test_collect.py`.
- **Add constant** `DEFAULT_DEDUP_RATIO = 0.90`. Thread a `dedup_ratio: float = DEFAULT_DEDUP_RATIO` param into the index-merge path; `run_collect` passes `profile.get("dedup", {}).get("title_ratio", DEFAULT_DEDUP_RATIO)`.
- **Contract:** when merging a NEW entry, compare only against existing entries with the SAME normalized company; if `_title_similar(new.title, existing.title, ratio)` → set `new_entry["dupe_of"] = <existing job_key>` (canonical = earliest `first_seen`). Never compare across companies. `role_key`, `first_seen` preservation, prune-at-45d, and the board applied-ledger are untouched.
- **Test cases:** `same_company_title_variant_gets_dupe_of`; `same_title_different_company_no_dupe_of`; `role_key_and_first_seen_preserved`; `exact_dup_still_by_job_key` (existing behavior intact).

### T4.3 — [mechanical] Profile dedup config (WS4)
- **Files:** modify `profile.example.yml`; test `tests/test_collect.py`.
- **Add** top-level `dedup:\n  title_ratio: 0.90`.
- **Test case:** `example_profile_has_dedup_ratio`.

### T4.4 — `build_cards` skips `dupe_of` entries (WS4)
- **Files:** modify `src/prepare.py` (`build_cards`); test `tests/test_prepare.py`.
- **Contract:** an index entry carrying `dupe_of` is NOT emitted as its own card (the canonical carries the role) — so a near-duplicate never scores separately and never reaches the board. Entries without `dupe_of` behave exactly as before.
- **Test cases:** `dupe_of_entry_excluded_from_cards`; `canonical_entry_present`; `no_dupe_of_unchanged`.

### T5.1 — Parity harness `tools/parity_check.py` (DoD)
- **Files:** create `tools/parity_check.py`; test `tests/test_parity_check.py`. NOT part of shipped `src/` core.
- **Signature:** `def compare(yoke: list[dict], proto: list[dict]) -> dict` where each record has `{role_key, tier, fit}`. CLI: `python tools/parity_check.py yoke.json proto.json` reads both, prints the report.
- **Contract:** join on `role_key`; report `{tier_agreement: {("A","A"):n, ...} confusion counts, topN_overlap: Jaccard of the two {tier∈A,B} role_key sets, divergences: [{role_key, yoke_tier, proto_tier} where |tier delta| ≥ 1]}`. Deterministic; roles absent on one side reported under `unmatched`. The prototype baseline (`proto.json`) is produced out-of-band (an exported prototype-scored window / `~/PBaaS` SHORTLIST); the verify stage runs both sides on one real window.
- **Test cases:** `perfect_agreement` (identical → overlap 1.0, no divergences); `tier_divergence_listed`; `topN_overlap_jaccard` (crafted sets); `unmatched_role_reported`.

---

## Self-review
- **Spec coverage:** WS1→T1.1-T1.4; WS2→T2.1-T2.2; WS3→T3.1-T3.3; WS4→T4.1-T4.4; parity harness→T5.1; live-run = verify-stage action (no code). Schema version bump = T1.2. Every design.md requirement maps to a task.
- **Placeholder scan:** no TODO/TBD/`...`; all decision slots resolved in grill/design (enum ownership, cap=0.5, ratio=0.90, penalties, thresholds).
- **Type consistency:** `penalties: list[float]`; `ghost_flags → list[str]` (category names) consumed by T1.3's map lookup; `comp_estimated` same shape as `comp_parsed`; `dupe_of: str` (a job_key); parity records `{role_key, tier, fit}`.

# ADR-0004: Near-duplicate collapse is deterministic (stdlib), not embeddings

Date: 2026-07-08 · Status: accepted (feature: m2-input-quality)

## Context

The ROADMAP lists M2 "semantic dedup … (local embeddings)" — the steal-list recipe uses Ollama `qwen3-embedding` + cosine similarity to collapse near-duplicate postings that the exact/normalized string keys (`job_key`, `role_key`) miss: the same role posted with slightly different title wording across sites. Embeddings would, however, (1) pull a heavy non-stdlib dependency into `src/` core — tripping `test_invariants.py`'s module-level third-party import ban, constitution #5 (stdlib-lean core) and #9 (no heaviness); and (2) be non-deterministic — embedding models drift across versions, violating constitution #2 (auditable, stable) and the project's determinism north star.

## Decision

- **Near-duplicate collapse is deterministic and stdlib-only.** Match on **same company first** (exact/normalized), then **fuzzy title similarity within that company** (hard title normalization — strip seniority words, punctuation, `js`↔`javascript`; `difflib.SequenceMatcher` ratio). Cross-company postings are never auto-merged — titles like "Senior Backend Engineer" are identical across many companies, so title-alone matching would wrongly merge distinct roles. **Seniority is stripped for the fuzzy comparison but is NOT discardable:** two titles with *different explicit levels* (senior vs junior) are a hard non-match even at ratio 1.0 — a level change is a different role, and merging it would hide a wanted posting (review finding, stage 7).
- **It augments `role_key`, never replaces it.** `role_key` (`company|normalized-title`) and the board applied-ledger prune stay load-bearing and untouched; fuzzy dedup only catches near-title-variants the exact key misses.
- **Embeddings are rejected** for this milestone, not deferred-then-reconsidered: the determinism + stdlib-lean constraints are standing. If ever revisited, embeddings must live at an optional plugin edge (lazy-imported, off by default), never in core.

## Consequences

- Recall is bounded: genuinely different wording, or the same job across *different* companies, is not caught. This is an accepted limit — cross-company auto-merge is itself risky and undesirable.
- No new dependency; `test_invariants` import ban holds; the dedup logic is unit-testable on recorded fixtures with stable, deterministic output.
- The dedup threshold is profile data (a `dedup:` block), keeping the tunable as data per the ADR-0001 pattern.

## Fail-open constraint (design rule, from m2 stage-7 review)

Dedup is an **augmentation layer, and augmentation must never silently drop a real role** — it degrades by surfacing, not by hiding. Two lifecycle rules follow, both enforced in code:

- **Dangling canonical fails open.** `dupe_of` points at the earliest-`first_seen` canonical, but the 45-day prune can delete that canonical while its reposts are still live. `build_cards` therefore skips a `dupe_of` entry **only while its canonical is still in the index**; a dangling pointer falls through and the role is emitted. (Reviewer-reproduced CRITICAL: without this, a repost-churning role vanishes from the board entirely.)
- **A category penalizes once.** Where dedup/ghost signals feed the WS1 penalty seam, a red-flag category contributes its penalty at most once even if both the model and a code-detected ghost flag raise it — deduped by category, not summed per instance.

This "fail-open, never drop a real role" rule was considered for constitutional weight in the m2 close pass; the user routed it here (ADR) rather than displacing a load-bearing principle at the 10-principle cap. It generalizes WS3's flag-never-drop stance to every filter/dedup/penalty/gate layer.

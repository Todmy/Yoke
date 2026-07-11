# Krukit Flow: m3-self-improvement
Started: 2026-07-11 | Route: full
Task: M3 "Self-improvement loop" (ROADMAP.md) — `eval.py` (safety gates on a frozen golden set, zero model calls) + `tune.py` (refit scoring weights to real apply/drop labels, deterministic grid-search). Goal: score converges on the user's real decisions. No issue ref.
- [x] 1 recon — done 2026-07-11, artifact: context.md
- [x] 2 grill — done 2026-07-11, artifact: flow-state.md
- [x] 3 design — done 2026-07-11, artifact: design.md
- [x] 4 plan — done 2026-07-11, artifact: plan.md
- [x] 5 act — done 2026-07-11, artifact: plan.md
- [x] 6 verify — done 2026-07-11, artifact: verify.md
- [x] 7 review — done 2026-07-11, artifact: flow-state.md

## Grill summary (2026-07-11)
**Reframe (load-bearing):** "self-improvement" (M3) = improving the **process quality**, not just the weight numbers. `eval` must *localize which pipeline part underperforms* (comp estimation, red-flag detection, geo) — the per-dimension diagnostic is the primary value; `tune`'s weight-refit is one narrow automated lever. (User: "self-improvement процесу, не self-improvement ваг… не було достатньо добре пропрацьована зарплата, чи не було достатньо добре знайдено Red Flags".)

**Resolved (user-confirmed via grill form):**
- Q7 Scope: **eval + tune together in this one flow.** Cold-start accepted (tune ships now; strengthens as `_labels.json` fills).
- Q1 Feature-snapshot (blocker): **new flat append store `home()/_labels.json`.** At apply/drop, snapshot `{job_key, role_key, label, features{}, fit, tier, geo_certainty, gates, reason?, date}` BEFORE board prune. board stays lean; tune reads one file.
- Q2 Tuned-weights sink: **propose only** — print `before→after` diff + write `home()/_tuned_weights.json`; **never mutate `profile.yml`** (→ ADR-0005).
- Q5 eval scorecard: **per-dimension diagnostic** — per-feature agreement/error (localizes weak part) + safety-gates as dominant hard counts + aggregate fit-MAE subordinate.
- Q3 Golden set: **hybrid** (stronger model bootstraps candidates → human reviews/corrects safety dimensions → freeze) + **split storage** (sanitized fixture in `tests/fixtures/` for unit tests; real private `home()/_golden.json`, never committed). Preserves JD (m2 parity lesson).
- Q4 eval data flow: **record + score split.** `yoke eval --record` = consented model pass over golden roles → `home()/_eval_run.json`; `yoke eval` = zero-model-call scoring vs golden truth.
- Q6 tune objective: **balanced accuracy at fit ≥ 55** (Tier-B cutline, FIXED — not tuned); positives=applied, negatives=dropped; deterministic integer grid over weights summing to 100 (step 5), max BA, ties→smallest change; cold-start guard `<5 applied/dropped` → decline with message.

**Sharpened terms (CONTEXT.md):** self-improvement (M3), golden set, labels store, scorecard, tuned-weights proposal, worth-pursuing threshold.
**ADRs created:** ADR-0005 (tuner proposes weights, never mutates profile.yml).
**Deferred:** none — all 7 open questions resolved. Design-stage details (exact `_labels.json`/`_golden.json`/scorecard field schemas, `--json` contracts, exact grid step & min-label count) carried into stage 3.

## Design approval (2026-07-11)
> "+" — 2026-07-11 (design.md approved; constitution check 0 violations). Design clarification: golden-set tooling scope = schema + committed fixture + documented manual build (bootstrap deferred).

## Act summary (2026-07-11)
Inline TDD, 9 tasks (T1 labels → T9 invariants), one commit per task (`ff9083d`→`83e0ff9`). Full suite 301 OK. Live loop proven: base 60/40 @ BA 0.0 → refit 40/60 @ 1.0.

## Review summary (2026-07-11)
Independent zero-context reviewer on `git diff 6931fe9..HEAD` (src+tests, ~1049 lines). Findings: 1 Critical, 2 Important, 6 Minor.
- **Fixed (6):** C1 tune re-literalled the Tier-B cutline → now references `scoring.TIER_B` (single-home #3). I1 eval not fully fail-open (crash on list-with-non-dict / corrupt run file) → filter + guard → exit 2. I2 feature-less labels were permanent false-negatives past the cold-start guard → tune uses only usable feature vectors. M3 analysis-failed golden roles (geo="") now count as unparseable safety hits. M4 `eval --record` honours `--json`. M1 non-dict feature value no longer crashes tune. One commit per fix.
- **Declined (3, with reason):** M2 duplicate golden keys double-count safety — golden is a curated human-frozen artifact; silent dedup would mask an authoring error. M5 diagnostic denominators (red-flag recall 0.0 on a clean set) — cosmetic, doesn't touch the safety verdict. M6 `eval` builtin shadow + grid coarsen-once — cosmetic / perf-only, concrete-with-seams #4.
- Fixed 6, declined 3. Full suite **310/310** on final state. Knowledge: Valis lesson `d0456309` (proposed), builds on grill decision `e1ee284f`.
- Branch: committed directly to `main` (repo convention); no worktrees. Remote outcome: pushed to origin/main with user permission (AskUserQuestion "Пуш main у remote", 2026-07-11).

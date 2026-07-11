# Krukit Flow: m3-self-improvement
Started: 2026-07-11 | Route: full
Task: M3 "Self-improvement loop" (ROADMAP.md) — `eval.py` (safety gates on a frozen golden set, zero model calls) + `tune.py` (refit scoring weights to real apply/drop labels, deterministic grid-search). Goal: score converges on the user's real decisions. No issue ref.
- [x] 1 recon — done 2026-07-11, artifact: context.md
- [x] 2 grill — done 2026-07-11, artifact: flow-state.md
- [x] 3 design — done 2026-07-11, artifact: design.md
- [x] 4 plan — done 2026-07-11, artifact: plan.md
- [x] 5 act — done 2026-07-11, artifact: plan.md
- [x] 6 verify — done 2026-07-11, artifact: verify.md
- [ ] 7 review

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

# Verify: m2-input-quality

## Evidence (verified fresh, not from memory)

| Claim | Command | Result |
|---|---|---|
| Full suite green | `python3 -m unittest discover -s tests` | **203 passed**, 0 fail (baseline was 147; +56 for M2) |
| Schema versioned (DoD #3) | `grep ANALYSIS_SCHEMA_VERSION src/analyze.py` | `= 2` ✅ |
| DoD #1 per-WS unit tests | test_scoring / test_analyze / test_prepare / test_collect | green |
| DoD #2 model-path via mock | test_analyze mock-backend cases | green |
| DoD #4 live-run (const. #10) | `YOKE_HOME=tmp yoke run --dry-run --sources hn` | **92 roles**, real network, zero LLM, `_index.json` written |
| DoD #4 sane shortlist | `YOKE_HOME=tmp yoke run --mock --yes --sources hn` | 92 roles → **34 tier B, 58 tier C**, SHORTLIST rendered |

Live-run notes: WS4 dedup and WS3 `ghost_flags` ran on the real HN window; **zero** ghost flags fired — correct, not a defect (fresh ycombinator postings are neither stale, shortened, nor confidential). WS2 model-estimate path is not exercised by `--mock` (mock returns no estimate); it is covered by unit tests (T2.1/T2.2). A real-model live-run would confirm it but is not required (const. #10 mandates zero-LLM).

## Reality-check pass (independent, read-only)

Independent subagent verified design.md + plan.md + context.md invariants against src/ code. **Verdict: no drift.** All plan-referenced symbols resolve; all four workstreams match the approved design (WS1 formula + before-tier + independent hard-C; WS2 precedence + soft estimate + prepare-gate-sees-source-only; WS3 purity — no network import; WS4 same-company-scoped, role_key/applied-ledger untouched); all context.md invariants hold; no module-level third-party import in `src/**` (jobspy import is lazy in-function); `norm` still 8-key; no TODO/placeholder in new code; no terminology drift.

## Findings

| ID | Severity | Location | Summary | Recommendation |
|---|---|---|---|---|
| F1 | HIGH | DoD #5 / tools/parity_check.py | Parity-vs-prototype **comparison not executed** — the harness is built & proven (unit + CLI + live-window smoke), but the actual number needs the prototype's scored baseline (`proto.json`, `{role_key,tier,fit}`) from `~/PBaaS`, which exists only as a rendered `SHORTLIST.md` on a different window/rubric. A shared-window prototype adapter was scoped out-of-band by design. | User runs the comparison in their `~/PBaaS` environment (export a shared window through both scorers), OR accepts deferral in writing. |
| F2 | LOW | design.md:27,64,99 | Design cites stale `analyze.py` line numbers (design-time approximations; behavior present & correct). | Cosmetic; refresh if design is treated as living. |
| F3 | LOW | src/analyze.py (WS2) | Model-estimate comp path verified via mock/unit tests only; no real-model live confirmation (not required by DoD/const. #10). | Confirm on first real-model run post-merge. |

## Metrics

- Requirements (design DoD): 5 total — **4 fully verified** (unit + mock + full-suite + live-run), **1 partial** (parity harness delivered & proven; prototype comparison deferred — F1).
- Constitution MUST principles: 10 checked, **0 violated**. #10 live-run collector dry-run done here; #10 independent zero-context diff review = stage 7 (krukit-review, next).
- Findings: 1 HIGH (F1), 2 LOW (F2, F3). 0 CRITICAL.

## HIGH-finding resolution

**F1 — accepted as DEFERRED (user, written).** The parity comparison against the prototype was investigated live during verify:
- The prototype (`~/PBaaS/personal/job-search`) is an **agent-driven markdown workflow**, not runnable scorer code.
- Its `board_all.json` (133 roles) is a usable `{role_key, tier, fit}` baseline (tiers A:5, B:13, C:115) — `proto.json` is derivable via Yoke's own `role_key`.
- **Blocker:** the prototype **never persisted per-role JD text** (`roles_jobspy.json` carries only a `has_jd` flag; `board_all.json` has no url/jd). Scoring these roles through Yoke would run **blind on the JD** (title/company/location only), biasing Yoke's fit/tier low — divergences would reflect the missing input, not the rubric.
- Yoke's real backend (`claude_code`/haiku) was confirmed runnable headlessly; a full run = ~127 model calls (6 of 133 hard-gate to C for free).
- A fair, full-fidelity parity therefore needs a **shared window with JD preserved on both sides** — exactly the out-of-band capture the design scoped for this DoD.

User decision (AskUserQuestion, 2026-07-08):
> "Defer to a JD-preserved window" — accept F1 as deferred; run the full-fidelity parity later on a JD-preserved shared window; harness ships proven.

F2/F3 (LOW) recorded for stage 7. No CRITICAL findings. Gate satisfied: full suite green, `verify.md` complete, 0 CRITICAL, the single HIGH accepted in writing.

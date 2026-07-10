# Krukit Flow: sources-help
Started: 2026-07-10 | Route: full
Task: `yoke help` + `yoke sources` doctor report + `yoke sources <name>` setup page (per-plugin inline HELP), agent-facing --json contract
- [x] 1 recon — done 2026-07-10, artifact: context.md
- [x] 2 grill — done 2026-07-10, artifact: flow-state.md
- [x] 3 design — done 2026-07-10, artifact: design.md
- [x] 4 plan — done 2026-07-10, artifact: plan.md
- [x] 5 act — done 2026-07-10, artifact: plan.md
- [x] 6 verify — done 2026-07-10, artifact: verify.md
- [x] 7 review — done 2026-07-10, artifact: flow-state.md

## Grill summary (2026-07-10)
**Resolved (code/default):**
- Q3 roles-last-run: count newest `scans/*.json` grouped by `source` (post-gate matched count); source absent from last run → `—`, not `0`; run-mode (mock/dry-run) not distinguished (snapshot carries no marker — YAGNI).
- Q4 `yoke help` source of truth: derive from the built argparse subparsers (choices + help); sync test asserts every subparser appears in output.
- Q5 unknown source: `yoke sources bogus` → stderr `unknown source: bogus`, return 2 (matches ProfileError exit).
- Q6 COST/HELP: confirmed COST — only `brave="key"`, all others `"free"`; gate-able sources = `brave` (BRAVE_API_KEY) + `jobspy` (python-jobspy) only. HELP: full setup steps for brave+jobspy; concise HELP (what/returns/"no setup needed") for the other 10.

**Resolved (user-confirmed "+"):**
- Q1 Profile-optional: `yoke sources` does NOT require a profile — source list from `load_sources()` always; `load_profile()` attempted, on `ProfileError` degrade (enabled=`—`, recommended-grouping off). `yoke sources <name>` / `yoke help` never need a profile.
- Q2 `--json` contract (per-subcommand, not root; help stays text-only):
  - `yoke sources --json` → `{"sources":[{name, geo(raw tag: pl/intl/any/de), cost, available(bool), reason, enabled(bool|null), roles_last_run(int|null)}]}`.
  - `yoke sources <name> --json` → same object + `"help"` (HELP body).

**Terms sharpened:** none conflicting (no CONTEXT.md glossary edit). **ADRs:** none (decisions covered by constitution #2 stable/auditable output + recorded here; none met the hard-to-reverse+surprising+trade-off bar). **Deferred:** none — all 6 open questions resolved.

## Design approval (2026-07-10)
> "+" — 2026-07-10 (design.md approved; constitution check 0 violations)

## Review summary (2026-07-10)
Independent zero-context reviewer on `git diff b44ce3c..HEAD`. Findings: 0 Critical, 1 Important, 7 Minor.
- **Fixed:** Important #1 — `_last_run_counts` crashed on valid-JSON-wrong-shape scan (commit 4def12d, TDD red→green). Minor #2/#3/#4/#5/#6 — single `load_sources`, JSON geo `None→any`, raw-tag + enabled-bool contract lock tests, argparse-internals comment (commit f7fd6b4).
- **Declined (with reason):** #7 unknown-source under `--json` returns no JSON — design-specified stderr + exit 2 (grill Q5); agent checks exit code. #8 "0 roles" unrepresentable vs `—` — accepted design (grill Q3), noted in verify V2.
- Fixed 6, declined 2. Full suite 252/252 on final state. Knowledge: Valis lesson f0124ff2 (proposed).
- Branch: committed directly to `main` (repo convention); no worktrees created. Remote outcome: awaiting user.

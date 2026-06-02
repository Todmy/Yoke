# Yoke — Product Requirements

Status: Draft · Date: 2026-06-02

## Problem

Job search for engineers is a signal-to-noise problem, not a volume problem. Boards surface the same companies, listings repeat, a growing share are stale or never meant to be filled, and most "AI job search" tools answer this by helping you apply to *more* roles faster. That makes the noise worse for everyone and gets applicants flagged as spam.

The opposite move is to decide, before you spend an application, which few roles are actually worth it — and to trust that decision. But the tools that score a role against your CV are either keyword counters or opaque LLM wrappers: you can't see why a role scored well, the score drifts run to run, and nothing learns from the choices you actually make.

Yoke is the scoring and triage step done with rigor. It scores roles against your profile, keeps a small live shortlist, and wraps the scoring in an evaluation loop so the score is measurable, auditable, and improvable. You still decide; you still apply yourself.

## Target users

**Primary — the passive, employed engineer.** Has a job, keeps half an eye on the market, wants a background sensor: pull roles continuously, score them against my profile, surface only what genuinely fits. Tolerates a local setup, treats bring-your-own-LLM-key and local-first as a feature, and does not want auto-apply. Underserved — every incumbent tracker assumes urgent, high-volume applying.

**Secondary — the active seeker.** Needs to cut board noise and apply well to a few roles instead of blasting hundreds. Wants a shortlist, a way to not apply to the same role twice, and a tracker for what's in flight.

Out of audience for v1: non-technical seekers (the self-host friction is a hard filter), and anyone who wants the tool to apply on their behalf.

## Scenarios

### S1 — Passive engineer, background sensor
Sets up profile + CV + an LLM provider once, schedules a twice-daily run. The harness decides the rule-able roles itself, scores the rest, and only Tier A/B reach the board. They check it occasionally. On a strong match they open the apply step, see a gap analysis (what the role wants that their CV doesn't show, and what's worth learning), tailor, and mark it applied. Email replies update the application status on their own.

### S2 — Active seeker, cut the noise
Runs the pipeline now, gets a board split into A/B/C. Rejects the irrelevant ones fast (with a reason), applies to the A roles through the apply step, runs a gap analysis per role. The tracker guarantees an applied role never resurfaces. After enough decisions, one command refits the scoring to their taste.

### S3 — Hiring engineer / reviewer (the launch audience)
Lands on the repo, sees the evaluation harness, regression gate, and self-improving loop as the headline rather than a footnote, reads the eval doc and a sample scorecard, and concludes this is quality engineering rather than another AI wrapper.

## Principles

Yoke is a harness: a rig around a model decision that makes it verifiable, safe, and self-improving. Four layers, top to bottom:

1. **Deterministic core.** Anything reducible to a rule (geo, lane, hard blockers) is code, and decides roughly a quarter of roles without ever calling a model.
2. **Thin model surface.** The model fills a fixed feature schema, one role per call — the kind of narrow task a weak or local model does reliably.
3. **Transparent scoring.** A weighted formula turns features into the score. The model supplies features, never the number, so the score is stable and auditable.
4. **Feedback loops.** An eval harness measures the model against a reference (safety gates dominate); a tuner refits the formula weights to your real decisions; email replies close the outcome loop.

## Features (scope)

| Capability | What it does | Status |
|---|---|---|
| `collect` / `prepare` / `analyze` | Pull roles from pluggable sources, build deterministic feature cards, score + tier with a thin LLM surface | Built |
| `board` | A live, self-pruning shortlist with a local triage UI | Built |
| `track` | Application tracker: a decision log (applied / rejected + reason), a status pipeline, funnel analytics, and a dedup guarantee — an applied role never resurfaces (key = URL + company\|title) | Built; elevated to a first-class core layer |
| `gap` | Gap analysis against a role: which skills are matched vs missing, what's worth learning and how, and accept/reject resume-tuning suggestions for skills you actually have. Never a one-click rewrite | New |
| `mail-sync` | Read-only email sync that matches employer replies to your applications and updates their status | New (later phase) |
| `eval` | Scores the model against a reference on a frozen golden set; safety gates (geo false-positive, tier overreach, parse failure) dominate; a regression gate to trust a cheaper model on evidence | Built |
| `tune` | Refits the scoring weights to your apply/reject decisions (balanced accuracy at the "worth pursuing" threshold), zero model calls | Built |

Every capability is a CLI command first; the web panel is a thin client over the same logic; an Electron shell is a later wrapper over the same CLI.

## Non-goals

- **No auto-apply.** Yoke picks which roles deserve an application; you apply yourself. Mass applying creates noise, gets flagged as spam, and risks account bans.
- **No one-click resume rewrite.** Gap analysis gives suggestions you accept or reject; it never fabricates skills, metrics, or seniority, and never auto-edits your resume.
- **Not a job board, not a chat wrapper.** It scores and triages roles you can act on.

## Success criteria

- A reviewer reading the repo can state, in one sentence, what makes the scoring trustworthy (the eval harness + the tunable, auditable formula).
- The deterministic path runs end to end with no LLM provider configured.
- `eval` produces a saved scorecard; `tune` shows a before/after improvement on real labels.
- An applied role never reappears on the board.
- `gap` returns matched/missing skills and learning suggestions, and the suggestion layer never invents a skill the user doesn't have.

## Roadmap (post-v1)

Full email outcome-loop, a richer learning-path layer (resources and sequencing), and an Electron shell. The architecture (CLI-first engine, thin client, outcome-loop) already accommodates these.

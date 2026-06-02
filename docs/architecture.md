# Architecture

Yoke is a pipeline of small, mostly-deterministic stages with a deliberately thin
LLM surface in the middle, and feedback loops (eval, tune, email) wrapped around
it. It is a harness: a rig around a model decision that makes it verifiable, safe,
and self-improving.

## CLI-first

All logic lives in the CLI as the single API. Every capability is a `yoke <cmd>`
that a person can run and an agent can drive. The web panel is a **thin client**
over the same modules — it holds no business logic of its own. An Electron shell
is a future wrapper over the same CLI. A new feature is a CLI command first, a UI
second.

```
 presentation:   CLI (primary, agent-drivable)  →  thin web client  →  Electron (roadmap)
                       │   all call one core; no duplicated logic
 ──────────────────────┼───────────────────────────────────────────────────────────
 core (commands):  collect → prepare → analyze → board → track → gap
                                          │               │       │
                               eval ⇄ tune (auto-tune)   mail-sync (outcome loop)
```

## Core flow

```
 job sources ─┐
 (ATS/RSS/HN/ │   collect      deterministic. pull + normalize + dedup -> index
  dorks/      ├──────────────► (JD text + comp cached from ATS APIs)
  optional    │
  LinkedIn)   │
              ▼
          prepare        deterministic. per role -> a "feature card":
                         geo (remote/verify), lane (in/out/ambiguous), comp,
                         and a `needs_ai` list of what's still unknown
              ▼
          analyze        the ONLY required LLM step. model fills a narrow feature
                         schema (lane_match, differentiator_hits, seniority, lang,
                         employer) -> score_fit() = weighted formula -> tier
                         (model can't move the number, only the features)
              ▼
          store          SQLite: roles + decisions(labels) + tunable weights
              ▼
        board / serve     live shortlist (CLI + thin web client). you triage:
                          ✓ apply (a logged step) / ✗ reject(+reason)
              ▼
          track           application tracker: decision log, status pipeline,
                          funnel analytics, dedup guarantee (applied never resurfaces)
              │
      ┌───────┼──────────────┬───────────────────┐
      ▼       ▼              ▼                    ▼
   eval     tune          gap                 mail-sync
   model vs refit weights  skill gap +         employer replies ->
   reference to YOUR       learning path +     match to applications ->
   safety   labels         tuning suggestions  auto-update status
   gates    (no LLM)       (truthfulness-      (read-only, outcome loop)
                            guarded)
```

## Components

| Module | Role | LLM? |
|---|---|---|
| `collect.py` | pull + normalize roles from pluggable sources into the index | no |
| `prepare.py` | deterministic feature cards (geo/lane/comp from rules + cached JD) | no |
| `analyze.py` | LLM fills features → weighted `score_fit` → tier → board | yes (narrow) |
| `store.py` | SQLite store: roles, decisions, weights, applied log, application status | no |
| `board.py` | board CLI: add / apply / drop --reason / sync-folders / render | no |
| `track` | application tracker over `store`: status pipeline, funnel, dedup guarantee | no (opt. LLM in `mail-sync`) |
| `gap.py` | deterministic skill match/gap + optional truthfulness-guarded learning/tuning suggestions | optional |
| `mail.py` | read-only email sync: match replies to applications, update status | optional (status classify) |
| `serve.py` | thin web client over the modules above: board, triage, apply flow, gap | no |
| `eval.py` | reference-vs-candidate scorecard, safety gates, regression gate | yes (reference) |
| `tune.py` | grid-fit `score_fit` weights to labels (auto-tune) | no |
| `llm/` | pluggable backends: claude_code (subscription) + openai_compatible | — |

## Harness pattern catalog

The patterns that make this a harness rather than a prompt — the part worth
reusing around any model decision in production:

| Pattern | Where |
|---|---|
| Deterministic guardrails (hard gates decide ~¼ of roles) | `prepare` / `analyze` |
| Thin model surface (model fills a fixed feature schema, one role per call) | `analyze` |
| Transparent, auditable scoring (model never emits the number) | `score_fit` |
| Reference-based eval on a frozen golden set | `eval` |
| Safety gates dominate fuzzy accuracy (geo FP, tier overreach, parse fail) | `eval` |
| Regression gate (trust a cheaper model on evidence) | `eval` |
| Auto-tune / self-improvement from real labels (zero model calls) | `tune` |
| Dedup / idempotency (an applied role never resurfaces) | `track` / `collect` |
| Outcome loop (email replies → auto status update) | `mail-sync` |
| Pluggable backends + pluggable sources | `llm/` / `collect` |

## Principles

1. **CLI-first.** Logic lives in commands; the UI is a thin client. A feature is
   a command before it is a screen.
2. **Determinize what you can.** Any decision reducible to a rule, regex, or
   formula is code, not a prompt. The LLM gets a narrow extraction task with a
   fixed schema — the kind of job a weak/cheap model does reliably.
3. **The model proposes features; code computes the score.** `score_fit` is a
   transparent weighted sum. The model never emits the number, so the score is
   stable and auditable.
4. **Ground truth is the user's behavior.** Optimizing against another model is
   circular. The labels that matter are which roles you actually applied to or
   rejected. `tune.py` fits the weights to those.
5. **Safety gates over fuzzy accuracy.** The eval cares most about not telling
   you a geo-blocked role is remote, not about matching a reference within a few
   points.
6. **The human decides.** Yoke scores and triages; it never applies for you and
   never rewrites your resume. Suggestions are accept/reject and truthfulness-guarded.
7. **Pluggable everywhere.** Sources and LLM backends are drop-in; the pipeline
   doesn't change when you add either.

See [adr/](adr/) for the decisions behind these, and [PRD.md](PRD.md) for the
product framing.

# Architecture

Yoke is a pipeline of small, mostly-deterministic stages with a deliberately thin
LLM surface in the middle, and two feedback loops (eval, tune) wrapped around it.

```
 job sources ─┐
 (ATS/RSS/HN/ │   collect.py        deterministic. pull + normalize + dedup -> index
  dorks/      ├──────────────────►  (JD text + comp cached from ATS APIs)
  optional    │
  LinkedIn)   │
              ▼
          prepare.py        deterministic. per role -> a "feature card":
                            geo (remote/verify), lane (in/out/ambiguous), comp,
                            and a `needs_ai` list of what's still unknown
              ▼
          analyze.py        the ONLY LLM step. model fills a narrow feature schema
                            (lane_match, differentiator_hits, seniority, lang, employer)
                            -> score_fit() = weighted formula -> tier  (model can't
                            move the number, only the features)
              ▼
          store.py          SQLite: roles + decisions(labels) + tunable weights
              ▼
        board.py / serve.py live shortlist (CLI + local web UI). you triage:
                            ✓ applied / ✗ rejected(+reason) -> decision labels
              │
      ┌───────┴────────┐
      ▼                ▼
   eval.py          tune.py
   model vs a       refit score_fit weights to YOUR labels (balanced accuracy);
   reference,       gated behind enough both-class labels; deterministic, no LLM
   safety gates
```

## Components

| File | Role | LLM? |
|---|---|---|
| `collect.py` | pull + normalize roles from pluggable sources into the index | no |
| `prepare.py` | deterministic feature cards (geo/lane/comp from rules + cached JD) | no |
| `analyze.py` | LLM fills features → weighted `score_fit` → tier → board | yes (narrow) |
| `store.py` | SQLite store: roles, decisions, weights, applied log | no |
| `board.py` | board CLI: add / apply / drop --reason / sync-folders / render | no |
| `serve.py` | local web UI: view board, mark decisions, Improve button | no |
| `eval.py` | reference-vs-candidate scorecard, safety gates | yes (reference) |
| `tune.py` | grid-fit `score_fit` weights to labels (Improve) | no |
| `llm/` | pluggable backends: claude_code (subscription) + openai_compatible | — |

## Principles

1. **Determinize what you can.** Any decision reducible to a rule, regex, or
   formula is code, not a prompt. The LLM gets a narrow extraction task with a
   fixed schema — the kind of job a weak/cheap model can do reliably.
2. **The model proposes features; code computes the score.** `score_fit` is a
   transparent weighted sum. The model never emits the number, so the score is
   stable and auditable.
3. **Ground truth is the user's behavior.** Optimizing against another model is
   circular. The labels that matter are which roles you actually applied to or
   rejected. `tune.py` fits the weights to those.
4. **Safety gates over fuzzy accuracy.** The eval cares most about not telling
   you a geo-blocked role is remote, not about matching a reference within a few
   points.
5. **Pluggable everywhere.** Sources and LLM backends are drop-in; the pipeline
   doesn't change when you add either.

See [adr/](adr/) for the decisions behind these.

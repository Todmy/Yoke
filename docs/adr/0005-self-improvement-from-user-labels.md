# 5. Self-improvement from the user's own decisions

Date: 2026-06-01

## Status

Accepted

## Context

We want the scoring to get better over time. The tempting approach — have a strong
model (say Opus) grade a weak one and nudge the weak one toward it — is circular:
the strong model isn't ground truth for whether *you* should apply to a role. It's
just another opinion. Optimizing for it teaches the tool to imitate a model, not
to predict you.

## Decision

The ground-truth signal is the user's behavior. Every decision the user makes —
applied (a folder appears, or a ✓ in the UI), or rejected with a reason — is
written as a labeled example with the role's raw features. `tune.py` grid-searches
the `score_fit` weights to maximize balanced accuracy at the "worth pursuing"
threshold: pursued roles should score high, rejected roles low. It runs only when
there are enough labels of both classes, and makes zero model calls.

The eval harness (model vs a reference) stays separate — it guards reliability and
safety (geo false-positives, hallucinations), which the user can't easily label.

## Consequences

- The tool converges on the user's taste, not a model's.
- Cold start: with no labels, the default weights apply and Improve stays locked
  until enough decisions accumulate. The flywheel needs fuel before it turns.
- Labels require raw features to be persisted at scoring time, so `analyze.py`
  stores them on each role.
- Eval failures and tune results point at what to determinize or escalate next,
  closing the loop.

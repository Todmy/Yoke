# 9. Application tracker as a first-class layer, with a dedup guarantee

Date: 2026-06-02

## Status

Accepted

## Context

The pipeline was described as `collect → prepare → analyze → board → eval → tune`.
The application tracker existed in the store and the web UI, but it wasn't a named
layer — which hid two things that matter. First, the decision log (what you
applied to, what you rejected and why) is not bookkeeping: it's the ground-truth
signal the tuner learns from (see ADR 0005). Second, when you apply to many roles
over weeks, the hardest small problem is not re-applying to a role you already
handled — boards repost the same listing under new URLs and IDs.

## Decision

Promote the tracker to a first-class core layer, `track`, alongside the others in
the architecture, the docs, and the CLI. It owns:

- the **decision log** — applied / rejected with a reason — persisted with each
  role's raw features so the tuner can use it;
- the **status pipeline** — applied → screening → interview → offer →
  accepted / rejected / ghosted;
- **funnel analytics** — response, interview, and offer rates, available from the
  CLI, not only the web panel;
- a **dedup guarantee** — an applied (or rejected) role never resurfaces on the
  board. The dedup key is the URL plus a normalized `company|title`, so a repost
  under a new URL is still caught.

## Consequences

- The signal the tuner needs has an explicit home and is not treated as a UI
  side-effect.
- You don't waste an application on a role you already acted on, even after a
  repost.
- The dedup key is a heuristic: a genuinely different role at the same company
  with the same title is rare but possible — accepted as a deliberate trade-off in
  favor of never double-applying.
- `track` is a CLI command like the rest; the web tracker view is a thin client
  over it.

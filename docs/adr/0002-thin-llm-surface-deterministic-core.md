# 2. Thin LLM surface, deterministic core

Date: 2026-06-01

## Status

Accepted

## Context

A job-search tool can be built as one big prompt: "here's my CV and a job, score
it." That's easy to write and hard to trust. The output drifts run to run, you
can't see why a role scored well, and you're paying a frontier model to do work a
regex could do (is "remote" in the location? is this a full-stack role?).

We also want this to run cheaply and locally — on a small model, or Ollama — and
to be improvable with a measurable signal.

## Decision

Keep the LLM surface as small as possible. Each role goes through deterministic
stages first (`collect`, `prepare`) that decide everything rule-able: geo from the
location string and JD, lane from the title, comp from a regex, hard rejects. Only
the genuinely judgment-bound part reaches the model, and even then the model only
fills a fixed feature schema (lane match, differentiator hits, seniority fit,
language fit, employer winnability). A plain weighted formula (`score_fit`) turns
those features into the number.

## Consequences

- The score is stable and auditable — the model can't move the number directly,
  only the features that feed the formula.
- A weak/cheap/local model is enough for the extraction task; we verify that with
  the eval harness rather than assuming it.
- The formula weights are data, not code constants, so they can be refit to the
  user's real decisions (see ADR 0005).
- Roughly a quarter of roles are fully decided by rules and never call a model.
- Cost: when determinism is wrong (e.g. geo from a bare city), the model has to
  catch it — so `prepare` flags `needs_ai` rather than guessing.

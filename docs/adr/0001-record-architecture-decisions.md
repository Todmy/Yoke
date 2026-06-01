# 1. Record architecture decisions

Date: 2026-06-01

## Status

Accepted

## Context

Yoke will keep changing — new sources, new providers, new scoring logic. Decisions
made now (why a thin LLM surface, why SQLite, why fit-to-user-labels) will look
arbitrary in six months without a record of the reasoning, and contributors will
relitigate settled tradeoffs.

## Decision

We record architecturally significant decisions as ADRs, using the lightweight
format Michael Nygard described: one short markdown file per decision, numbered
sequentially, with Context / Decision / Consequences. They live in `docs/adr/`.

## Consequences

- A new significant decision = a new numbered file; superseded ones are marked,
  not deleted, so the history stays walkable.
- "Architecturally significant" = anything affecting structure, dependencies,
  interfaces, or the determinism/AI boundary. Small fixes don't need an ADR.

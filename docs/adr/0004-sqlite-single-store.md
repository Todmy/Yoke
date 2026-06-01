# 4. SQLite as the single store

Date: 2026-06-01

## Status

Accepted

## Context

The board (live roles), the decision labels, and the tunable weights all need a
home. Flat JSON files worked at first but a local web UI needs transactional
read-of-board + write-of-decision, and a cron job writes at the same time the UI
reads. Two stores drift; files don't lock well.

## Decision

One SQLite database (`$YOKE_HOME/yoke.db`) holds roles, decisions, applied log,
and weights, accessed through `store.py` in WAL mode. It's stdlib (`sqlite3`), so
no dependency and it runs everywhere Python does. The CLI and the web UI are thin
layers over the same store; the human-readable shortlist is a rendered export.

## Consequences

- Concurrent cron + UI access is safe (WAL).
- Queryable history (decisions over time) for the tuner and for drift tracking.
- Zero install, cross-platform.
- A binary DB isn't diff-friendly in git — but it's user data, so it's gitignored
  anyway.

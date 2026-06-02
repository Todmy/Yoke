# 6. CLI-first, with the UI as a thin client

Date: 2026-06-02

## Status

Accepted

## Context

Yoke started panel-first: `yoke` with no arguments opens a local web control panel,
and most of the workflow lives in the browser. That is good for a first-time user,
but it created a quiet risk — logic started to accrete in the web handlers
(`serve.py`) rather than in the pipeline modules. When the same capability exists
both as a command and as a POST handler, the two drift, and an agent driving the
tool from a terminal can't reach what the browser can.

We also want the tool to be drivable by an agent: "run collect, then analyze with
this model, then show me the board" should be a sequence of commands, not clicks.

## Decision

All logic lives in the CLI as the single API. Every capability is a `yoke <cmd>`
backed by a pipeline module. The web panel is a **thin client**: it presents and
collects input, then calls the same modules — it holds no business logic of its
own. An Electron shell, if it happens, wraps the same CLI.

The rule going forward: a new feature is a CLI command first and a screen second.
Where a web handler currently does work a command should own, that work moves into
the module and the handler calls it.

## Consequences

- One source of truth per capability; the browser and the terminal can't diverge.
- The tool is scriptable and agent-drivable end to end.
- `yoke help` documents the whole surface for both humans and agents.
- The panel-first default (`yoke` opens the panel) stays — it's a presentation
  choice, not a logic location.
- Some existing `serve.py` handlers need refactoring to call modules rather than
  reimplement them; this is paid down incrementally, not in one rewrite.

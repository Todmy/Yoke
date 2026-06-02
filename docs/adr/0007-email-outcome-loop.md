# 7. Email outcome loop

Date: 2026-06-02

## Status

Accepted

## Context

The tracker knows what you applied to, but not what happened next. Status updates
are manual — you have to remember to mark a role as screening, interview, or
rejected. In practice that means the funnel data rots, and the most useful signal
(did this employer respond, and how) lives in your inbox, untouched.

Auto-capturing application outcomes from email is the most-requested upgrade for
trackers, and it closes a real loop: the harness can show a true funnel and,
later, feed outcomes back into scoring.

## Decision

Add a read-only email sync (`mail.py`, `yoke mail-sync`). It connects to the
user's mailbox, reads incoming mail, matches messages to tracked applications (by
company domain, subject, sender), and updates the application status — with a note
recording the source (date, subject). A thin optional LLM classifier maps a
message to a status (replied / screening / interview / rejected) when heuristics
are ambiguous.

Constraints, non-negotiable:

- **Read-only.** Yoke never sends, never deletes, never modifies mail.
- **User authenticates.** The user supplies an app password or OAuth token; Yoke
  never asks for or enters a primary password. The token is stored locally under
  `$YOKE_HOME`, never in the repo.
- **Provider-pluggable.** Generic IMAP + app password first; Gmail OAuth optional
  later — the same drop-in shape as the LLM backends.
- **Manual status wins.** A status the user set by hand is never overwritten by a
  sync.

## Consequences

- The funnel reflects reality without manual upkeep.
- The outcome loop is a harness pattern: real results, not just applications,
  flow back into the system.
- Email is a sensitive surface — the read-only, local-token, user-authenticated,
  explicit opt-in stance is the whole safety story and must be documented as such.
- This is a later-phase feature; it does not block the launch-ready core.

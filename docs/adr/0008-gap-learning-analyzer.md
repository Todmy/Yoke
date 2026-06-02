# 8. Gap analyzer: gap and learning path, not rewrite

Date: 2026-06-02

## Status

Accepted

## Context

Scoring a role tells you whether to pursue it. It doesn't tell you *why* your CV
falls short of one you want, or what to do about it. The obvious feature is resume
tailoring — and the obvious implementation is the one most tools ship: paste CV +
JD, let a model rewrite the resume. That feature is also the single most-regretted
one in paid tools. Full LLM rewrites hallucinate skills, invent metrics, inflate
seniority, and produce generic output that recruiters detect and discount. What
people actually value is "tell me what's missing and let me edit," plus
bullet-level suggestions they accept or reject.

We looked at integrating Resume-Matcher (Apache-2.0, ~27k stars). Its real engine
is a trivial deterministic keyword matcher plus an LLM that emits truthfulness-
guarded per-bullet diffs — not the embedding engine its marketing claims. The
value worth taking is its prompt design and truthfulness rules, not its
Next.js/FastAPI/TinyDB app.

## Decision

Build a thin gap analyzer (`gap.py`, `yoke gap <role>`):

- **Deterministic core.** Tokenize the JD and the resume, extract a skill/keyword
  set, intersect → matched vs missing (missing ranked by JD frequency) → a match
  percentage. Runs with no LLM.
- **Learning layer (LLM, guarded).** For missing skills, suggest what to learn and
  how — so the user can upskill toward roles they want, not just edit words.
- **Tuning layer (LLM, guarded).** For skills the user genuinely has but didn't
  surface, propose accept/reject per-bullet edits. Adapt Resume-Matcher's
  truthfulness rules (Apache-2.0, with attribution): never add a skill, tool, or
  cert not present; never invent metrics; never upgrade seniority; never drop
  items. No auto-applied rewrite — the user copies what they accept.

ATS framing is honest: the "75% auto-rejected by ATS" figure is a debunked myth;
most ATS don't content-reject. The match percentage is a relevance signal for the
human reader and a catcher of genuinely-missing-but-true keywords, not a bot-beater.

## Consequences

- A felt user benefit on top of the (invisible) scoring rigor.
- No new heavy dependency — the matcher is stdlib; the suggestion layer reuses the
  existing LLM backend.
- The learning layer (curated resources, sequencing) starts basic and grows in a
  later phase.
- We carry one attribution obligation (Apache-2.0) for the adapted prompt text.

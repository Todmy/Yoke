# 3. Pluggable LLM backends

Date: 2026-06-01

## Status

Accepted

## Context

People will want to run Yoke against whatever they already pay for or trust: a
Claude subscription, OpenRouter, OpenAI, a local Ollama model for privacy. Hard-
coding one provider would force everyone onto it and make local-first impossible.

## Decision

The AI step talks to a single narrow interface — `complete(prompt, schema) -> dict`
— with swappable implementations under `llm/`. Two cover the field:

- `claude_code`: shells out to the `claude` CLI, using a Claude subscription
  (works headless via a long-lived token, no per-call API billing).
- `openai_compatible`: one class with presets for OpenRouter, OpenAI, Anthropic,
  Groq, Together, DeepInfra, Ollama, LM Studio, and any custom OpenAI-compatible
  endpoint. They all speak `/chat/completions`, so one backend covers them all.

Selection is by env (`YOKE_PROVIDER`, key, model, base URL). The pipeline never
knows which backend is active.

## Consequences

- Adding a provider is a preset entry, not new code.
- Local models work with no key — the privacy-first path.
- The eval harness can validate any chosen model, so downgrading to a cheaper one
  is a measured decision, not a guess.
- `claude_code` depends on an external CLI being installed and authed; that's the
  price of using a subscription instead of an API key.

"""Pluggable LLM backend for the jobsearch pipeline.

    from llm import get_backend
    be = get_backend()                 # auto-selects A or B from env
    result = be.complete(prompt, schema=SCHEMA, system=SYS)   # -> dict

Selection (predictable, no surprises from stray keys):
  • JOBSEARCH_PROVIDER set (openai|groq|together|ollama|lmstudio|openrouter|…)
                            -> OpenAICompatBackend(that provider)
  • else OPENROUTER_API_KEY set (back-compat)  -> OpenAICompatBackend('openrouter')
  • else                    -> ClaudeCodeBackend  (A: Claude subscription via claude -p)

Override model with JOBSEARCH_MODEL, base url with JOBSEARCH_BASE_URL, key with
JOBSEARCH_API_KEY (or the provider's own key env). `force` overrides selection.
"""
import os

from .base import LLMBackend, extract_json, build_prompt

__all__ = ["get_backend", "LLMBackend", "extract_json", "build_prompt"]


def get_backend(model=None, force=None):
    """Return the active backend. `force` = 'claude_code' or a provider name."""
    if force == "claude_code":
        from .claude_code import ClaudeCodeBackend
        return ClaudeCodeBackend(model=model)
    prov = force or os.environ.get("JOBSEARCH_PROVIDER")
    if not prov and os.environ.get("OPENROUTER_API_KEY"):
        prov = "openrouter"  # back-compat with the original B trigger
    if prov:
        from .openai_compatible import OpenAICompatBackend
        return OpenAICompatBackend(provider=prov, model=model)
    from .claude_code import ClaudeCodeBackend
    return ClaudeCodeBackend(model=model)

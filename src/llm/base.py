"""LLM backend interface for the jobsearch pipeline.

The AI step is ONE narrow call: `complete(prompt, schema) -> dict`. Everything
around it (prepare.py, score.py, board.py) is deterministic and backend-agnostic.
Swapping who runs the model = swapping the backend, not rewriting the pipeline.
That is what makes A (Claude Code / your subscription) -> B (standalone agent
with an OpenRouter key) a config flip.

A backend's job: take a prompt (+ optional JSON schema + system), return a parsed
Python dict. The model is instructed to emit JSON only; `extract_json` is the
shared, wrapping-tolerant parser so every backend returns clean dicts.
"""
from __future__ import annotations  # `dict | None` hints work on Python 3.9 too
import json
import re
from abc import ABC, abstractmethod

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)
_JSON_ARR_RE = re.compile(r"\[.*\]", re.DOTALL)


def extract_json(text):
    """Pull a JSON object/array out of model output, tolerant of prose/fences.

    Raises ValueError if nothing parseable is found — callers should treat that
    as a backend failure (and the eval harness counts it as a hard error)."""
    if text is None:
        raise ValueError("empty model output")
    t = text.strip()
    # strip ```json fences if present
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    for rx in (_JSON_OBJ_RE, _JSON_ARR_RE):
        m = rx.search(t)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                continue
    raise ValueError(f"no JSON found in model output: {text[:200]!r}")


def build_prompt(prompt, schema):
    """Append a strict JSON-only instruction + schema to the user prompt.

    Backends that support native structured output (OpenRouter json_object) still
    benefit from this — it pins the shape. Claude Code has no forced schema, so
    this is its only guarantee."""
    if not schema:
        return prompt + "\n\nReturn ONLY valid JSON. No prose, no code fences."
    return (
        prompt
        + "\n\nReturn ONLY valid JSON matching this schema (no prose, no code fences):\n"
        + json.dumps(schema, ensure_ascii=False, indent=2)
    )


class LLMBackend(ABC):
    name = "base"

    @abstractmethod
    def complete(self, prompt: str, schema: dict | None = None, system: str | None = None) -> dict:
        """Run the model on `prompt`, return parsed JSON dict. Raises on failure."""
        raise NotImplementedError

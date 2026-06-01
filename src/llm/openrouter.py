"""Back-compat shim — OpenRouter is now just a preset of the generic
OpenAI-compatible backend. Kept so existing imports keep working."""
from .openai_compatible import OpenAICompatBackend


class OpenRouterBackend(OpenAICompatBackend):
    def __init__(self, model=None, **_):
        super().__init__(provider="openrouter", model=model)

"""Generic OpenAI-compatible backend — one class, many providers.

OpenAI, Groq, Together, OpenRouter, Ollama (local), LM Studio, vLLM, … all speak
the same /chat/completions API, so a single backend + presets covers them all.
stdlib-only (urllib). Pick a provider via env JOBSEARCH_PROVIDER, or override
base_url/key/model directly.

Env:
  JOBSEARCH_PROVIDER   preset name (see PRESETS); default 'openrouter'
  JOBSEARCH_MODEL      model slug (else the preset default)
  JOBSEARCH_BASE_URL   override base url (for a custom/self-hosted endpoint)
  JOBSEARCH_API_KEY    override key (else the preset's key_env, e.g. OPENROUTER_API_KEY)
"""
import json
import os
import urllib.request
import urllib.error

from .base import LLMBackend, build_prompt, extract_json

# base_url, env var holding the key (None = no key needed, e.g. local), default model
PRESETS = {
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY",
                   "model": "anthropic/claude-haiku-4.5"},
    "openai": {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY",
               "model": "gpt-4o-mini"},
    "anthropic": {"base_url": "https://api.anthropic.com/v1", "key_env": "ANTHROPIC_API_KEY",
                  "model": "claude-haiku-4-5"},  # Anthropic exposes an OpenAI-compatible route
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY",
             "model": "llama-3.3-70b-versatile"},
    "together": {"base_url": "https://api.together.xyz/v1", "key_env": "TOGETHER_API_KEY",
                 "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo"},
    "deepinfra": {"base_url": "https://api.deepinfra.com/v1/openai", "key_env": "DEEPINFRA_API_KEY",
                  "model": "meta-llama/Llama-3.3-70B-Instruct"},
    "ollama": {"base_url": "http://localhost:11434/v1", "key_env": None, "model": "llama3.1"},
    "lmstudio": {"base_url": "http://localhost:1234/v1", "key_env": None, "model": "local-model"},
}


class OpenAICompatBackend(LLMBackend):
    def __init__(self, provider=None, model=None, base_url=None, api_key=None, timeout=120):
        self.provider = provider or os.environ.get("JOBSEARCH_PROVIDER") or "openrouter"
        preset = PRESETS.get(self.provider, {})
        self.name = self.provider
        self.base_url = (base_url or os.environ.get("JOBSEARCH_BASE_URL")
                         or preset.get("base_url"))
        if not self.base_url:
            raise RuntimeError(f"unknown provider '{self.provider}' and no JOBSEARCH_BASE_URL")
        key_env = preset.get("key_env")
        self.api_key = (api_key or os.environ.get("JOBSEARCH_API_KEY")
                        or (os.environ.get(key_env) if key_env else None))
        if key_env and not self.api_key:
            raise RuntimeError(f"{key_env} not set for provider '{self.provider}'")
        self.model = model or os.environ.get("JOBSEARCH_MODEL") or preset.get("model") or "gpt-4o-mini"
        self.timeout = timeout

    def complete(self, prompt, schema=None, system=None):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": build_prompt(prompt, schema)})
        body = {"model": self.model, "messages": messages,
                "response_format": {"type": "json_object"}}
        headers = {"Content-Type": "application/json",
                   "HTTP-Referer": "https://github.com/Todmy/Yoke",
                   "X-Title": "Yoke"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.base_url.rstrip("/") + "/chat/completions",
                                     data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{self.provider} HTTP {e.code}: {e.read().decode()[:300]}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"{self.provider} unreachable: {e}") from e
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"{self.provider} unexpected response: {str(data)[:300]}") from e
        return extract_json(content)

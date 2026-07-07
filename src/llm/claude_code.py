"""Backend A — Claude Code (`claude -p`), the user's subscription.

Runs the model as a subprocess in print mode. Auth is inherited from the logged-in
session (no API key). This is the default backend when no OPENROUTER_API_KEY is set.

Auth caveat (cron): macOS cron runs without the login keychain, so `claude -p` may
not reach the OAuth session there. If autonomous cron is needed, run via launchd
(user session) — or set OPENROUTER_API_KEY to switch to backend B. Interactive /
Claude-Code-driven runs work fine.
"""
import shutil
import subprocess

from .base import LLMBackend, build_prompt, extract_json

DEFAULT_MODEL = "claude-haiku-4-5"  # the "weak model" target


class ClaudeCodeBackend(LLMBackend):
    name = "claude_code"

    def __init__(self, model=None, timeout=180, retries=1):
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self.retries = retries
        self.bin = shutil.which("claude") or "claude"

    def describe(self):
        return f"claude-code:{self.model}"

    def complete(self, prompt, schema=None, system=None):
        last = None
        for _ in range(self.retries + 1):
            try:
                return self._once(prompt, schema, system)
            except (RuntimeError, ValueError) as e:  # timeout / nonzero exit / unparseable
                last = e
        raise RuntimeError(f"claude -p failed after {self.retries + 1} attempts: {last}")

    def _once(self, prompt, schema, system):
        # --strict-mcp-config with no --mcp-config = load ZERO MCP servers (the
        # global multi-10k-token MCP set is what makes a naive `claude -p` slow /
        # time out). --max-turns 1 = single completion, no agentic loop.
        cmd = [self.bin, "-p", "--model", self.model,
               "--strict-mcp-config", "--max-turns", "1"]
        if system:
            cmd += ["--append-system-prompt", system]
        full = build_prompt(prompt, schema)
        try:
            proc = subprocess.run(
                cmd, input=full, capture_output=True, text=True, timeout=self.timeout
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"claude -p timed out after {self.timeout}s") from e
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude -p exited {proc.returncode}: {proc.stderr.strip()[:300]}"
            )
        return extract_json(proc.stdout)

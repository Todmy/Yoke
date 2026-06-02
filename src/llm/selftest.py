"""Structural selftest — no live model call. Verifies backend selection + the
shared JSON extractor. Run: python3 scripts/llm/selftest.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm import get_backend, extract_json  # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    ok = ok and cond


print("── extract_json ──")
check("plain object", extract_json('{"a": 1}') == {"a": 1})
check("fenced", extract_json('```json\n{"a": 1}\n```') == {"a": 1})
check("prose-wrapped", extract_json('Here: {"a": 1, "b": "x"} done')["b"] == "x")
check("array", extract_json("[1, 2, 3]") == [1, 2, 3])
try:
    extract_json("no json here at all")
    check("garbage raises", False)
except ValueError:
    check("garbage raises", True)

print("── backend selection ──")
saved = os.environ.pop("OPENROUTER_API_KEY", None)
be = get_backend()
check("no key -> claude_code", be.name == "claude_code")
check("default model = haiku", "haiku" in be.model.lower())

os.environ["OPENROUTER_API_KEY"] = "sk-test-not-real"
be2 = get_backend()
check("OPENROUTER_API_KEY -> openrouter (back-compat)", be2.name == "openrouter")
check("force claude_code overrides env", get_backend(force="claude_code").name == "claude_code")
os.environ.pop("OPENROUTER_API_KEY", None)

print("── multi-provider selection ──")
os.environ["YOKE_PROVIDER"] = "ollama"  # local, no key needed
check("YOKE_PROVIDER=ollama -> ollama", get_backend().name == "ollama")
os.environ["YOKE_PROVIDER"] = "groq"
os.environ["GROQ_API_KEY"] = "x"
check("provider=groq + key -> groq", get_backend().name == "groq")
os.environ.pop("GROQ_API_KEY", None)
try:
    os.environ["YOKE_PROVIDER"] = "groq"
    get_backend()  # missing key
    check("missing key raises", False)
except RuntimeError:
    check("missing key raises", True)
os.environ.pop("YOKE_PROVIDER", None)
if saved is not None:
    os.environ["OPENROUTER_API_KEY"] = saved

print(f"\n{'ALL PASS' if ok else 'FAILURES'} — active backend now: {get_backend().name}")
sys.exit(0 if ok else 1)

"""T036 — project invariants: the src/ core imports ONLY stdlib (zero-dependency,
constitution VII). The single allowed third-party touch is `jobspy`, and it must
stay inside a function (lazy, venv-optional), never a module-level import.
"""
import ast
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

# stdlib modules the core legitimately uses + first-party local modules
STDLIB_OK = {
    "argparse", "ast", "datetime", "fcntl", "functools", "hashlib", "html", "http",
    "itertools", "json", "os", "pathlib", "re", "shutil", "subprocess", "sys",
    "time", "typing", "urllib", "abc", "collections", "math", "textwrap", "io",
    "sqlite3", "__future__", "csv", "string", "enum", "dataclasses",
}
FIRST_PARTY = {"paths", "store", "analyze", "tune", "scoring", "llm", "gap", "cover",
               "prepare", "collect", "board", "eval", "serve"}
# the ONE sanctioned optional dependency — must be imported lazily inside a function
OPTIONAL_LAZY = {"jobspy"}


def _module_level_imports(tree):
    """Top-level import names only (not those nested inside functions)."""
    names = []
    for node in tree.body:  # module body only — lazy imports inside defs are exempt
        if isinstance(node, ast.Import):
            names += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module.split(".")[0])
    return names


class TestZeroDependencyCore(unittest.TestCase):
    def test_no_third_party_module_level_imports(self):
        offenders = {}
        for py in SRC.rglob("*.py"):
            tree = ast.parse(py.read_text())
            for name in _module_level_imports(tree):
                if name not in STDLIB_OK and name not in FIRST_PARTY:
                    offenders.setdefault(py.name, []).append(name)
        self.assertEqual(offenders, {}, f"non-stdlib module-level imports in core: {offenders}")

    def test_jobspy_is_lazy(self):
        collect_src = (SRC / "collect.py").read_text()
        self.assertIn("from jobspy import", collect_src)            # it's used
        self.assertNotRegex(collect_src, r"(?m)^from jobspy import")  # but never at module level


if __name__ == "__main__":
    unittest.main()

"""Architectural invariants: the src/ core keeps module-level imports to
stdlib and first-party (src.* / relative) modules only, and every
src/sources plugin exposes the contract collect.py relies on.
"""
import ast
import os
import pkgutil
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="yoke-test-invariants-")
os.environ["YOKE_HOME"] = _TMP

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

SRC = Path(_REPO_ROOT) / "src"

STDLIB = set(sys.stdlib_module_names)


def _is_allowed(name):
    return name in STDLIB or name.startswith("src") or name == ""


def _module_level_imports(tree):
    """Import names from module body and class bodies — lazy imports inside
    function defs are exempt."""
    names = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                continue  # relative import — first-party by construction
            if node.module:
                names.append(node.module.split(".")[0])
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, ast.Import):
                    names += [a.name.split(".")[0] for a in sub.names]
                elif isinstance(sub, ast.ImportFrom):
                    if sub.level > 0:
                        continue
                    if sub.module:
                        names.append(sub.module.split(".")[0])
    return names


class TestNoModuleLevelThirdPartyImports(unittest.TestCase):
    def test_no_module_level_third_party_imports(self):
        offenders = {}
        for py in SRC.rglob("*.py"):
            tree = ast.parse(py.read_text())
            for name in _module_level_imports(tree):
                if not _is_allowed(name):
                    offenders.setdefault(str(py.relative_to(SRC)), []).append(name)
        self.assertEqual(offenders, {}, f"non-stdlib module-level imports: {offenders}")


class TestSourcePluginsExposeContract(unittest.TestCase):
    def test_source_plugins_expose_contract(self):
        import src.sources as sources_pkg

        for _, name, ispkg in pkgutil.iter_modules(sources_pkg.__path__):
            if ispkg:
                continue
            mod = __import__(f"src.sources.{name}", fromlist=["_"])
            with self.subTest(module=name):
                self.assertIsInstance(getattr(mod, "NAME"), str)
                tags = getattr(mod, "TAGS")
                self.assertIsInstance(tags, dict)
                self.assertIn("domain", tags)
                self.assertIn("country", tags)
                self.assertIn(getattr(mod, "COST"), {"free", "key", "paid"})
                self.assertTrue(callable(getattr(mod, "available")))
                self.assertTrue(callable(getattr(mod, "fetch")))


class TestSourcePluginsHaveHelp(unittest.TestCase):
    def test_every_plugin_resolves_help(self):
        from src import collect, yoke

        for mod in collect.load_sources():
            with self.subTest(module=mod.NAME):
                help_text = yoke._source_help(mod)
                self.assertIsInstance(help_text, str)
                self.assertTrue(help_text.strip())


def _references_llm(tree):
    """True if the module body imports src.llm at module level (backend must be
    injected into the self-improvement modules, never imported)."""
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            if "llm" in node.module.split("."):
                return True
            if node.module == "src" and any(a.name == "llm" for a in node.names):
                return True
        elif isinstance(node, ast.Import):
            if any("llm" in a.name.split(".") for a in node.names):
                return True
    return False


class TestSelfImprovementModulesNoLLM(unittest.TestCase):
    def test_eval_tune_labels_dont_import_llm(self):
        for name in ("eval.py", "tune.py", "labels.py"):
            with self.subTest(module=name):
                tree = ast.parse((SRC / name).read_text())
                self.assertFalse(_references_llm(tree),
                                 f"{name} imports src.llm at module level; inject the backend")


class TestTuneWeightSumInvariant(unittest.TestCase):
    def test_refit_after_sums_to_100(self):
        from src import tune

        pairs = ([({"a": 90, "b": 10}, "applied")] * 5
                 + [({"a": 10, "b": 90}, "dropped")] * 5)
        res = tune.refit(pairs, {"a": 50, "b": 50})
        self.assertEqual(sum(res["after"].values()), 100)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from p6_support import git, init_git
from support import REPO, adopt, engine, files_under, write

from scaffold_p5.discovery import discover, resolve_existing
from scaffold_p5.io_util import read_yaml


FORBIDDEN_PRODUCTION = (
    "Roguelike",
    "Beacon",
    "Vortex",
    "concept-roguelike",
    "src/game",
    "src/content",
    "src/ui",
    "src/__tests__",
)
SCANNER_TERMS = (
    "entropy",
    "trufflehog",
    "gitleaks",
    "detect-secret",
    "credential scan",
    "secret scan",
    "vulnerability",
    "bandit",
    "semgrep",
)
DIVE_TOKEN = re.compile(r"(?<![A-Za-z])DIVE(?![A-Za-z])")
PRODUCTION_ROOTS = (
    REPO / "src" / "scaffold_p5",
    REPO / "skills" / "understand",
)


def _fact(facts, name: str):
    if facts and hasattr(facts[0], "name"):
        return next(row for row in facts if row.name == name)
    return next(row for row in facts if row["name"] == name)


def _write_json(host: Path, rel: str, data: dict) -> None:
    write(host, rel, json.dumps(data, indent=2) + "\n")


def _nested_js_host(host: Path, *, package_name: str | None = None) -> None:
    write(host, "README.md", "Synthetic fixture for nested test discovery.\n")
    manifest: dict = {
        "scripts": {
            "test": "vitest run",
            "build": "tsc --noEmit && vite build",
            "dev": "vite",
            "preview": "vite preview",
        }
    }
    if package_name:
        manifest["name"] = package_name
    _write_json(host, "package.json", manifest)
    write(host, "src/__tests__/a.test.ts", "export {}\n")


class PilotFeedbackPF1UnderstandTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _host(self, name: str = "host") -> Path:
        host = self.root / name
        host.mkdir()
        return host

    def test_PF01_nested_js_ts_test_location_is_observed(self):
        host = self._host()
        _nested_js_host(host)
        tests = _fact(discover(host), "test_tree")
        self.assertEqual(tests.confidence, "VERIFIED")
        self.assertIsInstance(tests.value, list)
        self.assertIn("src/__tests__", tests.value)
        self.assertNotEqual(tests.confidence, "UNKNOWN")

    def test_PF02_manifest_test_command_is_declared_not_executed(self):
        host = self._host()
        _nested_js_host(host)
        commands = _fact(discover(host), "declared_commands")
        self.assertEqual(commands.confidence, "INFERRED")
        rows = commands.value
        test_row = next(row for row in rows if row.get("kind") == "test")
        self.assertEqual(test_row["invocation"], "npm test")
        self.assertEqual(test_row["availability"], "declared")
        self.assertEqual(test_row["execution"], "not_validated")
        self.assertNotEqual(test_row["execution"], "PASS")
        self.assertNotEqual(test_row["execution"], "FAIL")
        self.assertNotEqual(test_row["confidence"], "VERIFIED")

    def test_PF03_observed_tests_do_not_create_required_policy(self):
        host = self._host()
        _nested_js_host(host)
        result = adopt(host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        tests = read_yaml(host / ".scaffold/tests.yaml")
        self.assertTrue(tests["profiles"])
        for profile in tests["profiles"]:
            self.assertNotEqual(profile.get("required"), True)
            self.assertEqual(profile.get("required_authority"), "UNKNOWN")
            self.assertNotEqual(profile.get("required_authority"), "VERIFIED")
            if profile.get("id") == "observed-tests":
                self.assertEqual(profile.get("policy"), "observed")
            else:
                self.assertEqual(profile.get("policy"), "discovered_command")
                self.assertIs(profile.get("required"), False)
                self.assertTrue(profile.get("command_ref"))
        self.assertEqual(tests.get("required_authority"), "UNKNOWN")
        self.assertNotEqual(tests.get("required"), True)

    def test_PF04_b3_plan_references_testing_knowledge_when_observed(self):
        host = self._host()
        _nested_js_host(host)
        before = files_under(host)
        result = engine(host).run("bootstrap")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertEqual(result.mutations, "none")
        self.assertEqual(files_under(host), before)
        plan = result.extras["plan"]
        targets = [action["target"] for action in plan["actions"]]
        self.assertIn("docs/project/testing.md", targets)
        self.assertIn("docs/project/testing.md", plan["mutation_envelope"])

    def test_PF05_repository_path_case_is_preserved_exactly(self):
        host = self._host()
        write(host, "README.md", "Synthetic mixed-case architecture fixture.\n")
        write(host, "docs/ARCHITECTURE.md", "# Human architecture\n")
        init_git(host)
        tracked = git(host, "ls-files").splitlines()
        self.assertIn("docs/ARCHITECTURE.md", tracked)
        architecture = _fact(discover(host), "architecture")
        self.assertEqual(architecture.confidence, "VERIFIED")
        self.assertEqual(architecture.value, "docs/ARCHITECTURE.md")

    def test_PF06_case_insensitive_lookup_cannot_emit_wrong_case(self):
        host = self._host()
        write(host, "README.md", "Synthetic mixed-case architecture fixture.\n")
        write(host, "docs/ARCHITECTURE.md", "# Human architecture\n")
        init_git(host)
        actual = resolve_existing(host, "docs/architecture.md")
        self.assertEqual(actual, "docs/ARCHITECTURE.md")
        self.assertNotEqual(actual, "docs/architecture.md")
        architecture = _fact(discover(host), "architecture")
        self.assertEqual(architecture.value, "docs/ARCHITECTURE.md")
        self.assertNotEqual(architecture.value, "docs/architecture.md")

    def test_PF07_workspace_basename_does_not_override_package_identity(self):
        host = self._host("foo-pilot-copy")
        write(host, "README.md", "Synthetic fixture without a product heading.\n")
        _write_json(host, "package.json", {"name": "canonical-demo"})
        facts = discover(host)
        name = _fact(facts, "project_name")
        self.assertEqual(name.value, "canonical-demo")
        self.assertNotEqual(name.value, "foo-pilot-copy")
        self.assertEqual(_fact(facts, "workspace_basename").value, "foo-pilot-copy")
        result = adopt(host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        project = read_yaml(host / ".scaffold/project.yaml")
        self.assertEqual(project["name"], "canonical-demo")
        self.assertNotEqual(project["name"], "foo-pilot-copy")

    def test_PF08_conflicting_identity_remains_unresolved(self):
        host = self._host("foo-pilot-copy")
        write(host, "README.md", "# Canonical Demo\n")
        _write_json(host, "package.json", {"name": "canonical-demo"})
        name = _fact(discover(host), "project_name")
        self.assertEqual(name.confidence, "CONFLICTING")
        self.assertIsInstance(name.value, dict)
        self.assertEqual(name.value.get("package"), "canonical-demo")
        self.assertEqual(name.value.get("title"), "Canonical Demo")
        self.assertNotEqual(name.value, "foo-pilot-copy")
        result = adopt(host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        project = read_yaml(host / ".scaffold/project.yaml")
        self.assertNotEqual(project["name"], "foo-pilot-copy")
        self.assertIn(project["name"], {"", None})

    def test_PF09_uninspected_secret_claim_is_unknown_not_verified_false(self):
        host = self._host()
        write(host, "README.md", "Synthetic fixture without secret inspection.\n")
        secrets = _fact(discover(host), "secrets_in_shared_knowledge")
        self.assertEqual(secrets.confidence, "UNKNOWN")
        self.assertIsNot(secrets.value, False)
        self.assertNotEqual(secrets.confidence, "VERIFIED")
        self.assertFalse(secrets.critical)
        recorded = _fact(engine(host).run("bootstrap").extras["facts"], "secrets_in_shared_knowledge")
        self.assertEqual(recorded["confidence"], "UNKNOWN")
        self.assertIsNot(recorded["value"], False)

    def test_PF10_no_secret_or_security_scanner_was_introduced(self):
        discovery = (REPO / "src" / "scaffold_p5" / "discovery.py").read_text(
            encoding="utf-8"
        )
        lowered = discovery.lower()
        for term in SCANNER_TERMS:
            self.assertNotIn(term, lowered)
        src = REPO / "src" / "scaffold_p5"
        self.assertFalse((src / "secrets.py").exists())
        self.assertFalse((src / "scan.py").exists())
        self.assertFalse((src / "security.py").exists())
        self.assertNotIn("subprocess", discovery)

    def test_PF11_evidence_backed_multi_module_fixture(self):
        host = self._host()
        write(host, "README.md", "Synthetic multi-area fixture.\n")
        write(host, "src/core/index.ts", "export {}\n")
        write(host, "src/catalog/index.ts", "export {}\n")
        write(host, "src/frontend/index.ts", "export {}\n")
        write(
            host,
            "docs/architecture.md",
            "# Areas\n\n- `src/core`\n- `src/catalog`\n- `src/frontend`\n",
        )
        modules = _fact(discover(host), "modules")
        self.assertEqual(modules.confidence, "VERIFIED")
        self.assertEqual(
            modules.value,
            ["src/catalog", "src/core", "src/frontend"],
        )
        self.assertNotEqual(modules.value, ["src"])

    def test_PF12_directory_only_weak_evidence_stays_coarse(self):
        host = self._host()
        write(host, "README.md", "Synthetic weak folder fixture.\n")
        write(host, "src/alpha/index.ts", "export {}\n")
        write(host, "src/beta/index.ts", "export {}\n")
        write(host, "src/gamma/index.ts", "export {}\n")
        modules = _fact(discover(host), "modules")
        self.assertEqual(modules.value, ["src"])
        self.assertNotIn("src/alpha", modules.value)
        self.assertNotIn("src/beta", modules.value)
        self.assertNotIn("src/gamma", modules.value)

    def test_PF13_existing_agents_claude_and_rules_remain_preserved(self):
        host = self._host()
        write(host, "README.md", "Synthetic existing-client fixture.\n")
        write(host, "AGENTS.md", "Human Agent notes for this host.\n")
        write(host, "CLAUDE.md", "Human Claude notes for this host.\n")
        write(host, ".cursor/rules/keep.mdc", "Human Cursor rule text.\n")
        agents = (host / "AGENTS.md").read_bytes()
        claude = (host / "CLAUDE.md").read_bytes()
        rules = (host / ".cursor/rules/keep.mdc").read_bytes()
        before = files_under(host)
        result = engine(host).run("bootstrap")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertEqual(result.mutations, "none")
        self.assertEqual(files_under(host), before)
        self.assertEqual((host / "AGENTS.md").read_bytes(), agents)
        self.assertEqual((host / "CLAUDE.md").read_bytes(), claude)
        self.assertEqual((host / ".cursor/rules/keep.mdc").read_bytes(), rules)
        self.assertFalse((host / ".scaffold").exists())
        actions = {
            action["target"]: action for action in result.extras["plan"]["actions"]
        }
        self.assertEqual(actions["AGENTS.md"]["action_class"], "MANAGED_UPDATE")
        self.assertEqual(actions["AGENTS.md"]["ownership"], "MANAGED")
        self.assertEqual(actions["AGENTS.md"]["client_strategy"], "THIN_BRIDGE")
        self.assertNotEqual(actions["AGENTS.md"]["action_class"], "CREATE")
        self.assertEqual(actions["CLAUDE.md"]["action_class"], "PRESERVE")
        self.assertEqual(actions[".cursor/rules"]["action_class"], "PRESERVE")
        envelope = result.extras["plan"]["mutation_envelope"]
        self.assertIn("AGENTS.md", envelope)
        self.assertNotIn("CLAUDE.md", envelope)
        self.assertNotIn(".cursor/rules", envelope)
        presented = result.extras["preservation_presentation"]["areas"]
        self.assertNotIn("AGENTS.md", presented)
        self.assertIn("CLAUDE.md", presented)
        self.assertIn(".cursor/rules", presented)

    def test_PF14_missing_dependencies_do_not_fabricate_pass(self):
        host = self._host()
        _nested_js_host(host)
        self.assertFalse((host / "node_modules").exists())
        result = engine(host).run("bootstrap")
        self.assertFalse((host / "node_modules").exists())
        commands = _fact(discover(host), "declared_commands").value
        for row in rows_of(commands):
            self.assertNotEqual(row.get("execution"), "PASS")
            self.assertNotEqual(row.get("availability"), "PASS")
        dumped = json.dumps(result.extras["facts"])
        self.assertNotIn('"PASS"', dumped)

    def test_PF15_missing_dependencies_do_not_fabricate_fail(self):
        host = self._host()
        _nested_js_host(host)
        result = engine(host).run("bootstrap")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        commands = _fact(result.extras["facts"], "declared_commands")["value"]
        for row in rows_of(commands):
            self.assertEqual(row.get("execution"), "not_validated")
            self.assertNotEqual(row.get("execution"), "FAIL")
        self.assertFalse((host / "node_modules").exists())
        dumped = json.dumps(result.extras["facts"])
        self.assertNotIn('"FAIL"', dumped)

    def test_PF16_no_dive_specific_production_hardcoding(self):
        for root in PRODUCTION_ROOTS:
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in {".py", ".md", ".yaml", ".yml"}:
                    continue
                if "__pycache__" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(
                    DIVE_TOKEN.search(text),
                    f"DIVE token in production file {path}",
                )
                for token in FORBIDDEN_PRODUCTION:
                    self.assertNotIn(token, text, f"{token} in {path}")

    def test_PF17_wrong_case_architecture_pointer_regression(self):
        host = self._host()
        write(host, "README.md", "Synthetic mixed-case architecture fixture.\n")
        write(host, "docs/ARCHITECTURE.md", "# Human architecture\n")
        init_git(host)
        result = adopt(host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        pointer = (host / "docs/project/architecture.md").read_text(encoding="utf-8")
        self.assertIn("`docs/ARCHITECTURE.md`", pointer)
        self.assertNotIn("`docs/architecture.md`", pointer)
        architecture = _fact(
            read_yaml(host / ".scaffold/project.yaml")["facts"], "architecture"
        )
        self.assertEqual(architecture["value"], "docs/ARCHITECTURE.md")

    def test_PF18_worktree_copy_suffix_does_not_become_project_name(self):
        host = self._host("canonical-demo-copy")
        write(host, "README.md", "Synthetic copy-suffix identity fixture.\n")
        _write_json(host, "package.json", {"name": "canonical-demo"})
        name = _fact(discover(host), "project_name")
        self.assertEqual(name.value, "canonical-demo")
        self.assertNotEqual(name.value, "canonical-demo-copy")
        self.assertNotIn("-copy", str(name.value))


def rows_of(value) -> list:
    return list(value) if isinstance(value, list) else []


if __name__ == "__main__":
    unittest.main()

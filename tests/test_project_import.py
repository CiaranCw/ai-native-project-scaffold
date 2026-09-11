from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import REPO
from test_consumer_installation import (
    EXPECTED_PACKAGES,
    GITATTRIBUTES,
    _clean_env,
    _clone_repo,
    _empty_host,
    _git,
)
from test_first_use_enforcement import (
    FIRST_USE_RULE_REL,
    HOOK_SCRIPT_REL,
    HOOKS_JSON_REL,
    _apply_command,
    _bootstrap_plan_digest,
    _run_hook,
    _shell_before,
    _simulate_rc2,
)

from scaffold_p5.consumer_install import (
    CURSOR_ADAPTERS,
    GENERIC_CURSOR_ADAPTER,
    IMPORT_ALREADY_READY,
    IMPORT_FAILED,
    IMPORT_PROBLEM_MANAGED_DRIFT,
    IMPORT_PROBLEM_OWNERSHIP,
    IMPORT_READY,
    import_project,
    verify_consumer_install,
)
from scaffold_p5.first_use import evaluate_cursor_hook
from scaffold_p5.host_state import snapshot_host
from scaffold_p5.models import CORE_SKILLS
from scaffold_p5.packages import load_package


CONSUMER_PILOT = Path(r"F:\NewResearch\Project-City-consumer-pilot")
CANONICAL_PROJECT_CITY = Path(r"F:\NewResearch\Project-City")
REMOTE_URL = "https://example.invalid/team/consumer-host.git"
HUMAN_AGENTS = "# Human project rules\nDo not lose this paragraph.\n"
HUMAN_GITATTR = "* text=auto\n*.md text eol=lf\n"
HUMAN_HOOK = {"command": "./human-audit.sh"}
HUMAN_RULE = "---\nalwaysApply: false\n---\n# human rule\n"
UNRELATED_SKILL = "---\nname: team-notes\n---\n# notes\n"
IMPECCABLE = "# impeccable remains\n"


def _seed_existing_content(host: Path) -> None:
    (host / "AGENTS.md").write_text(HUMAN_AGENTS, encoding="utf-8")
    (host / GITATTRIBUTES).write_text(HUMAN_GITATTR, encoding="utf-8")
    cursor = host / ".cursor"
    (cursor / "hooks").mkdir(parents=True)
    (cursor / "rules").mkdir(parents=True)
    (cursor / "skills" / "team-notes").mkdir(parents=True)
    (cursor / "hooks.json").write_text(
        json.dumps({"version": 1, "hooks": {"preToolUse": [HUMAN_HOOK]}}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    (cursor / "rules" / "team.mdc").write_text(HUMAN_RULE, encoding="utf-8")
    (cursor / "skills" / "team-notes" / "SKILL.md").write_text(
        UNRELATED_SKILL, encoding="utf-8"
    )
    agents = host / ".agents" / "skills" / "impeccable"
    agents.mkdir(parents=True)
    (agents / "SKILL.md").write_text(IMPECCABLE, encoding="utf-8")
    (host / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")


def _git_project(host: Path) -> None:
    _git(host, "init")
    _git(host, "config", "core.autocrlf", "true")
    _git(host, "remote", "add", "origin", REMOTE_URL)


def _cli_import(host: Path, host_arg: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(REPO / "src" / "scaffold_consumer.py"),
            "import-project",
            "--host",
            host_arg if host_arg is not None else str(host),
        ],
        cwd=str(host if host_arg == "." else REPO),
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=180,
    )


def _managed_text(host: Path) -> str:
    chunks: list[str] = []
    for rel in (
        ".scaffold/install",
        ".cursor/skills/scaffold-understand",
        ".cursor/skills/scaffold-develop",
        ".cursor/skills/scaffold-test",
        ".cursor/skills/scaffold-submit",
        FIRST_USE_RULE_REL,
        HOOKS_JSON_REL,
        "AGENTS.md",
        GITATTRIBUTES,
    ):
        path = host / rel
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
            continue
        if not path.is_dir():
            continue
        for child in path.rglob("*"):
            if child.is_file() and child.suffix.lower() not in {".pyc"}:
                if "__pycache__" in child.parts:
                    continue
                try:
                    chunks.append(child.read_text(encoding="utf-8", errors="replace"))
                except (OSError, UnicodeError):
                    continue
    return "\n".join(chunks)


class ProjectImportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.host = _empty_host(self.tmp)
        _seed_existing_content(self.host)
        _git_project(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def test_IMP01_fresh_import(self):
        proc = _cli_import(self.host, ".")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(IMPORT_READY, proc.stdout)
        self.assertIn("NOT_ADOPTED", proc.stdout)
        self.assertIn("Understand / Develop / Test / Submit", proc.stdout)
        self.assertNotIn("plan_digest", proc.stdout)
        result = import_project(self.host, REPO)
        self.assertEqual(result["outcome"], IMPORT_ALREADY_READY, result)

    def test_IMP02_post_import_valid_not_adopted(self):
        result = import_project(self.host, REPO)
        self.assertEqual(result["outcome"], IMPORT_READY, result)
        self.assertEqual(verify_consumer_install(self.host)["status"], "VALID")
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")
        self.assertFalse((self.host / ".scaffold" / "project.yaml").exists())
        self.assertFalse((self.host / ".scaffold" / "skills.lock").exists())
        self.assertFalse((self.host / ".scaffold" / "tasks").exists())
        self.assertFalse((self.host / ".scaffold" / "sessions").exists())
        self.assertFalse((self.host / ".scaffold" / "changes").exists())

    def test_IMP03_product_surface_and_first_use_smoke(self):
        result = import_project(self.host, REPO)
        self.assertEqual(result["outcome"], IMPORT_READY, result)
        adapters = sorted(
            path.name
            for path in (self.host / ".cursor" / "skills").iterdir()
            if (path / "SKILL.md").is_file() and path.name.startswith("scaffold")
        )
        self.assertEqual(adapters, sorted(CURSOR_ADAPTERS))
        self.assertFalse((self.host / GENERIC_CURSOR_ADAPTER).exists())
        self.assertTrue((self.host / FIRST_USE_RULE_REL).is_file())
        self.assertTrue((self.host / HOOK_SCRIPT_REL).is_file())
        self.assertTrue((self.host / HOOKS_JSON_REL).is_file())
        for skill_id, (version, digest) in EXPECTED_PACKAGES.items():
            pkg = load_package(self.host / ".scaffold" / "install" / "packages" / skill_id)
            self.assertEqual(pkg.ref.skill_version, version, skill_id)
            self.assertEqual(pkg.ref.package_digest, digest, skill_id)
        self.assertEqual(tuple(CORE_SKILLS), ("understand", "develop", "test", "submit"))
        write = evaluate_cursor_hook(
            {
                "cwd": str(self.host),
                "workspace_roots": [str(self.host)],
                "hook_event_name": "preToolUse",
                "tool_name": "Write",
                "tool_input": {"path": "src/app.py", "contents": "x\n"},
            },
            self.host,
        )
        self.assertEqual(write["permission"], "deny")
        digest, planned = _bootstrap_plan_digest(self.host)
        self.assertEqual(planned["outcome"], "NEEDS_HUMAN")
        asked = _run_hook(self.host, _shell_before(self.host, _apply_command(digest)))
        self.assertEqual(asked["permission"], "ask", asked)
        self.assertNotEqual(asked["permission"], "allow")
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")

    def test_IMP04_preservation(self):
        import_project(self.host, REPO)
        agents = (self.host / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Do not lose this paragraph.", agents)
        gitattr = (self.host / GITATTRIBUTES).read_text(encoding="utf-8")
        self.assertIn("* text=auto", gitattr)
        hooks = json.loads((self.host / HOOKS_JSON_REL).read_text(encoding="utf-8"))
        self.assertTrue(
            any(item.get("command") == "./human-audit.sh" for item in hooks["hooks"]["preToolUse"])
        )
        self.assertEqual(
            (self.host / ".cursor" / "rules" / "team.mdc").read_text(encoding="utf-8"),
            HUMAN_RULE,
        )
        self.assertEqual(
            (self.host / ".cursor" / "skills" / "team-notes" / "SKILL.md").read_text(
                encoding="utf-8"
            ),
            UNRELATED_SKILL,
        )
        self.assertEqual(
            (self.host / ".agents" / "skills" / "impeccable" / "SKILL.md").read_text(
                encoding="utf-8"
            ),
            IMPECCABLE,
        )
        self.assertEqual((self.host / "dirty.txt").read_text(encoding="utf-8"), "uncommitted\n")
        self.assertEqual(_git(self.host, "remote", "get-url", "origin").stdout.strip(), REMOTE_URL)
        self.assertIn("dirty.txt", _git(self.host, "status", "--porcelain").stdout)

    def test_IMP05_idempotence_and_rc2_update(self):
        first = import_project(self.host, REPO)
        self.assertEqual(first["outcome"], IMPORT_READY, first)
        run_digest = (self.host / ".scaffold" / "install" / "run.py").read_bytes()
        second = import_project(self.host, REPO)
        self.assertEqual(second["outcome"], IMPORT_ALREADY_READY, second)
        self.assertEqual(
            (self.host / ".scaffold" / "install" / "run.py").read_bytes(),
            run_digest,
        )
        _simulate_rc2(self.host)
        self.assertEqual(verify_consumer_install(self.host)["status"], "INCOMPLETE")
        upgraded = import_project(self.host, REPO)
        self.assertEqual(upgraded["outcome"], IMPORT_READY, upgraded)
        self.assertEqual(upgraded["action"], "update")
        self.assertEqual(verify_consumer_install(self.host)["status"], "VALID")
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")
        self.assertTrue((self.host / FIRST_USE_RULE_REL).is_file())

    def test_IMP06_fail_closed(self):
        import_project(self.host, REPO)
        runner = self.host / ".scaffold" / "install" / "run.py"
        runner.write_text(runner.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
        drifted = import_project(self.host, REPO)
        self.assertEqual(drifted["outcome"], IMPORT_FAILED, drifted)
        self.assertEqual(drifted["problem"], IMPORT_PROBLEM_MANAGED_DRIFT)
        conflict_root = self.tmp / "conflict"
        conflict_root.mkdir()
        conflict_host = _empty_host(conflict_root)
        (conflict_host / ".cursor" / "skills" / "scaffold-understand").mkdir(parents=True)
        (conflict_host / ".cursor" / "skills" / "scaffold-understand" / "SKILL.md").write_text(
            "unmanaged\n", encoding="utf-8"
        )
        conflicted = import_project(conflict_host, REPO)
        self.assertEqual(conflicted["outcome"], IMPORT_FAILED, conflicted)
        self.assertEqual(conflicted["problem"], IMPORT_PROBLEM_OWNERSHIP)
        self.assertEqual(
            (conflict_host / ".cursor" / "skills" / "scaffold-understand" / "SKILL.md").read_text(
                encoding="utf-8"
            ),
            "unmanaged\n",
        )

    def test_IMP07_portability_without_distribution(self):
        result = import_project(self.host, REPO)
        self.assertEqual(result["outcome"], IMPORT_READY, result)
        _git(self.host, "add", "-A")
        _git(self.host, "commit", "-m", "imported")
        clone = _clone_repo(self.host, self.tmp / "portable", "true")
        env = _clean_env()
        env.pop("PYTHONPATH", None)
        verify = subprocess.run(
            [sys.executable, str(clone / ".scaffold" / "install" / "run.py"), "verify"],
            cwd=str(clone),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        payload = json.loads(verify.stdout)
        self.assertEqual(payload["status"], "VALID", payload)
        status = subprocess.run(
            [sys.executable, str(clone / ".scaffold" / "install" / "run.py"), "status"],
            cwd=str(clone),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertIn("NOT_ADOPTED", status.stdout)
        denied = evaluate_cursor_hook(
            {
                "cwd": str(clone),
                "workspace_roots": [str(clone)],
                "hook_event_name": "preToolUse",
                "tool_name": "Write",
                "tool_input": {"path": "x.py", "contents": "x"},
            },
            clone,
        )
        self.assertEqual(denied["permission"], "deny")
        digest, planned = _bootstrap_plan_digest(clone)
        self.assertEqual(planned["outcome"], "NEEDS_HUMAN")
        asked = evaluate_cursor_hook(_shell_before(clone, _apply_command(digest)), clone)
        self.assertEqual(asked["permission"], "ask", asked)

    def test_IMP08_location_and_remote_neutrality(self):
        host_abs = str(self.host.resolve())
        result = import_project(self.host, REPO)
        self.assertEqual(result["outcome"], IMPORT_READY, result)
        blob = _managed_text(self.host)
        self.assertNotIn(host_abs, blob)
        self.assertNotIn(host_abs.replace("\\", "/"), blob)
        self.assertNotIn(REMOTE_URL, blob)
        self.assertNotIn("Project-City", blob)
        _git(self.host, "remote", "remove", "origin")
        _git(self.host, "remote", "add", "origin", "https://example.invalid/elsewhere.git")
        self.assertEqual(verify_consumer_install(self.host)["status"], "VALID")
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")
        moved = self.tmp / "moved-host"
        self.host.rename(moved)
        self.assertEqual(verify_consumer_install(moved)["status"], "VALID")
        self.assertNotIn(str(moved.resolve()), _managed_text(moved))

    def test_IMP_forensic_and_canonical_untouched(self):
        if CANONICAL_PROJECT_CITY.is_dir():
            self.assertFalse(CANONICAL_PROJECT_CITY.joinpath(".scaffold", "install").exists())
        if CONSUMER_PILOT.is_dir():
            before = None
            agents = CONSUMER_PILOT / "AGENTS.md"
            if agents.is_file():
                before = agents.read_bytes()
            import_project(self.host, REPO)
            if before is not None:
                self.assertEqual(agents.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

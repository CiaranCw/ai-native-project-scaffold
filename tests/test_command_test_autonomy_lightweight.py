"""Focused command and Test autonomy lightweight tests.

Does not run the full suite. Proves ordinary project commands are autonomous
after Adoption, hard boundaries remain, INFERRED commands may execute as
trials, and TEST_COMPLETE cannot be manufactured from unknown coverage.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from p6_support import (
    CORE_OWNERSHIP,
    passing_profile,
    write_commands,
    write_host,
    write_project,
    write_tests,
)
from p6_support import test_engine as make_test_engine
from p7_support import write_active_host, write_task
from support import adopt, engine as understand_engine, write

from scaffold_p5.discovery import discover
from scaffold_p5.first_use import (
    FAIL_CLOSED_USER_MESSAGE,
    GATE_BOOTSTRAP,
    GATE_DEVELOP,
    GATE_FAIL_CLOSED,
    HOOK_SCRIPT_TEXT,
    SHELL_ALLOW,
    SHELL_DENY,
    SHELL_ORDINARY_ALLOW_REASON,
    classify_first_use_shell,
    evaluate_cursor_hook,
    hook_main,
)
from scaffold_p5.client_support import (
    is_client_support_path,
    is_protected_mutation_target,
    mutation_consumes_protected_target,
    path_operand_selects_protected_authority,
    reset_cache,
)
from scaffold_p5.full import _commands_data, _tests_data
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p5.refresh import refresh_host
from scaffold_p6.adapter import LocalTargetAdapter, resolve_local_process_argv
from scaffold_p6.candidate import observe_candidate
from scaffold_p7.develop_authority import resolve_current_develop_authority
from scaffold_p7.mutation import hard_mutation_boundary_reason


def _facts(host: Path) -> list[dict]:
    return [
        {
            "name": fact.name,
            "value": fact.value,
            "confidence": fact.confidence,
        }
        for fact in discover(host)
    ]


def _shell(host: Path, command: str) -> dict:
    return evaluate_cursor_hook(
        {
            "cwd": str(host),
            "workspace_roots": [str(host)],
            "hook_event_name": "beforeShellExecution",
            "command": command,
            "sandbox": False,
        },
        host,
    )


def _write_tool(host: Path, rel: str) -> dict:
    return evaluate_cursor_hook(
        {
            "cwd": str(host),
            "workspace_roots": [str(host)],
            "hook_event_name": "preToolUse",
            "tool_name": "Write",
            "tool_input": {"path": rel, "contents": "mutated\n"},
        },
        host,
    )


def _write_manager_stub(directory: Path, name: str, marker: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path = directory / f"{name}.cmd"
        path.write_text(
            f"@echo off\r\necho {marker}\r\nexit /b 0\r\n",
            encoding="ascii",
        )
    else:
        path = directory / name
        path.write_text(f"#!/bin/sh\necho {marker}\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    return path


def _js_trial(manager: str, argv: list[str]) -> tuple[dict, dict]:
    command_id = f"cmd-{manager}"
    profile = {
        "id": manager,
        "purpose": f"{manager} trial",
        "required": False,
        "auto": True,
        "adapter": "local",
        "command_ref": command_id,
        "working_directory": ".",
        "timeout_seconds": 15,
        "success": {"exit_code": 0},
        "evidence_required": ["command_result"],
        "provenance": "LOCAL_EXECUTION",
    }
    command = {
        "id": command_id,
        "argv": argv,
        "availability": "declared",
        "execution": "not_validated",
        "confidence": "INFERRED",
    }
    return profile, command


class CommandTestAutonomyLightweightTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.host = self.root / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _allow(self, command: str, *, policy: str = GATE_DEVELOP) -> str:
        kind, detail = classify_first_use_shell(
            command, self.host, policy=policy
        )
        self.assertEqual(kind, SHELL_ALLOW, (command, kind, detail))
        return detail

    def _deny(self, command: str, *, policy: str = GATE_DEVELOP) -> str:
        kind, detail = classify_first_use_shell(
            command, self.host, policy=policy
        )
        self.assertEqual(kind, SHELL_DENY, (command, kind, detail))
        return detail

    def test_ordinary_commands_are_autonomous_after_adoption(self):
        for command in (
            "node --version",
            "npm --version",
            "pnpm --version",
            "yarn --version",
            "bun --version",
            "npm run test:mvp:rules",
            "pnpm test:mvp:rules",
            "pnpm.cmd test:mvp:rules",
            "npx vitest run",
            "python -m pytest",
            "python -m compileall src",
            "git status",
            "git log -1 --oneline",
            "git diff --stat",
            "git rev-parse HEAD",
        ):
            detail = self._allow(command)
            self.assertEqual(detail, SHELL_ORDINARY_ALLOW_REASON)

    def test_command_freedom_does_not_depend_on_package_manager_name(self):
        from scaffold_p5 import first_use
        from scaffold_p5 import shell_boundary

        source = Path(first_use.__file__).read_text(encoding="utf-8")
        self.assertNotIn('"npm"', source)
        self.assertNotIn("'pnpm'", source)
        self.assertNotIn('"vitest"', source)
        self.assertNotIn("node --version", source)
        self.assertTrue(hasattr(shell_boundary, "ordinary_shell_hard_boundary"))

    def test_hard_boundaries_remain_denied(self):
        outside = self.root / "other"
        outside.mkdir()
        cases = {
            "git commit -m x": "publication",
            "git push origin HEAD": "publication",
            "git reset --hard": "destructive",
            "git rebase HEAD~1": "destructive",
            "git clean -fd": "destructive",
            "git filter-branch": "destructive",
            "python -c \"print 1\"": "inline",
            "node --eval 1": "inline",
            "nmap localhost": "attack",
            "sqlmap -u http://127.0.0.1/": "attack",
            f"node {outside / 'app.js'}": "workspace",
            "rm -rf .git": "governance",
            "rm -rf .scaffold": "governance",
            "python .scaffold/install/run.py verify && git reset --hard": "metachar",
        }
        for command, kind in cases.items():
            detail = self._deny(command)
            lowered = detail.lower()
            if kind == "metachar":
                self.assertIn("metachar", lowered)
            elif kind == "publication":
                self.assertIn("publication", lowered)
            elif kind == "destructive":
                self.assertIn("destructive", lowered)
            elif kind == "inline":
                self.assertIn("inline", lowered)
            elif kind == "attack":
                self.assertIn("attack", lowered)
            elif kind == "workspace":
                self.assertIn("outside", lowered)
            else:
                self.assertTrue(
                    "governance" in lowered or "protected" in lowered or "hard boundary" in lowered,
                    detail,
                )

    def test_not_adopted_host_still_requires_official_launcher(self):
        detail = self._deny("node --version", policy=GATE_BOOTSTRAP)
        self.assertIn("official Scaffold launcher", detail)
        self._deny("git status", policy=GATE_BOOTSTRAP)

    def test_fail_closed_does_not_claim_non_adoption(self):
        detail = self._deny("git status", policy=GATE_FAIL_CLOSED)
        self.assertIn("could not be determined", detail)
        self.assertNotIn("not yet adopted", detail)
        self.assertNotIn("NOT_ADOPTED", HOOK_SCRIPT_TEXT)
        self.assertNotIn("not yet adopted", HOOK_SCRIPT_TEXT)
        self.assertIn("could not be determined", HOOK_SCRIPT_TEXT)
        stdout = io.StringIO()
        code = hook_main(stdin=io.StringIO("not-json"), stdout=stdout)
        self.assertEqual(code, 2)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["permission"], "deny")
        self.assertNotIn("not yet adopted", payload["user_message"])
        self.assertEqual(payload["user_message"], FAIL_CLOSED_USER_MESSAGE)
        self.assertIn("could not be determined", payload["agent_message"].lower())

    def test_active_host_hook_allows_ordinary_commands_without_session(self):
        write_active_host(self.host)
        authority = resolve_current_develop_authority(self.host)
        self.assertFalse(authority.ok)
        npm = _shell(self.host, "npm run test:mvp:rules")
        self.assertEqual(npm["permission"], "allow", npm)
        self.assertIn("ordinary", npm["reason"])
        pnpm = _shell(self.host, "pnpm --version")
        self.assertEqual(pnpm["permission"], "allow", pnpm)
        git_status = _shell(self.host, "git status")
        self.assertEqual(git_status["permission"], "allow", git_status)
        write_denied = _write_tool(self.host, "src/app.py")
        self.assertEqual(write_denied["permission"], "deny", write_denied)
        self.assertNotIn("not yet adopted", write_denied.get("user_message", ""))
        self.assertNotIn("not yet adopted", write_denied.get("agent_message", ""))
        commit = _shell(self.host, "git commit -m x")
        self.assertEqual(commit["permission"], "deny", commit)
        self.assertNotIn("not yet adopted", commit.get("user_message", ""))
        self.assertNotIn("not yet adopted", commit.get("agent_message", ""))
        self.assertIn("publication", commit["reason"])

    def test_session_seal_is_not_reported_as_non_adoption(self):
        write_active_host(self.host)
        write_task(self.host)
        denied = _write_tool(self.host, "src/app.py")
        self.assertEqual(denied["permission"], "deny")
        combined = (
            denied.get("agent_message", "") + " " + denied.get("user_message", "")
        )
        self.assertNotIn("not yet adopted", combined)
        self.assertIn("Develop", denied.get("agent_message", ""))

    def test_adoption_emits_inferred_executable_argv_without_pretending_verified(self):
        write(self.host, "README.md", "Synthetic imported JS fixture.\n")
        write(
            self.host,
            "package.json",
            json.dumps(
                {
                    "name": "demo",
                    "scripts": {
                        "test": "vitest run",
                        "test:mvp:rules": "vitest run --config vitest.mvp.config.ts",
                        "build": "tsc --noEmit",
                    },
                }
            )
            + "\n",
        )
        write(self.host, "pnpm-lock.yaml", "lockfileVersion: 9.0\n")
        write(self.host, "src/__tests__/a.test.ts", "export {}\n")
        commands = _commands_data(_facts(self.host))
        rows = {row["id"]: row for row in commands["commands"]}
        test_row = rows["package-json-test"]
        mvp_row = rows["package-json-test-mvp-rules"]
        self.assertEqual(test_row["confidence"], "INFERRED")
        self.assertEqual(test_row["execution"], "not_validated")
        self.assertEqual(test_row["argv"], ["pnpm", "test"])
        self.assertEqual(mvp_row["argv"], ["pnpm", "run", "test:mvp:rules"])
        self.assertNotEqual(test_row["confidence"], "VERIFIED")
        tests = _tests_data(_facts(self.host))
        self.assertEqual(tests["required_authority"], "UNKNOWN")
        ids = [row["id"] for row in tests["profiles"]]
        self.assertIn("observed-tests", ids)
        self.assertIn("discovered-package-json-test", ids)
        by_id = {row["id"]: row for row in tests["profiles"]}
        primary = by_id["discovered-package-json-test"]
        mvp = by_id["discovered-package-json-test-mvp-rules"]
        self.assertIs(primary["required"], False)
        self.assertTrue(primary["auto"])
        self.assertFalse(mvp["auto"])
        self.assertEqual(primary["command_ref"], "package-json-test")
        self.assertEqual(mvp["command_ref"], "package-json-test-mvp-rules")
        self.assertEqual(primary["policy"], "discovered_command")
        self.assertEqual(primary["required_authority"], "UNKNOWN")

    def test_inferred_command_executes_into_candidate_bound_evidence(self):
        profile, command = passing_profile("trial", required=False)
        profile["auto"] = True
        command["confidence"] = "INFERRED"
        write_host(self.host, [(profile, command)])
        write_tests(
            self.host,
            [profile],
            required_authority="UNKNOWN",
        )
        engine = make_test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(engine.adapter_invocations, 1)
        report = result.extras["report"]
        row = report["profiles"][0]
        self.assertEqual(row["result"], "PASS")
        self.assertEqual(row["provenance"], "LOCAL_EXECUTION")
        evidence = report["evidence"][0]
        self.assertEqual(evidence["candidate_digest"], observe_candidate(self.host).digest)
        self.assertTrue(result.extras["test_pass"])
        self.assertFalse(result.extras["test_complete"])
        self.assertFalse(result.extras["completeness"]["required_set_authoritative"])
        self.assertEqual(result.extras["completeness"]["required_policy"], "UNKNOWN")

    def test_inferred_required_trial_cannot_fake_test_complete(self):
        profile, command = passing_profile("unit", required=True)
        profile["confidence"] = "INFERRED"
        command["confidence"] = "INFERRED"
        write_host(self.host, [(profile, command)])
        write_tests(
            self.host,
            [profile],
            required_authority="UNKNOWN",
        )
        engine = make_test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(engine.adapter_invocations, 1)
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "PASS")
        self.assertTrue(result.extras["test_pass"])
        self.assertFalse(result.extras["test_complete"])
        self.assertFalse(result.extras["completeness"]["required_set_authoritative"])

    def test_unexecuted_observed_profile_is_not_evidence(self):
        write(self.host, "README.md", "# observed\n")
        write_project(self.host)
        write_commands(self.host, [])
        write_tests(
            self.host,
            [
                {
                    "id": "observed-tests",
                    "paths": ["tests"],
                    "policy": "observed",
                    "required_authority": "UNKNOWN",
                }
            ],
            required_authority="UNKNOWN",
        )
        engine = make_test_engine(self.host)
        result = engine.run()
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertFalse(result.extras["test_pass"])
        self.assertFalse(result.extras["test_complete"])
        self.assertFalse(result.extras["completeness"]["required_set_authoritative"])

    def test_relative_traversal_cannot_escape_the_host(self):
        for command in (
            "rm -rf ../..",
            "rm -rf ../../..",
            r"rm -rf ..\..",
            "rm -rf ..",
            "cat ../../secret.txt",
            "git -C ../.. status",
        ):
            detail = self._deny(command)
            self.assertIn("outside", detail.lower(), (command, detail))
        self._allow("rm -rf node_modules")
        self._allow("mv src/app.py src/app2.py")

    def test_protected_governance_move_copy_rename_denied(self):
        for command in (
            "mv .scaffold ../stolen",
            r"move .scaffold ..\stolen",
            "cp evil.yaml .scaffold/project.yaml",
            r"copy evil.yaml .scaffold\project.yaml",
            "mv .git ../stolen-git",
            "rename .scaffold stolen",
            "cp foo.yaml foo/../.scaffold/project.yaml",
        ):
            detail = self._deny(command)
            lowered = detail.lower()
            self.assertTrue(
                "governance" in lowered
                or "protected" in lowered
                or "outside" in lowered,
                (command, detail),
            )
        self._allow("type .scaffold/project.yaml")
        self._allow("git status")
        self._allow("npm run test:mvp:rules")

    def test_git_path_mutation_cannot_touch_protected_governance(self):
        for command in (
            "git status",
            "git log -1 --oneline",
            "git diff --stat",
            "git show HEAD",
            "git branch -vv",
            "git blame src/app.py",
            "git mv src/app.py src/app2.py",
            "git rm src/obsolete.py",
        ):
            self._allow(command)
        # R7 P3-F8: discard-shaped Git operations on business paths now
        # destroy uncommitted in-scope work and are blocked automatically
        # (with a non-destructive alternative) instead of being allowed.
        for command in (
            "git checkout HEAD -- src/app.py",
            "git restore src/app.py",
        ):
            detail = self._deny(command)
            self.assertIn("irreversibly discarded", detail)
        for command in (
            "git mv .scaffold scaffold-off",
            "git mv .scaffold/tests.yaml .scaffold/tests.bak",
            "git mv .git stolen-git",
            "git rm -rf .scaffold",
            "git rm --cached .scaffold/tests.yaml",
            "git rm -rf .git",
            "git checkout HEAD -- .scaffold",
            "git checkout -- .scaffold/project.yaml",
            r"git checkout HEAD -- .scaffold\tests.yaml",
            "git restore .scaffold",
            "git restore --source=HEAD -- .scaffold/tests.yaml",
            "git checkout HEAD -- foo/../.scaffold/tests.yaml",
            "git mv foo/../.git stolen-git",
        ):
            detail = self._deny(command)
            lowered = detail.lower()
            self.assertTrue(
                "governance" in lowered
                or "protected" in lowered
                or "outside" in lowered,
                (command, detail),
            )
        self._deny("git commit -m x")
        self._deny("git push origin HEAD")
        self._deny("git reset --hard")
        self._deny("git rebase HEAD~1")

    def _write_managed_enforcement_host(self) -> None:
        write_project(
            self.host,
            clients=[
                {
                    "path": ".cursor/",
                    "strategy": "CLIENT_SUPPORT",
                    "authoritative": False,
                },
                {
                    "path": ".cursor/rules",
                    "strategy": "PRESERVE",
                    "authoritative": False,
                    "ownership": "HUMAN_OWNED",
                },
                {
                    "path": ".cursor/skills/scaffold-develop/SKILL.md",
                    "strategy": "THIN_BRIDGE",
                    "authoritative": False,
                    "ownership": "MANAGED",
                },
            ],
            ownership={
                **CORE_OWNERSHIP,
                "AGENTS.md": "MANAGED",
                ".cursor/rules": "HUMAN_OWNED",
                ".cursor/skills/scaffold-develop/SKILL.md": "MANAGED",
            },
        )
        install_dir = self.host / ".scaffold/install"
        install_dir.mkdir(parents=True, exist_ok=True)
        write_yaml_atomic(
            install_dir / "install.yaml",
            {
                "schema_version": "1",
                "files": [
                    {
                        "path": ".cursor/rules/scaffold-first-use.mdc",
                        "ownership": "MANAGED",
                        "digest": "a" * 64,
                    },
                    {
                        "path": ".cursor/skills/scaffold-develop/SKILL.md",
                        "ownership": "MANAGED",
                        "digest": "b" * 64,
                    },
                ],
                "json_fragments": [
                    {
                        "path": ".cursor/hooks.json",
                        "ownership": "MANAGED_JSON_FRAGMENT",
                        "fragment_id": "scaffold-first-use",
                        "digest": "c" * 64,
                    }
                ],
            },
        )
        reset_cache()

    def test_managed_client_enforcement_is_protected_without_locking_cursor(self):
        self._write_managed_enforcement_host()
        self.assertTrue(
            is_protected_mutation_target(self.host, ".cursor/hooks.json")
        )
        self.assertTrue(
            is_protected_mutation_target(
                self.host, ".cursor/rules/scaffold-first-use.mdc"
            )
        )
        self.assertTrue(
            is_protected_mutation_target(
                self.host, ".cursor/skills/scaffold-develop/SKILL.md"
            )
        )
        self.assertTrue(is_protected_mutation_target(self.host, "AGENTS.md"))
        self.assertTrue(is_protected_mutation_target(self.host, ".gitattributes"))
        self.assertTrue(is_protected_mutation_target(self.host, ".scaffold"))
        self.assertFalse(
            is_protected_mutation_target(self.host, ".cursor/user-settings.json")
        )
        self.assertFalse(
            is_protected_mutation_target(self.host, ".cursor/rules/my-rule.mdc")
        )
        self.assertFalse(is_protected_mutation_target(self.host, ".cursor"))
        self.assertTrue(mutation_consumes_protected_target(self.host, ".cursor"))
        self.assertTrue(
            mutation_consumes_protected_target(self.host, ".cursor/skills")
        )
        self.assertFalse(
            mutation_consumes_protected_target(
                self.host, ".cursor/user-settings.json"
            )
        )
        self.assertFalse(mutation_consumes_protected_target(self.host, "tmp"))
        self.assertTrue(
            is_client_support_path(self.host, ".cursor/user-settings.json")
        )
        self.assertIsNotNone(
            hard_mutation_boundary_reason(self.host, ".cursor/hooks.json")
        )
        self.assertIsNotNone(hard_mutation_boundary_reason(self.host, "AGENTS.md"))
        self.assertIsNotNone(
            hard_mutation_boundary_reason(self.host, ".gitattributes")
        )
        self.assertIsNone(hard_mutation_boundary_reason(self.host, "src/app.py"))
        for command in (
            "rm .cursor/hooks.json",
            "rm .cursor/rules/scaffold-first-use.mdc",
            "rm -rf .cursor/skills/scaffold-develop",
            "mv .cursor/hooks.json hooks.bak",
            "cp evil.json .cursor/hooks.json",
            "git rm .cursor/hooks.json",
            "git mv .cursor/hooks.json hooks.bak",
            "git checkout HEAD -- .cursor/hooks.json",
            "git restore .cursor/rules/scaffold-first-use.mdc",
            "rm foo/../.cursor/hooks.json",
            "rm AGENTS.md",
            "rm .gitattributes",
            "git rm AGENTS.md",
            "git checkout HEAD -- .gitattributes",
            "rm -rf .cursor",
            "rm -rf .cursor/skills",
            "rm -rf .cursor/rules",
            "mv .cursor stolen-cursor",
            "git rm -rf .cursor",
            "git mv .cursor stolen-cursor",
        ):
            detail = self._deny(command)
            lowered = detail.lower()
            self.assertTrue(
                "governance" in lowered
                or "protected" in lowered
                or "outside" in lowered,
                (command, detail),
            )
        for command in (
            "type .cursor/hooks.json",
            "git diff .cursor/hooks.json",
            "git status",
            "rm .cursor/user-settings.json",
            "rm .cursor/rules/my-rule.mdc",
            "mv .cursor/user-settings.json .cursor/user-settings.bak",
            "mv src/app.py src/app2.py",
            "rm -rf tmp",
        ):
            self._allow(command)

    def test_direct_path_patterns_cannot_select_protected_authority(self):
        self._write_managed_enforcement_host()
        self.assertTrue(
            path_operand_selects_protected_authority(
                self.host, ".cursor/*.json"
            )
        )
        self.assertTrue(
            path_operand_selects_protected_authority(
                self.host, ".cursor/skills/*/SKILL.md"
            )
        )
        self.assertTrue(
            path_operand_selects_protected_authority(self.host, "AGENTS.*")
        )
        self.assertFalse(
            path_operand_selects_protected_authority(
                self.host, ".cursor/*.tmp"
            )
        )
        self.assertFalse(
            path_operand_selects_protected_authority(self.host, "docs/*.md")
        )
        self.assertFalse(
            path_operand_selects_protected_authority(
                self.host, ".cursor/rules/my-*.mdc"
            )
        )
        for command in (
            "rm .cursor/*.json",
            "rm .cursor/hooks.*",
            "rm .cursor/rules/*.mdc",
            "rm .cursor/rules/scaffold-*",
            "rm .cursor/skills/*/SKILL.md",
            "rm -rf .cursor/skills/*",
            "rm AGENTS.*",
            r"rm .cursor\*.json",
            "git rm .cursor/*.json",
            "git checkout HEAD -- .cursor/rules/*.mdc",
            "rm -rf .cursor",
        ):
            detail = self._deny(command)
            lowered = detail.lower()
            self.assertTrue(
                "governance" in lowered
                or "protected" in lowered
                or "outside" in lowered,
                (command, detail),
            )
        for command in (
            "rm .cursor/*.tmp",
            "rm docs/*.md",
            "rm .cursor/rules/my-*.mdc",
            "rm .cursor/user-settings.json",
            "mv src/app.py src/app2.py",
            "type .cursor/hooks.json",
            "git diff .cursor/hooks.json",
        ):
            self._allow(command)

    def test_windows_npm_and_pnpm_style_test_engine_execution(self):
        bin_dir = self.root / "shim"
        _write_manager_stub(bin_dir, "npm", "NPM_STUB_PASS")
        _write_manager_stub(bin_dir, "pnpm", "PNPM_STUB_PASS")
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(bin_dir) + os.pathsep + old_path
        try:
            npm_resolved = resolve_local_process_argv(["npm", "run", "test:mvp:rules"])
            pnpm_resolved = resolve_local_process_argv(["pnpm", "test"])
            self.assertTrue(npm_resolved)
            self.assertTrue(pnpm_resolved)
            self.assertNotEqual(npm_resolved[0], "npm")
            self.assertNotEqual(pnpm_resolved[0], "pnpm")
            if os.name == "nt":
                self.assertTrue(npm_resolved[0].lower().endswith(".cmd"))
                self.assertTrue(pnpm_resolved[0].lower().endswith(".cmd"))
            npm_obs = LocalTargetAdapter().execute(
                command=["npm", "run", "test:mvp:rules"],
                working_directory=self.host,
                timeout_seconds=15,
            )
            pnpm_obs = LocalTargetAdapter().execute(
                command=["pnpm", "test"],
                working_directory=self.host,
                timeout_seconds=15,
            )
            self.assertEqual(npm_obs.termination, "exited", npm_obs.error)
            self.assertEqual(npm_obs.exit_code, 0, npm_obs.stderr)
            self.assertIn("NPM_STUB_PASS", npm_obs.stdout)
            self.assertEqual(pnpm_obs.exit_code, 0, pnpm_obs.stderr)
            self.assertIn("PNPM_STUB_PASS", pnpm_obs.stdout)

            npm_profile, npm_command = _js_trial(
                "npm", ["npm", "run", "test:mvp:rules"]
            )
            write_host(self.host, [(npm_profile, npm_command)])
            write_tests(self.host, [npm_profile], required_authority="UNKNOWN")
            engine = make_test_engine(self.host)
            result = engine.run()
            self.assertEqual(result.outcome, "COMPLETED", result.blockers)
            self.assertEqual(engine.adapter_invocations, 1)
            self.assertEqual(result.extras["report"]["profiles"][0]["result"], "PASS")
            evidence = result.extras["report"]["evidence"][0]
            self.assertEqual(
                evidence["candidate_digest"], observe_candidate(self.host).digest
            )
            self.assertTrue(result.extras["test_pass"])
            self.assertFalse(result.extras["test_complete"])
            self.assertEqual(result.extras["completeness"]["required_policy"], "UNKNOWN")
        finally:
            os.environ["PATH"] = old_path

    def test_understand_refresh_rewrites_old_adopted_tooling_without_verified(self):
        write(self.host, "README.md", "Synthetic older adopted JS host.\n")
        write(
            self.host,
            "package.json",
            json.dumps(
                {
                    "name": "demo",
                    "scripts": {"test": "vitest run", "test:mvp:rules": "vitest run"},
                }
            )
            + "\n",
        )
        write(self.host, "src/__tests__/a.test.ts", "export {}\n")
        write(self.host, "src/app.ts", "export const value = 1;\n")
        adopted = adopt(self.host)
        self.assertEqual(adopted.outcome, "COMPLETED", adopted.blockers)
        task_rel = ".scaffold/tasks/task-preserved.yaml"
        write(self.host, task_rel, "record_id: task-preserved\nstatus: IN_PROGRESS\n")
        app_before = (self.host / "src/app.ts").read_bytes()
        task_before = (self.host / task_rel).read_bytes()
        write_yaml_atomic(
            self.host / ".scaffold/commands.yaml",
            {
                "schema_version": "1",
                "commands": [
                    {
                        "id": "package-json-test",
                        "invocation": "npm test",
                        "source": "package.json#scripts.test",
                        "availability": "declared",
                        "execution": "not_validated",
                        "kind": "test",
                        "confidence": "INFERRED",
                    }
                ],
            },
        )
        write_yaml_atomic(
            self.host / ".scaffold/tests.yaml",
            {
                "schema_version": "1",
                "applicable": True,
                "applicability": "APPLICABLE",
                "confidence": "VERIFIED",
                "required_authority": "UNKNOWN",
                "profiles": [
                    {
                        "id": "observed-tests",
                        "paths": ["src/__tests__"],
                        "policy": "observed",
                        "required_authority": "UNKNOWN",
                    }
                ],
            },
        )
        refreshed = understand_engine(self.host).run("refresh")
        self.assertEqual(refreshed.outcome, "COMPLETED", refreshed.blockers)
        commands = read_yaml(self.host / ".scaffold/commands.yaml")
        tests = read_yaml(self.host / ".scaffold/tests.yaml")
        rows = {row["id"]: row for row in commands["commands"]}
        test_row = rows["package-json-test"]
        self.assertEqual(test_row["confidence"], "INFERRED")
        self.assertEqual(test_row["execution"], "not_validated")
        self.assertEqual(test_row["argv"], ["npm", "test"])
        self.assertNotEqual(test_row["confidence"], "VERIFIED")
        self.assertEqual(tests["required_authority"], "UNKNOWN")
        ids = [row["id"] for row in tests["profiles"]]
        self.assertIn("observed-tests", ids)
        self.assertIn("discovered-package-json-test", ids)
        discovered = next(
            row for row in tests["profiles"] if row["id"] == "discovered-package-json-test"
        )
        self.assertIs(discovered.get("required"), False)
        self.assertEqual(discovered.get("command_ref"), "package-json-test")
        self.assertEqual((self.host / "src/app.ts").read_bytes(), app_before)
        self.assertEqual((self.host / task_rel).read_bytes(), task_before)

    def test_old_active_host_refresh_then_windows_test_engine(self):
        write_active_host(self.host)
        write(self.host, "src/app.ts", "export const value = 1;\n")
        write(
            self.host,
            "package.json",
            json.dumps({"name": "demo", "scripts": {"test": "vitest run"}}) + "\n",
        )
        write(self.host, "src/__tests__/a.test.ts", "export {}\n")
        write(self.host, ".scaffold/tasks/task-preserved.yaml", "status: IN_PROGRESS\n")
        project_path = self.host / ".scaffold/project.yaml"
        project = read_yaml(project_path)
        ownership = dict(project.get("ownership") or {})
        ownership["AGENTS.md"] = "GENERATED"
        project["ownership"] = ownership
        write_yaml_atomic(project_path, project)
        write_yaml_atomic(
            self.host / ".scaffold/commands.yaml",
            {
                "schema_version": "1",
                "commands": [
                    {
                        "id": "package-json-test",
                        "invocation": "npm test",
                        "kind": "test",
                        "confidence": "INFERRED",
                        "execution": "not_validated",
                    }
                ],
            },
        )
        write_yaml_atomic(
            self.host / ".scaffold/tests.yaml",
            {
                "schema_version": "1",
                "applicability": "APPLICABLE",
                "applicable": True,
                "confidence": "VERIFIED",
                "required_authority": "UNKNOWN",
                "profiles": [
                    {
                        "id": "observed-tests",
                        "paths": ["src/__tests__"],
                        "policy": "observed",
                        "required_authority": "UNKNOWN",
                    }
                ],
            },
        )
        app_before = (self.host / "src/app.ts").read_bytes()
        task_before = (self.host / ".scaffold/tasks/task-preserved.yaml").read_bytes()
        result = refresh_host(self.host)
        self.assertTrue(result.get("ok"), result)
        commands = read_yaml(self.host / ".scaffold/commands.yaml")
        test_row = next(
            row for row in commands["commands"] if row["id"] == "package-json-test"
        )
        self.assertEqual(test_row["confidence"], "INFERRED")
        self.assertEqual(test_row["argv"], ["npm", "test"])
        self.assertEqual((self.host / "src/app.ts").read_bytes(), app_before)
        self.assertEqual(
            (self.host / ".scaffold/tasks/task-preserved.yaml").read_bytes(),
            task_before,
        )
        bin_dir = self.root / "shim"
        _write_manager_stub(bin_dir, "npm", "NPM_STUB_PASS")
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(bin_dir) + os.pathsep + old_path
        try:
            engine = make_test_engine(self.host)
            ran = engine.run()
            self.assertEqual(ran.outcome, "COMPLETED", ran.blockers)
            self.assertGreaterEqual(engine.adapter_invocations, 1)
            executed = [
                row
                for row in ran.extras["report"]["profiles"]
                if row["result"] != "NOT_RUN"
            ]
            self.assertTrue(executed)
            self.assertEqual(executed[0]["result"], "PASS")
            self.assertEqual(
                ran.extras["report"]["evidence"][0]["candidate_digest"],
                observe_candidate(self.host).digest,
            )
            self.assertFalse(ran.extras["test_complete"])
            self.assertEqual(ran.extras["completeness"]["required_policy"], "UNKNOWN")
            self.assertFalse(ran.extras["completeness"]["required_set_authoritative"])
        finally:
            os.environ["PATH"] = old_path


if __name__ == "__main__":
    unittest.main()

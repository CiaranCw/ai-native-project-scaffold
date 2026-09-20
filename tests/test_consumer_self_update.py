from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from p6_support import CORE_OWNERSHIP, git
from p7_support import (
    TASK_A,
    develop_engine,
    ensure_noscms_accepted_anchor,
    write_active_host,
    write_task,
)
from support import REPO, write
from test_compatibility_lock_update_public import (
    _compact_json,
    _evaluation_result,
    _launcher_json,
    _new_expected_payload,
    _prepare_adopted_consumer,
    _shell_payload,
    _write_live_lock,
)
from test_consumer_installation import (
    EXPECTED_PACKAGES,
    _copy_live_dist,
    _empty_host,
    _install,
    _run_installed,
)
from test_pc_consumer_003 import _install_marker, _knowledge

from scaffold_p5.consumer_install import (
    VERIFY_VALID,
    _run_installed_consumer,
    current_manifest,
    installed_main,
    verify_consumer_install,
)
from scaffold_p5.first_use import (
    FAIL_CLOSED_RUN_ARGV,
    GATE_BOOTSTRAP,
    GATE_DEVELOP,
    GATE_FAIL_CLOSED,
    GATE_RECOVERY,
    SHELL_ALLOW,
    SHELL_DENY,
    classify_first_use_shell,
    evaluate_cursor_hook,
)
from scaffold_p5.io_util import read_yaml, sha256_bytes
from scaffold_p5.packages import load_package
from scaffold_p5.schemas import CURRENT_PROJECT_CONTRACT_GENERATION
from scaffold_p7.develop_authority import load_execution_pointer
from scaffold_p7.models import SESSIONS_DIR
from scaffold_p7.session import (
    MUTATION_OBSERVED,
    persist_files_yaml,
    persist_mutation_attempts,
    snapshot_open_inventory,
)


def _git_commit(root: Path, message: str) -> str:
    git(root, "init")
    git(root, "add", "-A")
    git(
        root,
        "-c",
        "user.name=Scaffold Test",
        "-c",
        "user.email=scaffold-test@example.invalid",
        "commit",
        "-m",
        message,
    )
    return git(root, "rev-parse", "HEAD")


def _replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError(f"marker site missing in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def _update_command(distribution: Path) -> str:
    dist = str(distribution.resolve()).replace("\\", "/")
    return "python .scaffold/install/run.py consumer update --distribution " + dist


class ConsumerSelfUpdateSurfaceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = _empty_host(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_fresh_install_exposes_help_and_self_update_surface(self):
        plan, result = _install(self.host)
        self.assertTrue(getattr(plan, "allowed", True), getattr(plan, "blockers", result))
        self.assertEqual(result.get("outcome"), "COMPLETED", result)
        runner = self.host / ".scaffold" / "install" / "run.py"
        self.assertTrue(runner.is_file())
        help_proc = _run_installed(self.host, "--help")
        self.assertEqual(help_proc.returncode, 0, help_proc.stderr)
        text = (help_proc.stdout or "") + (help_proc.stderr or "")
        self.assertIn("consumer", text)
        self.assertIn("update", text)
        self.assertIn("--distribution", text)
        self.assertIn("current host is implicit", text.lower())
        missing = _launcher_json(self.host, "consumer", "update")[1]
        self.assertEqual(missing.get("outcome"), "BLOCKED", missing)
        self.assertTrue(
            any("distribution" in str(item) for item in missing.get("blockers") or [])
        )

    def test_rejects_invalid_sources_and_foreign_host(self):
        _install(self.host)
        tmp = Path(self._tmp.name)
        empty = tmp / "not-a-dist"
        empty.mkdir()
        script = tmp / "payload.py"
        script.write_text("print('no')\n", encoding="utf-8")
        missing = tmp / "missing-dist"
        other = tmp / "other-host"
        other.mkdir()
        invalid = _launcher_json(
            self.host, "consumer", "update", "--distribution", str(empty)
        )[1]
        file_src = _launcher_json(
            self.host, "consumer", "update", "--distribution", str(script)
        )[1]
        absent = _launcher_json(
            self.host, "consumer", "update", "--distribution", str(missing)
        )[1]
        foreign = _launcher_json(
            self.host,
            "consumer",
            "update",
            "--host",
            str(other),
            "--distribution",
            str(REPO),
        )[1]
        same_host = _launcher_json(
            self.host,
            "consumer",
            "update",
            "--host",
            str(self.host),
            "--distribution",
            str(REPO),
        )[1]
        malformed = _launcher_json(
            self.host, "consumer", "update", "--distribution", ""
        )[1]
        unknown = _launcher_json(
            self.host, "consumer", "update", "--distribution", str(REPO), "--rewrite"
        )[1]
        action = _launcher_json(self.host, "consumer", "install")[1]
        self.assertEqual(invalid.get("outcome"), "BLOCKED", invalid)
        self.assertEqual(file_src.get("outcome"), "BLOCKED", file_src)
        self.assertEqual(absent.get("outcome"), "BLOCKED", absent)
        self.assertEqual(foreign.get("outcome"), "BLOCKED", foreign)
        self.assertEqual(same_host.get("outcome"), "BLOCKED", same_host)
        self.assertEqual(malformed.get("outcome"), "BLOCKED", malformed)
        self.assertEqual(unknown.get("outcome"), "BLOCKED", unknown)
        self.assertEqual(action.get("outcome"), "BLOCKED", action)
        self.assertTrue(
            any("implicit" in str(item) for item in foreign.get("blockers") or []),
            foreign,
        )
        self.assertTrue(
            any("implicit" in str(item) for item in same_host.get("blockers") or []),
            same_host,
        )
        self.assertFalse(any(empty.rglob("*")), "update must not write the source")
        self.assertEqual(script.read_text(encoding="utf-8"), "print('no')\n")


class ConsumerSelfUpdateFirstUseTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write(self.host, "src/app.py", "value = 0\n")
        write_task(self.host, TASK_A, status="IN_PROGRESS")
        _install_marker(self.host)
        _knowledge(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def _allow_update(self, command: str, *, policy: str) -> None:
        kind, detail = classify_first_use_shell(
            command, self.host, adopted=True, policy=policy
        )
        self.assertEqual(kind, SHELL_ALLOW, (command, policy, detail))

    def test_exact_update_allowed_across_gates(self):
        command = _update_command(REPO)
        self._allow_update(command, policy=GATE_BOOTSTRAP)
        self._allow_update(command, policy=GATE_DEVELOP)
        self._allow_update(command, policy=GATE_RECOVERY)
        self._allow_update(command, policy=GATE_FAIL_CLOSED)
        self.assertIn(("consumer", "update"), FAIL_CLOSED_RUN_ARGV)

    def test_active_unknown_and_open_session_allow_update_hook(self):
        adopted_root = Path(self._tmp.name) / "adopted"
        adopted_root.mkdir()
        adopted = _empty_host(adopted_root)
        _prepare_adopted_consumer(adopted)
        _write_live_lock(adopted, develop_digest="b" * 64)
        hook = evaluate_cursor_hook(
            _shell_payload(adopted, _update_command(REPO)),
            adopted,
        )
        self.assertEqual(hook.get("permission"), "allow", hook)

    def test_arbitrary_python_and_chaining_remain_denied(self):
        dist = str(REPO).replace("\\", "/")
        cases = [
            "python -c print(1)",
            "python payload.py",
            "python .scaffold/install/run.py consumer update --distribution "
            + dist
            + " && echo pwn",
            "python .scaffold/install/run.py consumer install --distribution " + dist,
            "python .scaffold/install/run.py consumer update --rewrite",
            "python src/scaffold_consumer.py update --host "
            + str(self.host).replace("\\", "/"),
            "python .scaffold/install/run.py consumer update --host "
            + str(self.host).replace("\\", "/")
            + " --distribution "
            + dist,
            "echo hello",
        ]
        for command in cases:
            kind, detail = classify_first_use_shell(
                command, self.host, adopted=True
            )
            self.assertEqual(kind, SHELL_DENY, (command, detail))


class ConsumerSelfUpdateForwardE2ETests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.host = _empty_host(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_n_to_n1_self_update_then_lock_update(self):
        dist_n = _copy_live_dist(self.root / "dist-n")
        n_commit = _git_commit(dist_n, "N")
        dist_n1 = shutil.copytree(dist_n, self.root / "dist-n1")
        develop_md = dist_n1 / "skills" / "develop" / "SKILL.md"
        develop_md.write_text(
            develop_md.read_text(encoding="utf-8") + "\n# n1-package-marker\n",
            encoding="utf-8",
            newline="\n",
        )
        entry = dist_n1 / "src" / "scaffold_entry.py"
        entry.write_text(
            entry.read_text(encoding="utf-8") + "\n# n1-runtime-marker\n",
            encoding="utf-8",
            newline="\n",
        )
        _replace_once(
            dist_n1 / "src" / "scaffold_p5" / "consumer_install.py",
            "raise SystemExit(installed_main(INSTALL_ROOT, sys.argv[1:]))\n'''",
            "raise SystemExit(installed_main(INSTALL_ROOT, sys.argv[1:]))\n"
            "# n1-launcher-marker\n'''",
        )
        _replace_once(
            dist_n1 / "src" / "scaffold_p5" / "first_use.py",
            "    raise SystemExit(hook_main())\n'''",
            "    raise SystemExit(hook_main())\n# n1-hook-marker\n'''",
        )
        _replace_once(
            dist_n1 / "src" / "scaffold_p5" / "first_use.py",
            "or direct implementation appears faster.\n\"\"\"",
            "or direct implementation appears faster.\n"
            "n1-first-use-marker\n\"\"\"",
        )
        git(dist_n1, "add", "-A")
        git(
            dist_n1,
            "-c",
            "user.name=Scaffold Test",
            "-c",
            "user.email=scaffold-test@example.invalid",
            "commit",
            "-m",
            "N+1",
        )
        n1_commit = git(dist_n1, "rev-parse", "HEAD")
        self.assertNotEqual(n_commit, n1_commit)
        n_develop = load_package(dist_n / "skills" / "develop")
        n1_develop = load_package(dist_n1 / "skills" / "develop")
        self.assertNotEqual(n_develop.ref.package_digest, n1_develop.ref.package_digest)

        plan, installed = _install(self.host, dist=dist_n)
        self.assertTrue(plan.allowed, plan.blockers)
        self.assertEqual(installed.get("outcome"), "COMPLETED", installed)
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write(self.host, "src/app.py", "value = 0\n")
        _knowledge(self.host)
        _write_live_lock(self.host)
        write_task(self.host, TASK_A, status="IN_PROGRESS")
        ensure_noscms_accepted_anchor(self.host)
        opened = develop_engine(
            self.host,
            package_root=self.host / ".scaffold" / "install" / "packages" / "develop",
        ).open_develop_session(task_id=TASK_A)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        session_id = opened.extras["session"]["record_id"]
        session_dir = self.host / SESSIONS_DIR / session_id
        write(self.host, "src/app.py", "value = 1\n")
        persist_files_yaml(
            session_dir,
            [
                {
                    "path": "src/app.py",
                    "change_kind": "modified",
                    "before_kind": "file",
                    "after_kind": "file",
                    "before_digest": sha256_bytes(b"value = 0\n"),
                    "after_digest": sha256_bytes(b"value = 1\n"),
                    "stage_ids": ["stage-1"],
                    "mutation_state": MUTATION_OBSERVED,
                }
            ],
        )
        persist_mutation_attempts(
            session_dir,
            [
                {
                    "path": "src/app.py",
                    "mutation_state": MUTATION_OBSERVED,
                    "tool": "Write",
                }
            ],
        )
        snapshot_open_inventory(self.host, session_dir, overwrite=True)

        before_eval = _launcher_json(self.host, "understand", "compatibility")[1]
        self.assertEqual(before_eval.get("compatibility"), "EXACT", before_eval)
        lock_bytes = (self.host / ".scaffold" / "skills.lock").read_bytes()
        task_before = read_yaml(self.host / ".scaffold" / "tasks" / f"{TASK_A}.yaml")
        task_bytes = (self.host / ".scaffold" / "tasks" / f"{TASK_A}.yaml").read_bytes()
        stage_status_before = (task_before.get("stages") or [{}])[0].get("status")
        session_bytes = (session_dir / "session.yaml").read_bytes()
        files_bytes = (session_dir / "files.yaml").read_bytes()
        app_bytes = (self.host / "src" / "app.py").read_bytes()
        pointer_before, pointer_error = load_execution_pointer(self.host)
        self.assertEqual(pointer_error, "")
        self.assertIsNotNone(pointer_before)
        generation = read_yaml(self.host / ".scaffold" / "project.yaml").get(
            "project_contract_generation"
        )
        before_manifest = current_manifest(self.host) or {}
        self.assertEqual((before_manifest.get("source") or {}).get("git_commit"), n_commit)
        runner_before = (self.host / ".scaffold" / "install" / "run.py").resolve()

        proc = _run_installed(
            self.host,
            "consumer",
            "update",
            "--distribution",
            str(dist_n1),
        )
        self.assertEqual(
            Path(proc.args[1]).resolve(),
            runner_before,
        )
        payload = json.loads(proc.stdout or "{}")
        self.assertEqual(payload.get("outcome"), "COMPLETED", payload)
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify.get("status"), VERIFY_VALID, verify)
        after_manifest = current_manifest(self.host) or {}
        self.assertEqual((after_manifest.get("source") or {}).get("git_commit"), n1_commit)
        self.assertEqual(
            (after_manifest.get("skills") or {}).get("develop", {}).get("package_digest"),
            n1_develop.ref.package_digest,
        )
        runtime = (
            self.host / ".scaffold" / "install" / "runtime" / "scaffold_entry.py"
        ).read_text(encoding="utf-8")
        self.assertIn("n1-runtime-marker", runtime)
        self.assertIn(
            "n1-launcher-marker",
            (self.host / ".scaffold" / "install" / "run.py").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "n1-hook-marker",
            (
                self.host / ".scaffold" / "install" / "cursor_first_use_hook.py"
            ).read_text(encoding="utf-8"),
        )
        self.assertIn(
            "n1-first-use-marker",
            (
                self.host / ".cursor" / "rules" / "scaffold-first-use.mdc"
            ).read_text(encoding="utf-8"),
        )
        installed_develop = load_package(
            self.host / ".scaffold" / "install" / "packages" / "develop"
        )
        self.assertEqual(installed_develop.ref.package_digest, n1_develop.ref.package_digest)
        self.assertEqual((self.host / ".scaffold" / "skills.lock").read_bytes(), lock_bytes)
        self.assertEqual(
            (self.host / ".scaffold" / "tasks" / f"{TASK_A}.yaml").read_bytes(),
            task_bytes,
        )
        self.assertEqual((session_dir / "session.yaml").read_bytes(), session_bytes)
        self.assertEqual((session_dir / "files.yaml").read_bytes(), files_bytes)
        self.assertEqual((self.host / "src" / "app.py").read_bytes(), app_bytes)
        pointer_after, pointer_after_error = load_execution_pointer(self.host)
        self.assertEqual(pointer_after_error, "")
        self.assertEqual(pointer_after, pointer_before)
        self.assertEqual(
            read_yaml(self.host / ".scaffold" / "project.yaml").get(
                "project_contract_generation"
            ),
            generation,
        )
        self.assertEqual(generation, CURRENT_PROJECT_CONTRACT_GENERATION)
        task_after = read_yaml(self.host / ".scaffold" / "tasks" / f"{TASK_A}.yaml")
        self.assertEqual(task_after.get("status"), "IN_PROGRESS")
        self.assertEqual(
            (task_after.get("stages") or [{}])[0].get("status"),
            stage_status_before,
        )
        self.assertEqual(read_yaml(session_dir / "session.yaml").get("status"), "OPEN")

        after_eval = _launcher_json(self.host, "understand", "compatibility")[1]
        self.assertEqual(after_eval.get("compatibility"), "UNKNOWN", after_eval)
        self.assertEqual(_evaluation_result(after_eval, "develop"), "UNKNOWN")
        new_expected = _new_expected_payload(self.host)
        self.assertEqual(
            new_expected["develop"]["package_digest"], n1_develop.ref.package_digest
        )
        preview = _launcher_json(
            self.host,
            "understand",
            "compatibility",
            "--action",
            "lock_update",
            "--new-expected",
            _compact_json(new_expected),
        )[1]
        digest = ((preview.get("extras") or {}).get("lock_update_plan") or {}).get("digest")
        self.assertEqual(len(digest or ""), 64, preview)
        applied = _launcher_json(
            self.host,
            "understand",
            "compatibility",
            "--action",
            "lock_update",
            "--new-expected",
            _compact_json(new_expected),
            "--plan-digest",
            digest,
        )[1]
        self.assertEqual(applied.get("outcome"), "COMPLETED", applied)
        final_eval = _launcher_json(self.host, "understand", "compatibility")[1]
        self.assertEqual(final_eval.get("compatibility"), "EXACT", final_eval)
        self.assertEqual((session_dir / "session.yaml").read_bytes(), session_bytes)
        self.assertEqual((self.host / "src" / "app.py").read_bytes(), app_bytes)
        self.assertEqual(
            (self.host / ".scaffold" / "tasks" / f"{TASK_A}.yaml").read_bytes(),
            task_bytes,
        )

    def test_repo_package_identity_unchanged(self):
        for skill_id, (version, digest) in EXPECTED_PACKAGES.items():
            pkg = load_package(REPO / "skills" / skill_id)
            self.assertEqual(pkg.ref.skill_version, version, skill_id)
            self.assertEqual(pkg.ref.package_digest, digest, skill_id)

    def test_core_update_bridge_is_client_neutral(self):
        import inspect

        bridge = inspect.getsource(_run_installed_consumer)
        self.assertIn("plan_consumer_install", bridge)
        self.assertIn('mode="update"', bridge)
        self.assertIn("apply_consumer_install", bridge)
        for needle in ("beforeShellExecution", "preToolUse", "cursor", "Cursor"):
            self.assertNotIn(needle, bridge)
        self.assertTrue(callable(installed_main))


if __name__ == "__main__":
    unittest.main()

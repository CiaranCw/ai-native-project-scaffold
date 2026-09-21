from __future__ import annotations

import base64
import json
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path

from p6_support import CORE_OWNERSHIP
from p7_support import (
    TASK_A,
    develop_engine,
    ensure_noscms_accepted_anchor,
    write_active_host,
    write_task,
)
from support import (
    REPO,
    REPO_UNDERSTAND,
    distribution,
    write,
)
from test_consumer_installation import (
    _empty_host,
    _install,
    _run_installed,
)
from test_first_use_enforcement import _hook_payload
from test_pc_consumer_003 import _install_marker, _knowledge

from scaffold_p5.compatibility import evaluate_package
from scaffold_p5.consumer_install import installed_main, plan_consumer_install, apply_consumer_install
from scaffold_p5.first_use import (
    SHELL_ALLOW,
    SHELL_DENY,
    classify_first_use_shell,
    evaluate_cursor_hook,
)
from scaffold_p5.host_state import snapshot_host
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
from scaffold_p7.unexplained import UNEXPLAINED_REL


OLD_DEVELOP_DIGEST = (
    "b3899647323b0f8b3d1e0a314b7ca6c63a25dd108690ab6293749ede5fcf7f9d"
)
ARBITRARY_DIGEST = "a" * 64


def _shell_payload(host: Path, command: str) -> dict:
    return _hook_payload(
        host,
        hook_event_name="beforeShellExecution",
        tool_name="Shell",
        tool_input={"command": command},
    )


def _installed_entry(host: Path, skill_id: str) -> dict:
    pkg = load_package(host / ".scaffold" / "install" / "packages" / skill_id)
    return {
        "skill_version": pkg.ref.skill_version,
        "package_digest": pkg.ref.package_digest,
        "package_format_version": pkg.ref.package_format_version,
    }


def _live_lock_skills(host: Path, *, develop_digest: str | None = None) -> dict:
    skills = {
        skill_id: _installed_entry(host, skill_id)
        for skill_id in ("understand", "develop", "test", "submit")
    }
    if develop_digest is not None:
        skills["develop"] = {
            **skills["develop"],
            "package_digest": develop_digest,
        }
    return skills


def _write_live_lock(host: Path, *, develop_digest: str | None = None) -> dict:
    from p6_support import write_lock

    skills = _live_lock_skills(host, develop_digest=develop_digest)
    write_lock(host, skills)
    return skills


def _new_expected_payload(host: Path) -> dict:
    develop = _installed_entry(host, "develop")
    return {
        "develop": {
            "skill_version": develop["skill_version"],
            "package_digest": develop["package_digest"],
        }
    }


def _compact_json(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _b64_json(payload: dict) -> str:
    return base64.b64encode(_compact_json(payload).encode("utf-8")).decode("ascii")


def _lock_update_command(
    payload: dict,
    *,
    plan_digest: str | None = None,
    use_b64: bool = False,
) -> str:
    parts = [
        "python .scaffold/install/run.py understand compatibility --action lock_update"
    ]
    if use_b64:
        parts.append("--new-expected-b64 " + _b64_json(payload))
    else:
        parts.append("--new-expected " + shlex.quote(_compact_json(payload)))
    if plan_digest:
        parts.append("--plan-digest " + plan_digest)
    return " ".join(parts)


def _launcher_json(host: Path, *args: str) -> tuple[int, dict]:
    proc = _run_installed(host, *args)
    text = (proc.stdout or "").strip()
    payload = json.loads(text) if text else {}
    return proc.returncode, payload


def _evaluation_result(payload: dict, skill_id: str) -> str | None:
    extras = payload.get("extras") or {}
    evaluation = extras.get("evaluation") or {}
    results = evaluation.get("results") or {}
    row = results.get(skill_id) or {}
    return row.get("result")


def _prepare_adopted_consumer(host: Path) -> dict:
    _install(host)
    write_active_host(
        host,
        ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
        source_areas=["src"],
    )
    write(host, "src/app.py", "value = 0\n")
    _knowledge(host)
    live = _write_live_lock(host)
    write_task(host, TASK_A, status="IN_PROGRESS")
    ensure_noscms_accepted_anchor(host)
    opened = develop_engine(
        host,
        package_root=host / ".scaffold" / "install" / "packages" / "develop",
    ).open_develop_session(task_id=TASK_A)
    if opened.outcome not in {"COMPLETED", "NEEDS_HUMAN"} or not (
        opened.extras.get("session") or {}
    ).get("record_id"):
        raise AssertionError(opened.outcome, opened.blockers, opened.extras)
    session = opened.extras["session"]
    session_id = session["record_id"]
    directory = host / SESSIONS_DIR / session_id
    write(host, "src/app.py", "value = 1\n")
    persist_files_yaml(
        directory,
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
        directory,
        [
            {
                "path": "src/app.py",
                "mutation_state": MUTATION_OBSERVED,
                "tool": "Write",
            }
        ],
    )
    snapshot_open_inventory(host, directory, overwrite=True)
    return {
        "live": live,
        "session_id": session_id,
        "directory": directory,
    }


class CompatibilityLockUpdatePublicTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = _empty_host(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_public_evaluate_and_lock_update_r5_shape(self):
        prepared = _prepare_adopted_consumer(self.host)
        live_develop = prepared["live"]["develop"]
        other_before = {
            skill_id: dict(prepared["live"][skill_id])
            for skill_id in ("understand", "test", "submit")
        }
        lock_before = _write_live_lock(self.host, develop_digest=OLD_DEVELOP_DIGEST)
        project_before = read_yaml(self.host / ".scaffold/project.yaml")
        task_before = (self.host / ".scaffold/tasks" / f"{TASK_A}.yaml").read_bytes()
        session_dir = prepared["directory"]
        session_before = (session_dir / "session.yaml").read_bytes()
        files_before = (session_dir / "files.yaml").read_bytes()
        attempts_before = (session_dir / "mutation-attempts.yaml").read_bytes()
        inventory_before = (session_dir / "open-inventory.yaml").read_bytes()
        unexplained_path = self.host / UNEXPLAINED_REL
        unexplained_before = (
            unexplained_path.read_bytes() if unexplained_path.is_file() else None
        )
        app_before = (self.host / "src/app.py").read_bytes()
        pointer_before, pointer_error = load_execution_pointer(self.host)
        self.assertEqual(pointer_error, "")
        self.assertIsNotNone(pointer_before)

        code, evaluated = _launcher_json(self.host, "understand", "compatibility")
        self.assertEqual(code, 0, evaluated)
        self.assertEqual(evaluated.get("outcome"), "COMPLETED", evaluated)
        self.assertEqual(evaluated.get("compatibility"), "UNKNOWN", evaluated)
        self.assertEqual(_evaluation_result(evaluated, "develop"), "UNKNOWN")

        new_expected = _new_expected_payload(self.host)
        code, preview = _launcher_json(
            self.host,
            "understand",
            "compatibility",
            "--action",
            "lock_update",
            "--new-expected",
            _compact_json(new_expected),
        )
        self.assertEqual(code, 0, preview)
        self.assertEqual(preview.get("outcome"), "NEEDS_HUMAN", preview)
        plan = (preview.get("extras") or {}).get("lock_update_plan") or {}
        self.assertTrue(plan.get("valid"), plan)
        self.assertFalse(plan.get("migration_required"), plan)
        digest = plan.get("digest")
        self.assertEqual(len(digest or ""), 64, plan)
        self.assertNotIn("--approved", json.dumps(preview))

        code, rejected = _launcher_json(
            self.host,
            "understand",
            "compatibility",
            "--action",
            "lock_update",
            "--new-expected",
            _compact_json(
                {
                    "develop": {
                        "skill_version": live_develop["skill_version"],
                        "package_digest": ARBITRARY_DIGEST,
                    }
                }
            ),
        )
        self.assertNotEqual(rejected.get("outcome"), "COMPLETED", rejected)
        self.assertEqual(
            read_yaml(self.host / ".scaffold/skills.lock")["skills"]["develop"][
                "package_digest"
            ],
            OLD_DEVELOP_DIGEST,
        )

        stale = _launcher_json(
            self.host,
            "understand",
            "compatibility",
            "--action",
            "lock_update",
            "--new-expected",
            _compact_json(new_expected),
            "--plan-digest",
            "f" * 64,
        )[1]
        self.assertEqual(stale.get("outcome"), "NEEDS_HUMAN", stale)
        self.assertEqual(
            read_yaml(self.host / ".scaffold/skills.lock")["skills"]["develop"][
                "package_digest"
            ],
            OLD_DEVELOP_DIGEST,
        )

        code, applied = _launcher_json(
            self.host,
            "understand",
            "compatibility",
            "--action",
            "lock_update",
            "--new-expected",
            _compact_json(new_expected),
            "--plan-digest",
            digest,
        )
        self.assertEqual(code, 0, applied)
        self.assertEqual(applied.get("outcome"), "COMPLETED", applied)
        lock_after = read_yaml(self.host / ".scaffold/skills.lock")
        self.assertEqual(
            lock_after["skills"]["develop"]["package_digest"],
            live_develop["package_digest"],
        )
        self.assertEqual(
            lock_after["skills"]["develop"]["skill_version"],
            live_develop["skill_version"],
        )
        for skill_id, entry in other_before.items():
            self.assertEqual(lock_after["skills"][skill_id], entry, skill_id)

        project_after = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertEqual(
            project_after.get("project_contract_generation"),
            project_before.get("project_contract_generation"),
        )
        self.assertEqual(
            project_after.get("project_contract_generation"),
            CURRENT_PROJECT_CONTRACT_GENERATION,
        )
        self.assertEqual(
            (self.host / ".scaffold/tasks" / f"{TASK_A}.yaml").read_bytes(),
            task_before,
        )
        self.assertEqual((session_dir / "session.yaml").read_bytes(), session_before)
        self.assertEqual((session_dir / "files.yaml").read_bytes(), files_before)
        self.assertEqual(
            (session_dir / "mutation-attempts.yaml").read_bytes(),
            attempts_before,
        )
        self.assertEqual(
            (session_dir / "open-inventory.yaml").read_bytes(),
            inventory_before,
        )
        if unexplained_before is not None:
            self.assertEqual(unexplained_path.read_bytes(), unexplained_before)
        self.assertEqual((self.host / "src/app.py").read_bytes(), app_before)
        pointer_after, pointer_after_error = load_execution_pointer(self.host)
        self.assertEqual(pointer_after_error, "")
        self.assertEqual(pointer_after, pointer_before)
        session = read_yaml(session_dir / "session.yaml")
        self.assertEqual(session.get("status"), "OPEN")

        code, after = _launcher_json(self.host, "understand", "compatibility")
        self.assertEqual(code, 0, after)
        self.assertEqual(after.get("compatibility"), "EXACT", after)
        self.assertEqual(_evaluation_result(after, "develop"), "EXACT")
        self.assertEqual(lock_before["develop"]["package_digest"], OLD_DEVELOP_DIGEST)

    def test_public_lock_update_does_not_use_private_python(self):
        _prepare_adopted_consumer(self.host)
        _write_live_lock(self.host, develop_digest=OLD_DEVELOP_DIGEST)
        new_expected = _new_expected_payload(self.host)
        proc = _run_installed(
            self.host,
            "understand",
            "compatibility",
            "--action",
            "lock_update",
            "--new-expected",
            _compact_json(new_expected),
        )
        self.assertNotIn("python -c", " ".join(proc.args))
        self.assertTrue(str(proc.args[1]).endswith("run.py"))
        payload = json.loads(proc.stdout)
        self.assertEqual(payload.get("outcome"), "NEEDS_HUMAN", payload)

    def test_update_alone_does_not_rewrite_skills_lock(self):
        _install(self.host)
        write_active_host(self.host)
        live = _write_live_lock(self.host)
        lock_path = self.host / ".scaffold" / "skills.lock"
        before = lock_path.read_bytes()
        plan = plan_consumer_install(self.host, REPO, mode="update")
        self.assertTrue(plan.allowed, plan.blockers)
        result = apply_consumer_install(plan)
        self.assertEqual(result.get("outcome"), "COMPLETED", result)
        self.assertEqual(lock_path.read_bytes(), before)
        self.assertEqual(
            read_yaml(lock_path)["skills"]["develop"]["package_digest"],
            live["develop"]["package_digest"],
        )

    def test_changed_package_identity_fails_closed(self):
        _prepare_adopted_consumer(self.host)
        _write_live_lock(self.host, develop_digest=OLD_DEVELOP_DIGEST)
        new_expected = _new_expected_payload(self.host)
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
        skill_md = (
            self.host / ".scaffold" / "install" / "packages" / "develop" / "SKILL.md"
        )
        skill_md.write_text(skill_md.read_text(encoding="utf-8") + "\n", encoding="utf-8")
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
        self.assertNotEqual(applied.get("outcome"), "COMPLETED", applied)
        self.assertEqual(
            read_yaml(self.host / ".scaffold/skills.lock")["skills"]["develop"][
                "package_digest"
            ],
            OLD_DEVELOP_DIGEST,
        )

    def test_malformed_and_unsupported_flags_are_rejected(self):
        _install(self.host)
        write_active_host(self.host)
        _write_live_lock(self.host)
        unknown = _launcher_json(
            self.host,
            "understand",
            "compatibility",
            "--rewrite-lock",
        )[1]
        self.assertEqual(unknown.get("outcome"), "BLOCKED", unknown)
        migrate = _launcher_json(
            self.host,
            "understand",
            "compatibility",
            "--action",
            "migrate",
        )[1]
        self.assertEqual(migrate.get("outcome"), "BLOCKED", migrate)
        approved = _launcher_json(
            self.host,
            "understand",
            "compatibility",
            "--action",
            "lock_update",
            "--approved",
        )[1]
        self.assertEqual(approved.get("outcome"), "BLOCKED", approved)

    def test_b64_lock_update_apply_and_exact_evaluate(self):
        _prepare_adopted_consumer(self.host)
        _write_live_lock(self.host, develop_digest=OLD_DEVELOP_DIGEST)
        new_expected = _new_expected_payload(self.host)
        preview = _launcher_json(
            self.host,
            "understand",
            "compatibility",
            "--action",
            "lock_update",
            "--new-expected-b64",
            _b64_json(new_expected),
        )[1]
        digest = ((preview.get("extras") or {}).get("lock_update_plan") or {}).get("digest")
        applied = _launcher_json(
            self.host,
            "understand",
            "compatibility",
            "--action",
            "lock_update",
            "--new-expected-b64",
            _b64_json(new_expected),
            "--plan-digest",
            digest,
        )[1]
        self.assertEqual(applied.get("outcome"), "COMPLETED", applied)
        after = _launcher_json(self.host, "understand", "compatibility")[1]
        self.assertEqual(after.get("compatibility"), "EXACT", after)

    def test_matching_lock_evaluate_remains_exact(self):
        _install(self.host)
        write_active_host(self.host)
        _write_live_lock(self.host)
        payload = _launcher_json(self.host, "understand", "compatibility")[1]
        self.assertEqual(payload.get("compatibility"), "EXACT", payload)

    def test_core_has_no_cursor_specific_lock_update_authority(self):
        _prepare_adopted_consumer(self.host)
        _write_live_lock(self.host, develop_digest=OLD_DEVELOP_DIGEST)
        cursor = self.host / ".cursor"
        if cursor.exists():
            shutil.rmtree(cursor)
        new_expected = _new_expected_payload(self.host)
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
        self.assertFalse((self.host / ".cursor").exists())


class CompatibilityLockUpdateFirstUseTests(unittest.TestCase):
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

    def test_supported_lock_update_invocation_is_allowed(self):
        payload = {
            "develop": {
                "skill_version": "2.1.0",
                "package_digest": OLD_DEVELOP_DIGEST,
            }
        }
        evaluate = classify_first_use_shell(
            "python .scaffold/install/run.py understand compatibility",
            self.host,
            adopted=True,
        )
        preview = classify_first_use_shell(
            _lock_update_command(payload),
            self.host,
            adopted=True,
        )
        apply = classify_first_use_shell(
            _lock_update_command(payload, plan_digest="b" * 64, use_b64=True),
            self.host,
            adopted=True,
        )
        self.assertEqual(evaluate[0], SHELL_ALLOW, evaluate)
        self.assertEqual(preview[0], SHELL_ALLOW, preview)
        self.assertEqual(apply[0], SHELL_ALLOW, apply)
        hook = evaluate_cursor_hook(
            _shell_payload(self.host, _lock_update_command(payload, use_b64=True)),
            self.host,
        )
        self.assertEqual(hook.get("permission"), "allow", hook)

    def test_arbitrary_python_and_malformed_flags_remain_denied(self):
        denied = [
            "python -c print(1)",
            "python .scaffold/install/run.py understand compatibility --rewrite-lock",
            "python .scaffold/install/run.py understand compatibility --action migrate",
            "python .scaffold/install/run.py understand compatibility --action lock_update --approved",
            "python .scaffold/install/run.py understand compatibility --plan-digest " + ("c" * 64),
            "python .scaffold/install/run.py develop --action lock_update",
        ]
        for command in denied:
            kind, detail = classify_first_use_shell(
                command, self.host, adopted=True
            )
            self.assertEqual(kind, SHELL_DENY, (command, detail))
            hook = evaluate_cursor_hook(_shell_payload(self.host, command), self.host)
            self.assertEqual(hook.get("permission"), "deny", (command, hook))
        kind, detail = classify_first_use_shell(
            "python -m scaffold_p5.engine", self.host, adopted=True
        )
        self.assertEqual(kind, SHELL_ALLOW, (kind, detail))
        hook = evaluate_cursor_hook(
            _shell_payload(self.host, "python -m scaffold_p5.engine"),
            self.host,
        )
        self.assertEqual(hook.get("permission"), "allow", hook)


class CompatibilityTaxonomyUnchangedTests(unittest.TestCase):
    def test_five_result_taxonomy_unchanged(self):
        released = load_package(
            REPO / "tests/fixtures/distribution/packages/understand-2.0.0"
        )
        pinned = released.ref
        dist = distribution()
        exact = evaluate_package(
            pinned,
            released,
            project={"project_contract_generation": "2"},
            distribution=dist,
        )
        compatible = evaluate_package(
            pinned,
            load_package(REPO / "tests/fixtures/distribution/packages/understand-2.0.1"),
            project={"project_contract_generation": "2"},
            distribution=distribution("2.0.1"),
        )
        migration = evaluate_package(
            pinned,
            load_package(REPO / "tests/fixtures/distribution/packages/understand-2.1.0"),
            project={"project_contract_generation": "2"},
            distribution=distribution("2.1.0"),
        )
        unknown = evaluate_package(
            pinned,
            load_package(REPO / "tests/fixtures/distribution/packages/understand-2.2.0"),
            project={"project_contract_generation": "2"},
            distribution=distribution("2.2.0"),
        )
        incompat = evaluate_package(
            pinned,
            load_package(REPO / "tests/fixtures/distribution/packages/understand-incompat"),
            project={"project_contract_generation": "2"},
            distribution=distribution(),
        )
        live = load_package(REPO_UNDERSTAND)
        live_exact = evaluate_package(
            live.ref,
            live,
            project={"project_contract_generation": "2"},
            distribution=dist,
        )
        self.assertEqual(exact["result"], "EXACT")
        self.assertEqual(live_exact["result"], "EXACT")
        self.assertEqual(compatible["result"], "COMPATIBLE")
        self.assertEqual(migration["result"], "MIGRATION_REQUIRED")
        self.assertEqual(unknown["result"], "UNKNOWN")
        self.assertEqual(incompat["result"], "INCOMPATIBLE")

    def test_installed_main_is_the_public_entry(self):
        self.assertTrue(callable(installed_main))
        self.assertEqual(snapshot_host.__module__, "scaffold_p5.host_state")


if __name__ == "__main__":
    unittest.main()

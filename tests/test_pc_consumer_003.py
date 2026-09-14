from __future__ import annotations

import base64
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from p6_support import CORE_OWNERSHIP
from p7_support import TASK_A, TASK_B, develop_engine, write_active_host, write_task
from support import write
from test_first_use_enforcement import _hook_payload

from scaffold_p5.consumer_install import CURSOR_ADAPTERS, installed_main
from scaffold_p5.first_use import (
    DECISION_BLOCK,
    GATE_FAIL_CLOSED,
    GATE_RECOVERY,
    REQUIRED_ROUTE_DEVELOP,
    REQUIRED_ROUTE_RECOVERY,
    evaluate_cursor_hook,
    first_use_decision,
)
from scaffold_p5.full import GENERATED_AGENTS
from scaffold_p5.host_state import snapshot_host
from scaffold_p5.io_util import write_yaml_atomic
from scaffold_p5.models import CORE_SKILLS
from scaffold_p6.candidate import observe_candidate
from scaffold_p7.models import DEVELOP_MODES, SESSIONS_DIR


PROPOSAL = {
    "title": "Implement fixture source",
    "goal": "Change src/app.py under Task authority.",
    "acceptance": "src/app.py contains the expected line.",
    "scope": {
        "paths": ["src/app.py"],
        "modules": [],
        "exclude": [],
    },
    "stages": [
        {
            "stage_id": "stage-1",
            "goal": "Write the fixture source.",
            "acceptance": "src/app.py has the expected content.",
            "required_tests": [],
        }
    ],
    "final_tests": [],
}


def _install_marker(host: Path) -> None:
    install = host / ".scaffold" / "install"
    install.mkdir(parents=True, exist_ok=True)
    marker = install / "install.yaml"
    if not marker.is_file():
        marker.write_text("product: scaffold\n", encoding="utf-8")
    runner = install / "run.py"
    if not runner.is_file():
        runner.write_text("#!/usr/bin/env python3\n", encoding="utf-8")


def _knowledge(host: Path) -> None:
    write_yaml_atomic(
        host / ".scaffold" / "tests.yaml",
        {"schema_version": "1", "profiles": []},
    )
    write_yaml_atomic(
        host / ".scaffold" / "commands.yaml",
        {"schema_version": "1", "commands": []},
    )


def _write_payload(host: Path, rel: str = "src/app.py") -> dict:
    return _hook_payload(
        host,
        hook_event_name="preToolUse",
        tool_name="Write",
        tool_input={"path": rel, "contents": "mutated = True\n"},
    )


def _shell_payload(host: Path, command: str) -> dict:
    return _hook_payload(
        host,
        hook_event_name="beforeShellExecution",
        command=command,
    )


def _open_session(host: Path, task_id: str, *, status: str = "OPEN") -> None:
    session_id = "dev-20260913T000000Z-abcd1234"
    directory = host / SESSIONS_DIR / session_id
    directory.mkdir(parents=True, exist_ok=True)
    write_yaml_atomic(
        directory / "session.yaml",
        {
            "record_type": "develop_session",
            "schema_version": "1",
            "record_id": session_id,
            "status": status,
            "task_id": task_id,
        },
    )


def _begin_execution(host: Path, task_id: str = TASK_A):
    return develop_engine(host).open_develop_session(task_id=task_id)


def _in_progress_stages() -> list[dict]:
    return [
        {
            "stage_id": "stage-1",
            "goal": "Write the fixture source.",
            "acceptance": "src/app.py has the expected content.",
            "status": "IN_PROGRESS",
            "required_tests": [],
        }
    ]


def _envelope(proposal: dict | None = None) -> dict:
    body = proposal or PROPOSAL
    return {
        "structured_intent": {
            "kind": "develop",
            "action": "implement",
            "request": "Implement the fixture source change now.",
            "explicit_implementation": True,
            "authorized_proposal": body,
        },
        "proposal": body,
        "grounding": {
            "intent_fields": ["goal", "scope", "acceptance", "stages", "tests"],
            "knowledge_fields": ["scope", "rules", "ownership", "tests"],
            "uncertainties": [],
            "material_decisions": [],
        },
    }


def _b64(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _run_installed(host: Path, argv: list[str]) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = installed_main(host / ".scaffold" / "install", argv)
    text = buf.getvalue().strip()
    return code, json.loads(text) if text else {}


class PcConsumer003Tests(unittest.TestCase):
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
        write_task(
            self.host,
            TASK_A,
            status="IN_PROGRESS",
            stages=_in_progress_stages(),
        )
        _install_marker(self.host)
        _knowledge(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def test_C003_01_active_host_without_session_blocks_write(self):
        self.assertEqual(snapshot_host(self.host).host_class, "ESTABLISHED_HOST")
        decision = first_use_decision(self.host)
        self.assertEqual(decision["decision"], DECISION_BLOCK)
        self.assertEqual(decision["required_route"], REQUIRED_ROUTE_DEVELOP)
        self.assertFalse(decision["project_mutation_allowed"])
        result = evaluate_cursor_hook(_write_payload(self.host), self.host)
        self.assertEqual(result["permission"], "deny", result)
        self.assertIn("Develop", result.get("agent_message") or "")

    def test_C003_02_official_develop_launcher_allowed(self):
        develop = evaluate_cursor_hook(
            _shell_payload(self.host, "python .scaffold/install/run.py develop"),
            self.host,
        )
        enter = evaluate_cursor_hook(
            _shell_payload(self.host, "python .scaffold/install/run.py enter develop"),
            self.host,
        )
        tasked = evaluate_cursor_hook(
            _shell_payload(
                self.host,
                f"python .scaffold/install/run.py develop --task-id {TASK_A}",
            ),
            self.host,
        )
        intake = evaluate_cursor_hook(
            _shell_payload(
                self.host,
                "python .scaffold/install/run.py enter develop --intake-json-b64 "
                + _b64(_envelope()),
            ),
            self.host,
        )
        self.assertEqual(develop["permission"], "allow", develop)
        self.assertEqual(enter["permission"], "allow", enter)
        self.assertEqual(tasked["permission"], "allow", tasked)
        self.assertEqual(intake["permission"], "allow", intake)

    def test_C003_03_arbitrary_shell_and_direct_write_denied(self):
        shell = evaluate_cursor_hook(
            _shell_payload(self.host, "python -m pytest tests/unit"),
            self.host,
        )
        write_result = evaluate_cursor_hook(_write_payload(self.host), self.host)
        self.assertEqual(shell["permission"], "deny", shell)
        self.assertEqual(write_result["permission"], "deny", write_result)

    def test_C003_04_open_session_permits_in_scope_mutation_only(self):
        opened = _begin_execution(self.host)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        decision = first_use_decision(self.host)
        self.assertEqual(decision["decision"], DECISION_BLOCK)
        self.assertFalse(decision["project_mutation_allowed"])
        self.assertTrue(decision["first_use_gate_active"])
        self.assertTrue((decision.get("develop_authority") or {}).get("ok"))
        allowed = evaluate_cursor_hook(_write_payload(self.host), self.host)
        denied = evaluate_cursor_hook(
            _write_payload(self.host, "docs/unrelated.md"),
            self.host,
        )
        self.assertEqual(allowed["permission"], "allow", allowed)
        self.assertEqual(denied["permission"], "deny", denied)

    def test_C003_05_develop_run_creates_session_before_source_write(self):
        denied = evaluate_cursor_hook(_write_payload(self.host), self.host)
        self.assertEqual(denied["permission"], "deny", denied)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "ok = True\n"}],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.extras.get("writes_applied"), ["src/app.py"])
        sessions = list((self.host / SESSIONS_DIR).glob("*/session.yaml"))
        self.assertTrue(sessions)
        self.assertEqual(
            (self.host / "src" / "app.py").read_text(encoding="utf-8"),
            "ok = True\n",
        )
        after = evaluate_cursor_hook(_write_payload(self.host), self.host)
        self.assertEqual(after["permission"], "deny", after)

    def test_C003_06_four_skills_repair_is_develop_mode(self):
        self.assertEqual(CORE_SKILLS, ("understand", "develop", "test", "submit"))
        self.assertEqual(len(CURSOR_ADAPTERS), 4)
        self.assertEqual(
            set(CURSOR_ADAPTERS),
            {
                "scaffold-understand",
                "scaffold-develop",
                "scaffold-test",
                "scaffold-submit",
            },
        )
        self.assertEqual(DEVELOP_MODES, ("normal_task", "repair"))
        self.assertTrue(observe_candidate(self.host).usable)
        from scaffold_p5 import first_use, consumer_install

        self.assertFalse(hasattr(first_use, "auto_adopt"))
        self.assertFalse(hasattr(consumer_install, "auto_adopt"))
        joined = " ".join(CURSOR_ADAPTERS).lower()
        self.assertNotIn("codebuddy", joined)
        self.assertNotIn("claude", joined)
        self.assertNotIn("codex", joined)

    def test_C003_C_task_a_does_not_authorize_task_b_or_unrelated(self):
        write(self.host, "src/other.py", "other = 0\n")
        write_task(
            self.host,
            TASK_B,
            status="DRAFT",
            scope={"paths": ["src/other.py"], "modules": [], "exclude": []},
            stages=_in_progress_stages(),
        )
        _begin_execution(self.host)
        allowed = evaluate_cursor_hook(_write_payload(self.host), self.host)
        other = evaluate_cursor_hook(
            _write_payload(self.host, "src/other.py"), self.host
        )
        self.assertEqual(allowed["permission"], "allow", allowed)
        self.assertEqual(other["permission"], "deny", other)

    def test_C003_C_complete_only_stage_does_not_authorize(self):
        write_task(
            self.host,
            TASK_A,
            status="IN_PROGRESS",
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Done.",
                    "acceptance": "Done.",
                    "status": "COMPLETE",
                    "required_tests": [],
                }
            ],
        )
        opened = _begin_execution(self.host)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        result = evaluate_cursor_hook(_write_payload(self.host), self.host)
        self.assertEqual(result["permission"], "deny", result)
        self.assertIn("COMPLETE-only", result.get("reason") or "")

    def test_C003_C_sealed_session_does_not_authorize(self):
        opened = _begin_execution(self.host)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "COMPLETED", sealed.blockers)
        result = evaluate_cursor_hook(_write_payload(self.host), self.host)
        self.assertEqual(result["permission"], "deny", result)

    def test_C003_C_aborted_session_does_not_authorize(self):
        opened = _begin_execution(self.host)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        aborted = develop_engine(self.host).abort_develop_execution(task_id=TASK_A)
        self.assertEqual(aborted.outcome, "COMPLETED", aborted.blockers)
        result = evaluate_cursor_hook(_write_payload(self.host), self.host)
        self.assertEqual(result["permission"], "deny", result)

    def test_C003_C_governance_and_arbitrary_shell_denied_with_open_session(self):
        opened = _begin_execution(self.host)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        governance = evaluate_cursor_hook(
            _write_payload(self.host, ".scaffold/project.yaml"),
            self.host,
        )
        lock = evaluate_cursor_hook(
            _write_payload(self.host, ".scaffold/skills.lock"),
            self.host,
        )
        shell = evaluate_cursor_hook(
            _shell_payload(self.host, "python -c \"open('mutated.txt','w').write('x')\""),
            self.host,
        )
        rm = evaluate_cursor_hook(
            _shell_payload(self.host, "rm -rf src"),
            self.host,
        )
        self.assertEqual(governance["permission"], "deny", governance)
        self.assertEqual(lock["permission"], "deny", lock)
        self.assertEqual(shell["permission"], "deny", shell)
        self.assertEqual(rm["permission"], "deny", rm)


class PcConsumer003AIntakeTests(unittest.TestCase):
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
        _install_marker(self.host)
        _knowledge(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def test_C003_A_fresh_active_host_without_task_cannot_mutate(self):
        decision = first_use_decision(self.host)
        self.assertEqual(decision["decision"], DECISION_BLOCK)
        self.assertFalse(decision["project_mutation_allowed"])
        self.assertEqual(
            evaluate_cursor_hook(_write_payload(self.host), self.host)["permission"],
            "deny",
        )

    def test_C003_A_installed_intake_creates_task_without_session(self):
        argv = [
            "enter",
            "develop",
            "--intake-json-b64",
            _b64(_envelope()),
        ]
        code, payload = _run_installed(self.host, argv)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload.get("outcome"), "COMPLETED", payload)
        task = (payload.get("extras") or {}).get("task") or {}
        self.assertTrue(task.get("record_id"))
        self.assertEqual(task.get("status"), "IN_PROGRESS")
        self.assertFalse((payload.get("extras") or {}).get("session"))
        self.assertFalse((self.host / SESSIONS_DIR).exists())
        task_files = list((self.host / ".scaffold" / "tasks").glob("task-*.yaml"))
        self.assertEqual(len(task_files), 1)
        self.assertEqual(
            evaluate_cursor_hook(_write_payload(self.host), self.host)["permission"],
            "deny",
        )
        opened = develop_engine(self.host).open_develop_session(
            task_id=str(task.get("record_id"))
        )
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        write_ok = evaluate_cursor_hook(_write_payload(self.host), self.host)
        self.assertEqual(write_ok["permission"], "allow", write_ok)
        unrelated = evaluate_cursor_hook(
            _write_payload(self.host, "docs/notes.md"),
            self.host,
        )
        self.assertEqual(unrelated["permission"], "deny", unrelated)
        cancelled = evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="postToolUseFailure",
                tool_name="Write",
                tool_input={"path": "src/app.py", "contents": "mutated = True\n"},
                failure_type="permission_denied",
            ),
            self.host,
        )
        self.assertEqual(cancelled["permission"], "allow", cancelled)
        sealed = develop_engine(self.host).seal_develop_execution(
            task_id=str(task.get("record_id"))
        )
        self.assertEqual(sealed.outcome, "COMPLETED", sealed.blockers)
        self.assertEqual(
            evaluate_cursor_hook(_write_payload(self.host), self.host)["permission"],
            "deny",
        )

    def test_C003_A_malformed_proposal_fails_closed(self):
        bad = _envelope()
        bad["proposal"] = {"title": "incomplete"}
        code, payload = _run_installed(
            self.host,
            ["enter", "develop", "--intake-json-b64", _b64(bad)],
        )
        self.assertNotEqual(payload.get("outcome"), "COMPLETED", payload)
        self.assertFalse(list((self.host / ".scaffold" / "tasks").glob("task-*.yaml")))
        self.assertEqual(
            evaluate_cursor_hook(_write_payload(self.host), self.host)["permission"],
            "deny",
        )
        garbage = evaluate_cursor_hook(
            _shell_payload(
                self.host,
                "python .scaffold/install/run.py enter develop --intake-json-b64 $$$",
            ),
            self.host,
        )
        self.assertEqual(garbage["permission"], "deny", garbage)
        bypass = evaluate_cursor_hook(
            _shell_payload(
                self.host,
                "python .scaffold/install/run.py develop --intake-json-b64 "
                + _b64(_envelope()),
            ),
            self.host,
        )
        self.assertEqual(bypass["permission"], "deny", bypass)
        del code


class PcConsumer003BHostPolicyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _consistency_host(self) -> None:
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write(self.host, "src/app.py", "value = 0\n")
        (self.host / ".scaffold" / "skills.lock").unlink()
        _install_marker(self.host)

    def _prior_footprint_host(self) -> None:
        write(self.host, "AGENTS.md", GENERATED_AGENTS)
        _install_marker(self.host)

    def test_C003_B_consistency_cannot_mutate_but_recovery_remains(self):
        self._consistency_host()
        self.assertEqual(
            snapshot_host(self.host).host_class, "ESTABLISHED_HOST_CONSISTENCY"
        )
        decision = first_use_decision(self.host)
        self.assertEqual(decision["decision"], DECISION_BLOCK)
        self.assertEqual(decision["gate_policy"], GATE_RECOVERY)
        self.assertEqual(decision["required_route"], REQUIRED_ROUTE_RECOVERY)
        self.assertEqual(
            evaluate_cursor_hook(_write_payload(self.host), self.host)["permission"],
            "deny",
        )
        self.assertEqual(
            evaluate_cursor_hook(
                _shell_payload(self.host, "python -m pytest tests/unit"),
                self.host,
            )["permission"],
            "deny",
        )
        self.assertEqual(
            evaluate_cursor_hook(
                _shell_payload(
                    self.host,
                    "python .scaffold/install/run.py understand compatibility",
                ),
                self.host,
            )["permission"],
            "allow",
        )
        self.assertEqual(
            evaluate_cursor_hook(
                _shell_payload(
                    self.host, "python .scaffold/install/run.py understand refresh"
                ),
                self.host,
            )["permission"],
            "allow",
        )
        self.assertEqual(
            evaluate_cursor_hook(
                _shell_payload(self.host, "python .scaffold/install/run.py status"),
                self.host,
            )["permission"],
            "allow",
        )
        self.assertEqual(
            evaluate_cursor_hook(
                _shell_payload(self.host, "python .scaffold/install/run.py verify"),
                self.host,
            )["permission"],
            "allow",
        )
        self.assertEqual(
            evaluate_cursor_hook(
                _shell_payload(self.host, "python .scaffold/install/run.py develop"),
                self.host,
            )["permission"],
            "deny",
        )

    def test_C003_B_prior_footprint_cannot_mutate(self):
        self._prior_footprint_host()
        self.assertEqual(snapshot_host(self.host).host_class, "PRIOR_FOOTPRINT")
        self.assertEqual(
            evaluate_cursor_hook(_write_payload(self.host, "src/app.py"), self.host)[
                "permission"
            ],
            "deny",
        )
        self.assertEqual(
            evaluate_cursor_hook(
                _shell_payload(
                    self.host,
                    "python .scaffold/install/run.py understand compatibility",
                ),
                self.host,
            )["permission"],
            "allow",
        )

    def test_C003_B_unknown_host_state_fail_closed(self):
        write_active_host(self.host)
        _install_marker(self.host)
        fake = SimpleNamespace(
            host_class="TOTALLY_NEW",
            lifecycle="ACTIVE",
            project={"lifecycle": "ACTIVE", "maintenance": []},
            preflight_context=None,
        )
        with patch("scaffold_p5.first_use.snapshot_host", return_value=fake):
            decision = first_use_decision(self.host)
            self.assertEqual(decision["gate_policy"], GATE_FAIL_CLOSED)
            self.assertEqual(decision["decision"], DECISION_BLOCK)
            result = evaluate_cursor_hook(_write_payload(self.host), self.host)
            self.assertEqual(result["permission"], "deny", result)
            status = evaluate_cursor_hook(
                _shell_payload(self.host, "python .scaffold/install/run.py status"),
                self.host,
            )
            self.assertEqual(status["permission"], "allow", status)
            develop = evaluate_cursor_hook(
                _shell_payload(self.host, "python .scaffold/install/run.py develop"),
                self.host,
            )
            self.assertEqual(develop["permission"], "deny", develop)

    def test_C003_B_interrupted_recovery_refresh_and_migration_deny_mutation(self):
        cases = [
            (
                "INTERRUPTED_INITIAL_ADOPTION",
                SimpleNamespace(
                    host_class="INTERRUPTED_INITIAL_ADOPTION",
                    lifecycle="ADOPTING",
                    project={"lifecycle": "ADOPTING", "maintenance": []},
                    preflight_context=None,
                ),
            ),
            (
                "RECOVERY_REQUIRED",
                None,
            ),
            (
                "NEEDS_REFRESH",
                None,
            ),
            (
                "NEEDS_MIGRATION",
                None,
            ),
        ]
        for label, fake in cases:
            with self.subTest(label=label):
                self._tmp.cleanup()
                self.setUp()
                if label == "RECOVERY_REQUIRED":
                    write_active_host(
                        self.host,
                        lifecycle="RECOVERY_REQUIRED",
                        ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
                        source_areas=["src"],
                    )
                    _install_marker(self.host)
                    self.assertEqual(
                        snapshot_host(self.host).lifecycle, "RECOVERY_REQUIRED"
                    )
                    decision = first_use_decision(self.host)
                elif label == "NEEDS_REFRESH":
                    write_active_host(
                        self.host,
                        ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
                        source_areas=["src"],
                        maintenance=["NEEDS_REFRESH"],
                    )
                    _install_marker(self.host)
                    decision = first_use_decision(self.host)
                elif label == "NEEDS_MIGRATION":
                    write_active_host(
                        self.host,
                        ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
                        source_areas=["src"],
                        maintenance=["NEEDS_MIGRATION"],
                    )
                    _install_marker(self.host)
                    decision = first_use_decision(self.host)
                else:
                    write_active_host(self.host)
                    _install_marker(self.host)
                    with patch("scaffold_p5.first_use.snapshot_host", return_value=fake):
                        decision = first_use_decision(self.host)
                        result = evaluate_cursor_hook(
                            _write_payload(self.host), self.host
                        )
                        status = evaluate_cursor_hook(
                            _shell_payload(
                                self.host, "python .scaffold/install/run.py status"
                            ),
                            self.host,
                        )
                    self.assertEqual(decision["gate_policy"], GATE_RECOVERY)
                    self.assertEqual(decision["decision"], DECISION_BLOCK)
                    self.assertEqual(result["permission"], "deny", result)
                    self.assertEqual(status["permission"], "allow", status)
                    continue
                self.assertEqual(decision["gate_policy"], GATE_RECOVERY, decision)
                self.assertEqual(decision["decision"], DECISION_BLOCK)
                self.assertEqual(
                    evaluate_cursor_hook(_write_payload(self.host), self.host)[
                        "permission"
                    ],
                    "deny",
                )
                self.assertEqual(
                    evaluate_cursor_hook(
                        _shell_payload(
                            self.host, "python .scaffold/install/run.py status"
                        ),
                        self.host,
                    )["permission"],
                    "allow",
                )
                self.assertEqual(
                    evaluate_cursor_hook(
                        _shell_payload(
                            self.host,
                            "python .scaffold/install/run.py understand compatibility",
                        ),
                        self.host,
                    )["permission"],
                    "allow",
                )


class PcConsumer003AuthorityChainTests(unittest.TestCase):
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
        write_task(
            self.host,
            TASK_A,
            status="IN_PROGRESS",
            stages=_in_progress_stages(),
        )
        _install_marker(self.host)
        _knowledge(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def test_open_session_without_pointer_is_denied(self):
        opened = _begin_execution(self.host)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        pointer = self.host / ".scaffold" / "runtime" / "develop-execution.yaml"
        self.assertTrue(pointer.is_file())
        pointer.unlink()
        denied = evaluate_cursor_hook(_write_payload(self.host), self.host)
        self.assertEqual(denied["permission"], "deny", denied)
        self.assertIn("execution binding", denied.get("reason") or "")

    def test_deleting_pointer_cannot_restore_authority(self):
        opened = _begin_execution(self.host)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        self.assertEqual(
            evaluate_cursor_hook(_write_payload(self.host), self.host)["permission"],
            "allow",
        )
        pointer = self.host / ".scaffold" / "runtime" / "develop-execution.yaml"
        pointer.unlink()
        self.assertEqual(
            evaluate_cursor_hook(_write_payload(self.host), self.host)["permission"],
            "deny",
        )

    def test_stale_pointer_is_denied(self):
        opened = _begin_execution(self.host)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "COMPLETED", sealed.blockers)
        session_id = (opened.extras or {}).get("session", {}).get("record_id")
        write_yaml_atomic(
            self.host / ".scaffold" / "runtime" / "develop-execution.yaml",
            {
                "schema_version": "1",
                "record_type": "develop_execution",
                "session_id": session_id,
                "task_id": TASK_A,
                "opened_candidate_digest": "sha256:" + ("0" * 64),
                "lineage_digest": "sha256:" + ("0" * 64),
                "selected_at": "2026-09-13T00:00:00Z",
            },
        )
        denied = evaluate_cursor_hook(_write_payload(self.host), self.host)
        self.assertEqual(denied["permission"], "deny", denied)

    def test_partial_and_orphan_sessions_are_denied(self):
        _open_session(self.host, TASK_A)
        self.assertEqual(
            evaluate_cursor_hook(_write_payload(self.host), self.host)["permission"],
            "deny",
        )

    def test_missing_files_yaml_is_denied(self):
        opened = _begin_execution(self.host)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        session_id = (opened.extras or {}).get("session", {}).get("record_id")
        files = self.host / SESSIONS_DIR / str(session_id) / "files.yaml"
        files.unlink()
        self.assertEqual(
            evaluate_cursor_hook(_write_payload(self.host), self.host)["permission"],
            "deny",
        )

    def test_two_in_progress_tasks_one_active_session(self):
        write(self.host, "src/other.py", "other = 0\n")
        write_task(
            self.host,
            TASK_B,
            status="IN_PROGRESS",
            scope={"paths": ["src/other.py"], "modules": [], "exclude": []},
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Other.",
                    "acceptance": "Other.",
                    "status": "IN_PROGRESS",
                    "required_tests": [],
                }
            ],
        )
        opened = _begin_execution(self.host, TASK_A)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        allowed = evaluate_cursor_hook(_write_payload(self.host), self.host)
        other = evaluate_cursor_hook(
            _write_payload(self.host, "src/other.py"), self.host
        )
        self.assertEqual(allowed["permission"], "allow", allowed)
        self.assertEqual(other["permission"], "deny", other)

    def test_ambiguous_open_sessions_fail_closed(self):
        from scaffold_p7.session import create_session

        digest = observe_candidate(self.host).digest
        create_session(
            self.host,
            task_id=TASK_A,
            mode="normal_task",
            project_name=self.host.name,
            candidate_digest=digest,
        )
        write_task(
            self.host,
            TASK_B,
            status="IN_PROGRESS",
            scope={"paths": ["src/app.py"], "modules": [], "exclude": []},
            stages=_in_progress_stages(),
        )
        create_session(
            self.host,
            task_id=TASK_B,
            mode="normal_task",
            project_name=self.host.name,
            candidate_digest=digest,
        )
        result = evaluate_cursor_hook(_write_payload(self.host), self.host)
        self.assertEqual(result["permission"], "deny", result)
        reason = result.get("reason") or ""
        self.assertTrue(
            "execution binding" in reason or "multiple OPEN" in reason,
            reason,
        )

    def test_in_scope_authorized_mutation_out_of_band_blocks(self):
        opened = _begin_execution(self.host)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        authorized = evaluate_cursor_hook(_write_payload(self.host), self.host)
        self.assertEqual(authorized["permission"], "allow", authorized)
        write(self.host, "src/app.py", "value = 1\n")
        still = evaluate_cursor_hook(_write_payload(self.host), self.host)
        self.assertEqual(still["permission"], "allow", still)
        write(self.host, "legacy.txt", "drift\n")
        blocked = evaluate_cursor_hook(_write_payload(self.host), self.host)
        self.assertEqual(blocked["permission"], "deny", blocked)
        self.assertIn("drift", blocked.get("reason") or "")

    def test_multiedit_is_classified_and_path_authorized(self):
        opened = _begin_execution(self.host)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        allowed = evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="MultiEdit",
                tool_input={
                    "edits": [
                        {"path": "src/app.py", "old_string": "0", "new_string": "1"}
                    ]
                },
            ),
            self.host,
        )
        denied = evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="MultiEdit",
                tool_input={
                    "edits": [
                        {"path": "docs/unrelated.md", "old_string": "a", "new_string": "b"}
                    ]
                },
            ),
            self.host,
        )
        self.assertEqual(allowed["permission"], "allow", allowed)
        self.assertEqual(denied["permission"], "deny", denied)

    def test_installed_session_seal_and_abort_routes(self):
        opened = _begin_execution(self.host)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        self.assertEqual(
            evaluate_cursor_hook(
                _shell_payload(
                    self.host,
                    f"python .scaffold/install/run.py develop seal --task-id {TASK_A}",
                ),
                self.host,
            )["permission"],
            "allow",
        )
        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "COMPLETED", sealed.blockers)
        self.assertEqual(
            evaluate_cursor_hook(_write_payload(self.host), self.host)["permission"],
            "deny",
        )
        again = _begin_execution(self.host)
        self.assertEqual(again.outcome, "COMPLETED", again.blockers)
        self.assertEqual(
            evaluate_cursor_hook(
                _shell_payload(
                    self.host,
                    f"python .scaffold/install/run.py develop abort --task-id {TASK_A}",
                ),
                self.host,
            )["permission"],
            "allow",
        )
        aborted = develop_engine(self.host).abort_develop_execution(task_id=TASK_A)
        self.assertEqual(aborted.outcome, "COMPLETED", aborted.blockers)
        self.assertEqual(
            evaluate_cursor_hook(_write_payload(self.host), self.host)["permission"],
            "deny",
        )


if __name__ == "__main__":
    unittest.main()

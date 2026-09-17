from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from p6_support import CORE_OWNERSHIP, passing_profile, write_commands, write_host, write_tests
from p6_support import test_engine as make_test_engine
from p7_support import (
    TASK_A,
    TASK_B,
    develop_engine,
    ensure_noscms_accepted_anchor,
    write_active_host,
    write_task,
)
from support import REPO, write
from test_first_use_enforcement import _hook_payload
from test_pc_consumer_003 import _install_marker, _knowledge
from test_task_supporting_delta import VAULT_SCOPE

from scaffold_p5.consumer_install import installed_main
from scaffold_p5.first_use import DEVELOP_DENY_MESSAGE, HOOK_EVENTS, evaluate_cursor_hook
from scaffold_p5.io_util import read_yaml
from scaffold_p5.result import skill_result
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.evidence import compile_supplied_sav_item, supporting_evidence_locator_issues
from scaffold_p6.published import consume_published_report
from scaffold_p7.develop_authority import (
    EXECUTION_POINTER_REL,
    execution_provenance_issues,
    resolve_current_develop_authority,
)
from scaffold_p7.handoff import invoke_test
from scaffold_p7.models import SESSIONS_DIR
from scaffold_p7.session import (
    MUTATION_CANCELLED,
    MUTATION_FAILED,
    MUTATION_OBSERVED,
    MUTATION_PENDING,
    create_session,
    load_files_yaml,
    load_mutation_attempts,
)
from scaffold_p8.completeness import evaluate_completeness
from scaffold_p8.delta import classify_delta, load_sealed_sessions, observe_real_diff
from scaffold_p8.preflight import inspect_host_project
from scaffold_p8.structural import review_structure


VAULT_PRODUCT = "src/mvp/vault.js"
VAULT_TEST = "tests/unit/vault.test.js"
VAULT_EVIDENCE = "artifacts/evidence/mvp-vault/run.log"


def _write_payload(host: Path, rel: str, contents: str = "mutated = True\n") -> dict:
    return _hook_payload(
        host,
        hook_event_name="preToolUse",
        tool_name="Write",
        tool_input={"path": rel, "contents": contents},
    )


def _after_payload(host: Path, rel: str) -> dict:
    return _hook_payload(
        host,
        hook_event_name="afterFileEdit",
        file_path=rel,
    )


class R3PointerAndLineageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write(self.host, VAULT_PRODUCT, "export const vault = true\n")
        write(self.host, VAULT_TEST, "assert(true)\n")
        write(self.host, VAULT_EVIDENCE, "ok\n")
        write(self.host, "legacy/dirty.txt", "inherited\n")
        self.task = write_task(
            self.host,
            TASK_A,
            status="IN_PROGRESS",
            scope=dict(VAULT_SCOPE),
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Vault.",
                    "acceptance": "Vault.",
                    "status": "IN_PROGRESS",
                    "required_tests": [],
                }
            ],
        )
        _install_marker(self.host)
        _knowledge(self.host)
        ensure_noscms_accepted_anchor(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def _open(self):
        opened = develop_engine(self.host).open_develop_session(task_id=TASK_A)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        session_id = (opened.extras or {}).get("session", {}).get("record_id")
        self.assertTrue(session_id)
        return str(session_id)

    def test_open_with_pointer_is_eligible(self):
        self._open()
        allowed = evaluate_cursor_hook(_write_payload(self.host, VAULT_PRODUCT), self.host)
        self.assertEqual(allowed["permission"], "allow", allowed)
        authority = resolve_current_develop_authority(self.host)
        self.assertTrue(authority.ok, authority.reason)

    def test_legitimate_editor_mutation_remains_valid(self):
        self._open()
        first = evaluate_cursor_hook(_write_payload(self.host, VAULT_PRODUCT), self.host)
        self.assertEqual(first["permission"], "allow", first)
        write(self.host, VAULT_PRODUCT, "export const vault = false\n")
        after = evaluate_cursor_hook(_after_payload(self.host, VAULT_PRODUCT), self.host)
        self.assertEqual(after["permission"], "allow", after)
        still = evaluate_cursor_hook(_write_payload(self.host, VAULT_TEST), self.host)
        self.assertEqual(still["permission"], "allow", still)

    def test_rogue_product_and_supporting_and_outside_are_detected(self):
        """FA2-FND-005 path-scoped Develop: same-scope X must not globally deny Y.

        Out-of-scope drift remains a global editor deny. Seal still fail-closes
        on this Session's unexplained same-scope delta.
        """
        self._open()
        evaluate_cursor_hook(_write_payload(self.host, VAULT_PRODUCT), self.host)
        write(self.host, "src/mvp/rogue.py", "rogue = True\n")
        product = evaluate_cursor_hook(_write_payload(self.host, VAULT_PRODUCT), self.host)
        self.assertEqual(product["permission"], "allow", product)
        authority = resolve_current_develop_authority(self.host)
        self.assertTrue(authority.ok, authority.reason)
        pointer = self.host / EXECUTION_POINTER_REL
        session_id = read_yaml(pointer)["session_id"]
        directory = self.host / SESSIONS_DIR / session_id
        issues = execution_provenance_issues(
            self.host,
            task=self.task,
            session=read_yaml(directory / "session.yaml"),
            directory=directory,
        )
        self.assertTrue(
            any("unexplained same-scope drift: src/mvp/rogue.py" in item for item in issues),
            issues,
        )

        (self.host / "src" / "mvp" / "rogue.py").unlink()
        write(self.host, "tests/unit/rogue_support.py", "nope\n")
        supporting = evaluate_cursor_hook(_write_payload(self.host, VAULT_TEST), self.host)
        self.assertEqual(supporting["permission"], "allow", supporting)
        supporting_issues = execution_provenance_issues(
            self.host,
            task=self.task,
            session=read_yaml(directory / "session.yaml"),
            directory=directory,
        )
        self.assertTrue(
            any(
                "unexplained same-scope drift: tests/unit/rogue_support.py" in item
                for item in supporting_issues
            ),
            supporting_issues,
        )

        (self.host / "tests" / "unit" / "rogue_support.py").unlink()
        write(self.host, "lib/other/secret.js", "nope\n")
        outside = evaluate_cursor_hook(_write_payload(self.host, VAULT_PRODUCT), self.host)
        self.assertEqual(outside["permission"], "deny", outside)
        self.assertIn("out-of-scope", outside.get("reason") or "")
        self.assertEqual(session_id, read_yaml(pointer)["session_id"])

    def test_inherited_baseline_remains_distinct(self):
        self._open()
        allowed = evaluate_cursor_hook(_write_payload(self.host, VAULT_PRODUCT), self.host)
        self.assertEqual(allowed["permission"], "allow", allowed)
        self.assertEqual(
            (self.host / "legacy" / "dirty.txt").read_text(encoding="utf-8"),
            "inherited\n",
        )

    def test_seal_rejects_unexplained_same_scope_delta(self):
        session_id = self._open()
        write(self.host, "src/mvp/rogue.py", "rogue = True\n")
        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "BLOCKED", sealed.blockers)
        self.assertTrue(
            any("unexplained same-scope" in item for item in sealed.blockers),
            sealed.blockers,
        )
        session = read_yaml(self.host / SESSIONS_DIR / session_id / "session.yaml")
        self.assertNotEqual(session.get("status"), "SEALED")

    def test_seal_reconciles_authorized_delta_and_clears_pointer(self):
        self._open()
        evaluate_cursor_hook(_write_payload(self.host, VAULT_PRODUCT), self.host)
        write(self.host, VAULT_PRODUCT, "export const vault = 2\n")
        evaluate_cursor_hook(_after_payload(self.host, VAULT_PRODUCT), self.host)
        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "COMPLETED", sealed.blockers)
        self.assertFalse((self.host / EXECUTION_POINTER_REL).is_file())
        self.assertEqual(
            evaluate_cursor_hook(_write_payload(self.host, VAULT_PRODUCT), self.host)[
                "permission"
            ],
            "deny",
        )
        sessions = load_sealed_sessions(self.host)
        self.assertTrue(sessions)
        files = {row["path"]: row for row in sessions[0]["files"]}
        self.assertIn(VAULT_PRODUCT, files)
        self.assertTrue(files[VAULT_PRODUCT].get("after_digest"))
        self.assertNotIn("legacy/dirty.txt", files)
        delta = classify_delta(
            self.host,
            real_paths=[VAULT_PRODUCT, "legacy/dirty.txt"],
            sessions=sessions,
            task=self.task,
        )
        self.assertEqual(delta["task_delta_classes"][VAULT_PRODUCT], "task_product_delta")

    def test_same_path_post_authorized_content_drift_is_detected(self):
        self._open()
        evaluate_cursor_hook(_write_payload(self.host, VAULT_PRODUCT), self.host)
        write(self.host, VAULT_PRODUCT, "export const vault = 2\n")
        after = evaluate_cursor_hook(_after_payload(self.host, VAULT_PRODUCT), self.host)
        self.assertEqual(after["permission"], "allow", after)
        write(self.host, VAULT_PRODUCT, "export const vault = 3\n")
        rogue = evaluate_cursor_hook(_write_payload(self.host, VAULT_PRODUCT), self.host)
        self.assertEqual(rogue["permission"], "deny", rogue)
        self.assertIn("out of band", rogue.get("reason") or "")

    def test_multiple_raw_open_sessions_without_pointer_deny(self):
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
            "task-20260829T120100Z-bbb22222",
            status="IN_PROGRESS",
            scope=dict(VAULT_SCOPE),
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
        create_session(
            self.host,
            task_id="task-20260829T120100Z-bbb22222",
            mode="normal_task",
            project_name=self.host.name,
            candidate_digest=digest,
        )
        denied = evaluate_cursor_hook(_write_payload(self.host, VAULT_PRODUCT), self.host)
        self.assertEqual(denied["permission"], "deny", denied)
        self.assertIn("execution binding", denied.get("reason") or "")


class R3P6CallerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        from p6_support import write_host

        write_host(self.host, [], ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"})
        write(self.host, VAULT_PRODUCT, "export const vault = true\n")
        write(self.host, VAULT_EVIDENCE, "observed\n")
        self.task = write_task(
            self.host,
            TASK_A,
            status="IN_PROGRESS",
            scope={
                "paths": ["src/mvp"],
                "modules": [],
                "exclude": [],
                "supporting_paths": ["artifacts/evidence/mvp-vault"],
            },
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Keep evidence supporting.",
                    "acceptance": "Evidence remains supporting.",
                    "status": "IN_PROGRESS",
                    "required_tests": [{"requirement_id": "req-vault"}],
                }
            ],
            final_tests=[{"requirement_id": "req-vault"}],
        )
        profile, command = passing_profile("human")
        profile["provenance"] = "HUMAN_OBSERVATION"
        profile["evidence_required"] = ["file_artifact"]
        write_commands(self.host, [command])
        write_tests(self.host, [profile])
        self.candidate = observe_candidate(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def _artifact(self, locator: str, **extra):
        payload = {
            "profile_id": "human",
            "provenance": "HUMAN_OBSERVATION",
            "kind": "file_artifact",
            "locator": locator,
            "candidate_digest": self.candidate.digest,
            "summary": "supporting evidence",
        }
        payload.update(extra)
        return payload

    def test_task_id_ingests_supporting_evidence_without_manufacturing_pass(self):
        result = make_test_engine(self.host).run(
            supplied_evidence=[self._artifact(VAULT_EVIDENCE)],
            task_id=TASK_A,
        )
        evidence = (result.extras or {}).get("report", {}).get("evidence") or []
        self.assertTrue(evidence, result.extras)
        self.assertFalse((result.extras or {}).get("test_pass"))
        completeness = (result.extras or {}).get("completeness") or {}
        self.assertFalse(completeness.get("test_complete"))
        self.assertFalse(completeness.get("test_pass"))

    def test_installed_cli_forwards_task_id(self):
        (self.host / ".scaffold" / "install").mkdir(parents=True, exist_ok=True)
        with patch(
            "scaffold_p5.consumer_install.load_installed_distribution",
            return_value=SimpleNamespace(),
        ), patch("scaffold_p6.engine.TestEngine") as engine_cls:
            instance = engine_cls.return_value
            instance.run.return_value = skill_result(
                skill_id="test",
                skill_version="0",
                mode="scoped_verification",
                outcome="COMPLETED",
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = installed_main(
                    self.host / ".scaffold" / "install",
                    ["test", "scoped_verification", "--task-id", TASK_A],
                )
            self.assertEqual(code, 0, buf.getvalue())
            self.assertEqual(instance.run.call_args.kwargs.get("task_id"), TASK_A)

    def test_develop_handoff_forwards_task_id(self):
        with patch("scaffold_p6.engine.TestEngine") as engine_cls:
            instance = engine_cls.return_value
            instance.run.return_value = SimpleNamespace(
                outcome="COMPLETED", extras={}, blockers=[]
            )
            invoke_test(
                self.host,
                {"task_id": TASK_A, "session_id": "dev-1", "test_requirement": {}},
                test_package=REPO / "skills" / "test",
            )
            self.assertEqual(instance.run.call_args.kwargs.get("task_id"), TASK_A)
            self.assertNotIn("task_book", instance.run.call_args.kwargs)

    def test_submit_completeness_forwards_task_id(self):
        with patch("scaffold_p8.completeness.TestEngine") as engine_cls:
            instance = engine_cls.return_value
            instance.run.return_value = SimpleNamespace(
                outcome="COMPLETED", extras={}
            )
            instance.load_report.return_value = None
            evaluate_completeness(
                self.host,
                task=self.task,
                report=None,
                invoke=True,
                selected=["human"],
                test_package=REPO / "skills" / "test",
            )
            self.assertIsNotNone(instance.run.call_args)
            self.assertEqual(instance.run.call_args.kwargs.get("task_id"), TASK_A)

    def test_sav_and_locator_fail_closed_paths(self):
        compiled, _refs, blockers = compile_supplied_sav_item(
            run_id="tr-fixture",
            profile_id="human",
            candidate=self.candidate,
            supplied=self._artifact(VAULT_EVIDENCE),
            index=0,
            host_root=self.host,
            task=self.task,
        )
        self.assertIsNotNone(compiled)
        self.assertFalse(blockers)

        write(self.host, "lib/other/secret.log", "nope\n")
        _compiled, _refs, out_scope = compile_supplied_sav_item(
            run_id="tr-fixture",
            profile_id="human",
            candidate=self.candidate,
            supplied=self._artifact("lib/other/secret.log"),
            index=1,
            host_root=self.host,
            task=self.task,
        )
        self.assertTrue(out_scope)
        self.assertTrue(any("outside Task supporting scope" in item for item in out_scope))

        governance = supporting_evidence_locator_issues(
            self.host,
            ".scaffold/project.yaml",
            task=self.task,
            kind="file_artifact",
        )
        self.assertTrue(any("governance" in item for item in governance), governance)

        missing = supporting_evidence_locator_issues(
            self.host,
            "artifacts/evidence/mvp-vault/missing.log",
            task=self.task,
            kind="file_artifact",
        )
        self.assertTrue(any("missing" in item for item in missing), missing)

        human = supporting_evidence_locator_issues(
            self.host,
            "",
            task=self.task,
            kind="human_observation",
        )
        self.assertEqual(human, [])
        ci = supporting_evidence_locator_issues(
            self.host,
            "https://ci.example/run/1",
            task=self.task,
            kind="external_ci",
        )
        self.assertEqual(ci, [])

        sav_blocked = make_test_engine(self.host).run(
            task_id=TASK_A,
            sav_evidence=[self._artifact("lib/other/secret.log")],
        )
        report = (sav_blocked.extras or {}).get("report") or {}
        profiles = report.get("profiles") or []
        self.assertTrue(profiles)
        self.assertEqual(profiles[0].get("result"), "BLOCKED")

    def test_string_task_book_is_not_canonical_authority(self):
        result = make_test_engine(self.host).run(
            supplied_evidence=[self._artifact("lib/other/secret.log")],
            task_book=TASK_A,
        )
        evidence = (result.extras or {}).get("report", {}).get("evidence") or []
        self.assertFalse(evidence)


def _session_dir(host: Path) -> Path:
    pointer = read_yaml(host / EXECUTION_POINTER_REL)
    return host / SESSIONS_DIR / str(pointer["session_id"])


def _pre(host: Path, rel: str, *, tool: str = "Write", tool_use_id: str = "", **input_extra) -> dict:
    tool_input = {"path": rel, "contents": "mutated = True\n"}
    tool_input.update(input_extra)
    payload = _hook_payload(
        host,
        hook_event_name="preToolUse",
        tool_name=tool,
        tool_input=tool_input,
    )
    if tool_use_id:
        payload["tool_use_id"] = tool_use_id
    return payload


def _post(host: Path, rel: str, *, tool: str = "Write", tool_use_id: str = "", **input_extra) -> dict:
    tool_input = {"path": rel}
    tool_input.update(input_extra)
    payload = _hook_payload(
        host,
        hook_event_name="postToolUse",
        tool_name=tool,
        tool_input=tool_input,
    )
    if tool_use_id:
        payload["tool_use_id"] = tool_use_id
    return payload


def _fail(host: Path, rel: str, *, tool: str = "Write", tool_use_id: str = "", **input_extra) -> dict:
    tool_input = {"path": rel}
    tool_input.update(input_extra)
    payload = _hook_payload(
        host,
        hook_event_name="postToolUseFailure",
        tool_name=tool,
        tool_input=tool_input,
        failure_type="error",
    )
    if tool_use_id:
        payload["tool_use_id"] = tool_use_id
    return payload


class R3PublishedTaskBindingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write_host(self.host, [passing_profile()], ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"})
        write(self.host, VAULT_PRODUCT, "export const vault = true\n")
        stages = [
            {
                "stage_id": "stage-1",
                "goal": "Keep candidate shared.",
                "acceptance": "Candidate remains shared.",
                "status": "IN_PROGRESS",
                "required_tests": [],
            }
        ]
        scope = {
            "paths": ["src/mvp"],
            "modules": [],
            "exclude": [],
            "supporting_paths": [],
        }
        self.task_a = write_task(
            self.host,
            TASK_A,
            status="IN_PROGRESS",
            scope=dict(scope),
            stages=stages,
        )
        self.task_b = write_task(
            self.host,
            TASK_B,
            status="IN_PROGRESS",
            scope=dict(scope),
            stages=stages,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_published_report_binds_task_and_rejects_other_task(self):
        result = make_test_engine(self.host).run(task_id=TASK_A, selected=["unit"])
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        report = (result.extras or {}).get("report") or {}
        refs = report.get("optional_refs") or {}
        self.assertEqual(refs.get("task_book"), TASK_A)
        report_id = (result.extras or {}).get("report_id")
        self.assertTrue(report_id)
        digest = observe_candidate(self.host).digest
        loaded_a = consume_published_report(self.host, report_id, task=self.task_a)
        self.assertTrue(loaded_a.get("ok"), loaded_a)
        loaded_b = consume_published_report(self.host, report_id, task=self.task_b)
        self.assertFalse(loaded_b.get("ok"), loaded_b)
        self.assertTrue(
            any("bound to a different Task Book" in item for item in loaded_b.get("blockers") or []),
            loaded_b,
        )
        self.assertEqual(observe_candidate(self.host).digest, digest)
        judged_a = evaluate_completeness(
            self.host,
            task=self.task_a,
            report=None,
            invoke=False,
            selected=["unit"],
            test_package=REPO / "skills" / "test",
            report_id=report_id,
        )
        self.assertFalse(
            any(
                "bound to a different Task Book" in item
                for item in judged_a.get("blockers") or []
            ),
            judged_a,
        )
        self.assertTrue(judged_a.get("usable"), judged_a)
        judged_b = evaluate_completeness(
            self.host,
            task=self.task_b,
            report=None,
            invoke=False,
            selected=["unit"],
            test_package=REPO / "skills" / "test",
            report_id=report_id,
        )
        self.assertFalse(judged_b.get("usable"), judged_b)
        self.assertFalse(judged_b.get("test_complete"), judged_b)
        self.assertFalse(judged_b.get("stale_report"), judged_b)
        self.assertTrue(
            any(
                "bound to a different Task Book" in item
                for item in judged_b.get("blockers") or []
            ),
            judged_b,
        )
        self.assertEqual(observe_candidate(self.host).digest, digest)

    def test_stale_published_report_keeps_identity_and_is_not_usable(self):
        result = make_test_engine(self.host).run(task_id=TASK_A, selected=["unit"])
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        report_id = (result.extras or {}).get("report_id")
        write(self.host, VAULT_PRODUCT, "export const vault = stale\n")
        judged = evaluate_completeness(
            self.host,
            task=self.task_a,
            report=None,
            invoke=False,
            selected=["unit"],
            test_package=REPO / "skills" / "test",
            report_id=report_id,
        )
        self.assertEqual(judged.get("report_id"), report_id)
        self.assertTrue(judged.get("stale_report"), judged)
        self.assertFalse(judged.get("usable"), judged)
        self.assertFalse(judged.get("test_complete"), judged)
        self.assertTrue(
            any("stale for the current candidate" in item for item in judged.get("blockers") or []),
            judged,
        )

    def test_missing_published_report_is_not_stale(self):
        judged = evaluate_completeness(
            self.host,
            task=self.task_a,
            report=None,
            invoke=False,
            selected=["unit"],
            test_package=REPO / "skills" / "test",
            report_id="tr-does-not-exist",
        )
        self.assertFalse(judged.get("stale_report"), judged)
        self.assertFalse(judged.get("usable"), judged)
        self.assertTrue(
            any("missing" in item or "invalid" in item for item in judged.get("blockers") or []),
            judged,
        )

    def test_deny_message_names_develop_session_route(self):
        self.assertIn("develop session --task-id", DEVELOP_DENY_MESSAGE)
        self.assertIn("postToolUse", HOOK_EVENTS)
        self.assertIn("postToolUseFailure", HOOK_EVENTS)


class R3MutationTransactionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write(self.host, VAULT_PRODUCT, "export const vault = true\n")
        write(self.host, VAULT_TEST, "assert(true)\n")
        write(self.host, VAULT_EVIDENCE, "ok\n")
        write(self.host, "legacy/dirty.txt", "inherited\n")
        self.task = write_task(
            self.host,
            TASK_A,
            status="IN_PROGRESS",
            scope=dict(VAULT_SCOPE),
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Vault.",
                    "acceptance": "Vault.",
                    "status": "IN_PROGRESS",
                    "required_tests": [],
                }
            ],
        )
        _install_marker(self.host)
        _knowledge(self.host)
        ensure_noscms_accepted_anchor(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def _open(self):
        opened = develop_engine(self.host).open_develop_session(task_id=TASK_A)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        return _session_dir(self.host)

    def _attempts(self, directory: Path) -> list[dict]:
        rows, issues = load_mutation_attempts(directory)
        self.assertFalse(issues, issues)
        return rows or []

    def _files(self, directory: Path) -> list[dict]:
        rows, issues = load_files_yaml(directory)
        self.assertFalse(issues, issues)
        return rows or []

    def test_pre_is_pending_not_provenance(self):
        directory = self._open()
        allowed = evaluate_cursor_hook(_pre(self.host, VAULT_PRODUCT, tool_use_id="tu-pre"), self.host)
        self.assertEqual(allowed["permission"], "allow", allowed)
        attempts = self._attempts(directory)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].get("state"), MUTATION_PENDING)
        self.assertEqual(self._files(directory), [])
        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "BLOCKED", sealed.blockers)
        self.assertTrue(
            any("unresolved pending" in item for item in sealed.blockers),
            sealed.blockers,
        )

    def test_success_and_failure_terminals_and_drift(self):
        directory = self._open()
        evaluate_cursor_hook(_pre(self.host, VAULT_PRODUCT, tool_use_id="tu-ok"), self.host)
        write(self.host, VAULT_PRODUCT, "export const vault = 2\n")
        observed = evaluate_cursor_hook(_post(self.host, VAULT_PRODUCT, tool_use_id="tu-ok"), self.host)
        self.assertEqual(observed["permission"], "allow", observed)
        attempts = self._attempts(directory)
        self.assertEqual(attempts[0].get("state"), MUTATION_OBSERVED)
        files = {row["path"]: row for row in self._files(directory)}
        self.assertEqual(files[VAULT_PRODUCT].get("mutation_state"), MUTATION_OBSERVED)
        self.assertTrue(files[VAULT_PRODUCT].get("after_digest"))

        write(self.host, VAULT_PRODUCT, "export const vault = rogue\n")
        drift = evaluate_cursor_hook(_pre(self.host, VAULT_TEST, tool_use_id="tu-later"), self.host)
        self.assertEqual(drift["permission"], "deny", drift)
        self.assertIn("out of band", drift.get("reason") or "")

    def test_failure_retracts_and_rogue_rewrite_is_blocked(self):
        directory = self._open()
        evaluate_cursor_hook(_pre(self.host, VAULT_PRODUCT, tool_use_id="tu-fail"), self.host)
        failed = evaluate_cursor_hook(_fail(self.host, VAULT_PRODUCT, tool_use_id="tu-fail"), self.host)
        self.assertEqual(failed["permission"], "allow", failed)
        self.assertEqual(self._attempts(directory)[0].get("state"), MUTATION_FAILED)
        self.assertEqual(self._files(directory), [])
        write(self.host, VAULT_PRODUCT, "export const vault = rogue\n")
        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "BLOCKED", sealed.blockers)
        self.assertFalse(any("unresolved pending" in item for item in sealed.blockers), sealed.blockers)

    def test_pre_only_rogue_rewrite_is_not_stamped_at_seal(self):
        directory = self._open()
        evaluate_cursor_hook(_pre(self.host, VAULT_PRODUCT, tool_use_id="tu-pending"), self.host)
        write(self.host, VAULT_PRODUCT, "export const vault = rogue\n")
        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "BLOCKED", sealed.blockers)
        self.assertTrue(
            any("unresolved pending" in item for item in sealed.blockers),
            sealed.blockers,
        )
        self.assertEqual(self._files(directory), [])

    def test_normal_success_seals_and_s2_s3_remain(self):
        directory = self._open()
        evaluate_cursor_hook(_pre(self.host, VAULT_PRODUCT, tool_use_id="tu-e"), self.host)
        write(self.host, VAULT_PRODUCT, "export const vault = 2\n")
        evaluate_cursor_hook(_post(self.host, VAULT_PRODUCT, tool_use_id="tu-e"), self.host)
        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "COMPLETED", sealed.blockers)
        self.assertEqual(self._attempts(directory)[0].get("state"), MUTATION_OBSERVED)
        sessions = load_sealed_sessions(self.host)
        delta = classify_delta(
            self.host,
            real_paths=[VAULT_PRODUCT, "legacy/dirty.txt"],
            sessions=sessions,
            task=self.task,
        )
        self.assertEqual(delta["classes"][VAULT_PRODUCT], "DEVELOP_KNOWN")
        self.assertEqual(delta["task_delta_classes"][VAULT_PRODUCT], "task_product_delta")
        self.assertNotEqual(delta["classes"].get("legacy/dirty.txt"), "DEVELOP_KNOWN")
        self.assertNotEqual(delta["task_delta_classes"].get("legacy/dirty.txt"), "task_product_delta")
        _status, _reasons, project = inspect_host_project(self.host)
        reviewed = review_structure(
            root=self.host,
            task=self.task,
            real_diff=observe_real_diff(self.host),
            project=project,
        )
        self.assertIn("blockers", reviewed)

    def test_replayed_and_unmatched_after_events_do_not_create_provenance(self):
        first = self._open()
        evaluate_cursor_hook(_pre(self.host, VAULT_PRODUCT, tool_use_id="tu-a"), self.host)
        write(self.host, VAULT_PRODUCT, "export const vault = 2\n")
        evaluate_cursor_hook(_after_payload(self.host, VAULT_PRODUCT), self.host)
        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "COMPLETED", sealed.blockers)
        self.assertTrue(self._files(first))

        opened = develop_engine(self.host).open_develop_session(task_id=TASK_A)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        second = _session_dir(self.host)
        replay = evaluate_cursor_hook(_after_payload(self.host, VAULT_PRODUCT), self.host)
        self.assertEqual(replay["permission"], "allow", replay)
        self.assertEqual(self._files(second), [])
        self.assertEqual(self._attempts(second), [])

        unmatched = evaluate_cursor_hook(_after_payload(self.host, VAULT_TEST), self.host)
        self.assertEqual(unmatched["permission"], "allow", unmatched)
        self.assertEqual(self._files(second), [])

    def test_ambiguous_after_event_fails_closed(self):
        directory = self._open()
        evaluate_cursor_hook(_pre(self.host, VAULT_PRODUCT), self.host)
        evaluate_cursor_hook(_pre(self.host, VAULT_PRODUCT), self.host)
        self.assertEqual(len(self._attempts(directory)), 2)
        after = evaluate_cursor_hook(_after_payload(self.host, VAULT_PRODUCT), self.host)
        self.assertEqual(after["permission"], "allow", after)
        self.assertIn("ambiguous", after.get("reason") or "")
        self.assertEqual(self._files(directory), [])
        self.assertTrue(all(row.get("state") == MUTATION_PENDING for row in self._attempts(directory)))

    def test_editor_tool_coverage_and_delete_move(self):
        extra = "src/mvp/temp.js"
        write(self.host, extra, "temp\n")
        directory = self._open()
        tools = [
            ("Write", VAULT_PRODUCT, {"contents": "export const vault = 4\n"}),
            ("Edit", VAULT_PRODUCT, {"contents": "export const vault = 5\n"}),
            ("StrReplace", VAULT_PRODUCT, {"old_string": "5", "new_string": "6"}),
            (
                "ApplyPatch",
                VAULT_PRODUCT,
                {"patch": "*** Update File: src/mvp/vault.js\n"},
            ),
            (
                "MultiEdit",
                VAULT_PRODUCT,
                {"edits": [{"path": VAULT_PRODUCT, "old_string": "x", "new_string": "y"}]},
            ),
        ]
        for index, (tool, rel, tool_extra) in enumerate(tools):
            tool_use_id = f"tu-tool-{index}"
            payload = _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name=tool,
                tool_input={"path": rel, **tool_extra} if tool != "MultiEdit" else tool_extra,
                tool_use_id=tool_use_id,
            )
            allowed = evaluate_cursor_hook(payload, self.host)
            self.assertEqual(allowed["permission"], "allow", (tool, allowed))
            write(self.host, rel, f"export const vault = {index}\n")
            post = _hook_payload(
                self.host,
                hook_event_name="postToolUse",
                tool_name=tool,
                tool_input={"path": rel, **tool_extra} if tool != "MultiEdit" else tool_extra,
                tool_use_id=tool_use_id,
            )
            self.assertEqual(evaluate_cursor_hook(post, self.host)["permission"], "allow", tool)

        notebook = "src/mvp/notes.ipynb"
        evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="EditNotebook",
                tool_input={"target_notebook": notebook, "cell_idx": 0},
                tool_use_id="tu-nb",
            ),
            self.host,
        )
        write(self.host, notebook, '{"cells":[]}\n')
        evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="postToolUse",
                tool_name="EditNotebook",
                tool_input={"target_notebook": notebook},
                tool_use_id="tu-nb",
            ),
            self.host,
        )

        moved = "src/mvp/vault-moved.js"
        evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="Move",
                tool_input={"old_path": VAULT_PRODUCT, "new_path": moved},
                tool_use_id="tu-move",
            ),
            self.host,
        )
        src = self.host / VAULT_PRODUCT
        dest = self.host / moved
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        src.unlink()
        evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="postToolUse",
                tool_name="Move",
                tool_input={"old_path": VAULT_PRODUCT, "new_path": moved},
                tool_use_id="tu-move",
            ),
            self.host,
        )
        files = {row["path"]: row for row in self._files(directory)}
        self.assertEqual(files[VAULT_PRODUCT].get("change_kind"), "deleted")
        self.assertEqual(files[moved].get("mutation_state"), MUTATION_OBSERVED)

        extra = "src/mvp/temp.js"
        evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="Delete",
                tool_input={"path": extra},
                tool_use_id="tu-del",
            ),
            self.host,
        )
        (self.host / extra).unlink()
        evaluate_cursor_hook(_post(self.host, extra, tool="Delete", tool_use_id="tu-del"), self.host)
        files = {row["path"]: row for row in self._files(directory)}
        self.assertEqual(files[extra].get("change_kind"), "deleted")

        evaluate_cursor_hook(_pre(self.host, VAULT_TEST, tool_use_id="tu-del-fail", tool="Delete"), self.host)
        evaluate_cursor_hook(_fail(self.host, VAULT_TEST, tool="Delete", tool_use_id="tu-del-fail"), self.host)
        self.assertTrue(any(row.get("state") == MUTATION_FAILED for row in self._attempts(directory)))
        self.assertNotIn(VAULT_TEST, files)
        evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="Rename",
                tool_input={"old_path": VAULT_TEST, "new_path": "src/mvp/renamed.js"},
                tool_use_id="tu-ren-fail",
            ),
            self.host,
        )
        evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="postToolUseFailure",
                tool_name="Rename",
                tool_input={"old_path": VAULT_TEST, "new_path": "src/mvp/renamed.js"},
                tool_use_id="tu-ren-fail",
                failure_type="error",
            ),
            self.host,
        )
        self.assertTrue(
            any(
                row.get("tool_name") == "Rename" and row.get("state") == MUTATION_FAILED
                for row in self._attempts(directory)
            )
        )

        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "COMPLETED", sealed.blockers)

    def test_p8_pending_and_failed_are_not_develop_known(self):
        pending_sessions = [
            {
                "session": {"record_id": "dev-pending", "status": "SEALED"},
                "files": [
                    {
                        "path": VAULT_PRODUCT,
                        "mutation_state": MUTATION_PENDING,
                        "change_kind": "modified",
                        "was_preexisting_dirty": False,
                        "before_kind": "regular_file",
                        "after_kind": "missing",
                        "before_digest": "sha256:" + ("a" * 64),
                        "after_digest": None,
                    }
                ],
            }
        ]
        pending = classify_delta(
            self.host,
            real_paths=[VAULT_PRODUCT],
            sessions=pending_sessions,
            task=self.task,
        )
        self.assertNotEqual(pending["classes"][VAULT_PRODUCT], "DEVELOP_KNOWN")
        failed_sessions = [
            {
                "session": {"record_id": "dev-failed", "status": "SEALED"},
                "files": [
                    {
                        "path": VAULT_PRODUCT,
                        "mutation_state": MUTATION_FAILED,
                        "change_kind": "modified",
                        "was_preexisting_dirty": False,
                        "before_kind": "regular_file",
                        "after_kind": "regular_file",
                        "before_digest": "sha256:" + ("a" * 64),
                        "after_digest": "sha256:" + ("b" * 64),
                    }
                ],
            }
        ]
        failed = classify_delta(
            self.host,
            real_paths=[VAULT_PRODUCT],
            sessions=failed_sessions,
            task=self.task,
        )
        self.assertNotEqual(failed["classes"][VAULT_PRODUCT], "DEVELOP_KNOWN")
        cancelled_sessions = [
            {
                "session": {"record_id": "dev-cancelled", "status": "SEALED"},
                "files": [
                    {
                        "path": VAULT_PRODUCT,
                        "mutation_state": MUTATION_CANCELLED,
                        "change_kind": "modified",
                        "was_preexisting_dirty": False,
                        "before_kind": "regular_file",
                        "after_kind": "regular_file",
                        "before_digest": "sha256:" + ("a" * 64),
                        "after_digest": "sha256:" + ("b" * 64),
                    }
                ],
            }
        ]
        cancelled = classify_delta(
            self.host,
            real_paths=[VAULT_PRODUCT],
            sessions=cancelled_sessions,
            task=self.task,
        )
        self.assertNotEqual(cancelled["classes"][VAULT_PRODUCT], "DEVELOP_KNOWN")


if __name__ == "__main__":
    unittest.main()

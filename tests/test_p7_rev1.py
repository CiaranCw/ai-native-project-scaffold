from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import CORE_OWNERSHIP
from p7_support import (
    TASK_A,
    TASK_B,
    develop_engine,
    ready_lifecycle_opts,
    repair_handoff,
    write_active_host,
    write_task,
)
from support import write
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p6.candidate import observe_candidate, report_usable_for
from scaffold_p6.engine import TestEngine
from scaffold_p7.models import SESSIONS_DIR
from scaffold_p7.session import create_session
from support import REPO


SESSION_A = "dev-20260830T180000Z-abcd1234"


class P7Rev1Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_E01_malformed_scope_paths_container_blocks(self):
        write_active_host(self.host)
        write_task(self.host, scope={"paths": {"src/app.py": False}, "modules": [], "exclude": []})
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("scope.paths" in item for item in result.blockers))

    def test_E02_malformed_scope_modules_or_exclude_blocks(self):
        write_active_host(self.host)
        write_task(self.host, scope={"paths": ["src/app.py"], "modules": "app", "exclude": []})
        modules = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(modules.outcome, "BLOCKED")
        self.assertTrue(any("scope.modules" in item for item in modules.blockers))
        write_task(self.host, scope={"paths": ["src/app.py"], "modules": [], "exclude": {"src/app.py": True}})
        excluded = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(excluded.outcome, "BLOCKED")
        self.assertTrue(any("scope.exclude" in item for item in excluded.blockers))

    def test_E03_malformed_final_tests_entry_blocks(self):
        write_active_host(self.host)
        write_task(self.host, final_tests={"unit": "PASS"})
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("final_tests" in item for item in result.blockers))

    def test_E04_malformed_stage_required_tests_blocks(self):
        write_active_host(self.host)
        write_task(
            self.host,
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Write the fixture source.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "PENDING",
                    "required_tests": {"unit": True},
                }
            ],
        )
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("required_tests" in item for item in result.blockers))

    def test_E05_malformed_develop_session_ids_blocks(self):
        write_active_host(self.host)
        write_task(self.host, develop_session_ids=["not-a-session-id"])
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("develop_session_ids" in item for item in result.blockers))

    def test_E06_valid_p3_task_book_remains_executable(self):
        write_active_host(self.host)
        write_task(self.host)
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.extras["task"]["record_id"], TASK_A)

    def test_E07_open_session_missing_candidate_binding_blocks(self):
        write_active_host(self.host)
        write_task(self.host)
        self._write_session(omit=["observed_candidate_digest"])
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            session_id=SESSION_A,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(
            any("observed_candidate_digest" in item or "malformed" in item for item in result.blockers)
        )

    def test_E08_session_cannot_resume_after_candidate_change(self):
        write_active_host(self.host)
        write_task(self.host)
        created = create_session(
            self.host,
            task_id=TASK_A,
            mode="normal_task",
            project_name=self.host.name,
            candidate_digest=observe_candidate(self.host).digest,
        )
        write(self.host, "README.md", "# P7 host changed\n")
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            session_id=created.session["record_id"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("different candidate" in item for item in result.blockers))

    def test_E09_missing_files_yaml_fails_closed(self):
        write_active_host(self.host)
        write_task(self.host)
        self._write_session(write_files=False)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            session_id=SESSION_A,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("files.yaml is missing" in item for item in result.blockers))

    def test_E10_malformed_files_yaml_fails_closed(self):
        write_active_host(self.host)
        write_task(self.host)
        directory = self._write_session()
        write_yaml_atomic(directory / "files.yaml", {"files": "not-a-list"})
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            session_id=SESSION_A,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("files.yaml" in item for item in result.blockers))

    def test_E11_valid_open_session_with_matching_bindings_may_resume(self):
        write_active_host(self.host)
        write_task(self.host)
        created = create_session(
            self.host,
            task_id=TASK_A,
            mode="normal_task",
            project_name=self.host.name,
            candidate_digest=observe_candidate(self.host).digest,
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            session_id=created.session["record_id"],
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.extras["session"]["record_id"], created.session["record_id"])
        self.assertEqual(result.extras["session"]["status"], "SEALED")

    def test_E12_repair_handoff_missing_task_binding_blocks(self):
        write_active_host(self.host)
        write_task(self.host)
        handoff = repair_handoff(
            task_id=TASK_A,
            candidate_digest=observe_candidate(self.host).digest,
        )
        del handoff["task_id"]
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            test_to_develop=handoff,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("missing task binding" in item for item in result.blockers))

    def test_E13_repair_handoff_bound_to_different_task_blocks(self):
        write_active_host(self.host)
        write_task(self.host)
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            test_to_develop=repair_handoff(
                task_id=TASK_B,
                candidate_digest=observe_candidate(self.host).digest,
            ),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("different Task Book" in item for item in result.blockers))

    def test_E14_repair_handoff_missing_candidate_binding_blocks(self):
        write_active_host(self.host)
        write_task(self.host)
        handoff = {
            "kind": "test_to_develop",
            "task_id": TASK_A,
            "test_pass": False,
            "blockers": ["required verification failed"],
        }
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            test_to_develop=handoff,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("missing candidate binding" in item for item in result.blockers))

    def test_E15_stale_repair_candidate_blocks_before_mutation(self):
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write_task(self.host)
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            test_to_develop=repair_handoff(
                task_id=TASK_A,
                candidate_digest="stale-candidate-digest",
            ),
            writes=[{"path": "src/app.py", "content": "should-not-write\n"}],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("does not match the current workspace" in item for item in result.blockers))
        self.assertFalse((self.host / "src/app.py").exists())
        self.assertFalse((self.host / SESSIONS_DIR).exists())
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(task["stages"][0]["status"], "PENDING")

    def test_E16_valid_current_candidate_failure_handoff_may_repair(self):
        write_active_host(self.host)
        write_task(self.host)
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            test_to_develop=repair_handoff(
                task_id=TASK_A,
                candidate_digest=observe_candidate(self.host).digest,
            ),
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.mode, "repair")

    def test_E17_material_repair_invalidates_previous_test_evidence(self):
        from p6_support import passing_profile, write_host
        from p7_support import bind_develop_lock

        profile, command = passing_profile("unit")
        write_host(self.host, [(profile, command)])
        bind_develop_lock(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        write_task(self.host)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        project["ownership"] = {**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"}
        project["source_areas"] = ["src"]
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        test = TestEngine(self.host, REPO / "skills" / "test").run(
            "scoped_verification",
            selected=["unit"],
        )
        report = test.extras["report"]
        before = observe_candidate(self.host)
        self.assertTrue(report_usable_for(report, before))
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            test_to_develop=repair_handoff(
                task_id=TASK_A,
                candidate_digest=before.digest,
                report=report,
            ),
            writes=[{"path": "src/app.py", "content": "value = 2\n"}],
        )
        self.assertEqual(result.outcome, "COMPLETED")
        after = observe_candidate(self.host)
        self.assertTrue(result.extras["stale_test_invalidated"])
        self.assertFalse(report_usable_for(report, after))

    def test_E18_unauthorized_write_does_not_advance_task_or_open_session(self):
        write_active_host(self.host)
        write_task(self.host)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "x\n"}],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.mutations, "none")
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(task["stages"][0]["status"], "PENDING")
        self.assertEqual(task["develop_session_ids"], [])
        self.assertFalse((self.host / SESSIONS_DIR).exists())

    def test_E19_late_block_aborts_started_session(self):
        write_active_host(self.host)
        write_task(self.host)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            request_ready_for_review=True,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        session = result.extras["session"]
        self.assertEqual(session["status"], "ABORTED")
        stored = read_yaml(
            self.host / SESSIONS_DIR / session["record_id"] / "session.yaml"
        )
        self.assertEqual(stored["status"], "ABORTED")

    def test_E20_blocked_result_reports_actual_task_mutation(self):
        write_active_host(self.host)
        write_task(self.host)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            request_ready_for_review=True,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertNotEqual(result.mutations, "none")
        self.assertEqual(result.mutations, "task_book")

    def test_E21_successful_source_mutation_reports_source(self):
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write_task(self.host)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "ok = True\n"}],
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.mutations, "source")

    def test_E22_legitimate_ready_for_review_transition_and_route(self):
        write_active_host(self.host)
        write_task(
            self.host,
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Write the fixture source.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "COMPLETE",
                    "required_tests": [],
                }
            ],
            final_tests=[],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            request_ready_for_review=True,
            **ready_lifecycle_opts(),
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue(result.extras["ready_for_review"])
        self.assertEqual(result.next_route, "submit")
        self.assertEqual(result.extras["submit_handoff"]["kind"], "develop_to_submit")
        self.assertFalse(result.extras["submit_authorized"])
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(task["status"], "READY_FOR_REVIEW")

    def test_E23_missing_ready_for_review_gate_blocks(self):
        write_active_host(self.host)
        write_task(self.host)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            request_ready_for_review=True,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["ready_for_review"])
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(task["status"], "IN_PROGRESS")

    def test_E24_test_pass_alone_does_not_set_ready_for_review(self):
        from p6_support import passing_profile, write_host
        from p7_support import bind_develop_lock

        profile, command = passing_profile("unit")
        write_host(self.host, [(profile, command)])
        bind_develop_lock(self.host)
        write_task(self.host)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertTrue(result.extras["test_pass"])
        self.assertFalse(result.extras["ready_for_review"])
        self.assertIsNone(result.extras["submit_handoff"])
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(task["status"], "IN_PROGRESS")

    def _write_session(self, *, omit: list[str] | None = None, write_files: bool = True):
        directory = self.host / SESSIONS_DIR / SESSION_A
        directory.mkdir(parents=True, exist_ok=True)
        data = {
            "record_type": "develop_session",
            "schema_version": "1",
            "record_id": SESSION_A,
            "created_at": "2026-08-30T18:00:00Z",
            "updated_at": "2026-08-30T18:00:00Z",
            "status": "OPEN",
            "task_id": TASK_A,
            "mode": "normal_task",
            "project_name": self.host.name,
            "baseline": {"kind": "none", "value": None},
            "workspace_overlay_s0": {"coverage": "unavailable", "paths": []},
            "observed_candidate_digest": observe_candidate(self.host).digest,
        }
        for key in omit or []:
            data.pop(key, None)
        write_yaml_atomic(directory / "session.yaml", data)
        if write_files:
            write_yaml_atomic(directory / "files.yaml", {"files": []})
        return directory

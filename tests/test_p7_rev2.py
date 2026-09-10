from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import CORE_OWNERSHIP, passing_profile, write_host
from p7_support import (
    TASK_A,
    bind_develop_lock,
    develop_engine,
    ready_lifecycle_opts,
    write_active_host,
    write_task,
)
from support import REPO
from scaffold_p5.io_util import read_text, read_yaml
from scaffold_p6.candidate import observe_candidate, report_usable_for
from scaffold_p6.engine import TestEngine
from scaffold_p7.models import SESSIONS_DIR
from scaffold_p7.tasks import publish_task


COMPLETE_STAGES = [
    {
        "stage_id": "stage-1",
        "goal": "Write the fixture source.",
        "acceptance": "src/app.py has the expected content.",
        "status": "COMPLETE",
        "required_tests": [],
    }
]
FINAL_PASS: list[dict] = []


class P7Rev2Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_F01_expected_revision_publishes_exact_next_revision(self):
        write_active_host(self.host)
        write_task(self.host)
        path = self._task_path()
        current = read_yaml(path)
        self.assertEqual(current["record_revision"], 1)
        updated = dict(current)
        updated["title"] = "published-from-n"
        result = publish_task(path, updated, expected_revision=1)
        self.assertTrue(result.ok)
        self.assertFalse(result.conflict)
        self.assertEqual(result.expected_revision, 1)
        self.assertEqual(result.published_revision, 2)
        stored = read_yaml(path)
        self.assertEqual(stored["record_revision"], 2)
        self.assertEqual(stored["title"], "published-from-n")

    def test_F02_second_writer_from_same_revision_conflicts(self):
        write_active_host(self.host)
        write_task(self.host)
        path = self._task_path()
        snapshot = read_yaml(path)
        writer_a = dict(snapshot)
        writer_a["title"] = "writer-A"
        first = publish_task(path, writer_a, expected_revision=1)
        self.assertTrue(first.ok)
        writer_b = dict(snapshot)
        writer_b["title"] = "writer-B"
        second = publish_task(path, writer_b, expected_revision=1)
        self.assertFalse(second.ok)
        self.assertTrue(second.conflict)
        self.assertEqual(second.expected_revision, 1)
        self.assertEqual(second.actual_revision, 2)
        stored = read_yaml(path)
        self.assertEqual(stored["title"], "writer-A")
        self.assertEqual(stored["record_revision"], 2)
        self.assertNotEqual(stored["title"], "writer-B")

    def test_F03_stale_publication_does_not_merge_or_overwrite(self):
        write_active_host(self.host)
        write_task(self.host)
        path = self._task_path()
        snapshot = read_yaml(path)
        writer_a = dict(snapshot)
        writer_a["title"] = "authoritative-title"
        writer_a["goal"] = "authoritative-goal"
        first = publish_task(path, writer_a, expected_revision=1)
        self.assertTrue(first.ok)
        stale = dict(snapshot)
        stale["title"] = "stale-title"
        stale["goal"] = "stale-goal"
        second = publish_task(path, stale, expected_revision=1)
        self.assertFalse(second.ok)
        self.assertTrue(second.conflict)
        stored = read_yaml(path)
        self.assertEqual(stored["title"], "authoritative-title")
        self.assertEqual(stored["goal"], "authoritative-goal")
        self.assertNotEqual(stored["title"], "stale-title")
        self.assertNotEqual(stored["goal"], "stale-goal")

    def test_F04_one_publication_increments_revision_once(self):
        write_active_host(self.host)
        write_task(self.host)
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "COMPLETED")
        stored = read_yaml(self._task_path())
        self.assertEqual(stored["record_revision"], 2)
        self.assertEqual(result.extras["task"]["record_revision"], 2)
        self.assertEqual(stored["stages"][0]["status"], "IN_PROGRESS")
        self.assertEqual(len(stored["develop_session_ids"]), 1)

    def test_F05_first_publication_conflict_blocks_source_and_aborts_session(self):
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write_task(self.host)

        def compete():
            path = self._task_path()
            snapshot = read_yaml(path)
            updated = dict(snapshot)
            updated["title"] = "competing-first"
            published = publish_task(path, updated, expected_revision=1)
            self.assertTrue(published.ok)

        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "should-not-write\n"}],
            before_first_task_publish=compete,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.extras["task_publication"]["conflict"])
        self.assertEqual(result.extras["task_publication"]["expected_revision"], 1)
        self.assertEqual(result.mutations, "none")
        self.assertFalse((self.host / "src/app.py").exists())
        stored = read_yaml(self._task_path())
        self.assertEqual(stored["title"], "competing-first")
        self.assertEqual(stored["record_revision"], 2)
        self.assertEqual(stored["stages"][0]["status"], "PENDING")
        self.assertEqual(stored["develop_session_ids"], [])
        session = result.extras["session"]
        self.assertEqual(session["status"], "ABORTED")
        persisted = read_yaml(
            self.host / SESSIONS_DIR / session["record_id"] / "session.yaml"
        )
        self.assertEqual(persisted["status"], "ABORTED")
        self.assertNotEqual(persisted["status"], "OPEN")

    def test_F06_ready_publication_uses_revision_after_prior_publication(self):
        write_active_host(self.host)
        write_task(self.host, stages=COMPLETE_STAGES, final_tests=FINAL_PASS)
        seen = {}

        def capture():
            seen["before_ready"] = read_yaml(self._task_path())["record_revision"]

        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            request_ready_for_review=True,
            **ready_lifecycle_opts(),
            before_ready_task_publish=capture,
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(seen["before_ready"], 2)
        stored = read_yaml(self._task_path())
        self.assertEqual(stored["record_revision"], 3)
        self.assertEqual(stored["status"], "READY_FOR_REVIEW")
        self.assertEqual(result.extras["task"]["record_revision"], 3)

    def test_F07_ready_revision_conflict_does_not_handoff(self):
        write_active_host(self.host)
        write_task(self.host, stages=COMPLETE_STAGES, final_tests=FINAL_PASS)

        def compete():
            path = self._task_path()
            current = read_yaml(path)
            updated = dict(current)
            updated["title"] = "late-writer"
            published = publish_task(
                path, updated, expected_revision=current["record_revision"]
            )
            self.assertTrue(published.ok)

        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            request_ready_for_review=True,
            **ready_lifecycle_opts(),
            before_ready_task_publish=compete,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.extras["task_publication"]["conflict"])
        self.assertEqual(result.extras["task_publication"]["expected_revision"], 2)
        self.assertIsNone(result.extras["submit_handoff"])
        self.assertNotEqual(result.next_route, "submit")
        self.assertFalse(result.extras["ready_for_review"])
        stored = read_yaml(self._task_path())
        self.assertEqual(stored["title"], "late-writer")
        self.assertEqual(stored["status"], "IN_PROGRESS")
        self.assertNotEqual(stored["status"], "READY_FOR_REVIEW")

    def test_F08_late_ready_conflict_keeps_source_mutation(self):
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write_task(self.host, stages=COMPLETE_STAGES, final_tests=FINAL_PASS)

        def compete():
            path = self._task_path()
            current = read_yaml(path)
            updated = dict(current)
            updated["title"] = "late-writer-after-source"
            published = publish_task(
                path, updated, expected_revision=current["record_revision"]
            )
            self.assertTrue(published.ok)

        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "kept = True\n"}],
            request_ready_for_review=True,
            **ready_lifecycle_opts(),
            before_ready_task_publish=compete,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.extras["task_publication"]["conflict"])
        self.assertEqual(result.mutations, "source")
        self.assertEqual(read_text(self.host / "src/app.py"), "kept = True\n")
        self.assertIsNone(result.extras["submit_handoff"])
        stored = read_yaml(self._task_path())
        self.assertEqual(stored["status"], "IN_PROGRESS")
        session = result.extras["session"]
        self.assertEqual(session["status"], "ABORTED")

    def test_F09_ready_transition_changes_candidate_identity(self):
        write_active_host(self.host)
        write_task(self.host, stages=COMPLETE_STAGES, final_tests=FINAL_PASS)
        seen = {}

        def capture():
            seen["before_ready"] = observe_candidate(self.host).digest

        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            request_ready_for_review=True,
            **ready_lifecycle_opts(),
            before_ready_task_publish=capture,
        )
        self.assertEqual(result.outcome, "COMPLETED")
        current = observe_candidate(self.host)
        # FA2-FND-003: READY control-plane publication is candidate-neutral.
        self.assertEqual(seen["before_ready"], current.digest)
        self.assertEqual(result.extras["candidate"]["candidate_digest"], current.digest)
        stored = read_yaml(self._task_path())
        self.assertEqual(stored["status"], "READY_FOR_REVIEW")

    def test_F10_submit_handoff_uses_fresh_post_ready_candidate(self):
        write_active_host(self.host)
        write_task(self.host, stages=COMPLETE_STAGES, final_tests=FINAL_PASS)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            request_ready_for_review=True,
            **ready_lifecycle_opts(),
        )
        self.assertEqual(result.outcome, "COMPLETED")
        current = observe_candidate(self.host)
        self.assertEqual(
            result.extras["submit_handoff"]["candidate_digest"],
            current.digest,
        )

    def test_F11_result_extras_describe_post_ready_candidate(self):
        write_active_host(self.host)
        write_task(self.host, stages=COMPLETE_STAGES, final_tests=FINAL_PASS)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            request_ready_for_review=True,
            **ready_lifecycle_opts(),
        )
        self.assertEqual(result.outcome, "COMPLETED")
        current = observe_candidate(self.host)
        self.assertEqual(result.extras["candidate"]["candidate_digest"], current.digest)
        self.assertEqual(result.baseline["candidate_digest"], current.digest)
        self.assertEqual(
            result.extras["submit_handoff"]["candidate_digest"],
            result.extras["candidate"]["candidate_digest"],
        )

    def test_F12_pre_ready_test_evidence_keeps_original_candidate(self):
        profile, command = passing_profile("unit")
        write_host(self.host, [(profile, command)])
        bind_develop_lock(self.host)
        write_task(self.host, stages=COMPLETE_STAGES, final_tests=FINAL_PASS)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            request_ready_for_review=True,
            **ready_lifecycle_opts(),
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue(result.extras["test_pass"])
        develop_to_test = result.extras["develop_to_test"]
        test_to_develop = result.extras["test_to_develop"]
        submit = result.extras["submit_handoff"]
        current = observe_candidate(self.host)
        self.assertEqual(submit["candidate_digest"], current.digest)
        self.assertEqual(
            develop_to_test["candidate_digest"],
            submit["candidate_digest"],
        )
        self.assertEqual(
            test_to_develop["candidate_digest"],
            develop_to_test["candidate_digest"],
        )
        report = TestEngine(self.host, REPO / "skills" / "test").load_report(
            test_to_develop["report_id"]
        )
        self.assertIsNotNone(report)
        bound = (report.get("candidate") or {}).get("candidate_digest")
        self.assertEqual(bound, develop_to_test["candidate_digest"])
        self.assertEqual(bound, current.digest)
        self.assertTrue(report_usable_for(report, current))
        self.assertTrue(result.extras["test_report_usable_for_current"])

    def _task_path(self) -> Path:
        return self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"

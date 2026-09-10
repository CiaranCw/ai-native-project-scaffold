from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import CORE_OWNERSHIP
from p7_support import TASK_A, develop_engine, ready_lifecycle_opts, write_active_host, write_task
from scaffold_p5.io_util import read_text, read_yaml
from scaffold_p6.candidate import observe_candidate
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


class P7ClosureTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_G01_first_conflict_returns_current_task_and_fresh_candidate(self):
        write_active_host(self.host)
        write_task(self.host)
        before = observe_candidate(self.host)

        def compete():
            self._publish_competing_title("competing-first", expected=1)

        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            before_first_task_publish=compete,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.extras["task_publication"]["conflict"])
        fresh = observe_candidate(self.host)
        self.assertNotEqual(before.digest, fresh.digest)
        self.assertEqual(result.extras["candidate"]["candidate_digest"], fresh.digest)
        self.assertEqual(result.baseline["candidate_digest"], fresh.digest)
        stored = read_yaml(self._task_path())
        self.assertEqual(stored["title"], "competing-first")
        self.assertEqual(result.extras["task"]["record_revision"], stored["record_revision"])
        self.assertEqual(result.extras["task"]["status"], stored["status"])
        self.assertEqual(result.extras["task"]["record_id"], TASK_A)

    def test_G02_first_conflict_does_not_attribute_competing_mutation(self):
        write_active_host(self.host)
        write_task(self.host)

        def compete():
            self._publish_competing_title("competing-first", expected=1)

        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            before_first_task_publish=compete,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.mutations, "none")
        session = result.extras["session"]
        self.assertEqual(session["status"], "ABORTED")
        persisted = read_yaml(
            self.host / SESSIONS_DIR / session["record_id"] / "session.yaml"
        )
        self.assertEqual(persisted["status"], "ABORTED")
        self.assertNotEqual(persisted["status"], "OPEN")

    def test_G03_ready_conflict_uses_fresh_candidate_and_does_not_handoff(self):
        write_active_host(self.host)
        write_task(self.host, stages=COMPLETE_STAGES, final_tests=FINAL_PASS)
        seen = {}

        def compete():
            seen["before_ready"] = observe_candidate(self.host).digest
            current = read_yaml(self._task_path())
            self._publish_competing_title(
                "late-writer", expected=current["record_revision"]
            )

        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            request_ready_for_review=True,
            **ready_lifecycle_opts(),
            before_ready_task_publish=compete,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.extras["task_publication"]["conflict"])
        fresh = observe_candidate(self.host)
        self.assertNotEqual(seen["before_ready"], fresh.digest)
        self.assertEqual(result.extras["candidate"]["candidate_digest"], fresh.digest)
        self.assertEqual(result.baseline["candidate_digest"], fresh.digest)
        self.assertIsNone(result.extras["submit_handoff"])
        self.assertNotEqual(result.next_route, "submit")
        self.assertFalse(result.extras["ready_for_review"])
        self.assertFalse(result.extras["submit_authorized"])
        stored = read_yaml(self._task_path())
        self.assertEqual(stored["title"], "late-writer")
        self.assertEqual(stored["status"], "IN_PROGRESS")
        self.assertNotEqual(stored["status"], "READY_FOR_REVIEW")
        self.assertEqual(result.extras["task"]["status"], "IN_PROGRESS")

    def test_G04_ready_conflict_keeps_source_and_honest_mutations(self):
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write_task(self.host, stages=COMPLETE_STAGES, final_tests=FINAL_PASS)
        seen = {}

        def compete():
            seen["before_ready"] = observe_candidate(self.host).digest
            current = read_yaml(self._task_path())
            self._publish_competing_title(
                "late-writer-after-source", expected=current["record_revision"]
            )

        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "kept = True\n"}],
            request_ready_for_review=True,
            **ready_lifecycle_opts(),
            before_ready_task_publish=compete,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.mutations, "source")
        self.assertEqual(read_text(self.host / "src/app.py"), "kept = True\n")
        fresh = observe_candidate(self.host)
        self.assertNotEqual(seen["before_ready"], fresh.digest)
        self.assertEqual(result.extras["candidate"]["candidate_digest"], fresh.digest)
        self.assertEqual(result.baseline["candidate_digest"], fresh.digest)
        self.assertIsNone(result.extras["submit_handoff"])
        stored = read_yaml(self._task_path())
        self.assertEqual(stored["title"], "late-writer-after-source")
        self.assertEqual(stored["status"], "IN_PROGRESS")

    def _task_path(self) -> Path:
        return self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"

    def _publish_competing_title(self, title: str, *, expected: int) -> None:
        path = self._task_path()
        current = read_yaml(path)
        updated = dict(current)
        updated["title"] = title
        published = publish_task(path, updated, expected_revision=expected)
        self.assertTrue(published.ok)

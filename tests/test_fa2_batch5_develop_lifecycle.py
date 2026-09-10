from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import CORE_OWNERSHIP, failing_profile, passing_profile, write_host
from p7_support import (
    TASK_A,
    TASK_B,
    bind_develop_lock,
    develop_engine,
    ready_lifecycle_opts,
    repair_handoff,
    satisfied_decision,
    submit_repair_handoff,
    write_active_host,
    write_task,
)
from p8_support import (
    bind_ready_completion_authority,
    submit_engine,
    write_ready_task,
    write_submit_host,
)
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.engine import TestEngine
from scaffold_p7.intake import prepare_proposal, proposal_digest, task_proposal
from scaffold_p7.tasks import publish_task
from scaffold_p8.delta import observe_real_diff
from scaffold_p8.handoff import UNRESOLVED_REPAIR_REASON
from support import REPO, write


TASK_REQUIREMENT = "task-required/check-save"
TEST_PROFILE = "unit-save-check"


def explicit_ref(
    requirement_id: str = TASK_REQUIREMENT,
    profile_id: str = TEST_PROFILE,
) -> dict:
    return {
        "requirement_id": requirement_id,
        "execution_binding": {"kind": "test_profile", "profile_id": profile_id},
    }


class FA2Batch5DevelopLifecycleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_B5D01_normal_stage_completion(self):
        self._prepare_test_host()
        write_task(
            self.host,
            stages=[self._in_progress_stage(required=True)],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "value = 1\n"}],
            invoke_test=True,
            selected=[TEST_PROFILE],
            request_stage_complete=True,
            stage_completion_decision=satisfied_decision(
                stage_id="stage-1",
                basis=[
                    {
                        "kind": "repository_observation",
                        "summary": "src/app.py has the expected content.",
                    },
                    {
                        "kind": "test_evidence",
                        "summary": "Required Stage verification passed for this candidate.",
                    },
                ]
            ),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        task = self._task()
        stage = task["stages"][0]
        self.assertEqual(stage["status"], "COMPLETE")
        decision = stage["completion_decision"]
        self.assertEqual(decision["outcome"], "SATISFIED")
        self.assertEqual(task["record_revision"], 3)
        self.assertGreater(task["record_revision"], 1)
        locators = [
            item.get("evidence_ref", {}).get("locator")
            for item in decision.get("basis") or []
            if isinstance(item, dict)
        ]
        self.assertTrue(any(str(item).startswith("test-runs/") for item in locators))

    def test_B5D02_task_ready(self):
        self._prepare_test_host()
        write_task(
            self.host,
            stages=[self._in_progress_stage(required=True)],
            final_tests=[explicit_ref()],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "value = 1\n"}],
            invoke_test=True,
            selected=[TEST_PROFILE],
            request_stage_complete=True,
            request_ready_for_review=True,
            stage_completion_decision=satisfied_decision(
                stage_id="stage-1",
                basis=[
                    {
                        "kind": "repository_observation",
                        "summary": "src/app.py has the expected content.",
                    },
                    {
                        "kind": "test_evidence",
                        "summary": "Required Stage verification passed.",
                    },
                ]
            ),
            task_completion_decision=satisfied_decision(
                basis=[
                    {
                        "kind": "task_fact",
                        "summary": "Stage acceptance and Task-level acceptance are satisfied.",
                    },
                    {
                        "kind": "test_evidence",
                        "summary": "Final required verification passed.",
                    },
                ]
            ),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        task = self._task()
        self.assertEqual(task["status"], "READY_FOR_REVIEW")
        self.assertEqual(task["stages"][0]["status"], "COMPLETE")
        self.assertEqual(task["task_completion_decision"]["outcome"], "SATISFIED")
        self.assertFalse(result.extras["submit_authorized"])
        self.assertEqual(result.extras["submit_handoff"]["kind"], "develop_to_submit")

    def test_B5D03_test_pass_is_not_stage_complete(self):
        self._prepare_test_host()
        write_task(
            self.host,
            stages=[self._in_progress_stage(required=True)],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "value = 1\n"}],
            invoke_test=True,
            selected=[TEST_PROFILE],
            request_stage_complete=True,
            stage_completion_decision={
                "stage_id": "stage-1",
                "outcome": "UNKNOWN",
                "rationale": "Stage acceptance remains UNKNOWN despite TEST_PASS.",
                "basis": [
                    {
                        "kind": "task_fact",
                        "summary": "TEST_PASS is not a Stage Completion Decision.",
                    }
                ],
            },
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras["test_pass"])
        self.assertEqual(self._task()["stages"][0]["status"], "IN_PROGRESS")
        self.assertNotEqual(self._task()["stages"][0]["status"], "COMPLETE")

    def test_B5D04_task_decision_unknown_is_not_ready(self):
        write_active_host(self.host)
        write_task(
            self.host,
            stages=[self._complete_stage()],
            final_tests=[],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            request_ready_for_review=True,
            stage_completion_decision=satisfied_decision(stage_id="stage-1"),
            task_completion_decision={
                "outcome": "UNKNOWN",
                "rationale": "Task-level acceptance cannot be established.",
                "basis": [
                    {
                        "kind": "task_fact",
                        "summary": "Stage completeness is not Task-level acceptance.",
                    }
                ],
            },
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(self._task()["status"], "IN_PROGRESS")
        self.assertNotEqual(self._task()["status"], "READY_FOR_REVIEW")

    def test_B5D05_required_fail_blocks_completion(self):
        self._prepare_test_host(failing=True)
        write_task(
            self.host,
            stages=[self._in_progress_stage(required=True)],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "value = 1\n"}],
            invoke_test=True,
            selected=[TEST_PROFILE],
            request_stage_complete=True,
            request_ready_for_review=True,
            stage_completion_decision=satisfied_decision(stage_id="stage-1"),
            task_completion_decision=satisfied_decision(),
        )
        self.assertNotEqual(self._task()["stages"][0]["status"], "COMPLETE")
        self.assertNotEqual(self._task()["status"], "READY_FOR_REVIEW")
        self.assertEqual(result.outcome, "BLOCKED")

    def test_B5D06_unresolved_required_test_blocks_completion(self):
        self._prepare_test_host()
        write_task(
            self.host,
            stages=[self._in_progress_stage(required=True)],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "value = 1\n"}],
            request_stage_complete=True,
            stage_completion_decision=satisfied_decision(stage_id="stage-1"),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(self._task()["stages"][0]["status"], "IN_PROGRESS")

    def test_B5D07_stale_stage_decision_cannot_complete(self):
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write_task(
            self.host,
            stages=[
                self._in_progress_stage(
                    completion_decision=satisfied_decision(
                        candidate_digest="sha256:" + ("c1" * 32),
                    )
                )
            ],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "value = 1\n"}],
            request_stage_complete=True,
            stage_completion_decision=satisfied_decision(
                stage_id="stage-1",
                candidate_digest="sha256:" + ("c1" * 32),
            ),
        )
        self.assertEqual(self._task()["stages"][0]["status"], "IN_PROGRESS")
        self.assertNotEqual(
            self._task()["stages"][0]["completion_decision"]["candidate_digest"],
            observe_candidate(self.host).digest,
        )

    def test_B5D08_stale_task_decision_cannot_ready(self):
        write_active_host(self.host)
        write_task(
            self.host,
            stages=[self._complete_stage()],
            final_tests=[],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            request_ready_for_review=True,
            stage_completion_decision=satisfied_decision(stage_id="stage-1"),
            task_completion_decision=satisfied_decision(
                candidate_digest="sha256:" + ("c1" * 32),
            ),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertNotEqual(self._task()["status"], "READY_FOR_REVIEW")

    def test_B5D09_complete_stage_revalidation_success(self):
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        stale = "sha256:" + ("c1" * 32)
        write_task(
            self.host,
            stages=[
                self._complete_stage(
                    completion_decision=satisfied_decision(candidate_digest=stale)
                )
            ],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "value = 2\n"}],
            revalidate_complete_stages=True,
            stage_completion_decision=satisfied_decision(stage_id="stage-1"),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        stage = self._task()["stages"][0]
        self.assertEqual(stage["status"], "COMPLETE")
        decision = stage["completion_decision"]
        self.assertEqual(decision["outcome"], "SATISFIED")
        self.assertNotEqual(decision["candidate_digest"], stale)
        self.assertEqual(decision["supersedes"]["candidate_digest"], stale)

    def test_B5D10_complete_stage_revalidation_failure(self):
        write_active_host(self.host)
        stale = "sha256:" + ("c1" * 32)
        write_task(
            self.host,
            stages=[
                self._complete_stage(
                    completion_decision=satisfied_decision(candidate_digest=stale)
                )
            ],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            revalidate_complete_stages=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        stage = self._task()["stages"][0]
        self.assertEqual(stage["status"], "IN_PROGRESS")
        self.assertEqual(stage["completion_decision"]["outcome"], "UNKNOWN")
        self.assertNotEqual(self._task()["status"], "READY_FOR_REVIEW")

    def test_B5D11_multi_stage_structural_complete(self):
        write_active_host(self.host)
        write_task(
            self.host,
            stages=[
                self._complete_stage(),
                {
                    "stage_id": "stage-2",
                    "goal": "Second stage.",
                    "acceptance": "Second criterion.",
                    "status": "IN_PROGRESS",
                    "required_tests": [],
                },
            ],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            request_ready_for_review=True,
            task_completion_decision=satisfied_decision(),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["task_complete"])
        self.assertNotEqual(self._task()["status"], "READY_FOR_REVIEW")

    def test_B5D12_task_cas_conflict(self):
        write_active_host(self.host)
        write_task(self.host, stages=[self._complete_stage()], final_tests=[])

        def compete():
            path = self._task_path()
            current = read_yaml(path)
            updated = dict(current)
            updated["title"] = "competing-lifecycle"
            published = publish_task(
                path, updated, expected_revision=current["record_revision"]
            )
            self.assertTrue(published.ok)

        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            request_ready_for_review=True,
            before_ready_task_publish=compete,
            **ready_lifecycle_opts(),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.extras["task_publication"]["conflict"])
        stored = self._task()
        self.assertEqual(stored["title"], "competing-lifecycle")
        self.assertNotEqual(stored["status"], "READY_FOR_REVIEW")

    def test_B5D13_portable_decision_basis(self):
        self._prepare_test_host()
        write_task(
            self.host,
            stages=[self._in_progress_stage(required=True)],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "value = 1\n"}],
            invoke_test=True,
            selected=[TEST_PROFILE],
            request_stage_complete=True,
            stage_completion_decision=satisfied_decision(
                stage_id="stage-1",
                basis=[
                    {
                        "kind": "repository_observation",
                        "summary": "src/app.py has the expected content.",
                    },
                    {
                        "kind": "test_evidence",
                        "summary": "Required Stage verification passed.",
                    },
                ]
            ),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        task = self._task()
        dumped = str(task)
        self.assertNotIn(str(self.host), dumped)
        self.assertNotIn("user said", dumped)
        self.assertNotIn("in chat", dumped)
        stage = task["stages"][0]
        self.assertNotIn("report", stage.get("completion_decision", {}))
        for item in stage["completion_decision"]["basis"]:
            self.assertNotIn("report", item)
            ref = item.get("evidence_ref")
            if ref:
                locator = ref["locator"]
                self.assertFalse(Path(locator).is_absolute())
                self.assertNotIn("\\", locator)
                self.assertTrue(locator.startswith("test-runs/"))

    def test_B5D14_subjective_acceptance_unknown(self):
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write_task(
            self.host,
            stages=[self._in_progress_stage()],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "value = 1\n"}],
            request_stage_complete=True,
            stage_completion_decision={
                "stage_id": "stage-1",
                "outcome": "SATISFIED",
                "rationale": "The user said yes in chat.",
                "basis": [
                    {
                        "kind": "chat",
                        "summary": "user said yes in chat",
                    }
                ],
            },
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        stage = self._task()["stages"][0]
        self.assertEqual(stage["status"], "IN_PROGRESS")
        self.assertEqual(stage["completion_decision"]["outcome"], "UNKNOWN")

    def test_B5R01_valid_ready_repair(self):
        write_active_host(self.host)
        write_task(
            self.host,
            status="READY_FOR_REVIEW",
            stages=[
                self._complete_stage(stage_id="stage-1"),
                self._complete_stage(stage_id="stage-2", goal="Repair target."),
            ],
        )
        digest = observe_candidate(self.host).digest
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                candidate_digest=digest,
                target_stage_ids=["stage-2"],
            ),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras["repair_reopen"])
        task = self._task()
        self.assertEqual(task["status"], "IN_PROGRESS")
        self.assertEqual(task["stages"][0]["status"], "COMPLETE")
        self.assertEqual(task["stages"][1]["status"], "IN_PROGRESS")

    def test_B5R02_normal_ready_still_blocked(self):
        write_active_host(self.host)
        write_task(self.host, status="READY_FOR_REVIEW", stages=[self._complete_stage()])
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(self._task()["status"], "READY_FOR_REVIEW")
        self.assertTrue(any("READY_FOR_REVIEW" in item for item in result.blockers))

    def test_B5R03_stale_handoff_candidate(self):
        write_active_host(self.host)
        write_task(self.host, status="READY_FOR_REVIEW", stages=[self._complete_stage()])
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                candidate_digest="sha256:" + ("ab" * 32),
                target_stage_ids=["stage-1"],
            ),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(self._task()["status"], "READY_FOR_REVIEW")
        self.assertEqual(self._task()["record_revision"], 1)

    def test_B5R04_wrong_task(self):
        write_active_host(self.host)
        write_task(self.host, status="READY_FOR_REVIEW", stages=[self._complete_stage()])
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                task_id=TASK_B,
                candidate_digest=observe_candidate(self.host).digest,
                target_stage_ids=["stage-1"],
            ),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(self._task()["status"], "READY_FOR_REVIEW")
        self.assertEqual(self._task()["record_revision"], 1)

    def test_B5R05_missing_targets_no_guess(self):
        write_active_host(self.host)
        write_task(self.host, status="READY_FOR_REVIEW", stages=[self._complete_stage()])
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=repair_handoff(
                kind="submit_to_develop",
                candidate_digest=observe_candidate(self.host).digest,
            ),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("target_stage_ids" in item for item in result.blockers))
        self.assertEqual(self._task()["status"], "READY_FOR_REVIEW")

    def test_B5R06_invalid_target_stage(self):
        write_active_host(self.host)
        write_task(self.host, status="READY_FOR_REVIEW", stages=[self._complete_stage()])
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                candidate_digest=observe_candidate(self.host).digest,
                target_stage_ids=["stage-missing"],
            ),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(self._task()["status"], "READY_FOR_REVIEW")

    def test_B5R07_permission_escalation(self):
        write_active_host(self.host)
        write_task(self.host, status="READY_FOR_REVIEW", stages=[self._complete_stage()])
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                candidate_digest=observe_candidate(self.host).digest,
                target_stage_ids=["stage-1"],
                capabilities={
                    "commit": True,
                    "push": False,
                    "submit_authorized": False,
                },
            ),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("escalate" in item for item in result.blockers))
        self.assertEqual(self._task()["status"], "READY_FOR_REVIEW")

    def test_B5R08_reopen_invalidates_target_decision(self):
        write_active_host(self.host)
        write_task(self.host, status="READY_FOR_REVIEW", stages=[self._complete_stage(stage_id="stage-2")])
        digest = observe_candidate(self.host).digest
        write_task(
            self.host,
            status="READY_FOR_REVIEW",
            stages=[
                self._complete_stage(
                    stage_id="stage-2",
                    completion_decision=satisfied_decision(candidate_digest=digest),
                )
            ],
        )
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                candidate_digest=observe_candidate(self.host).digest,
                target_stage_ids=["stage-2"],
            ),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        stage = self._task()["stages"][0]
        self.assertEqual(stage["status"], "IN_PROGRESS")
        decision = stage["completion_decision"]
        self.assertEqual(decision["outcome"], "UNKNOWN")
        self.assertEqual(decision["supersedes"]["outcome"], "SATISFIED")
        self.assertEqual(decision["supersedes"]["candidate_digest"], digest)

    def test_B5R09_reopen_invalidates_task_decision(self):
        write_active_host(self.host)
        write_task(self.host, status="READY_FOR_REVIEW", stages=[self._complete_stage()])
        digest = observe_candidate(self.host).digest
        write_task(
            self.host,
            status="READY_FOR_REVIEW",
            stages=[self._complete_stage()],
            task_completion_decision=satisfied_decision(candidate_digest=digest),
        )
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                candidate_digest=observe_candidate(self.host).digest,
                target_stage_ids=["stage-1"],
            ),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        decision = self._task()["task_completion_decision"]
        self.assertEqual(decision["outcome"], "UNKNOWN")
        self.assertEqual(decision["supersedes"]["outcome"], "SATISFIED")
        self.assertNotEqual(self._task()["status"], "READY_FOR_REVIEW")

    def test_B5R10_repair_c1_to_c2(self):
        self._prepare_test_host()
        write_task(
            self.host,
            status="READY_FOR_REVIEW",
            stages=[self._complete_stage(required=True)],
            final_tests=[explicit_ref()],
        )
        c1 = observe_candidate(self.host).digest
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                candidate_digest=c1,
                target_stage_ids=["stage-1"],
            ),
            writes=[{"path": "src/app.py", "content": "value = 2\n"}],
            invoke_test=True,
            selected=[TEST_PROFILE],
            request_ready_for_review=True,
        )
        self.assertNotEqual(self._task()["status"], "READY_FOR_REVIEW")
        self.assertNotEqual(observe_candidate(self.host).digest, c1)

    def test_B5R11_non_target_stage_stale(self):
        self._prepare_test_host()
        stale = "sha256:" + ("c1" * 32)
        write_task(
            self.host,
            status="READY_FOR_REVIEW",
            stages=[
                self._complete_stage(
                    stage_id="stage-1",
                    completion_decision=satisfied_decision(candidate_digest=stale),
                ),
                self._complete_stage(stage_id="stage-2", goal="Repair target."),
            ],
        )
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                candidate_digest=observe_candidate(self.host).digest,
                target_stage_ids=["stage-2"],
            ),
            writes=[{"path": "src/app.py", "content": "value = 2\n"}],
            invoke_test=True,
            selected=[TEST_PROFILE],
            request_stage_complete=True,
            request_ready_for_review=True,
            stage_completion_decision=satisfied_decision(stage_id="stage-2"),
            task_completion_decision=satisfied_decision(),
        )
        self.assertNotEqual(self._task()["status"], "READY_FOR_REVIEW")
        non_target = self._task()["stages"][0]
        if non_target["status"] == "COMPLETE":
            self.assertNotEqual(
                (non_target.get("completion_decision") or {}).get("candidate_digest"),
                observe_candidate(self.host).digest,
            )

    def test_B5R12_repair_full_e2e(self):
        write_submit_host(self.host)
        write_ready_task(
            self.host,
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Write the fixture source.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "COMPLETE",
                    "required_tests": [explicit_ref(profile_id="unit")],
                }
            ],
        )
        (self.host / "src/app.py").unlink()
        submitted = submit_engine(self.host).run(task_id=TASK_A)
        self.assertEqual(submitted.outcome, "BLOCKED")
        self.assertEqual(submitted.extras.get("stage"), "S1")
        self.assertEqual(submitted.next_route, "stop")
        self.assertIsNone(submitted.extras.get("repair_handoff"))
        c1 = observe_candidate(self.host).digest
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                candidate_digest=c1,
                target_stage_ids=["stage-1"],
            ),
            writes=[{"path": "src/app.py", "content": "value = 1\n"}],
            invoke_test=True,
            selected=["unit"],
            request_stage_complete=True,
            request_ready_for_review=True,
            stage_completion_decision=satisfied_decision(
                stage_id="stage-1",
                basis=[
                    {
                        "kind": "repository_observation",
                        "summary": "src/app.py has the expected content.",
                    },
                    {
                        "kind": "test_evidence",
                        "summary": "Required verification passed on the repair candidate.",
                    },
                ]
            ),
            task_completion_decision=satisfied_decision(),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        task = self._task()
        self.assertEqual(task["status"], "READY_FOR_REVIEW")
        self.assertEqual(task["stages"][0]["status"], "COMPLETE")
        self.assertEqual(task["task_completion_decision"]["outcome"], "SATISFIED")
        self.assertNotEqual(
            task["task_completion_decision"]["candidate_digest"],
            c1,
        )
        self.assertFalse(result.extras["submit_authorized"])

    def test_B5R13_reopen_cas_conflict(self):
        write_active_host(self.host)
        write_task(self.host, status="READY_FOR_REVIEW", stages=[self._complete_stage()])
        bind_ready_completion_authority(self.host)

        def compete():
            path = self._task_path()
            current = read_yaml(path)
            updated = dict(current)
            updated["progress_summary"] = "competing-reopen"
            published = publish_task(
                path, updated, expected_revision=current["record_revision"]
            )
            self.assertTrue(published.ok)

        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                candidate_digest=observe_candidate(self.host).digest,
                target_stage_ids=["stage-1"],
            ),
            before_repair_reopen_publish=compete,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.extras["task_publication"]["conflict"])
        stored = self._task()
        self.assertEqual(stored["progress_summary"], "competing-reopen")
        self.assertEqual(stored["status"], "READY_FOR_REVIEW")
        self.assertEqual(stored["stages"][0]["status"], "COMPLETE")

    def test_B5R14_in_progress_repair_regression(self):
        write_active_host(self.host)
        write_task(self.host)
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            test_to_develop=repair_handoff(
                candidate_digest=observe_candidate(self.host).digest,
            ),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.mode, "repair")
        self.assertEqual(self._task()["status"], "IN_PROGRESS")

    def test_B5F01_control_plane_candidate_stability(self):
        self._prepare_test_host()
        write(self.host, "src/app.py", "value = 1\n")
        write_task(
            self.host,
            stages=[self._in_progress_stage(required=True)],
            final_tests=[explicit_ref()],
        )
        before = observe_candidate(self.host).digest
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            invoke_test=True,
            selected=[TEST_PROFILE],
            request_stage_complete=True,
            request_ready_for_review=True,
            stage_completion_decision=satisfied_decision(
                stage_id="stage-1",
                basis=[
                    {
                        "kind": "repository_observation",
                        "summary": "src/app.py has the expected content.",
                    },
                    {
                        "kind": "test_evidence",
                        "summary": "Required Stage verification passed for this candidate.",
                    },
                ]
            ),
            task_completion_decision=satisfied_decision(),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        after = observe_candidate(self.host)
        self.assertEqual(after.digest, before)
        task = self._task()
        self.assertEqual(task["status"], "READY_FOR_REVIEW")
        self.assertEqual(task["stages"][0]["status"], "COMPLETE")
        self.assertEqual(task["stages"][0]["completion_decision"]["candidate_digest"], before)
        self.assertEqual(task["task_completion_decision"]["candidate_digest"], before)

    def test_B5F02_source_mutation_invalidates(self):
        self.test_B5F01_control_plane_candidate_stability()
        c1 = observe_candidate(self.host).digest
        write(self.host, "src/app.py", "value = 9\n")
        c2 = observe_candidate(self.host).digest
        self.assertNotEqual(c2, c1)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            request_ready_for_review=True,
            task_completion_decision=satisfied_decision(),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(self._task()["status"], "READY_FOR_REVIEW")
        decision = self._task()["task_completion_decision"]
        self.assertEqual(decision.get("candidate_digest"), c1)
        self.assertNotEqual(decision.get("candidate_digest"), c2)

    def test_B5F03_substantive_task_mutation_invalidates(self):
        self._prepare_test_host()
        write_task(self.host, stages=[self._in_progress_stage(required=True)])
        before = observe_candidate(self.host).digest
        current = self._task()
        current["acceptance"] = "Changed Task acceptance."
        published = publish_task(
            self._task_path(), current, expected_revision=current["record_revision"]
        )
        self.assertTrue(published.ok)
        after = observe_candidate(self.host).digest
        self.assertNotEqual(after, before)

    def test_B5F04_physical_diff_preserved(self):
        self._prepare_test_host()
        write(self.host, "src/app.py", "value = 1\n")
        write_task(
            self.host,
            stages=[self._in_progress_stage(required=True)],
            final_tests=[explicit_ref()],
        )
        from p6_support import init_git

        init_git(self.host)
        before_bytes = self._task_path().read_bytes()
        before = observe_candidate(self.host).digest
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            invoke_test=True,
            selected=[TEST_PROFILE],
            request_stage_complete=True,
            request_ready_for_review=True,
            stage_completion_decision=satisfied_decision(stage_id="stage-1"),
            task_completion_decision=satisfied_decision(),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(observe_candidate(self.host).digest, before)
        self.assertNotEqual(self._task_path().read_bytes(), before_bytes)
        diff = observe_real_diff(self.host)
        self.assertTrue(diff["ok"])
        rel = str(self._task_path().relative_to(self.host)).replace("\\", "/")
        self.assertIn(rel, diff["paths"])

    def test_B5F05_different_ids_bind_correctly(self):
        self._prepare_test_host()
        write_task(
            self.host,
            stages=[self._in_progress_stage(required=True)],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "value = 1\n"}],
            invoke_test=True,
            selected=[TEST_PROFILE],
            request_stage_complete=True,
            stage_completion_decision=satisfied_decision(stage_id="stage-1"),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        item = self._task()["stages"][0]["required_tests"][0]
        self.assertEqual(item["requirement_id"], TASK_REQUIREMENT)
        self.assertEqual(item["execution_binding"]["profile_id"], TEST_PROFILE)
        self.assertNotEqual(item["requirement_id"], item["execution_binding"]["profile_id"])
        locator = item["evidence_ref"]["locator"]
        self.assertTrue(locator.startswith("test-runs/"))
        resolved, issues = TestEngine(self.host, REPO / "skills" / "test").resolve_evidence(
            locator
        )
        self.assertFalse(issues)
        self.assertEqual(resolved["profile_id"], TEST_PROFILE)

    def test_B5F06_same_name_without_binding_does_not_attach(self):
        self._prepare_test_host(profile_id="unit")
        write_task(
            self.host,
            stages=[
                self._in_progress_stage(
                    required_refs=[{"requirement_id": "unit"}],
                )
            ],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "value = 1\n"}],
            invoke_test=True,
            selected=["unit"],
            request_stage_complete=True,
            stage_completion_decision=satisfied_decision(stage_id="stage-1"),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        item = self._task()["stages"][0]["required_tests"][0]
        self.assertEqual(item["requirement_id"], "unit")
        self.assertNotIn("execution_binding", item)
        self.assertIsNone(item.get("evidence_ref"))
        self.assertEqual(self._task()["stages"][0]["status"], "IN_PROGRESS")

    def test_B5F07_wrong_producer_rejected(self):
        other = "unit-other"
        profile, command = passing_profile(TEST_PROFILE)
        other_profile, other_command = passing_profile(other)
        write_host(self.host, [(profile, command), (other_profile, other_command)])
        bind_develop_lock(self.host)
        payload = read_yaml(self.host / ".scaffold/project.yaml")
        payload["ownership"] = {**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"}
        payload["source_areas"] = ["src"]
        write_yaml_atomic(self.host / ".scaffold/project.yaml", payload)
        write(self.host, "src/app.py", "value = 1\n")
        write_task(
            self.host,
            stages=[self._in_progress_stage(required=True)],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            invoke_test=True,
            selected=[other],
            request_stage_complete=True,
            stage_completion_decision=satisfied_decision(stage_id="stage-1"),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        item = self._task()["stages"][0]["required_tests"][0]
        self.assertIsNone(item.get("evidence_ref"))
        self.assertEqual(self._task()["stages"][0]["status"], "IN_PROGRESS")

    def test_B5F08_manual_evidence_path(self):
        profile, command = passing_profile("human")
        profile["provenance"] = "HUMAN_OBSERVATION"
        profile["evidence_required"] = ["human_observation"]
        write_host(self.host, [(profile, command)])
        bind_develop_lock(self.host)
        payload = read_yaml(self.host / ".scaffold/project.yaml")
        payload["ownership"] = {**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"}
        payload["source_areas"] = ["src"]
        write_yaml_atomic(self.host / ".scaffold/project.yaml", payload)
        write(self.host, "src/app.py", "value = 1\n")
        write_task(
            self.host,
            stages=[
                self._in_progress_stage(
                    required_refs=[{"requirement_id": "task-required/human-check"}]
                )
            ],
        )
        digest = observe_candidate(self.host).digest
        test = TestEngine(self.host, REPO / "skills" / "test").run(
            supplied_evidence=[
                {
                    "profile_id": "human",
                    "provenance": "HUMAN_OBSERVATION",
                    "kind": "human_observation",
                    "result": "PASS",
                    "candidate_digest": digest,
                    "summary": "seen by human",
                }
            ]
        )
        locators = [
            ref["locator"]
            for ref in TestEngine(self.host, REPO / "skills" / "test").build_evidence_refs(
                test.extras["report_id"]
            )
            if ref.get("locator")
        ]
        self.assertTrue(locators)
        current = self._task()
        current["stages"][0]["required_tests"][0]["evidence_ref"] = {
            "locator": locators[0]
        }
        current["stages"][0]["required_tests"][0]["observed_outcome"] = "PASS"
        published = publish_task(
            self._task_path(), current, expected_revision=current["record_revision"]
        )
        self.assertTrue(published.ok)
        self.assertEqual(observe_candidate(self.host).digest, digest)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            request_stage_complete=True,
            stage_completion_decision=satisfied_decision(stage_id="stage-1"),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(self._task()["stages"][0]["status"], "COMPLETE")
        self.assertNotIn(
            "execution_binding",
            self._task()["stages"][0]["required_tests"][0],
        )

    def test_B5F09_project_profile_and_task_requirement_stay_separate(self):
        self._prepare_test_host()
        write_task(
            self.host,
            stages=[self._in_progress_stage(required=True)],
        )
        from scaffold_p8.completeness import evaluate_completeness

        judged = evaluate_completeness(
            self.host,
            task=self._task(),
            report=None,
            invoke=False,
            selected=[],
            test_package=REPO / "skills" / "test",
        )
        self.assertIn(TEST_PROFILE, judged["project_required_ids"])
        self.assertIn(TASK_REQUIREMENT, judged["task_required_ids"])
        self.assertNotEqual(set(judged["project_required_ids"]), set(judged["task_required_ids"]))
        self.assertIn(TEST_PROFILE, judged["required_ids"])
        self.assertIn(TASK_REQUIREMENT, judged["required_ids"])

    def test_B5F10_unmappable_repair(self):
        write_submit_host(self.host)
        write_ready_task(
            self.host,
            stages=[
                self._complete_stage(stage_id="stage-1"),
                self._complete_stage(stage_id="stage-2", goal="Other stage."),
            ],
        )
        revision = self._task()["record_revision"]
        (self.host / "src/app.py").unlink()
        bind_ready_completion_authority(self.host)
        submitted = submit_engine(self.host).run(task_id=TASK_A)
        self.assertEqual(submitted.outcome, "BLOCKED")
        self.assertNotEqual(submitted.next_route, "develop.repair")
        self.assertEqual(submitted.next_route, "human")
        self.assertIsNone(submitted.extras.get("repair_handoff"))
        self.assertTrue(
            any(UNRESOLVED_REPAIR_REASON in item for item in submitted.blockers)
        )
        self.assertEqual(self._task()["status"], "READY_FOR_REVIEW")
        self.assertEqual(self._task()["record_revision"], revision)

    def test_B5F11_mappable_repair(self):
        write_submit_host(self.host)
        write_ready_task(
            self.host,
            stages=[self._complete_stage(stage_id="stage-1")],
        )
        (self.host / "src/app.py").unlink()
        bind_ready_completion_authority(self.host)
        submitted = submit_engine(self.host).run(task_id=TASK_A)
        self.assertEqual(submitted.outcome, "BLOCKED")
        self.assertNotEqual(submitted.next_route, "develop.repair")
        self.assertEqual(submitted.next_route, "human")
        self.assertIsNone(submitted.extras.get("repair_handoff"))
        self.assertTrue(
            any(UNRESOLVED_REPAIR_REASON in item for item in submitted.blockers)
        )

    def test_B5F12_ready_repair_e2e_under_fnd3(self):
        self._prepare_test_host()
        write(self.host, "src/app.py", "value = 1\n")
        write_task(
            self.host,
            stages=[self._in_progress_stage(required=True)],
            final_tests=[explicit_ref()],
        )
        first = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            invoke_test=True,
            selected=[TEST_PROFILE],
            request_stage_complete=True,
            request_ready_for_review=True,
            stage_completion_decision=satisfied_decision(stage_id="stage-1"),
            task_completion_decision=satisfied_decision(),
        )
        self.assertEqual(first.outcome, "COMPLETED", first.blockers)
        c1 = observe_candidate(self.host).digest
        self.assertEqual(self._task()["status"], "READY_FOR_REVIEW")
        reopen = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                candidate_digest=c1,
                target_stage_ids=["stage-1"],
            ),
            writes=[{"path": "src/app.py", "content": "value = 2\n"}],
            invoke_test=True,
            selected=[TEST_PROFILE],
            request_stage_complete=True,
            request_ready_for_review=True,
            stage_completion_decision=satisfied_decision(stage_id="stage-1"),
            task_completion_decision=satisfied_decision(),
        )
        self.assertEqual(reopen.outcome, "COMPLETED", reopen.blockers)
        task = self._task()
        c2 = observe_candidate(self.host).digest
        self.assertNotEqual(c2, c1)
        self.assertEqual(task["status"], "READY_FOR_REVIEW")
        self.assertEqual(task["task_completion_decision"]["candidate_digest"], c2)
        item = task["stages"][0]["required_tests"][0]
        self.assertEqual(item["requirement_id"], TASK_REQUIREMENT)
        self.assertEqual(item["execution_binding"]["profile_id"], TEST_PROFILE)
        self.assertNotEqual(item["requirement_id"], TEST_PROFILE)

    def test_B5F13_task_intake_preserves_binding(self):
        self._prepare_test_host()
        proposal = self._intake_proposal(tests=[explicit_ref()])
        normalized, issues = prepare_proposal(proposal)
        self.assertEqual(issues, [])
        self.assertIsNotNone(normalized)
        item = normalized["stages"][0]["required_tests"][0]
        self.assertEqual(item["requirement_id"], TASK_REQUIREMENT)
        self.assertEqual(
            item["execution_binding"],
            {"kind": "test_profile", "profile_id": TEST_PROFILE},
        )
        self.assertNotEqual(item["requirement_id"], TEST_PROFILE)
        result = self._intake(proposal)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.extras["operation"], "task_intake")
        self.assertFalse(result.extras["task_reused"])
        path = self.host / result.artifacts[0]
        published = read_yaml(path)
        stored = published["stages"][0]["required_tests"][0]
        self.assertEqual(stored["requirement_id"], TASK_REQUIREMENT)
        self.assertEqual(
            stored["execution_binding"],
            {"kind": "test_profile", "profile_id": TEST_PROFILE},
        )
        self.assertNotIn("evidence_ref", stored)
        self.assertEqual(published["status"], "IN_PROGRESS")

    def test_B5F14_malformed_binding_fails_closed(self):
        self._prepare_test_host()
        malformed = [
            "unit",
            {"kind": "something_else", "profile_id": "unit"},
            {"kind": "test_profile"},
            {"kind": "test_profile", "profile_id": ""},
        ]
        for binding in malformed:
            with self.subTest(binding=binding):
                proposal = self._intake_proposal(
                    tests=[
                        {
                            "requirement_id": TASK_REQUIREMENT,
                            "execution_binding": binding,
                        }
                    ]
                )
                normalized, issues = prepare_proposal(proposal)
                self.assertIsNone(normalized)
                self.assertTrue(issues)
                result = self._intake(proposal)
                self.assertEqual(result.outcome, "NEEDS_HUMAN", result.blockers)
                self.assertTrue(result.blockers)
                self.assertEqual(self._task_paths(), [])

    def test_B5F15_binding_is_part_of_proposal_identity(self):
        first_profile, command_a = passing_profile("unit-save-check")
        second_profile, command_b = passing_profile("unit-save-other")
        write_host(self.host, [(first_profile, command_a), (second_profile, command_b)])
        bind_develop_lock(self.host)
        payload = read_yaml(self.host / ".scaffold/project.yaml")
        payload["ownership"] = {**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"}
        payload["source_areas"] = ["src"]
        write_yaml_atomic(self.host / ".scaffold/project.yaml", payload)
        write(self.host, "src/app.py", "value = 0\n")
        first = self._intake_proposal(
            tests=[explicit_ref(profile_id="unit-save-check")]
        )
        second = self._intake_proposal(
            tests=[explicit_ref(profile_id="unit-save-other")]
        )
        first_norm, first_issues = prepare_proposal(first)
        second_norm, second_issues = prepare_proposal(second)
        self.assertEqual(first_issues, [])
        self.assertEqual(second_issues, [])
        self.assertNotEqual(proposal_digest(first_norm), proposal_digest(second_norm))
        published = self._intake(first)
        self.assertEqual(published.outcome, "COMPLETED", published.blockers)
        existing = read_yaml(self.host / published.artifacts[0])
        self.assertEqual(
            task_proposal(existing)["stages"][0]["required_tests"][0]["execution_binding"][
                "profile_id"
            ],
            "unit-save-check",
        )
        reused = self._intake(second)
        self.assertEqual(reused.outcome, "COMPLETED", reused.blockers)
        self.assertFalse(reused.extras["task_reused"])
        self.assertNotEqual(
            reused.extras["task"]["record_id"],
            published.extras["task"]["record_id"],
        )
        self.assertEqual(len(self._task_paths()), 2)

    def test_B5F16_legacy_no_binding_intake(self):
        self._prepare_test_host()
        proposal = self._intake_proposal(tests=[TEST_PROFILE])
        normalized, issues = prepare_proposal(proposal)
        self.assertEqual(issues, [])
        item = normalized["stages"][0]["required_tests"][0]
        self.assertEqual(item, {"requirement_id": TEST_PROFILE})
        self.assertNotIn("execution_binding", item)
        result = self._intake(proposal)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        published = read_yaml(self.host / result.artifacts[0])
        stored = published["stages"][0]["required_tests"][0]
        self.assertEqual(stored, {"requirement_id": TEST_PROFILE})
        self.assertNotIn("execution_binding", stored)

    def test_B5F17_natural_intake_full_lifecycle(self):
        self._prepare_test_host()
        self.assertEqual(self._task_paths(), [])
        proposal = self._intake_proposal(tests=[explicit_ref()])
        intake = self._intake(proposal)
        self.assertEqual(intake.outcome, "COMPLETED", intake.blockers)
        task_id = intake.extras["task"]["record_id"]
        published = read_yaml(self.host / intake.artifacts[0])
        item = published["stages"][0]["required_tests"][0]
        self.assertEqual(item["requirement_id"], TASK_REQUIREMENT)
        self.assertEqual(item["execution_binding"]["profile_id"], TEST_PROFILE)
        self.assertNotEqual(item["requirement_id"], TEST_PROFILE)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=task_id,
            writes=[{"path": "src/app.py", "content": "value = 1\n"}],
            invoke_test=True,
            selected=[TEST_PROFILE],
            request_stage_complete=True,
            request_ready_for_review=True,
            stage_completion_decision=satisfied_decision(
                stage_id="stage-1",
                basis=[
                    {
                        "kind": "repository_observation",
                        "summary": "src/app.py has the expected content.",
                    },
                    {
                        "kind": "test_evidence",
                        "summary": "Required Stage verification passed for this candidate.",
                    },
                ]
            ),
            task_completion_decision=satisfied_decision(),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        task = read_yaml(self.host / intake.artifacts[0])
        self.assertEqual(task["record_id"], task_id)
        self.assertEqual(task["status"], "READY_FOR_REVIEW")
        self.assertEqual(task["stages"][0]["status"], "COMPLETE")
        attached = task["stages"][0]["required_tests"][0]
        self.assertEqual(attached["requirement_id"], TASK_REQUIREMENT)
        self.assertEqual(attached["execution_binding"]["profile_id"], TEST_PROFILE)
        locator = (attached.get("evidence_ref") or {}).get("locator")
        self.assertTrue(str(locator).startswith("test-runs/"))

    def test_B5F18_unbound_non_profile_requirement_intake(self):
        self._prepare_test_host()
        proposal = self._intake_proposal(tests=["human-visual-check"])
        result = self._intake(proposal)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertFalse(
            any("tests.yaml" in item for item in result.blockers)
        )
        published = read_yaml(self.host / result.artifacts[0])
        stored = published["stages"][0]["required_tests"][0]
        self.assertEqual(stored, {"requirement_id": "human-visual-check"})
        self.assertNotIn("execution_binding", stored)

    def test_B5F19_bound_unknown_profile_blocks(self):
        self._prepare_test_host()
        proposal = self._intake_proposal(
            tests=[
                explicit_ref(
                    requirement_id="human-visual-check",
                    profile_id="missing-profile",
                )
            ]
        )
        result = self._intake(proposal)
        self.assertEqual(result.outcome, "NEEDS_HUMAN", result.blockers)
        self.assertTrue(
            any(
                "missing-profile" in item and "tests.yaml" in item
                for item in result.blockers
            )
        )
        self.assertEqual(self._task_paths(), [])

    def test_B5F20_unbound_equal_name_does_not_create_binding(self):
        profile, command = passing_profile("unit")
        write_host(self.host, [(profile, command)])
        bind_develop_lock(self.host)
        payload = read_yaml(self.host / ".scaffold/project.yaml")
        payload["ownership"] = {**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"}
        payload["source_areas"] = ["src"]
        write_yaml_atomic(self.host / ".scaffold/project.yaml", payload)
        write(self.host, "src/app.py", "value = 0\n")
        proposal = self._intake_proposal(tests=["unit"])
        result = self._intake(proposal)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        published = read_yaml(self.host / result.artifacts[0])
        stored = published["stages"][0]["required_tests"][0]
        self.assertEqual(stored, {"requirement_id": "unit"})
        self.assertNotIn("execution_binding", stored)

    def _intake(self, proposal: dict):
        return develop_engine(self.host).intake(
            structured_intent={
                "kind": "develop",
                "action": "implement",
                "explicit_implementation": True,
                "request": "Implement the bounded fixture save check.",
                "authorized_proposal": proposal,
            },
            proposal=proposal,
            grounding={
                "intent_fields": ["goal", "scope", "acceptance", "stages", "tests"],
                "knowledge_fields": ["scope", "rules", "ownership", "tests"],
                "uncertainties": [],
                "material_decisions": [],
            },
        )

    @staticmethod
    def _intake_proposal(*, tests: list) -> dict:
        return {
            "title": "Implement fixture save check",
            "goal": "Implement the fixture source change.",
            "acceptance": "src/app.py has the expected content.",
            "scope": {"paths": ["src/app.py"], "modules": [], "exclude": []},
            "stages": [
                {
                    "stage_id": "stage-1",
                    "goal": "Write the fixture source.",
                    "acceptance": "src/app.py has the expected content.",
                    "required_tests": tests,
                }
            ],
            "final_tests": [],
        }

    def _task_paths(self) -> list[Path]:
        folder = self.host / ".scaffold/tasks"
        if not folder.is_dir():
            return []
        return sorted(folder.glob("*.yaml"))

    def _prepare_test_host(self, *, failing: bool = False, profile_id: str = TEST_PROFILE) -> None:
        profile, command = (
            failing_profile(profile_id) if failing else passing_profile(profile_id)
        )
        write_host(self.host, [(profile, command)])
        bind_develop_lock(self.host)
        payload = read_yaml(self.host / ".scaffold/project.yaml")
        payload["ownership"] = {**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"}
        payload["source_areas"] = ["src"]
        write_yaml_atomic(self.host / ".scaffold/project.yaml", payload)
        write(self.host, "src/app.py", "value = 0\n")

    def _task_path(self) -> Path:
        return self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"

    def _task(self) -> dict:
        return read_yaml(self._task_path())

    @staticmethod
    def _in_progress_stage(
        *,
        stage_id: str = "stage-1",
        required: bool | list[str] | None = None,
        required_refs: list[dict] | None = None,
        completion_decision: dict | None = None,
    ) -> dict:
        if required_refs is not None:
            tests = required_refs
        elif required is True:
            tests = [explicit_ref()]
        elif isinstance(required, list):
            tests = [explicit_ref(item) for item in required]
        else:
            tests = []
        row = {
            "stage_id": stage_id,
            "goal": "Write the fixture source.",
            "acceptance": "src/app.py has the expected content.",
            "status": "IN_PROGRESS",
            "required_tests": tests,
        }
        if completion_decision is not None:
            row["completion_decision"] = _scoped_stage_decision(
                completion_decision, stage_id
            )
        return row

    @staticmethod
    def _complete_stage(
        *,
        stage_id: str = "stage-1",
        goal: str = "Write the fixture source.",
        required: bool | list[str] | None = None,
        required_refs: list[dict] | None = None,
        completion_decision: dict | None = None,
    ) -> dict:
        if required_refs is not None:
            tests = required_refs
        elif required is True:
            tests = [explicit_ref()]
        elif isinstance(required, list):
            tests = [explicit_ref(item) for item in required]
        else:
            tests = []
        row = {
            "stage_id": stage_id,
            "goal": goal,
            "acceptance": "src/app.py has the expected content.",
            "status": "COMPLETE",
            "required_tests": tests,
        }
        if completion_decision is not None:
            row["completion_decision"] = _scoped_stage_decision(
                completion_decision, stage_id
            )
        return row


def _scoped_stage_decision(decision: dict, stage_id: str) -> dict:
    """Bind a Batch-5 Stage-decision fixture to its containing Stage.

    Pre-FINAL-MAJ-001 fixtures stored COMPLETE/IN_PROGRESS Stage decisions
    without stage_id. That encoded the unscoped-authority defect. The helper
    stamps the containing Stage id; it does not infer a Stage in product code.
    """
    payload = dict(decision)
    if "stage_id" not in payload:
        payload["stage_id"] = stage_id
    return payload


if __name__ == "__main__":
    unittest.main()

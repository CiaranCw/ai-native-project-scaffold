from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import CORE_OWNERSHIP, write_modules
from p7_support import TASK_A, satisfied_decision, write_active_host, write_task
from p8_support import (
    publish_knowledge_outcomes,
    rebind_noscms_baseline,
    run_submit,
    write_ready_task,
    write_submit_host,
)
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p5.knowledge_assessment import (
    assessment_locator,
    current_head_path,
    resolve_current_knowledge_assessment,
)
from scaffold_p6.candidate import observe_candidate
from scaffold_p7.lifecycle import (
    evaluate_ready_for_review,
    persist_ready_if_legal,
    prepare_lifecycle,
    stage_completion_decision_binding,
)
from scaffold_p7.schemas import validate_task_book
from scaffold_p7.tasks import ready_publication_blockers
from scaffold_p8.models import NOSCMS_PUBLICATIONS_DIR
from scaffold_p8.noscms import (
    COMPLETE_NAME,
    load_noscms_baseline,
    verify_noscms_publication,
)
from scaffold_p8.records import durability_state, is_durable
from support import write


def _basis() -> list[dict]:
    return [
        {
            "kind": "repository_observation",
            "summary": "src/app.py has the expected content.",
        }
    ]


def _unscoped_satisfied(digest: str) -> dict:
    return {
        "outcome": "SATISFIED",
        "candidate_digest": digest,
        "rationale": "Unscoped Stage Completion Decision must not be authority.",
        "basis": _basis(),
    }


def _scoped_satisfied(digest: str, stage_id: str) -> dict:
    payload = _unscoped_satisfied(digest)
    payload["stage_id"] = stage_id
    return payload


def _complete_stage(stage_id: str, digest: str, *, scoped: bool = True) -> dict:
    decision = (
        _scoped_satisfied(digest, stage_id) if scoped else _unscoped_satisfied(digest)
    )
    return {
        "stage_id": stage_id,
        "goal": f"Goal {stage_id}.",
        "acceptance": "src/app.py has the expected content.",
        "status": "COMPLETE",
        "required_tests": [],
        "completion_decision": decision,
    }


def _in_progress(stage_id: str) -> dict:
    return {
        "stage_id": stage_id,
        "goal": f"Goal {stage_id}.",
        "acceptance": "src/app.py has the expected content.",
        "status": "IN_PROGRESS",
        "required_tests": [],
    }


class FA2FinalSurgicalATests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _ready_task(self, stages: list[dict], *, digest: str) -> dict:
        return write_task(
            self.host,
            status="READY_FOR_REVIEW",
            stages=stages,
            task_completion_decision=satisfied_decision(candidate_digest=digest),
        )

    def test_FINAL_A01_unscoped_one_stage_cannot_become_ready(self):
        write_active_host(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        digest = observe_candidate(self.host).digest
        task = self._ready_task(
            [_complete_stage("stage-1", digest, scoped=False)],
            digest=digest,
        )
        self.assertNotIn("stage_id", task["stages"][0]["completion_decision"])
        issues = validate_task_book(task, expected_id=TASK_A)
        self.assertTrue(any("unscoped" in item for item in issues), issues)
        ok, reason = evaluate_ready_for_review(
            task, candidate_digest=digest, root=self.host
        )
        self.assertFalse(ok)
        self.assertIn("unscoped", reason)
        _updated, published, pub_reason = persist_ready_if_legal(
            task, candidate_digest=digest, root=self.host
        )
        self.assertFalse(published)
        self.assertIn("unscoped", pub_reason)
        blockers = ready_publication_blockers(self.host, task)
        self.assertTrue(any("unscoped" in item for item in blockers), blockers)

    def test_FINAL_A02_two_stages_one_unscoped_has_no_ready(self):
        write_active_host(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        digest = observe_candidate(self.host).digest
        task = self._ready_task(
            [
                _complete_stage("stage-1", digest, scoped=False),
                _complete_stage("stage-2", digest, scoped=True),
            ],
            digest=digest,
        )
        bound, reason = stage_completion_decision_binding(
            task["stages"][0]["completion_decision"],
            stage_id="stage-1",
            stages=task["stages"],
        )
        self.assertFalse(bound)
        self.assertIn("unscoped", reason)
        ok, ready_reason = evaluate_ready_for_review(
            task, candidate_digest=digest, root=self.host
        )
        self.assertFalse(ok)
        self.assertIn("unscoped", ready_reason)

    def test_FINAL_A03_explicit_stage_1_binds_only_stage_1(self):
        write_active_host(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        task = write_task(self.host, stages=[_in_progress("stage-1"), _in_progress("stage-2")])
        digest = observe_candidate(self.host).digest
        updated, blockers, extras = prepare_lifecycle(
            task,
            root=self.host,
            candidate_digest=digest,
            request_stage_complete=True,
            stage_completion_decision=_scoped_satisfied(digest, "stage-1"),
        )
        self.assertEqual(blockers, [])
        self.assertFalse(extras.get("stage_completion_rejected"))
        self.assertEqual(updated["stages"][0]["status"], "COMPLETE")
        self.assertEqual(
            updated["stages"][0]["completion_decision"]["stage_id"],
            "stage-1",
        )
        self.assertEqual(updated["stages"][1]["status"], "IN_PROGRESS")
        self.assertNotEqual(
            (updated["stages"][1].get("completion_decision") or {}).get("stage_id"),
            "stage-1",
        )

    def test_FINAL_A04_nonexistent_stage_id_fails_closed(self):
        write_active_host(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        digest = observe_candidate(self.host).digest
        stage = _complete_stage("stage-1", digest, scoped=True)
        stage["completion_decision"]["stage_id"] = "stage-missing"
        task = self._ready_task([stage], digest=digest)
        issues = validate_task_book(task, expected_id=TASK_A)
        self.assertTrue(any("must match the containing Stage" in item for item in issues), issues)
        bound, bind_reason = stage_completion_decision_binding(
            stage["completion_decision"],
            stage_id="stage-missing",
            stages=task["stages"],
        )
        self.assertFalse(bound)
        self.assertIn("nonexistent", bind_reason)
        ok, reason = evaluate_ready_for_review(
            task, candidate_digest=digest, root=self.host
        )
        self.assertFalse(ok)
        self.assertTrue(
            "does not bind" in reason or "nonexistent" in reason,
            reason,
        )

    def test_FINAL_A05_stage_1_decision_cannot_satisfy_stage_2(self):
        write_active_host(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        digest = observe_candidate(self.host).digest
        stage = _complete_stage("stage-2", digest, scoped=True)
        stage["completion_decision"]["stage_id"] = "stage-1"
        task = self._ready_task(
            [_complete_stage("stage-1", digest, scoped=True), stage],
            digest=digest,
        )
        issues = validate_task_book(task, expected_id=TASK_A)
        self.assertTrue(any("must match the containing Stage" in item for item in issues), issues)
        bound, reason = stage_completion_decision_binding(
            stage["completion_decision"],
            stage_id="stage-2",
            stages=task["stages"],
        )
        self.assertFalse(bound)
        self.assertIn("does not bind", reason)
        ok, ready_reason = evaluate_ready_for_review(
            task, candidate_digest=digest, root=self.host
        )
        self.assertFalse(ok)

    def test_FINAL_A06_task_completion_decision_without_stage_id_is_valid(self):
        write_active_host(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        digest = observe_candidate(self.host).digest
        task_decision = satisfied_decision(candidate_digest=digest)
        self.assertNotIn("stage_id", task_decision)
        task = write_task(
            self.host,
            status="READY_FOR_REVIEW",
            stages=[_complete_stage("stage-1", digest, scoped=True)],
            task_completion_decision=task_decision,
        )
        issues = validate_task_book(task, expected_id=TASK_A)
        self.assertEqual(issues, [])
        ok, reason = evaluate_ready_for_review(
            task, candidate_digest=digest, root=self.host
        )
        self.assertTrue(ok, reason)

    def test_FINAL_A07_unscoped_stage_decision_is_blocked_before_s6(self):
        write_submit_host(self.host)
        path = self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
        task = read_yaml(path)
        digest = observe_candidate(self.host).digest
        task["status"] = "READY_FOR_REVIEW"
        task["stages"] = [_complete_stage("stage-1", digest, scoped=False)]
        task["task_completion_decision"] = satisfied_decision(candidate_digest=digest)
        write_yaml_atomic(path, task)
        self.assertTrue(
            any("unscoped" in item for item in validate_task_book(task, expected_id=TASK_A))
        )
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            bind_ready_authority=False,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertNotEqual(result.outcome, "COMPLETED")
        self.assertNotEqual(result.extras.get("stage"), "S6")
        self.assertEqual(result.extras.get("stage"), "S1")
        self.assertTrue(
            any("unscoped" in item for item in result.blockers),
            result.blockers,
        )


class FA2FinalSurgicalBTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _marker_path(self, record_id: str) -> Path:
        return self.host / NOSCMS_PUBLICATIONS_DIR / record_id / COMPLETE_NAME

    def _publish(self) -> str:
        write_submit_host(self.host)
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        return result.extras["change_record"]["record_id"]

    def _publish_later(self) -> tuple[str, str]:
        first = self._publish()
        write(self.host, "src/app.py", "value = 2\n")
        second = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(second.outcome, "COMPLETED", second.blockers)
        return first, second.extras["change_record"]["record_id"]

    def _assert_not_durable(self, record_id: str) -> None:
        verified = verify_noscms_publication(self.host, record_id)
        self.assertFalse(verified.get("ok"))
        self.assertFalse(verified.get("durable"))
        self.assertEqual(verified.get("observation_state"), "UNKNOWN")
        state = durability_state(self.host, record_id)
        self.assertNotEqual(state.get("state"), "durable")
        self.assertEqual(state.get("observation_state"), "UNKNOWN")
        self.assertFalse(is_durable(self.host, record_id))
        loaded = load_noscms_baseline(self.host)
        self.assertFalse(loaded.get("ok"))
        self.assertEqual(loaded.get("observation_state"), "UNKNOWN")

    def test_FINAL_B01_lineage_less_complete_is_not_durable(self):
        record_id = self._publish()
        path = self._marker_path(record_id)
        marker = read_yaml(path)
        for field in (
            "baseline_generation",
            "parent_generation",
            "parent_representation_digest",
            "parent_change_id",
        ):
            marker.pop(field, None)
        write_yaml_atomic(path, marker)
        self._assert_not_durable(record_id)

    def test_FINAL_B02_malformed_baseline_generation_fails_closed(self):
        record_id = self._publish()
        path = self._marker_path(record_id)
        marker = read_yaml(path)
        marker["baseline_generation"] = "1"
        write_yaml_atomic(path, marker)
        self._assert_not_durable(record_id)

    def test_FINAL_B03_non_genesis_missing_parent_lineage_is_not_durable(self):
        _first, second = self._publish_later()
        path = self._marker_path(second)
        marker = read_yaml(path)
        self.assertGreaterEqual(marker.get("baseline_generation"), 2)
        for field in (
            "parent_generation",
            "parent_representation_digest",
            "parent_change_id",
        ):
            marker.pop(field, None)
        write_yaml_atomic(path, marker)
        self._assert_not_durable(second)

    def test_FINAL_B04_parent_representation_digest_mismatch_is_not_durable(self):
        _first, second = self._publish_later()
        path = self._marker_path(second)
        marker = read_yaml(path)
        marker["parent_representation_digest"] = "ab" * 32
        write_yaml_atomic(path, marker)
        self._assert_not_durable(second)

    def test_FINAL_B05_healthy_genesis_publication_is_durable(self):
        record_id = self._publish()
        verified = verify_noscms_publication(self.host, record_id)
        self.assertTrue(verified.get("ok"), verified.get("blockers"))
        self.assertTrue(verified.get("durable"))
        self.assertTrue(is_durable(self.host, record_id))
        self.assertEqual(durability_state(self.host, record_id)["state"], "durable")
        loaded = load_noscms_baseline(self.host)
        self.assertTrue(loaded.get("ok"), loaded.get("blockers"))
        self.assertEqual(loaded.get("source"), "publication")
        self.assertEqual(loaded.get("change_id"), record_id)
        self.assertEqual(loaded.get("baseline_generation"), 1)

    def test_FINAL_B06_healthy_later_generation_publication_is_durable(self):
        first, second = self._publish_later()
        verified = verify_noscms_publication(self.host, second)
        self.assertTrue(verified.get("ok"), verified.get("blockers"))
        self.assertTrue(verified.get("durable"))
        self.assertTrue(is_durable(self.host, second))
        loaded = load_noscms_baseline(self.host)
        self.assertTrue(loaded.get("ok"), loaded.get("blockers"))
        self.assertEqual(loaded.get("change_id"), second)
        self.assertEqual(loaded.get("baseline_generation"), 2)
        self.assertTrue(verify_noscms_publication(self.host, first).get("durable"))

    def test_FINAL_B07_ok_false_complete_remains_non_durable(self):
        record_id = self._publish()
        path = self._marker_path(record_id)
        marker = read_yaml(path)
        marker["ok"] = False
        write_yaml_atomic(path, marker)
        verified = verify_noscms_publication(self.host, record_id)
        self.assertFalse(verified.get("ok"))
        self.assertFalse(verified.get("durable"))
        self.assertFalse(is_durable(self.host, record_id))
        loaded = load_noscms_baseline(self.host)
        self.assertFalse(loaded.get("ok"))
        self.assertEqual(loaded.get("observation_state"), "UNKNOWN")
        self.assertNotEqual(loaded.get("source"), "publication")
        self.assertNotEqual(loaded.get("source"), "file")

    def test_FINAL_B08_broken_publication_cannot_fall_back_to_baseline_cache(self):
        record_id = self._publish()
        manifest_path = (
            self.host / NOSCMS_PUBLICATIONS_DIR / record_id / "manifest.yaml"
        )
        payload = read_yaml(manifest_path)
        inventory = payload.get("inventory") or {}
        for _path, row in inventory.items():
            if isinstance(row, dict) and row.get("digest"):
                row["digest"] = "0" * 64
                break
        write_yaml_atomic(manifest_path, payload)
        loaded = load_noscms_baseline(self.host)
        self.assertFalse(loaded.get("ok"))
        self.assertEqual(loaded.get("observation_state"), "UNKNOWN")
        self.assertNotEqual(loaded.get("source"), "file")
        self.assertFalse(is_durable(self.host, record_id))


class FA2FinalSurgicalCTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _interface_host(self) -> None:
        write_submit_host(self.host, noscms_working_diff=False)
        write(self.host, "src/save/api.py", "def save():\n    return 1\n")
        write_modules(
            self.host,
            [
                {
                    "id": "save",
                    "path": "src/save/",
                    "interfaces": ["src/save/api.py"],
                }
            ],
        )
        payload = read_yaml(self.host / ".scaffold/project.yaml")
        payload["ownership"] = {**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"}
        payload["source_areas"] = ["src"]
        write_yaml_atomic(self.host / ".scaffold/project.yaml", payload)
        write_ready_task(
            self.host,
            scope={"paths": ["src/"], "modules": [], "exclude": []},
        )
        rebind_noscms_baseline(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        write(self.host, "src/save/api.py", "def save():\n    return 2\n")

    def _publish_satisfied(self) -> tuple[dict, dict]:
        first = run_submit(self.host, task_id=TASK_A)
        published = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="SATISFIED"
        )
        self.assertTrue(published.get("ok"), published.get("blockers"))
        return first, published

    def _head_path(self, published: dict) -> Path:
        path = current_head_path(self.host, published["current_head_locator"])
        self.assertIsNotNone(path)
        assert path is not None
        return path

    def test_FINAL_C01_contradictory_head_record_id_fails_s4(self):
        self._interface_host()
        _first, published = self._publish_satisfied()
        head_path = self._head_path(published)
        head = read_yaml(head_path)
        head["record_id"] = "ka-20990101T000000Z-deadbeef"
        self.assertEqual(head["locator"], published["locator"])
        write_yaml_atomic(head_path, head)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertNotEqual(result.extras.get("stage"), "S6")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertNotEqual(result.extras["knowledge"].get("assessment_state"), "satisfied")

    def test_FINAL_C02_record_id_a_locator_b_is_invalid(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        published_a = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="SATISFIED"
        )
        published_b = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="SATISFIED"
        )
        self.assertNotEqual(published_a["locator"], published_b["locator"])
        head_path = self._head_path(published_b)
        head = read_yaml(head_path)
        head["record_id"] = published_a["assessment"]["record_id"]
        head["locator"] = published_b["locator"]
        write_yaml_atomic(head_path, head)
        loaded = resolve_current_knowledge_assessment(
            self.host,
            candidate_digest=observe_candidate(self.host).digest,
            impact_digest=str(head.get("impact_digest") or ""),
        )
        self.assertFalse(loaded.get("ok"))
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])

    def test_FINAL_C03_mutated_assessment_bytes_fail_integrity(self):
        self._interface_host()
        _first, published = self._publish_satisfied()
        path = self.host / ".scaffold/runtime" / published["locator"]
        data = read_yaml(path)
        data["assessments"][0]["rationale"] = "mutated after P5 publication"
        write_yaml_atomic(path, data)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(
            result.extras["knowledge"].get("assessment_state"),
            "integrity_mismatch",
        )

    def test_FINAL_C04_head_candidate_mismatch_does_not_pass(self):
        self._interface_host()
        _first, published = self._publish_satisfied()
        head_path = self._head_path(published)
        head = read_yaml(head_path)
        head["candidate_digest"] = "ab" * 32
        write_yaml_atomic(head_path, head)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(
            result.extras["knowledge"].get("assessment_state"),
            "candidate_mismatch",
        )

    def test_FINAL_C05_head_impact_mismatch_does_not_pass(self):
        self._interface_host()
        _first, published = self._publish_satisfied()
        head_path = self._head_path(published)
        head = read_yaml(head_path)
        head["impact_digest"] = "cd" * 32
        write_yaml_atomic(head_path, head)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(
            result.extras["knowledge"].get("assessment_state"),
            "impact_mismatch",
        )

    def test_FINAL_C06_coherent_current_head_may_pass(self):
        self._interface_host()
        _first, published = self._publish_satisfied()
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            knowledge_assessment_ref=published["locator"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(result.extras["knowledge"].get("assessment_state"), "satisfied")

    def test_FINAL_C07_superseded_old_locator_remains_blocked(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        published_a = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="SATISFIED"
        )
        published_b = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="UNKNOWN"
        )
        self.assertNotEqual(published_a["locator"], published_b["locator"])
        result = run_submit(
            self.host,
            task_id=TASK_A,
            knowledge_assessment_ref=published_a["locator"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(result.extras["knowledge"].get("assessment_state"), "superseded")

    def test_FINAL_C08_fresh_resolve_recovers_coherent_current_head(self):
        self._interface_host()
        _first, published = self._publish_satisfied()
        digest = observe_candidate(self.host).digest
        first_resolve = resolve_current_knowledge_assessment(
            self.host,
            candidate_digest=digest,
            impact_digest=published["impact_digest"],
        )
        second_resolve = resolve_current_knowledge_assessment(
            self.host,
            candidate_digest=digest,
            impact_digest=published["impact_digest"],
        )
        self.assertTrue(first_resolve.get("ok"), first_resolve.get("blockers"))
        self.assertTrue(second_resolve.get("ok"), second_resolve.get("blockers"))
        self.assertEqual(first_resolve.get("locator"), second_resolve.get("locator"))
        self.assertEqual(
            first_resolve.get("assessment_digest"),
            second_resolve.get("assessment_digest"),
        )
        self.assertEqual(
            first_resolve["assessment"]["record_id"],
            published["assessment"]["record_id"],
        )
        self.assertEqual(
            first_resolve.get("locator"),
            assessment_locator(published["assessment"]["record_id"]),
        )


if __name__ == "__main__":
    unittest.main()

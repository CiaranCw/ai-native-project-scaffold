from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from p6_support import CORE_OWNERSHIP, write_modules
from p7_support import (
    TASK_A,
    satisfied_decision,
    write_active_host,
    write_task,
)
from p8_support import (
    bind_ready_completion_authority,
    init_submit_git,
    publish_knowledge_outcomes,
    rebind_noscms_baseline,
    run_submit,
    write_ready_task,
    write_submit_host,
)
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p6.candidate import observe_candidate
from scaffold_p7.tasks import persist_ready_for_review, publish_task
from scaffold_p8.models import NOSCMS_PUBLICATIONS_DIR
from scaffold_p8.noscms import (
    BASELINE_REL,
    COMPLETE_NAME,
    OBJECTS_DIRNAME,
    load_noscms_baseline,
    verify_noscms_publication,
)
from scaffold_p8.structural import IMPACT_PUBLIC_INTERFACE
from support import write


COMPLETE_STAGES = [
    {
        "stage_id": "stage-1",
        "goal": "Write the fixture source.",
        "acceptance": "src/app.py has the expected content.",
        "status": "COMPLETE",
        "required_tests": [],
    }
]
UNRELATED_DOC = "Weekly changelog typo pass. No interface notes.\n"
RELEVANT_DOC = "save module public interface src/save/api.py\n"
SPELLCHECK_DOC = (
    "Weekly formatting note: api.py was spell-checked;\n"
    "this does not document any public interface change.\n"
)
FULL_PATH_DOC = "Weekly formatting note: src/save/api.py was reflowed.\n"
MULTI_TOKEN_DOC = (
    "save / api.py / PUBLIC_INTERFACE review placeholder; no interface change.\n"
)


class FA2ReauditTrancheBTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _task_path(self, task_id: str = TASK_A) -> Path:
        return self.host / ".scaffold/tasks" / f"{task_id}.yaml"

    def _task(self, task_id: str = TASK_A) -> dict:
        return read_yaml(self._task_path(task_id))

    def _publish_ready(self, payload: dict, expected_revision: int = 1):
        return publish_task(
            self._task_path(), payload, expected_revision=expected_revision
        )

    def test_RB01_01_decisionless_ready_publication_fails_closed(self):
        write_active_host(self.host)
        write_task(self.host, status="IN_PROGRESS", stages=COMPLETE_STAGES)
        illegal = persist_ready_for_review(self._task())
        self.assertNotIn("completion_decision", illegal["stages"][0])
        self.assertNotIn("task_completion_decision", illegal)
        published = self._publish_ready(illegal)
        self.assertFalse(published.ok)
        self.assertFalse(published.conflict)
        stored = self._task()
        self.assertEqual(stored["record_revision"], 1)
        self.assertEqual(stored["status"], "IN_PROGRESS")
        self.assertNotEqual(stored["status"], "READY_FOR_REVIEW")

    def test_RB01_02_missing_task_completion_decision_rejects_ready(self):
        write_active_host(self.host)
        digest = observe_candidate(self.host).digest
        write_task(
            self.host,
            status="IN_PROGRESS",
            stages=[
                {
                    **COMPLETE_STAGES[0],
                    "completion_decision": satisfied_decision(
                        stage_id="stage-1",
                        candidate_digest=digest,
                    ),
                }
            ],
        )
        illegal = persist_ready_for_review(self._task())
        self.assertNotIn("task_completion_decision", illegal)
        published = self._publish_ready(illegal)
        self.assertFalse(published.ok)
        self.assertEqual(self._task()["status"], "IN_PROGRESS")
        self.assertEqual(self._task()["record_revision"], 1)

    def test_RB01_03_missing_stage_decision_rejects_ready(self):
        write_active_host(self.host)
        digest = observe_candidate(self.host).digest
        write_task(
            self.host,
            status="IN_PROGRESS",
            stages=COMPLETE_STAGES,
            task_completion_decision=satisfied_decision(candidate_digest=digest),
        )
        illegal = persist_ready_for_review(self._task())
        self.assertNotIn("completion_decision", illegal["stages"][0])
        published = self._publish_ready(illegal)
        self.assertFalse(published.ok)
        self.assertEqual(self._task()["status"], "IN_PROGRESS")

    def test_RB01_04_valid_ready_publication_remains_legal(self):
        write_active_host(self.host)
        write_task(self.host, status="IN_PROGRESS", stages=COMPLETE_STAGES)
        digest = observe_candidate(self.host).digest
        current = self._task()
        current["stages"][0]["completion_decision"] = satisfied_decision(
            stage_id="stage-1",
            candidate_digest=digest,
        )
        current["task_completion_decision"] = satisfied_decision(
            candidate_digest=digest
        )
        write_yaml_atomic(self._task_path(), current)
        self.assertEqual(observe_candidate(self.host).digest, digest)
        published = self._publish_ready(persist_ready_for_review(self._task()))
        self.assertTrue(published.ok, published.blockers)
        stored = self._task()
        self.assertEqual(stored["status"], "READY_FOR_REVIEW")
        self.assertEqual(stored["record_revision"], 2)
        in_progress = dict(stored)
        in_progress["status"] = "IN_PROGRESS"
        in_progress["title"] = "still-legal-non-ready"
        reopened = publish_task(
            self._task_path(), in_progress, expected_revision=2
        )
        self.assertTrue(reopened.ok, reopened.blockers)
        self.assertEqual(self._task()["status"], "IN_PROGRESS")

    def test_RB01_05_decisionless_ready_submit_blocked_before_s6(self):
        write_submit_host(self.host)
        write_ready_task(self.host, bind_ready_authority=False)
        result = run_submit(
            self.host,
            task_id=TASK_A,
            bind_ready_authority=False,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S1")
        self.assertNotEqual(result.extras.get("stage"), "S5")
        self.assertNotEqual(result.extras.get("stage"), "S6")
        self.assertFalse(result.extras.get("ready_authority", True))
        self.assertNotEqual(result.outcome, "COMPLETED")

    def test_RB01_06_stale_completion_digest_blocks_submit(self):
        write_submit_host(self.host)
        bind_ready_completion_authority(self.host)
        payload = self._task()
        stale = "ab" * 32
        payload["task_completion_decision"]["candidate_digest"] = stale
        payload["stages"][0]["completion_decision"]["candidate_digest"] = stale
        write_yaml_atomic(self._task_path(), payload)
        result = run_submit(
            self.host,
            task_id=TASK_A,
            bind_ready_authority=False,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S1")
        self.assertNotEqual(result.extras.get("stage"), "S6")

    def test_RB01_07_valid_ready_submit_regression(self):
        write_submit_host(self.host)
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras.get("knowledge", {}).get("knowledge_consistent"))
        self.assertNotEqual(result.extras.get("stage"), "S1")

    def _canonical_ready_c1(self) -> tuple[dict, str]:
        write_active_host(self.host)
        write_task(self.host, status="IN_PROGRESS", stages=COMPLETE_STAGES)
        digest = observe_candidate(self.host).digest
        current = self._task()
        current["stages"][0]["completion_decision"] = satisfied_decision(
            stage_id="stage-1",
            candidate_digest=digest,
        )
        current["task_completion_decision"] = satisfied_decision(
            candidate_digest=digest
        )
        write_yaml_atomic(self._task_path(), current)
        self.assertEqual(observe_candidate(self.host).digest, digest)
        published = self._publish_ready(persist_ready_for_review(self._task()))
        self.assertTrue(published.ok, published.blockers)
        stored = self._task()
        self.assertEqual(stored["status"], "READY_FOR_REVIEW")
        self.assertEqual(observe_candidate(self.host).digest, digest)
        return stored, digest

    def _assert_ready_rejects_substantive(self, mutate) -> None:
        stored, digest = self._canonical_ready_c1()
        proposed = copy.deepcopy(stored)
        mutate(proposed)
        published = publish_task(
            self._task_path(),
            proposed,
            expected_revision=stored["record_revision"],
        )
        self.assertFalse(published.ok, published.blockers)
        self.assertFalse(published.conflict)
        after = self._task()
        self.assertEqual(after["status"], "READY_FOR_REVIEW")
        self.assertEqual(after["record_revision"], stored["record_revision"])
        self.assertEqual(after["title"], stored["title"])
        self.assertEqual(after["goal"], stored["goal"])
        self.assertEqual(after["scope"], stored["scope"])
        self.assertEqual(observe_candidate(self.host).digest, digest)

    def test_RB01_R01_ready_cannot_change_title_with_c1_decisions(self):
        self._assert_ready_rejects_substantive(
            lambda proposed: proposed.__setitem__("title", "ready-title-c2")
        )

    def test_RB01_R02_ready_cannot_change_goal_with_c1_decisions(self):
        self._assert_ready_rejects_substantive(
            lambda proposed: proposed.__setitem__("goal", "ready-goal-c2")
        )

    def test_RB01_R03_ready_cannot_change_scope_with_c1_decisions(self):
        def mutate(proposed):
            proposed["scope"] = {
                "paths": ["src/other.py"],
                "modules": [],
                "exclude": [],
            }

        self._assert_ready_rejects_substantive(mutate)

    def test_RB01_R04_ready_cannot_change_stage_plan_with_c1_decisions(self):
        stored, digest = self._canonical_ready_c1()
        revision = stored["record_revision"]

        proposed = copy.deepcopy(stored)
        proposed["stages"][0]["acceptance"] = "changed-stage-acceptance"
        rejected = publish_task(
            self._task_path(), proposed, expected_revision=revision
        )
        self.assertFalse(rejected.ok)
        self.assertEqual(
            self._task()["stages"][0]["acceptance"],
            stored["stages"][0]["acceptance"],
        )

        proposed = copy.deepcopy(self._task())
        proposed["stages"][0]["goal"] = "changed-stage-goal"
        rejected = publish_task(
            self._task_path(), proposed, expected_revision=revision
        )
        self.assertFalse(rejected.ok)
        self.assertEqual(
            self._task()["stages"][0]["goal"], stored["stages"][0]["goal"]
        )

        proposed = copy.deepcopy(self._task())
        proposed["stages"][0]["required_tests"] = [
            {
                "requirement_id": "unit-req",
                "execution_binding": {
                    "kind": "test_profile",
                    "profile_id": "unit",
                },
            }
        ]
        rejected = publish_task(
            self._task_path(), proposed, expected_revision=revision
        )
        self.assertFalse(rejected.ok)
        self.assertEqual(self._task()["stages"][0]["required_tests"], [])
        self.assertEqual(observe_candidate(self.host).digest, digest)
        self.assertEqual(self._task()["status"], "READY_FOR_REVIEW")

    def test_RB01_R05_control_plane_ready_publication_remains_legal(self):
        stored, digest = self._canonical_ready_c1()
        proposed = copy.deepcopy(stored)
        proposed["progress_summary"] = "control-plane-only"
        published = publish_task(
            self._task_path(),
            proposed,
            expected_revision=stored["record_revision"],
        )
        self.assertTrue(published.ok, published.blockers)
        after = self._task()
        self.assertEqual(after["status"], "READY_FOR_REVIEW")
        self.assertEqual(after["progress_summary"], "control-plane-only")
        self.assertEqual(after["title"], stored["title"])
        self.assertEqual(observe_candidate(self.host).digest, digest)

    def test_RB01_R06_in_progress_substantive_then_c2_ready(self):
        stored, digest_c1 = self._canonical_ready_c1()
        in_progress = copy.deepcopy(stored)
        in_progress["status"] = "IN_PROGRESS"
        in_progress["title"] = "substantive-c2"
        first = publish_task(
            self._task_path(),
            in_progress,
            expected_revision=stored["record_revision"],
        )
        self.assertTrue(first.ok, first.blockers)
        digest_c2 = observe_candidate(self.host).digest
        self.assertNotEqual(digest_c2, digest_c1)
        mid = self._task()
        mid["stages"][0]["completion_decision"] = satisfied_decision(
            stage_id="stage-1",
            candidate_digest=digest_c2,
        )
        mid["task_completion_decision"] = satisfied_decision(
            candidate_digest=digest_c2
        )
        second = publish_task(
            self._task_path(),
            mid,
            expected_revision=mid["record_revision"],
        )
        self.assertTrue(second.ok, second.blockers)
        self.assertEqual(observe_candidate(self.host).digest, digest_c2)
        ready = persist_ready_for_review(self._task())
        published = publish_task(
            self._task_path(),
            ready,
            expected_revision=self._task()["record_revision"],
        )
        self.assertTrue(published.ok, published.blockers)
        after = self._task()
        self.assertEqual(after["status"], "READY_FOR_REVIEW")
        self.assertEqual(after["title"], "substantive-c2")
        self.assertEqual(observe_candidate(self.host).digest, digest_c2)

    def test_RB01_R07_manual_stale_ready_still_blocked_at_submit_s1(self):
        write_submit_host(self.host)
        write(self.host, "src/app.py", "value = 99\n")
        result = run_submit(
            self.host,
            task_id=TASK_A,
            bind_ready_authority=False,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S1")
        self.assertNotEqual(result.extras.get("stage"), "S6")
        self.assertNotEqual(result.outcome, "COMPLETED")

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

    def test_RB02_01_unrelated_current_doc_edit_does_not_satisfy_s4(self):
        self._interface_host()
        write(self.host, "docs/project/architecture.md", UNRELATED_DOC)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertIn(
            IMPACT_PUBLIC_INTERFACE,
            result.extras["structural"].get("impact_classes") or [],
        )
        self.assertIn(
            "docs/project/architecture.md",
            result.extras.get("delta", {}).get("paths") or [],
        )
        self.assertEqual(result.next_route, "understand.refresh")

    def test_RB02_02_relevant_looking_text_is_not_s4_authority(self):
        self._interface_host()
        write(self.host, "docs/project/architecture.md", RELEVANT_DOC)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(result.next_route, "understand.refresh")
        self.assertIn(
            "docs/project/architecture.md",
            result.extras.get("delta", {}).get("paths") or [],
        )

    def test_RB02_03_untouched_stale_doc_does_not_satisfy_current_impact(self):
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
        write(self.host, "docs/project/architecture.md", RELEVANT_DOC)
        write_ready_task(
            self.host,
            scope={"paths": ["src/"], "modules": [], "exclude": []},
        )
        rebind_noscms_baseline(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        write(self.host, "src/save/api.py", "def save():\n    return 2\n")
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertNotIn(
            "docs/project/architecture.md",
            result.extras.get("delta", {}).get("paths") or [],
        )

    def test_RB02_04_unrelated_edit_plus_old_token_does_not_pass(self):
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
        write(self.host, "docs/project/architecture.md", RELEVANT_DOC)
        write_ready_task(
            self.host,
            scope={"paths": ["src/"], "modules": [], "exclude": []},
        )
        init_submit_git(self.host)
        write(self.host, "src/save/api.py", "def save():\n    return 2\n")
        write(
            self.host,
            "docs/project/architecture.md",
            RELEVANT_DOC + UNRELATED_DOC,
        )
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertIn(
            "docs/project/architecture.md",
            result.extras.get("delta", {}).get("paths") or [],
        )

    def test_RB02_05_non_structural_edit_does_not_force_doc_churn(self):
        write_submit_host(self.host)
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.extras["structural"].get("impact_classes") or [], [])
        self.assertTrue(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(result.extras["knowledge"].get("missing_surfaces") or [], [])

    def test_RB02_06_unprovable_doc_relevance_is_unknown_not_pass(self):
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
        write(self.host, "docs/project/architecture.md", "placeholder\n")
        write_ready_task(
            self.host,
            scope={"paths": ["src/"], "modules": [], "exclude": []},
        )
        rebind_noscms_baseline(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        write(self.host, "src/save/api.py", "def save():\n    return 2\n")
        write(self.host, "docs/project/architecture.md", RELEVANT_DOC)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        knowledge = result.extras["knowledge"]
        self.assertFalse(knowledge["knowledge_consistent"])
        self.assertTrue(knowledge.get("unknown_relevance_surfaces"))
        self.assertEqual(result.next_route, "understand.refresh")

    def test_RB02_R01_spellcheck_basename_does_not_pass(self):
        self._interface_host()
        write(self.host, "docs/project/architecture.md", SPELLCHECK_DOC)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(result.next_route, "understand.refresh")

    def test_RB02_R02_full_path_token_does_not_pass(self):
        self._interface_host()
        write(self.host, "docs/project/architecture.md", FULL_PATH_DOC)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])

    def test_RB02_R03_multi_token_trap_does_not_pass(self):
        self._interface_host()
        write(self.host, "docs/project/architecture.md", MULTI_TOKEN_DOC)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])

    def test_RB02_R04_old_tokens_plus_current_basename_do_not_pass(self):
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
        write(self.host, "docs/project/architecture.md", RELEVANT_DOC)
        write_ready_task(
            self.host,
            scope={"paths": ["src/"], "modules": [], "exclude": []},
        )
        init_submit_git(self.host)
        write(self.host, "src/save/api.py", "def save():\n    return 2\n")
        write(
            self.host,
            "docs/project/architecture.md",
            RELEVANT_DOC + "Weekly formatting note: api.py was spell-checked.\n",
        )
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])

    def test_RB02_R05_current_satisfied_assessment_can_pass(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(first.extras.get("stage"), "S4")
        published = publish_knowledge_outcomes(
            self.host, first.extras["structural"]
        )
        self.assertTrue(published["ok"], published.get("blockers"))
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            knowledge_assessment_ref=published["locator"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras["knowledge"]["knowledge_consistent"])

    def test_RB02_R06_c1_assessment_stales_after_c2(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        published = publish_knowledge_outcomes(
            self.host, first.extras["structural"]
        )
        self.assertTrue(published["ok"], published.get("blockers"))
        write(self.host, "src/save/api.py", "def save():\n    return 3\n")
        result = run_submit(
            self.host,
            task_id=TASK_A,
            knowledge_assessment_ref=published["locator"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertIn("stale", " ".join(result.blockers).lower())

    def test_RB02_R07_assessment_for_different_impact_set_does_not_pass(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        published = publish_knowledge_outcomes(
            self.host,
            first.extras["structural"],
            impacts=[
                {
                    "class": "COMMAND",
                    "path": ".scaffold/commands.yaml",
                    "status": "DETERMINED",
                    "detail": "readable",
                }
            ],
        )
        self.assertTrue(published["ok"], published.get("blockers"))
        result = run_submit(
            self.host,
            task_id=TASK_A,
            knowledge_assessment_ref=published["locator"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])

    def _publish_noscms(self) -> str:
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

    def _marker_path(self, record_id: str) -> Path:
        return self.host / NOSCMS_PUBLICATIONS_DIR / record_id / COMPLETE_NAME

    def test_RB03_01_ok_false_complete_is_not_durable(self):
        record_id = self._publish_noscms()
        marker_path = self._marker_path(record_id)
        marker = read_yaml(marker_path)
        marker["ok"] = False
        write_yaml_atomic(marker_path, marker)
        verified = verify_noscms_publication(self.host, record_id)
        self.assertFalse(verified.get("ok"))
        self.assertFalse(verified.get("durable"))
        loaded = load_noscms_baseline(self.host)
        self.assertFalse(loaded.get("ok"))
        self.assertEqual(loaded.get("observation_state"), "UNKNOWN")
        self.assertNotEqual(loaded.get("source"), "publication")
        self.assertNotEqual(loaded.get("source"), "file")

    def test_RB03_02_malformed_complete_field_fails_closed(self):
        record_id = self._publish_noscms()
        marker_path = self._marker_path(record_id)
        marker = read_yaml(marker_path)
        marker["candidate_digest"] = 123
        write_yaml_atomic(marker_path, marker)
        verified = verify_noscms_publication(self.host, record_id)
        self.assertFalse(verified.get("ok"))
        loaded = load_noscms_baseline(self.host)
        self.assertFalse(loaded.get("ok"))
        self.assertEqual(loaded.get("observation_state"), "UNKNOWN")

    def test_RB03_03_inconsistent_representation_binding_fails(self):
        record_id = self._publish_noscms()
        marker_path = self._marker_path(record_id)
        marker = read_yaml(marker_path)
        marker["representation_digest"] = "ab" * 32
        write_yaml_atomic(marker_path, marker)
        verified = verify_noscms_publication(self.host, record_id)
        self.assertFalse(verified.get("ok"))
        self.assertFalse(verified.get("durable"))
        loaded = load_noscms_baseline(self.host)
        self.assertFalse(loaded.get("ok"))
        self.assertEqual(loaded.get("observation_state"), "UNKNOWN")

    def test_RB03_04_healthy_publication_remains_valid(self):
        record_id = self._publish_noscms()
        verified = verify_noscms_publication(self.host, record_id)
        self.assertTrue(verified.get("ok"), verified.get("blockers"))
        self.assertTrue(verified.get("durable"))
        loaded = load_noscms_baseline(self.host)
        self.assertTrue(loaded.get("ok"), loaded.get("blockers"))
        self.assertEqual(loaded.get("source"), "publication")
        self.assertEqual(loaded.get("change_id"), record_id)

    def test_RB03_05_initial_no_publication_baseline_remains_legal(self):
        write_submit_host(self.host, noscms_working_diff=False)
        pubs = self.host / NOSCMS_PUBLICATIONS_DIR
        if pubs.exists():
            self.assertFalse(any(pubs.iterdir()))
        loaded = load_noscms_baseline(self.host)
        self.assertTrue(loaded.get("ok"), loaded.get("blockers"))
        self.assertEqual(loaded.get("source"), "file")

    def test_RB03_06_maj007_broken_object_does_not_heal_from_cache(self):
        record_id = self._publish_noscms()
        objects = self.host / NOSCMS_PUBLICATIONS_DIR / record_id / OBJECTS_DIRNAME
        blobs = list(objects.iterdir()) if objects.is_dir() else []
        self.assertTrue(blobs)
        blobs[0].unlink()
        self.assertTrue((self.host / BASELINE_REL).is_file())
        self.assertTrue(self._marker_path(record_id).is_file())
        marker = read_yaml(self._marker_path(record_id))
        self.assertIs(marker.get("ok"), True)
        loaded = load_noscms_baseline(self.host)
        self.assertFalse(loaded.get("ok"))
        self.assertEqual(loaded.get("observation_state"), "UNKNOWN")
        self.assertNotEqual(loaded.get("source"), "file")
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S2")


if __name__ == "__main__":
    unittest.main()

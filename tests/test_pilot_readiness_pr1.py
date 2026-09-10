from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from p6_support import (
    CORE_OWNERSHIP,
    dummy_lock_entry,
    init_git,
    passing_profile,
    write_host,
    write_lock,
)
from p7_support import (
    REPO_DEVELOP,
    TASK_A,
    TASK_B,
    bind_develop_lock,
    develop_engine,
    four_core_lock_skills,
    write_task,
)
from support import write

from scaffold_entry import enter_project, present_result, project_status
from scaffold_p5.host_state import snapshot_host
from scaffold_p5.io_util import file_digest, read_text, read_yaml, write_yaml_atomic
from scaffold_p5.packages import load_package
from scaffold_p5.scm import OBSERVATION_FAILED
from scaffold_p5 import scm as scm_mod
from scaffold_p7.intake import task_proposal
from scaffold_p7.models import DEVELOP_MODES
from scaffold_p7.schemas import validate_task_book
from scaffold_p7.tasks import resolve_task


class PilotReadinessPR1Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.host = self.root / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_PRT01_zero_context_active_host_creates_canonical_task(self):
        self._active_host()
        result = self._enter(self._proposal(), self._grounding())
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        task_id = result.extras["task"]["record_id"]
        resolved = resolve_task(self.host, task_id=task_id)
        self.assertTrue(resolved.ok, resolved.blockers)
        self.assertEqual(resolved.task["status"], "IN_PROGRESS")
        self.assertFalse((self.host / ".scaffold/runtime/develop-sessions").exists())

    def test_PRT02_explicit_existing_task_routes_without_duplicate(self):
        self._active_host()
        write_task(self.host)
        before = self._task_paths()
        decision = enter_project(
            self.host,
            structured_intent={
                "kind": "develop",
                "action": "implement",
                "task_id": TASK_A,
            },
            develop_package=REPO_DEVELOP,
        )
        self.assertEqual(decision["outcome"], "ROUTED")
        self.assertEqual(decision["route"], "develop.normal_task")
        self.assertEqual(self._task_paths(), before)

    def test_PRT03_ambiguous_intent_needs_human_without_task(self):
        self._active_host()
        grounding = self._grounding(
            uncertainties=["Which combat behavior should change?"],
            material_decisions=["Choose a combat redesign"],
        )
        result = self._enter(self._proposal(goal="Improve combat."), grounding)
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertEqual(self._task_paths(), [])
        self.assertTrue(result.extras["grounding"]["issues"])
        self.assertEqual(result.mutations, "none")

    def test_PRT04_hard_rule_conflict_blocks_task_activation(self):
        self._active_host()
        project_path = self.host / ".scaffold/project.yaml"
        project = read_yaml(project_path)
        project["rule_refs"] = ["docs/project/no-source.rules.yaml"]
        write_yaml_atomic(project_path, project)
        write_yaml_atomic(
            self.host / "docs/project/no-source.rules.yaml",
            {
                "schema_version": "1",
                "rules": [
                    {
                        "rule_id": "no-pilot-source",
                        "applies_to": ["develop"],
                        "effect": "PROHIBIT",
                        "operations": ["source_write"],
                        "scope": {"kind": "path", "paths": ["src/app.py"]},
                        "statement": "Do not modify the pilot source.",
                    }
                ],
            },
        )
        result = self._enter(self._proposal(), self._grounding())
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertTrue(any("no-pilot-source" in item for item in result.blockers))
        self.assertEqual(self._task_paths(), [])
        self.assertFalse((self.host / ".scaffold/runtime/develop-sessions").exists())

    def test_PRT05_unadopted_project_routes_to_understand_bootstrap(self):
        write(self.host, "README.md", "# ordinary project\n")
        decision = enter_project(
            self.host,
            structured_intent={"kind": "develop", "action": "implement"},
            proposal=self._proposal(),
            grounding=self._grounding(),
            develop_package=REPO_DEVELOP,
        )
        self.assertEqual(decision["outcome"], "ROUTED")
        self.assertEqual(decision["route"], "understand.bootstrap")
        self.assertEqual(project_status(self.host)["next_route"], "understand.bootstrap")
        self.assertEqual(self._task_paths(), [])

    def test_PRT06_needs_refresh_routes_before_task_intake(self):
        self._active_host(maintenance=["NEEDS_REFRESH"])
        decision = enter_project(
            self.host,
            structured_intent={"kind": "develop", "action": "implement"},
            proposal=self._proposal(),
            grounding=self._grounding(),
            develop_package=REPO_DEVELOP,
        )
        self.assertEqual(decision["route"], "understand.refresh")
        self.assertEqual(project_status(self.host)["next_route"], "understand.refresh")
        self.assertEqual(self._task_paths(), [])

    def test_PRT07_concurrent_same_proposal_has_one_authoritative_task(self):
        self._active_host()

        def invoke():
            return self._enter(self._proposal(), self._grounding())

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _item: invoke(), range(2)))
        self.assertTrue(all(result.outcome == "COMPLETED" for result in results))
        self.assertEqual(len(self._task_paths()), 1)
        ids = {result.extras["task"]["record_id"] for result in results}
        self.assertEqual(len(ids), 1)
        self.assertEqual(
            sum(bool(result.extras["task_reused"]) for result in results),
            1,
        )

    def test_PRT08_public_entry_requires_no_manual_scaffold_edit(self):
        self._active_host()
        source_before = read_text(self.host / "src/app.py")
        proposal = self._proposal()
        result = enter_project(
            self.host,
            structured_intent={
                "kind": "develop",
                "action": "implement",
                "explicit_implementation": True,
                "request": "Add the bounded app behavior and tests.",
                "authorized_proposal": proposal,
            },
            proposal=proposal,
            grounding=self._grounding(),
            develop_package=REPO_DEVELOP,
        )
        self.assertEqual(result.outcome, "COMPLETED")
        task_file = self.host / result.artifacts[0]
        self.assertTrue(task_file.is_file())
        self.assertEqual(read_text(self.host / "src/app.py"), source_before)
        self.assertEqual(result.mutations, "task_book")

    def test_PRT09_status_is_projection_from_durable_authority(self):
        self._active_host()
        write_task(self.host)
        status = project_status(self.host)
        self.assertEqual(status["kind"], "status_projection")
        self.assertEqual(status["project"]["name"], self.host.name)
        self.assertEqual(status["project"]["lifecycle"], "ACTIVE")
        self.assertEqual(status["current_task"]["record_id"], TASK_A)
        self.assertEqual(status["next_route"], "develop.normal_task")
        self.assertFalse(status["executable_compatibility_evaluated"])
        self.assertIn("project.yaml", status["source"])
        self.assertIn("not executable package compatibility", status["source"])

    def test_PRT10_task_intake_grants_no_other_permission(self):
        self._active_host()
        result = self._enter(self._proposal(), self._grounding())
        capabilities = result.extras["capabilities"]
        self.assertTrue(all(value is False for value in capabilities.values()))
        self.assertFalse(result.extras["submit_authorized"])
        gate = present_result(result)
        self.assertIn("remains_unchanged", gate)

    def test_PRT11_bounded_explicit_request_may_create_in_progress(self):
        self._active_host()
        proposal = self._proposal()
        result = develop_engine(self.host).intake(
            structured_intent=self._intent(proposal),
            proposal=proposal,
            grounding=self._grounding(),
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.extras["task"]["status"], "IN_PROGRESS")
        self.assertEqual(result.extras["grounding"]["direct_activation"], True)

    def test_PRT12_material_design_choices_do_not_auto_activate(self):
        self._active_host()
        result = self._enter(
            self._proposal(goal="Redesign combat around a new timing model."),
            self._grounding(
                intent_fields=["goal"],
                material_decisions=[
                    "Select timing model",
                    "Redesign combat interfaces",
                ],
            ),
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertFalse(result.extras["grounding"]["direct_activation"])
        self.assertFalse(
            any(
                read_yaml(path).get("status") == "IN_PROGRESS"
                for path in self._task_paths()
            )
        )

    def test_PRT12_proposal_scope_expansion_stays_draft(self):
        self._active_host()
        authorized = self._proposal(paths=["src/app.py"])
        expanded = self._proposal(paths=["src/app.py", "tests/test_app.py"])
        intent = self._intent(authorized)
        result = enter_project(
            self.host,
            structured_intent=intent,
            proposal=expanded,
            grounding=self._grounding(),
            develop_package=REPO_DEVELOP,
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertFalse(result.extras["grounding"]["direct_activation"])
        self.assertTrue(
            any(
                "exceeds or differs" in issue
                for issue in result.extras["grounding"]["direct_activation_issues"]
            )
        )
        task = read_yaml(self.host / result.artifacts[0])
        self.assertEqual(task["status"], "DRAFT")

    def test_PRT13_matching_tasks_are_status_aware(self):
        expected = {
            "DRAFT": ("COMPLETED", "IN_PROGRESS"),
            "IN_PROGRESS": ("COMPLETED", "IN_PROGRESS"),
            "READY_FOR_REVIEW": ("NEEDS_HUMAN", "READY_FOR_REVIEW"),
            "CANCELED": ("NEEDS_HUMAN", "CANCELED"),
        }
        for status, (outcome, final_status) in expected.items():
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as tmp:
                    self.host = Path(tmp) / "host"
                    self.host.mkdir()
                    self._active_host()
                    self._write_matching_task(TASK_A, status)
                    result = self._enter(self._proposal(), self._grounding())
                    stored = read_yaml(self._task_paths()[0])
                    self.assertEqual(result.outcome, outcome)
                    self.assertEqual(stored["status"], final_status)
                    self.assertEqual(len(self._task_paths()), 1)

    def test_PRT13_grounded_planning_request_creates_draft(self):
        self._active_host()
        intent = {
            "kind": "develop",
            "action": "plan",
            "explicit_implementation": False,
            "request": "Prepare a bounded plan for this app behavior.",
        }
        result = develop_engine(self.host).intake(
            structured_intent=intent,
            proposal=self._proposal(),
            grounding=self._grounding(),
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        task = read_yaml(self.host / result.artifacts[0])
        self.assertEqual(task["status"], "DRAFT")
        self.assertEqual(task["record_revision"], 1)

    def test_PRT14_multiple_matching_tasks_are_conflict(self):
        self._active_host()
        self._write_matching_task(TASK_A, "IN_PROGRESS")
        self._write_matching_task(TASK_B, "IN_PROGRESS")
        result = self._enter(self._proposal(), self._grounding())
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertTrue(any("multiple authoritative" in item for item in result.blockers))
        self.assertEqual(len(self._task_paths()), 2)
        self.assertIsNone(result.extras["task"])

    def test_PRT15_real_generic_evaluator_allows_declared_2_1_substitute(self):
        self._active_host()
        old = four_core_lock_skills(
            develop_entry=dummy_lock_entry("2.0.0", "1" * 64)
        )
        write_lock(self.host, old)
        lock_path = self.host / ".scaffold/skills.lock"
        before = file_digest(lock_path)
        result = self._enter(self._proposal(), self._grounding())
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.compatibility, "COMPATIBLE")
        self.assertEqual(
            result.extras["actual_package"]["skill_version"], "2.1.0"
        )
        self.assertEqual(
            result.extras["expected_package"]["skill_version"], "2.0.0"
        )
        self.assertEqual(file_digest(lock_path), before)
        self.assertTrue(
            any(
                entry.get("skill_version") == "2.0.0"
                for entry in load_package(REPO_DEVELOP).may_substitute_for
            )
        )

    def test_PRT16_intake_digest_adds_no_task_field(self):
        self._active_host()
        result = self._enter(self._proposal(), self._grounding())
        task = read_yaml(self.host / result.artifacts[0])
        self.assertEqual(validate_task_book(task), [])
        self.assertNotIn("proposal_digest", task)
        self.assertNotIn("intake", task)
        self.assertNotIn("request", task)
        self.assertNotIn("caller_prose", task)

    def test_PRT17_entry_requires_structured_intent_not_keywords(self):
        self._active_host()
        decision = enter_project(
            self.host,
            structured_intent={
                "request": "Implement this immediately and run tests."
            },
            proposal=self._proposal(),
            grounding=self._grounding(),
            develop_package=REPO_DEVELOP,
        )
        self.assertEqual(decision["outcome"], "NEEDS_HUMAN")
        self.assertEqual(decision["route"], "human")
        self.assertEqual(self._task_paths(), [])

    def test_PRT18_intake_reports_normal_task_mode_without_implementation(self):
        self._active_host()
        result = self._enter(self._proposal(), self._grounding())
        self.assertEqual(result.skill_id, "develop")
        self.assertEqual(result.mode, "normal_task")
        self.assertEqual(result.extras["operation"], "task_intake")
        capabilities = result.extras["capabilities"]
        self.assertFalse(capabilities["source_write"])
        self.assertFalse(capabilities["commit"])
        self.assertFalse(capabilities["push"])
        self.assertFalse(capabilities["submit_authorized"])
        self.assertFalse(result.extras["submit_authorized"])
        self.assertFalse((self.host / ".scaffold/runtime/develop-sessions").exists())
        self.assertEqual(result.mutations, "task_book")

    def test_PRT19_planning_intake_stays_normal_task_prelude(self):
        self._active_host()
        intent = {
            "kind": "develop",
            "action": "plan",
            "explicit_implementation": False,
            "request": "Prepare a bounded plan for this app behavior.",
        }
        result = develop_engine(self.host).intake(
            structured_intent=intent,
            proposal=self._proposal(),
            grounding=self._grounding(),
        )
        self.assertEqual(result.skill_id, "develop")
        self.assertEqual(result.mode, "normal_task")
        self.assertEqual(result.extras["operation"], "task_intake")
        self.assertEqual(result.extras["task"]["status"], "DRAFT")
        self.assertEqual(tuple(result.extras["package"]["modes"]), DEVELOP_MODES)
        self.assertEqual(DEVELOP_MODES, ("normal_task", "repair"))
        manifest_modes = load_package(REPO_DEVELOP).manifest.get("modes")
        self.assertEqual(manifest_modes, ["normal_task", "repair"])
        self.assertNotIn("task_intake", manifest_modes)

    def test_PRT20_recovery_required_status_does_not_recommend_develop(self):
        self._active_host(lifecycle="RECOVERY_REQUIRED")
        write_task(self.host)
        snap = snapshot_host(self.host)
        self.assertEqual(snap.lifecycle, "RECOVERY_REQUIRED")
        self.assertTrue(snap.lock.complete_authoritative)
        status = project_status(self.host)
        self.assertNotEqual(status["next_route"], "develop.normal_task")
        self.assertEqual(status["next_route"], "understand.compatibility")
        self.assertTrue(
            any("RECOVERY_REQUIRED" in item for item in status["blockers"])
        )
        decision = enter_project(
            self.host,
            structured_intent={"kind": "develop", "action": "implement"},
            proposal=self._proposal(),
            grounding=self._grounding(),
            develop_package=REPO_DEVELOP,
        )
        self.assertEqual(decision["route"], status["next_route"])
        self.assertEqual(len(self._task_paths()), 1)

    def test_PRT21_unusable_scm_status_does_not_recommend_develop(self):
        self._active_host()
        write_task(self.host)
        init_git(self.host)
        failed = scm_mod._GitBytesResult(False, 1, b"", b"fixture failure")
        with mock.patch("scaffold_p5.scm._run_git_bytes", return_value=failed):
            status = project_status(self.host)
        self.assertNotEqual(status["next_route"], "develop.normal_task")
        self.assertEqual(status["next_route"], "human")
        self.assertTrue(status["blockers"])
        self.assertEqual(status["scm"]["kind"], "git")
        self.assertEqual(status["scm"]["observation_state"], OBSERVATION_FAILED)
        self.assertFalse(status["scm"]["observation_ok"])
        self.assertNotEqual(status["scm"]["kind"], "none")
        self.assertNotEqual(status["scm"]["observation_state"], "clean")

    def test_PRT22_malformed_task_authority_status_fails_closed(self):
        self._active_host()
        write_task(self.host)
        malformed = self.host / ".scaffold/tasks" / f"{TASK_B}.yaml"
        malformed.write_text("this is not a Task Book\n: :\n", encoding="utf-8")
        before = malformed.read_text(encoding="utf-8")
        status = project_status(self.host)
        after_paths = self._task_paths()
        self.assertTrue(status["blockers"])
        self.assertNotEqual(status["next_route"], "develop.normal_task")
        self.assertEqual(status["next_route"], "human")
        self.assertIsNone(status["current_task"])
        self.assertEqual(malformed.read_text(encoding="utf-8"), before)
        self.assertEqual(after_paths, [self.host / ".scaffold/tasks" / f"{TASK_A}.yaml", malformed])

    def test_PRT23_multiple_in_progress_status_does_not_choose(self):
        self._active_host()
        write_task(self.host, TASK_A)
        write_task(self.host, TASK_B)
        status = project_status(self.host)
        self.assertNotEqual(status["next_route"], "develop.normal_task")
        self.assertEqual(status["next_route"], "human")
        self.assertIsNone(status["current_task"])
        self.assertTrue(
            any("multiple IN_PROGRESS" in item for item in status["blockers"])
        )

    def test_DIVE_like_request_stays_generic_and_bounded(self):
        self._active_host(source_areas=["src", "tests"])
        write(self.host, "AGENTS.md", read_text(self.host / "AGENTS.md"))
        write(
            self.host,
            "docs/design.md",
            "# Design\n\nBeacon is an existing content-layer concept.\n",
        )
        write(self.host, "src/beacon.py", "ENABLED = False\n")
        write(self.host, "tests/test_beacon.py", "# beacon tests\n")
        project_path = self.host / ".scaffold/project.yaml"
        project = read_yaml(project_path)
        project["ownership"]["AGENTS.md"] = "HUMAN_OWNED"
        project["ownership"]["docs/design.md"] = "HUMAN_OWNED"
        project["ownership"]["tests/"] = "HUMAN_OWNED"
        project["rule_refs"] = ["docs/project/beacon.rules.yaml"]
        write_yaml_atomic(project_path, project)
        write_yaml_atomic(
            self.host / "docs/project/beacon.rules.yaml",
            {
                "schema_version": "1",
                "rules": [
                    {
                        "rule_id": "beacon-content-only",
                        "applies_to": ["develop"],
                        "effect": "ADVISE",
                        "operations": ["source_write"],
                        "scope": {
                            "kind": "path",
                            "paths": ["src/beacon.py", "tests/test_beacon.py"],
                        },
                        "statement": "Keep Beacon work in content and tests.",
                    }
                ],
            },
        )
        proposal = self._proposal(
            title="Enable Beacon",
            goal="Enable the existing Beacon content-layer concept and add tests.",
            paths=["src/beacon.py", "tests/test_beacon.py"],
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Enable the existing Beacon content behavior.",
                    "acceptance": "Beacon content is enabled without UI expansion.",
                    "required_tests": [],
                },
                {
                    "stage_id": "stage-2",
                    "goal": "Add the necessary Beacon tests.",
                    "acceptance": "The existing unit profile covers Beacon.",
                    "required_tests": ["unit"],
                },
            ],
        )
        result = self._enter(proposal, self._grounding())
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        task = read_yaml(self.host / result.artifacts[0])
        rendered = str(task).lower()
        self.assertIn("src/beacon.py", task["scope"]["paths"])
        self.assertIn("tests/test_beacon.py", task["scope"]["paths"])
        self.assertNotIn("engine special", rendered)
        self.assertNotIn("new ui", rendered)
        self.assertEqual(
            result.extras["project_rules"]["advisories"][0]["rule_id"],
            "beacon-content-only",
        )

    def _active_host(
        self,
        *,
        maintenance: list[str] | None = None,
        source_areas: list[str] | None = None,
        lifecycle: str = "ACTIVE",
    ) -> None:
        profile, command = passing_profile("unit")
        areas = source_areas or ["src", "tests"]
        ownership = {
            **CORE_OWNERSHIP,
            **{f"{area.rstrip('/')}/": "HUMAN_OWNED" for area in areas},
        }
        write_host(
            self.host,
            [(profile, command)],
            ownership=ownership,
            source_areas=areas,
            maintenance=list(maintenance or []),
            lifecycle=lifecycle,
        )
        bind_develop_lock(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        write(self.host, "tests/test_app.py", "# app tests\n")

    def _enter(self, proposal: dict, grounding: dict):
        return enter_project(
            self.host,
            structured_intent=self._intent(proposal),
            proposal=proposal,
            grounding=grounding,
            develop_package=REPO_DEVELOP,
        )

    @staticmethod
    def _intent(proposal: dict) -> dict:
        return {
            "kind": "develop",
            "action": "implement",
            "explicit_implementation": True,
            "request": "Implement the bounded app behavior and tests.",
            "authorized_proposal": proposal,
        }

    @staticmethod
    def _grounding(
        *,
        intent_fields: list[str] | None = None,
        knowledge_fields: list[str] | None = None,
        uncertainties: list[str] | None = None,
        material_decisions: list[str] | None = None,
    ) -> dict:
        return {
            "intent_fields": intent_fields
            if intent_fields is not None
            else ["goal", "scope", "acceptance", "stages", "tests"],
            "knowledge_fields": knowledge_fields
            if knowledge_fields is not None
            else ["scope", "rules", "ownership", "tests"],
            "uncertainties": list(uncertainties or []),
            "material_decisions": list(material_decisions or []),
        }

    @staticmethod
    def _proposal(
        *,
        title: str = "Implement bounded app behavior",
        goal: str = "Implement the bounded app behavior and its tests.",
        paths: list[str] | None = None,
        stages: list[dict] | None = None,
    ) -> dict:
        return {
            "title": title,
            "goal": goal,
            "acceptance": "The app behavior is implemented and unit verification is planned.",
            "scope": {
                "paths": paths or ["src/app.py", "tests/test_app.py"],
                "modules": [],
                "exclude": [],
            },
            "stages": stages
            or [
                {
                    "stage_id": "stage-1",
                    "goal": "Implement the bounded source behavior.",
                    "acceptance": "The source reflects the requested behavior.",
                    "required_tests": [],
                },
                {
                    "stage_id": "stage-2",
                    "goal": "Add or update the necessary tests.",
                    "acceptance": "Unit verification covers the behavior.",
                    "required_tests": ["unit"],
                },
            ],
            "final_tests": ["unit"],
        }

    def _write_matching_task(self, task_id: str, status: str) -> None:
        proposal = self._proposal()
        normalized = task_proposal(
            {
                **proposal,
                "stages": [
                    {
                        **stage,
                        "status": "PENDING",
                        "required_tests": [
                            {"requirement_id": test_id}
                            for test_id in stage["required_tests"]
                        ],
                    }
                    for stage in proposal["stages"]
                ],
                "final_tests": [
                    {"requirement_id": test_id}
                    for test_id in proposal["final_tests"]
                ],
            }
        )
        write_task(
            self.host,
            task_id,
            title=normalized["title"],
            goal=normalized["goal"],
            acceptance=normalized["acceptance"],
            scope=normalized["scope"],
            status=status,
            stages=[
                {
                    **stage,
                    "status": "COMPLETE"
                    if status == "READY_FOR_REVIEW"
                    else "PENDING",
                }
                for stage in normalized["stages"]
            ],
            final_tests=[
                {
                    **item,
                    **(
                        {"observed_outcome": "PASS"}
                        if status == "READY_FOR_REVIEW"
                        else {}
                    ),
                }
                for item in normalized["final_tests"]
            ],
        )

    def _task_paths(self) -> list[Path]:
        folder = self.host / ".scaffold/tasks"
        return sorted(folder.glob("*.yaml")) if folder.is_dir() else []


if __name__ == "__main__":
    unittest.main()

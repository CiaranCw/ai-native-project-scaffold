from __future__ import annotations

import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from p6_support import (
    CORE_OWNERSHIP,
    actual_test_lock_entry,
    failing_profile,
    passing_profile,
    py_command,
    write_host,
    write_lock,
    write_skill_package,
)
from p7_support import (
    TASK_A,
    TASK_B,
    actual_develop_lock_entry,
    bind_develop_lock,
    develop_engine,
    ensure_noscms_accepted_anchor,
    repair_handoff,
    satisfied_decision,
    submit_repair_handoff,
    write_active_host,
    write_task,
)
from p8_support import bind_ready_completion_authority
from scaffold_p5.compatibility import evaluate_host, migration_need
from scaffold_p5.distribution import load_fixture_distribution
from scaffold_p5.engine import UnderstandEngine
from scaffold_p5.host_state import snapshot_host
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p5.migration import load_execution, validate_recovery_state
from scaffold_p5.packages import load_package
from scaffold_p5.schemas import whole_file_mutation_allowed
from scaffold_p6.candidate import observe_candidate
from scaffold_p7.migration_run import reconstruct_migration_view
from scaffold_p7.repair_state import reconstruct_repair_view
from scaffold_p7.repair_targets import map_repair_target_stage_ids
from scaffold_p7.session import existing_session_ids
from scaffold_p7.tasks import publish_task
from support import FIXTURE_DIST, RELEASED_UNDERSTAND, REPO, adopt, apply_fresh_migration, distribution, live_understand_distribution, write


MOVEMENT_PROFILE = "movement-smoke"
MOVEMENT_REQUIREMENT = "movement/smoke"
LIVE_SKILL_DIRS = [
    REPO / "skills" / "develop",
    REPO / "skills" / "test",
    REPO / "skills" / "submit",
]


def p9_dist(
    actual_understand_version: str = "2.0.0",
    *,
    actual_understand_dir: Path | None = None,
):
    return load_fixture_distribution(
        FIXTURE_DIST,
        selected_release_id="rel-r1",
        actual_understand_version=actual_understand_version,
        actual_understand_dir=actual_understand_dir,
        extra_package_dirs=LIVE_SKILL_DIRS,
        repo_understand=REPO / "skills" / "understand",
    )


def bind_resolvable_lock(
    host: Path,
    *,
    understand: Path | None = None,
    test_entry: dict | None = None,
) -> None:
    understand_pkg = load_package(understand or RELEASED_UNDERSTAND)
    submit_pkg = load_package(REPO / "skills" / "submit")
    write_lock(
        host,
        {
            "understand": {
                "skill_version": understand_pkg.ref.skill_version,
                "package_digest": understand_pkg.ref.package_digest,
                "package_format_version": understand_pkg.ref.package_format_version,
            },
            "develop": actual_develop_lock_entry(),
            "test": test_entry if test_entry is not None else actual_test_lock_entry(),
            "submit": {
                "skill_version": submit_pkg.ref.skill_version,
                "package_digest": submit_pkg.ref.package_digest,
                "package_format_version": submit_pkg.ref.package_format_version,
            },
        },
    )


def explicit_ref(
    requirement_id: str = MOVEMENT_REQUIREMENT,
    profile_id: str = MOVEMENT_PROFILE,
) -> dict:
    return {
        "requirement_id": requirement_id,
        "execution_binding": {"kind": "test_profile", "profile_id": profile_id},
    }


def current_task(host: Path, task_id: str = TASK_A) -> dict:
    return read_yaml(host / ".scaffold/tasks" / f"{task_id}.yaml")


def bound_migration_approval(
    host: Path,
    plan: dict,
    task_id: str = TASK_A,
) -> dict:
    task = current_task(host, task_id)
    return {
        "approved": True,
        "plan_id": plan["plan_id"],
        "plan_digest": plan["digest"],
        "task_id": task["record_id"],
        "task_revision": task["record_revision"],
        "candidate_digest": observe_candidate(host).digest,
    }


def preview_migration(host: Path, task_id: str = TASK_A, dist=None):
    return develop_engine(host).run(
        "normal_task",
        task_id=task_id,
        execute_approved_migration=True,
        distribution=dist or distribution("2.1.0"),
    )


def movement_profile() -> tuple[dict, dict]:
    profile, command = passing_profile(MOVEMENT_PROFILE)
    command["argv"] = py_command(
        "from pathlib import Path; "
        "text = Path('src/movement.py').read_text(encoding='utf-8'); "
        "raise SystemExit(0 if 'velocity' in text else 1)"
    )
    return profile, command


class P9RepairTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_P9_R01_ready_explicit_target_reopens(self):
        write_active_host(self.host)
        ensure_noscms_accepted_anchor(self.host)
        write_task(
            self.host,
            status="READY_FOR_REVIEW",
            stages=[
                self._complete_stage("stage-a"),
                self._complete_stage("stage-b"),
                self._complete_stage("stage-c"),
            ],
        )
        bind_ready_completion_authority(self.host)
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                candidate_digest=observe_candidate(self.host).digest,
                target_stage_ids=["stage-b"],
            ),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        task = self._task()
        self.assertEqual(task["status"], "IN_PROGRESS")
        by_id = {row["stage_id"]: row for row in task["stages"]}
        self.assertEqual(by_id["stage-a"]["status"], "COMPLETE")
        self.assertEqual(by_id["stage-b"]["status"], "IN_PROGRESS")
        self.assertEqual(by_id["stage-c"]["status"], "COMPLETE")
        self.assertEqual(by_id["stage-b"]["completion_decision"]["outcome"], "UNKNOWN")

    def test_P9_R02_ready_without_targets_fails_closed(self):
        write_active_host(self.host)
        ensure_noscms_accepted_anchor(self.host)
        write_task(self.host, status="READY_FOR_REVIEW", stages=[self._complete_stage()])
        bind_ready_completion_authority(self.host)
        handoff = submit_repair_handoff(
            candidate_digest=observe_candidate(self.host).digest,
            target_stage_ids=["stage-1"],
        )
        del handoff["target_stage_ids"]
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=handoff,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("target_stage_ids" in item for item in result.blockers))
        self.assertEqual(self._task()["status"], "READY_FOR_REVIEW")

    def test_P9_R03_nonexistent_stage_fails_closed(self):
        write_active_host(self.host)
        ensure_noscms_accepted_anchor(self.host)
        write_task(self.host, status="READY_FOR_REVIEW", stages=[self._complete_stage()])
        bind_ready_completion_authority(self.host)
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                candidate_digest=observe_candidate(self.host).digest,
                target_stage_ids=["stage-missing"],
            ),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("does not exist" in item for item in result.blockers))
        self.assertEqual(self._task()["status"], "READY_FOR_REVIEW")

    def test_P9_R04_old_decisions_cannot_restore_ready(self):
        write_active_host(self.host)
        ensure_noscms_accepted_anchor(self.host)
        write_task(self.host, status="READY_FOR_REVIEW", stages=[self._complete_stage()])
        bind_ready_completion_authority(self.host)
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                candidate_digest=observe_candidate(self.host).digest,
                target_stage_ids=["stage-1"],
            ),
            request_ready_for_review=True,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertNotEqual(self._task()["status"], "READY_FOR_REVIEW")
        self.assertEqual(
            self._task()["task_completion_decision"]["outcome"], "UNKNOWN"
        )
        self.assertTrue(self._task()["task_completion_decision"].get("supersedes"))

    def test_P9_R05_test_fail_execution_binding_maps_stage(self):
        self._prepare_failing_bound_host()
        write_task(
            self.host,
            stages=[self._in_progress_stage(required_refs=[explicit_ref()])],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "value = 0\n"}],
            invoke_test=True,
            selected=[MOVEMENT_PROFILE],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        handoff = result.extras["test_to_develop"]
        self.assertIs(handoff["test_pass"], False)
        self.assertEqual(handoff["target_stage_ids"], ["stage-1"])
        self.assertEqual(handoff["target_mapping"], "execution_binding")
        self.assertEqual(result.next_route, "develop.repair")
        view = reconstruct_repair_view(self.host, TASK_A)
        self.assertEqual(view["target_stage_ids"], ["stage-1"])
        self.assertEqual(view["repair_state_status"], "pending")

    def test_P9_R06_name_collision_without_binding_does_not_map(self):
        profile, command = failing_profile(MOVEMENT_PROFILE)
        write_host(self.host, [(profile, command)])
        bind_develop_lock(self.host)
        self._own_src()
        write(self.host, "src/app.py", "value = 0\n")
        ensure_noscms_accepted_anchor(self.host)
        write_task(
            self.host,
            stages=[
                self._in_progress_stage(
                    required_refs=[{"requirement_id": MOVEMENT_PROFILE}]
                )
            ],
        )
        mapped = map_repair_target_stage_ids(
            self._task(), fail_ids=[MOVEMENT_PROFILE]
        )
        self.assertEqual(mapped, [])
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            invoke_test=True,
            selected=[MOVEMENT_PROFILE],
        )
        handoff = result.extras["test_to_develop"]
        self.assertIs(handoff["test_pass"], False)
        self.assertNotIn("target_stage_ids", handoff)
        self.assertEqual(handoff["target_mapping"], "unresolved")
        self.assertEqual(result.next_route, "human")

    def test_P9_R07_retest_replaces_stale_authority(self):
        self._prepare_passing_bound_host()
        write_task(
            self.host,
            status="READY_FOR_REVIEW",
            stages=[
                self._complete_stage(
                    "stage-1", required_refs=[explicit_ref(profile_id="unit")]
                )
            ],
            final_tests=[explicit_ref(requirement_id="final/unit", profile_id="unit")],
        )
        bind_ready_completion_authority(self.host)
        old = self._task()["task_completion_decision"]
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                candidate_digest=observe_candidate(self.host).digest,
                target_stage_ids=["stage-1"],
            ),
            writes=[{"path": "src/app.py", "content": "value = 2\n"}],
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
                ],
            ),
            task_completion_decision=satisfied_decision(),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        task = self._task()
        self.assertEqual(task["status"], "READY_FOR_REVIEW")
        self.assertEqual(task["task_completion_decision"]["outcome"], "SATISFIED")
        self.assertNotEqual(
            task["task_completion_decision"].get("candidate_digest"),
            old.get("candidate_digest"),
        )

    def test_P9_R08_fresh_process_reconstructs_repair_state(self):
        write_active_host(self.host)
        ensure_noscms_accepted_anchor(self.host)
        write_task(self.host, status="READY_FOR_REVIEW", stages=[self._complete_stage()])
        bind_ready_completion_authority(self.host)
        develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                candidate_digest=observe_candidate(self.host).digest,
                target_stage_ids=["stage-1"],
            ),
        )
        view = reconstruct_repair_view(self.host, TASK_A)
        self.assertTrue(view["ok"])
        self.assertEqual(view["task_id"], TASK_A)
        self.assertEqual(view["task_status"], "IN_PROGRESS")
        self.assertEqual(view["target_stage_ids"], ["stage-1"])
        self.assertTrue(view["stale_completion_authority"])
        self.assertFalse(view["ready_possible"])
        self.assertIn("Complete reopened Stages", view["next"])

    def test_P9_R09_stale_cas_revision_rejects(self):
        write_active_host(self.host)
        ensure_noscms_accepted_anchor(self.host)
        write_task(self.host, status="READY_FOR_REVIEW", stages=[self._complete_stage()])
        bind_ready_completion_authority(self.host)

        def compete():
            path = self._task_path()
            current = read_yaml(path)
            updated = dict(current)
            updated["progress_summary"] = "competing-repair"
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
        self.assertEqual(self._task()["status"], "READY_FOR_REVIEW")

    def test_P9_R10_concurrent_repair_cas_one_winner(self):
        write_active_host(self.host)
        ensure_noscms_accepted_anchor(self.host)
        write_task(self.host, status="READY_FOR_REVIEW", stages=[self._complete_stage()])
        bind_ready_completion_authority(self.host)
        barrier = threading.Barrier(2)
        results: list = []

        def worker():
            barrier.wait()
            results.append(
                develop_engine(self.host).run(
                    "repair",
                    task_id=TASK_A,
                    submit_to_develop=submit_repair_handoff(
                        candidate_digest=observe_candidate(self.host).digest,
                        target_stage_ids=["stage-1"],
                    ),
                )
            )

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        completed = [row for row in results if row.outcome == "COMPLETED"]
        blocked = [row for row in results if row.outcome == "BLOCKED"]
        self.assertEqual(len(completed), 1, [row.outcome for row in results])
        self.assertEqual(len(blocked), 1)
        self.assertEqual(self._task()["status"], "IN_PROGRESS")
        self.assertEqual(self._task()["stages"][0]["status"], "IN_PROGRESS")

    def test_P9_R11_replayed_repair_does_not_duplicate(self):
        write_active_host(self.host)
        ensure_noscms_accepted_anchor(self.host)
        write_task(self.host, status="READY_FOR_REVIEW", stages=[self._complete_stage()])
        bind_ready_completion_authority(self.host)
        first = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                candidate_digest=observe_candidate(self.host).digest,
                target_stage_ids=["stage-1"],
            ),
        )
        self.assertEqual(first.outcome, "COMPLETED", first.blockers)
        sessions_after_first = existing_session_ids(self.host)
        revision = self._task()["record_revision"]
        second = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=submit_repair_handoff(
                candidate_digest=observe_candidate(self.host).digest,
                target_stage_ids=["stage-1"],
            ),
        )
        self.assertEqual(second.outcome, "COMPLETED", second.blockers)
        self.assertTrue(second.extras.get("repair_replayed"))
        self.assertEqual(self._task()["record_revision"], revision)
        self.assertEqual(existing_session_ids(self.host), sessions_after_first)

    def test_P9_R12_unresolved_blocker_blocks_ready(self):
        self._prepare_failing_bound_host()
        write_task(
            self.host,
            stages=[self._in_progress_stage(required_refs=[explicit_ref()])],
            final_tests=[explicit_ref()],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "value = 0\n"}],
            invoke_test=True,
            selected=[MOVEMENT_PROFILE],
            request_stage_complete=True,
            request_ready_for_review=True,
            stage_completion_decision=satisfied_decision(stage_id="stage-1"),
            task_completion_decision=satisfied_decision(),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertNotEqual(self._task()["status"], "READY_FOR_REVIEW")

    def _prepare_failing_bound_host(self) -> None:
        profile, command = failing_profile(MOVEMENT_PROFILE)
        write_host(self.host, [(profile, command)])
        bind_develop_lock(self.host)
        self._own_src()
        write(self.host, "src/app.py", "value = 0\n")
        ensure_noscms_accepted_anchor(self.host)

    def _prepare_passing_bound_host(self) -> None:
        profile, command = passing_profile("unit")
        write_host(self.host, [(profile, command)])
        bind_develop_lock(self.host)
        self._own_src()
        write(self.host, "src/app.py", "value = 1\n")
        ensure_noscms_accepted_anchor(self.host)

    def _own_src(self) -> None:
        payload = read_yaml(self.host / ".scaffold/project.yaml")
        payload["ownership"] = {**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"}
        payload["source_areas"] = ["src"]
        write_yaml_atomic(self.host / ".scaffold/project.yaml", payload)

    def _task_path(self) -> Path:
        return self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"

    def _task(self) -> dict:
        return read_yaml(self._task_path())

    @staticmethod
    def _in_progress_stage(
        *,
        stage_id: str = "stage-1",
        required_refs: list[dict] | None = None,
    ) -> dict:
        return {
            "stage_id": stage_id,
            "goal": "Write the fixture source.",
            "acceptance": "src/app.py has the expected content.",
            "status": "IN_PROGRESS",
            "required_tests": list(required_refs or []),
        }

    @staticmethod
    def _complete_stage(
        stage_id: str = "stage-1",
        *,
        required_refs: list[dict] | None = None,
    ) -> dict:
        return {
            "stage_id": stage_id,
            "goal": "Write the fixture source.",
            "acceptance": "src/app.py has the expected content.",
            "status": "COMPLETE",
            "required_tests": list(required_refs or []),
        }


class P9MigrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_P9_M01_valid_exact_no_migration(self):
        write_active_host(self.host)
        ensure_noscms_accepted_anchor(self.host)
        bind_resolvable_lock(self.host)
        need = self._need(p9_dist("2.0.0"))
        self.assertEqual(need["validity"], "VALID")
        self.assertEqual(need["compatibility"], "EXACT")
        self.assertFalse(need["needed"])

    def test_P9_M02_valid_compatible_does_not_force_migration(self):
        write_active_host(self.host)
        ensure_noscms_accepted_anchor(self.host)
        bind_resolvable_lock(self.host)
        before = (self.host / ".scaffold/skills.lock").read_bytes()
        need = self._need(p9_dist("2.1.0", actual_understand_dir=REPO / "skills" / "understand"))
        self.assertEqual(need["validity"], "VALID")
        self.assertEqual(need["compatibility"], "COMPATIBLE")
        self.assertFalse(need["needed"])
        self.assertEqual((self.host / ".scaffold/skills.lock").read_bytes(), before)

    def test_P9_M03_valid_migration_required_is_explicit(self):
        write_active_host(self.host)
        ensure_noscms_accepted_anchor(self.host)
        bind_resolvable_lock(self.host)
        need = self._need(p9_dist("2.1.0"))
        self.assertEqual(need["validity"], "VALID")
        self.assertEqual(need["compatibility"], "MIGRATION_REQUIRED")
        self.assertTrue(need["needed"])
        self.assertTrue(need["migration_causes"])
        self.assertTrue(need["reasons"])

    def test_P9_M04_invalid_is_not_migration_required(self):
        write_active_host(self.host)
        ensure_noscms_accepted_anchor(self.host)
        bind_resolvable_lock(self.host)
        dest = Path(self._tmp.name) / "bad-understand"
        write_skill_package(
            dest,
            skill_version="2.1.0",
            extra_manifest={"skill_id": "understand", "provides": ["not-a-capability"]},
        )
        dist = p9_dist("2.1.0", actual_understand_dir=dest)
        need = self._need(dist)
        self.assertEqual(need["validity"], "INVALID")
        self.assertIsNone(need["compatibility"])
        self.assertFalse(need["needed"])

    def test_P9_M05_version_difference_with_explicit_compatibility(self):
        write_active_host(self.host)
        ensure_noscms_accepted_anchor(self.host)
        bind_resolvable_lock(self.host)
        need = self._need(
            p9_dist("2.1.0", actual_understand_dir=REPO / "skills" / "understand")
        )
        self.assertEqual(need["compatibility"], "COMPATIBLE")
        self.assertFalse(need["needed"])

    def test_P9_M06_human_owned_whole_file_blocked(self):
        adopt(self.host)
        ensure_noscms_accepted_anchor(self.host)
        allowed, reason = whole_file_mutation_allowed(
            {"docs/notes.md": "HUMAN_OWNED"},
            "docs/notes.md",
        )
        self.assertFalse(allowed)
        self.assertIn("HUMAN_OWNED", reason)
        payload = read_yaml(self.host / ".scaffold/project.yaml")
        payload["ownership"][".scaffold/project.yaml"] = "MANAGED"
        write_yaml_atomic(self.host / ".scaffold/project.yaml", payload)
        write_task(self.host)
        before = (self.host / ".scaffold/project.yaml").read_bytes()
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
        )
        self.assertIn(result.outcome, {"BLOCKED", "NEEDS_HUMAN"})
        self.assertTrue(
            any(
                "MANAGED" in item or "HUMAN_OWNED" in item or "ownership" in item.lower()
                for item in result.blockers
            ),
            result.blockers,
        )
        self.assertEqual((self.host / ".scaffold/project.yaml").read_bytes(), before)

    def test_P9_M07_authorized_bounded_migration_through_develop(self):
        adopt(self.host)
        ensure_noscms_accepted_anchor(self.host)
        write_task(self.host)
        preview = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
        )
        self.assertEqual(preview.outcome, "NEEDS_HUMAN", preview.blockers)
        plan = preview.extras["migration"]["migration_plan"]
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval=bound_migration_approval(self.host, plan),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertEqual(project["project_contract_generation"], "3")
        self.assertIn(
            result.extras.get("post_compatibility"),
            {"EXACT", "COMPATIBLE"},
        )

    def test_P9_M08_post_migration_recheck_is_truthful(self):
        self.test_P9_M07_authorized_bounded_migration_through_develop()
        need = self._need(distribution("2.1.0"))
        self.assertEqual(need["validity"], "VALID")
        self.assertIn(need["compatibility"], {"EXACT", "COMPATIBLE"})
        self.assertFalse(need["needed"])

    def test_P9_M09_unprovable_post_state_is_not_forced_pass(self):
        adopt(self.host)
        ensure_noscms_accepted_anchor(self.host)
        write_task(self.host)
        preview = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
        )
        plan = preview.extras["migration"]["migration_plan"]
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_revalidation_distribution=live_understand_distribution(),
            migration_approval=bound_migration_approval(self.host, plan),
        )
        self.assertNotEqual(result.outcome, "COMPLETED", result.blockers)
        post = result.extras.get("post_compatibility")
        self.assertNotIn(post, {"EXACT", "COMPATIBLE"})
        self.assertIn(post, {"MIGRATION_REQUIRED", "UNKNOWN", None})
        execution = (result.extras.get("migration") or {}).get("migration")
        if isinstance(execution, dict):
            self.assertNotEqual(execution.get("status"), "COMPLETED")
        view = reconstruct_migration_view(self.host)
        if view["executions"]:
            self.assertNotEqual(view["executions"][0].get("status"), "COMPLETED")

    def test_P9_M10_fresh_process_reconstructs_pending_migration(self):
        adopt(self.host)
        ensure_noscms_accepted_anchor(self.host)
        write_task(self.host)
        preview = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
        )
        plan = preview.extras["migration"]["migration_plan"]
        interrupted = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval=bound_migration_approval(self.host, plan),
            interrupt_after_migration="first_mutation",
        )
        self.assertEqual(interrupted.outcome, "BLOCKED")
        view = reconstruct_migration_view(self.host)
        self.assertTrue(view["pending"])
        self.assertTrue(view["executions"])
        status = view["executions"][0].get("status")
        self.assertEqual(status, "RECOVERY_REQUIRED")
        self.assertEqual(
            view["executions"][0].get("observed_expected_state"),
            "VALIDATING",
        )

    def _need(self, dist) -> dict:
        return migration_need(evaluate_host(snapshot_host(self.host), dist))


class P9DiveReadinessTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_P9_DIVE_movement_fail_repair_pass_ready(self):
        profile, command = movement_profile()
        write_host(self.host, [(profile, command)])
        bind_develop_lock(self.host)
        payload = read_yaml(self.host / ".scaffold/project.yaml")
        payload["ownership"] = {**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"}
        payload["source_areas"] = ["src"]
        write_yaml_atomic(self.host / ".scaffold/project.yaml", payload)
        write(self.host, "src/movement.py", "speed = 1\n")
        ensure_noscms_accepted_anchor(self.host)
        write_task(
            self.host,
            title="Implement movement velocity",
            goal="Change movement so velocity is present.",
            acceptance="src/movement.py contains velocity.",
            scope={"paths": ["src/movement.py"], "modules": [], "exclude": []},
            stages=[
                {
                    "stage_id": "movement-implementation",
                    "goal": "Implement movement velocity.",
                    "acceptance": "src/movement.py contains velocity.",
                    "status": "IN_PROGRESS",
                    "required_tests": [explicit_ref()],
                }
            ],
            final_tests=[explicit_ref()],
        )
        failed = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/movement.py", "content": "speed = 1\n"}],
            invoke_test=True,
            selected=[MOVEMENT_PROFILE],
        )
        self.assertEqual(failed.outcome, "COMPLETED", failed.blockers)
        self.assertIs(failed.extras["test_to_develop"]["test_pass"], False)
        self.assertEqual(
            failed.extras["test_to_develop"]["target_stage_ids"],
            ["movement-implementation"],
        )
        self.assertEqual(failed.next_route, "develop.repair")
        pending = reconstruct_repair_view(self.host, TASK_A)
        self.assertEqual(pending["target_stage_ids"], ["movement-implementation"])
        repaired = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            test_to_develop=repair_handoff(
                candidate_digest=observe_candidate(self.host).digest,
                target_stage_ids=["movement-implementation"],
            ),
            writes=[{"path": "src/movement.py", "content": "velocity = 1\n"}],
            invoke_test=True,
            selected=[MOVEMENT_PROFILE],
            request_stage_complete=True,
            request_ready_for_review=True,
            stage_completion_decision=satisfied_decision(
                stage_id="movement-implementation",
                basis=[
                    {
                        "kind": "repository_observation",
                        "summary": "src/movement.py contains velocity.",
                    },
                    {
                        "kind": "test_evidence",
                        "summary": "movement-smoke passed on the repair candidate.",
                    },
                ],
            ),
            task_completion_decision=satisfied_decision(),
        )
        self.assertEqual(repaired.outcome, "COMPLETED", repaired.blockers)
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(task["status"], "READY_FOR_REVIEW")
        self.assertEqual(task["stages"][0]["status"], "COMPLETE")
        self.assertEqual(task["task_completion_decision"]["outcome"], "SATISFIED")
        fresh = reconstruct_repair_view(self.host, TASK_A)
        self.assertEqual(fresh["task_status"], "READY_FOR_REVIEW")
        self.assertTrue(fresh["ready_possible"])
        self.assertIn("Repair loop is complete", fresh["next"])


class P9MigrationTaskBindingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        adopt(self.host)
        ensure_noscms_accepted_anchor(self.host)
        write_task(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def test_P9_X01_unrelated_task_cannot_carry_approval(self):
        write(self.host, "docs/note.md", "note\n")
        write_task(
            self.host,
            TASK_B,
            title="edit docs",
            goal="edit docs",
            scope={"paths": ["docs/note.md"], "modules": [], "exclude": []},
        )
        preview = preview_migration(self.host)
        plan = preview.extras["migration"]["migration_plan"]
        approval = bound_migration_approval(self.host, plan, TASK_A)
        before = (self.host / ".scaffold/project.yaml").read_bytes()
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_B,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval=approval,
        )
        self.assertNotEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(
            any("different Task" in item for item in result.blockers),
            result.blockers,
        )
        self.assertEqual(
            (self.host / ".scaffold/project.yaml").read_bytes(),
            before,
        )

    def test_P9_X02_correct_task_and_revision_may_execute(self):
        preview = preview_migration(self.host)
        plan = preview.extras["migration"]["migration_plan"]
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval=bound_migration_approval(self.host, plan),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertEqual(project["project_contract_generation"], "3")

    def test_P9_X03_stale_task_revision_requires_reapproval(self):
        preview = preview_migration(self.host)
        plan = preview.extras["migration"]["migration_plan"]
        approval = bound_migration_approval(self.host, plan)
        path = self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
        current = read_yaml(path)
        touched = dict(current)
        touched["title"] = str(current.get("title") or "") + " touched"
        published = publish_task(
            path,
            touched,
            expected_revision=int(current["record_revision"]),
        )
        self.assertTrue(published.ok, published.blockers)
        before = (self.host / ".scaffold/project.yaml").read_bytes()
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval=approval,
        )
        self.assertNotEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertTrue(
            any("stale" in item for item in result.blockers),
            result.blockers,
        )
        self.assertEqual(
            (self.host / ".scaffold/project.yaml").read_bytes(),
            before,
        )

    def test_P9_X04_task_binding_survives_fresh_reconstruction(self):
        preview = preview_migration(self.host)
        plan = preview.extras["migration"]["migration_plan"]
        approval = bound_migration_approval(self.host, plan)
        develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval=approval,
            interrupt_after_migration="first_mutation",
        )
        view = reconstruct_migration_view(self.host)
        binding = view.get("task_binding") or {}
        self.assertEqual(binding.get("task_id"), TASK_A)
        self.assertIsInstance(binding.get("task_revision"), int)
        self.assertTrue(binding.get("candidate_digest"))

    def test_P9_X05_migration_keyword_is_not_authority(self):
        write_task(
            self.host,
            title="Please run migration",
            goal="migration of the project contract generation",
        )
        preview = preview_migration(self.host)
        plan = preview.extras["migration"]["migration_plan"]
        before = (self.host / ".scaffold/project.yaml").read_bytes()
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval={
                "approved": True,
                "plan_id": plan["plan_id"],
                "plan_digest": plan["digest"],
            },
        )
        self.assertNotEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(
            any("not bound to a Task identity" in item for item in result.blockers),
            result.blockers,
        )
        self.assertEqual(
            (self.host / ".scaffold/project.yaml").read_bytes(),
            before,
        )


class P9MigrationCompletionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        adopt(self.host)
        ensure_noscms_accepted_anchor(self.host)
        write_task(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def _apply(self, *, revalidation=None, lock_understand=None):
        if lock_understand is not None:
            pkg = load_package(lock_understand)
            lock = read_yaml(self.host / ".scaffold/skills.lock")
            lock["skills"]["understand"] = {
                "skill_version": pkg.ref.skill_version,
                "package_digest": pkg.ref.package_digest,
                "package_format_version": pkg.ref.package_format_version,
            }
            write_yaml_atomic(self.host / ".scaffold/skills.lock", lock)
        preview = preview_migration(self.host)
        plan = preview.extras["migration"]["migration_plan"]
        kwargs = {
            "task_id": TASK_A,
            "execute_approved_migration": True,
            "distribution": distribution("2.1.0"),
            "migration_approval": bound_migration_approval(self.host, plan),
        }
        if revalidation is not None:
            kwargs["migration_revalidation_distribution"] = revalidation
        return develop_engine(self.host).run("normal_task", **kwargs)

    def test_P9_Y01_post_migration_required_is_not_completed(self):
        result = self._apply(revalidation=live_understand_distribution())
        self.assertNotEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(
            result.extras.get("post_compatibility"),
            "MIGRATION_REQUIRED",
        )
        view = reconstruct_migration_view(self.host)
        self.assertTrue(view["executions"])
        self.assertNotEqual(view["executions"][0].get("status"), "COMPLETED")
        self.assertEqual(view["executions"][0].get("status"), "RECOVERY_REQUIRED")

    def test_P9_Y02_post_unknown_is_not_completed(self):
        dest = Path(self._tmp.name) / "understand-unknown"
        shutil.copytree(FIXTURE_DIST / "packages" / "understand-2.2.0", dest)
        payload = read_yaml(dest / "skill.yaml")
        contracts = dict(payload.get("contracts") or {})
        contracts["project_contract_generations"] = ["2", "3"]
        payload["contracts"] = contracts
        write_yaml_atomic(dest / "skill.yaml", payload)
        unknown = load_fixture_distribution(
            FIXTURE_DIST,
            selected_release_id="rel-r1",
            actual_understand_dir=dest,
            extra_package_dirs=[dest],
            repo_understand=REPO / "skills" / "understand",
        )
        result = self._apply(revalidation=unknown)
        self.assertNotEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.extras.get("post_compatibility"), "UNKNOWN")
        view = reconstruct_migration_view(self.host)
        self.assertNotEqual(view["executions"][0].get("status"), "COMPLETED")

    def test_P9_Y03_post_incompatible_is_not_completed(self):
        incompat = load_fixture_distribution(
            FIXTURE_DIST,
            selected_release_id="rel-r1",
            actual_understand_dir=FIXTURE_DIST / "packages" / "understand-incompat",
            repo_understand=REPO / "skills" / "understand",
        )
        result = self._apply(revalidation=incompat)
        self.assertNotEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.extras.get("post_compatibility"), "INCOMPATIBLE")
        view = reconstruct_migration_view(self.host)
        self.assertNotEqual(view["executions"][0].get("status"), "COMPLETED")

    def test_P9_Y04_post_exact_may_complete(self):
        result = self._apply(
            lock_understand=FIXTURE_DIST / "packages" / "understand-2.1.0",
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.extras.get("post_compatibility"), "EXACT")
        self.assertEqual(
            (result.extras.get("migration") or {}).get("migration", {}).get("status"),
            "COMPLETED",
        )

    def test_P9_Y05_post_compatible_may_complete(self):
        result = self._apply()
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.extras.get("post_compatibility"), "COMPATIBLE")


class P9MigrationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        adopt(self.host)
        ensure_noscms_accepted_anchor(self.host)
        write_task(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def _interrupt(self):
        preview = preview_migration(self.host)
        plan = preview.extras["migration"]["migration_plan"]
        return develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval=bound_migration_approval(self.host, plan),
            interrupt_after_migration="first_mutation",
        )

    def test_P9_Z01_interrupt_is_canonical_recovery_state(self):
        interrupted = self._interrupt()
        self.assertEqual(interrupted.outcome, "BLOCKED")
        view = reconstruct_migration_view(self.host)
        execution = view["executions"][0]
        self.assertEqual(execution.get("status"), "RECOVERY_REQUIRED")
        self.assertEqual(
            execution.get("checkpoints_completed"),
            ["CONTRACT_GENERATION_UPDATED"],
        )
        self.assertEqual(
            execution.get("checkpoints_remaining"),
            ["VALIDATION_PASSED"],
        )
        self.assertEqual(execution.get("observed_expected_state"), "VALIDATING")
        self.assertNotEqual(execution.get("status"), "APPLYING")

    def test_P9_Z02_fresh_p5_accepts_p7_execution(self):
        self._interrupt()
        snap = snapshot_host(self.host)
        row = snap.migrations[0]
        directory = Path(row["_dir"])
        data = load_execution(directory)
        plan = read_yaml(directory / "plan.yaml")
        issues = validate_recovery_state(
            self.host,
            data,
            plan,
            snap,
            evaluate_host(snap, distribution("2.1.0")),
        )
        self.assertFalse(
            any(
                "inconsistent" in item or "contradicts validation checkpoint" in item
                for item in issues
            ),
            issues,
        )
        self.assertEqual(issues, [])
        inspected = UnderstandEngine(self.host, distribution("2.1.0")).run(
            "compatibility"
        )
        joined = " ".join(inspected.blockers)
        self.assertNotIn("inconsistent", joined)
        self.assertNotIn("contradicts validation checkpoint", joined)

    def test_P9_Z03_interrupt_establishes_recovery_required(self):
        self._interrupt()
        project = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertEqual(project.get("lifecycle"), "RECOVERY_REQUIRED")
        view = reconstruct_migration_view(self.host)
        self.assertEqual(view["executions"][0].get("status"), "RECOVERY_REQUIRED")
        self.assertEqual(view["host_lifecycle"], "RECOVERY_REQUIRED")

    def test_P9_Z04_ordinary_work_cannot_bypass_recovery(self):
        self._interrupt()
        blocked = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(blocked.outcome, "BLOCKED")
        self.assertTrue(
            any("RECOVERY_REQUIRED" in item for item in blocked.blockers),
            blocked.blockers,
        )

    def test_P9_Z05_resume_completes_only_after_exact_or_compatible(self):
        self._interrupt()
        directory = Path(snapshot_host(self.host).migrations[0]["_dir"])
        plan = read_yaml(directory / "plan.yaml")
        resumed = UnderstandEngine(self.host, distribution("2.1.0")).run(
            "compatibility",
            action="migrate",
            approval={
                "approved": True,
                "plan_id": plan["plan_id"],
                "plan_digest": plan["digest"],
            },
        )
        self.assertEqual(resumed.outcome, "COMPLETED", resumed.blockers)
        self.assertEqual(
            (resumed.extras.get("migration") or {}).get("status"),
            "COMPLETED",
        )
        project = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertEqual(project.get("lifecycle"), "ACTIVE")
        self.assertEqual(project.get("project_contract_generation"), "3")


def _task_snapshot(host: Path, task_id: str = TASK_A) -> dict:
    path = host / ".scaffold/tasks" / f"{task_id}.yaml"
    data = read_yaml(path)
    stages = data.get("stages") or []
    first = stages[0] if stages and isinstance(stages[0], dict) else {}
    return {
        "bytes": path.read_bytes(),
        "revision": data.get("record_revision"),
        "stage": first.get("status"),
        "sessions": list(data.get("develop_session_ids") or []),
    }


class P9PreMutationAuthorityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        adopt(self.host)
        ensure_noscms_accepted_anchor(self.host)
        write_task(self.host)
        self.before_task = _task_snapshot(self.host)
        self.before_project = (self.host / ".scaffold/project.yaml").read_bytes()
        self.before_sessions = existing_session_ids(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def _assert_unmutated(self):
        after = _task_snapshot(self.host)
        self.assertEqual(after["bytes"], self.before_task["bytes"])
        self.assertEqual(after["revision"], self.before_task["revision"])
        self.assertEqual(after["stage"], self.before_task["stage"])
        self.assertEqual(after["sessions"], self.before_task["sessions"])
        self.assertEqual(
            (self.host / ".scaffold/project.yaml").read_bytes(),
            self.before_project,
        )
        self.assertEqual(existing_session_ids(self.host), self.before_sessions)

    def test_P9_W01_no_approval_preview_is_non_mutating(self):
        result = preview_migration(self.host)
        self.assertEqual(result.outcome, "NEEDS_HUMAN", result.blockers)
        self.assertIn("migration_plan", result.extras.get("migration") or {})
        observed = ((result.extras.get("human_action") or {}).get("observed") or "")
        self.assertIn("No durable project-local state has been changed", observed)
        self._assert_unmutated()

    def test_P9_W02_wrong_plan_digest_does_not_mutate(self):
        preview = preview_migration(self.host)
        plan = preview.extras["migration"]["migration_plan"]
        approval = bound_migration_approval(self.host, plan)
        approval["plan_digest"] = "0" * 64
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval=approval,
        )
        self.assertEqual(result.outcome, "BLOCKED", result.blockers)
        self._assert_unmutated()

    def test_P9_W03_wrong_plan_id_does_not_mutate(self):
        preview = preview_migration(self.host)
        plan = preview.extras["migration"]["migration_plan"]
        approval = bound_migration_approval(self.host, plan)
        approval["plan_id"] = "migplan-not-the-current"
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval=approval,
        )
        self.assertEqual(result.outcome, "BLOCKED", result.blockers)
        self._assert_unmutated()

    def test_P9_W04_wrong_task_does_not_mutate_either_task(self):
        write(self.host, "docs/note.md", "note\n")
        write_task(
            self.host,
            TASK_B,
            title="edit docs",
            goal="edit docs",
            scope={"paths": ["docs/note.md"], "modules": [], "exclude": []},
        )
        self.before_task = _task_snapshot(self.host, TASK_A)
        before_b = _task_snapshot(self.host, TASK_B)
        self.before_project = (self.host / ".scaffold/project.yaml").read_bytes()
        self.before_sessions = existing_session_ids(self.host)
        preview = preview_migration(self.host, TASK_A)
        plan = preview.extras["migration"]["migration_plan"]
        approval = bound_migration_approval(self.host, plan, TASK_A)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_B,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval=approval,
        )
        self.assertEqual(result.outcome, "BLOCKED", result.blockers)
        self._assert_unmutated()
        self.assertEqual(_task_snapshot(self.host, TASK_B)["bytes"], before_b["bytes"])

    def test_P9_W05_stale_revision_does_not_mutate(self):
        preview = preview_migration(self.host)
        plan = preview.extras["migration"]["migration_plan"]
        approval = bound_migration_approval(self.host, plan)
        path = self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
        current = read_yaml(path)
        touched = dict(current)
        touched["title"] = str(current.get("title") or "") + " touched"
        published = publish_task(
            path,
            touched,
            expected_revision=int(current["record_revision"]),
        )
        self.assertTrue(published.ok, published.blockers)
        after_touch = _task_snapshot(self.host)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval=approval,
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN", result.blockers)
        self.assertEqual(_task_snapshot(self.host)["bytes"], after_touch["bytes"])
        self.assertEqual(
            (self.host / ".scaffold/project.yaml").read_bytes(),
            self.before_project,
        )
        self.assertEqual(existing_session_ids(self.host), self.before_sessions)

    def test_P9_W06_stale_candidate_does_not_mutate(self):
        preview = preview_migration(self.host)
        plan = preview.extras["migration"]["migration_plan"]
        approval = bound_migration_approval(self.host, plan)
        write(self.host, "src/app.py", "changed = True\n")
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval=approval,
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN", result.blockers)
        self.assertEqual(_task_snapshot(self.host)["bytes"], self.before_task["bytes"])
        self.assertEqual(
            (self.host / ".scaffold/project.yaml").read_bytes(),
            self.before_project,
        )
        self.assertEqual(existing_session_ids(self.host), self.before_sessions)

    def test_P9_W07_correct_approval_may_begin_session_progress(self):
        preview = preview_migration(self.host)
        plan = preview.extras["migration"]["migration_plan"]
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval=bound_migration_approval(self.host, plan),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        after = _task_snapshot(self.host)
        self.assertGreater(after["revision"], self.before_task["revision"])
        self.assertTrue(after["sessions"])
        self.assertEqual(after["stage"], "IN_PROGRESS")
        self.assertTrue(existing_session_ids(self.host) - self.before_sessions)

    def test_P9_W08_prepared_plan_equals_applied_plan(self):
        preview = preview_migration(self.host)
        plan = preview.extras["migration"]["migration_plan"]
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval=bound_migration_approval(self.host, plan),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        extras = result.extras.get("migration") or {}
        self.assertTrue(extras.get("plan_identity_held"))
        self.assertEqual(extras.get("approved_plan_id"), extras.get("applied_plan_id"))
        self.assertEqual(
            extras.get("approved_plan_digest"),
            extras.get("applied_plan_digest"),
        )
        self.assertEqual(extras.get("approved_plan_id"), plan["plan_id"])
        self.assertEqual(extras.get("approved_plan_digest"), plan["digest"])


class P9PostCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        adopt(self.host)
        ensure_noscms_accepted_anchor(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def test_P9_V01_p5_success_reports_exact(self):
        pkg = load_package(FIXTURE_DIST / "packages" / "understand-2.1.0")
        lock = read_yaml(self.host / ".scaffold/skills.lock")
        lock["skills"]["understand"] = {
            "skill_version": pkg.ref.skill_version,
            "package_digest": pkg.ref.package_digest,
            "package_format_version": pkg.ref.package_format_version,
        }
        write_yaml_atomic(self.host / ".scaffold/skills.lock", lock)
        planned = UnderstandEngine(self.host, distribution("2.1.0")).run(
            "compatibility",
            action="migrate",
        )
        self.assertEqual(planned.outcome, "NEEDS_HUMAN", planned.blockers)
        self.assertEqual(planned.mutations, "none")
        self.assertIn("develop", planned.next_route)
        plan = planned.extras["migration_plan"]
        plan_only = UnderstandEngine(self.host, distribution("2.1.0")).run(
            "compatibility",
            action="migrate",
            approval={
                "approved": True,
                "plan_id": plan["plan_id"],
                "plan_digest": plan["digest"],
            },
        )
        self.assertEqual(plan_only.outcome, "NEEDS_HUMAN", plan_only.blockers)
        self.assertEqual(plan_only.mutations, "none")
        self.assertFalse(_fresh_execution_dirs(self.host))
        done = apply_fresh_migration(
            self.host,
            plan,
            develop_binding={
                "task_id": "task-helper",
                "task_revision": 1,
                "candidate_digest": observe_candidate(self.host).digest,
            },
        )
        self.assertEqual(done.outcome, "COMPLETED", done.blockers)
        self.assertEqual(done.compatibility, "EXACT")
        self.assertEqual(done.extras.get("post_compatibility"), "EXACT")
        self.assertEqual(done.extras.get("current_compatibility"), "EXACT")

    def test_P9_V02_p5_success_reports_compatible(self):
        planned = UnderstandEngine(self.host, distribution("2.1.0")).run(
            "compatibility",
            action="migrate",
        )
        self.assertEqual(planned.outcome, "NEEDS_HUMAN", planned.blockers)
        self.assertEqual(planned.mutations, "none")
        plan = planned.extras["migration_plan"]
        plan_only = UnderstandEngine(self.host, distribution("2.1.0")).run(
            "compatibility",
            action="migrate",
            approval={
                "approved": True,
                "plan_id": plan["plan_id"],
                "plan_digest": plan["digest"],
            },
        )
        self.assertNotEqual(plan_only.outcome, "COMPLETED", plan_only.blockers)
        self.assertEqual(plan_only.mutations, "none")
        done = apply_fresh_migration(
            self.host,
            plan,
            develop_binding={
                "task_id": "task-helper",
                "task_revision": 1,
                "candidate_digest": observe_candidate(self.host).digest,
            },
        )
        self.assertEqual(done.outcome, "COMPLETED", done.blockers)
        self.assertEqual(done.compatibility, "COMPATIBLE")
        self.assertEqual(done.extras.get("post_compatibility"), "COMPATIBLE")

    def test_P9_V03_p7_success_has_no_contradictory_current_state(self):
        write_task(self.host)
        preview = preview_migration(self.host)
        plan = preview.extras["migration"]["migration_plan"]
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval=bound_migration_approval(self.host, plan),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.compatibility, "COMPATIBLE")
        self.assertEqual(result.extras.get("post_compatibility"), "COMPATIBLE")
        self.assertEqual(result.extras.get("current_compatibility"), "COMPATIBLE")
        self.assertNotEqual(result.compatibility, "MIGRATION_REQUIRED")
        self.assertNotEqual(result.extras.get("current_compatibility"), "MIGRATION_REQUIRED")
        self.assertNotEqual(
            result.extras.get("pre_compatibility"),
            result.extras.get("post_compatibility"),
        )

    def test_P9_V04_post_migration_required_is_current_and_incomplete(self):
        write_task(self.host)
        preview = preview_migration(self.host)
        plan = preview.extras["migration"]["migration_plan"]
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_revalidation_distribution=live_understand_distribution(),
            migration_approval=bound_migration_approval(self.host, plan),
        )
        self.assertNotEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.compatibility, "MIGRATION_REQUIRED")
        self.assertEqual(result.extras.get("post_compatibility"), "MIGRATION_REQUIRED")

    def test_P9_V05_post_unknown_is_current_and_incomplete(self):
        dest = Path(self._tmp.name) / "understand-unknown"
        shutil.copytree(FIXTURE_DIST / "packages" / "understand-2.2.0", dest)
        payload = read_yaml(dest / "skill.yaml")
        contracts = dict(payload.get("contracts") or {})
        contracts["project_contract_generations"] = ["2", "3"]
        payload["contracts"] = contracts
        write_yaml_atomic(dest / "skill.yaml", payload)
        unknown = load_fixture_distribution(
            FIXTURE_DIST,
            selected_release_id="rel-r1",
            actual_understand_dir=dest,
            extra_package_dirs=[dest],
            repo_understand=REPO / "skills" / "understand",
        )
        write_task(self.host)
        preview = preview_migration(self.host)
        plan = preview.extras["migration"]["migration_plan"]
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_revalidation_distribution=unknown,
            migration_approval=bound_migration_approval(self.host, plan),
        )
        self.assertNotEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.compatibility, "UNKNOWN")
        self.assertEqual(result.extras.get("post_compatibility"), "UNKNOWN")

    def test_P9_V06_pre_state_is_inspectable_separately(self):
        planned = UnderstandEngine(self.host, distribution("2.1.0")).run(
            "compatibility",
            action="migrate",
        )
        self.assertEqual(planned.compatibility, "MIGRATION_REQUIRED")
        self.assertEqual(planned.outcome, "NEEDS_HUMAN", planned.blockers)
        plan = planned.extras["migration_plan"]
        done = apply_fresh_migration(
            self.host,
            plan,
            develop_binding={
                "task_id": "task-helper",
                "task_revision": 1,
                "candidate_digest": observe_candidate(self.host).digest,
            },
        )
        self.assertEqual(done.outcome, "COMPLETED", done.blockers)
        self.assertEqual(done.compatibility, "COMPATIBLE")
        self.assertEqual(done.extras.get("pre_compatibility"), "MIGRATION_REQUIRED")
        self.assertEqual(done.extras.get("post_compatibility"), "COMPATIBLE")
        self.assertNotEqual(
            done.extras.get("pre_compatibility"),
            done.extras.get("post_compatibility"),
        )


def _fresh_execution_dirs(host: Path) -> list[Path]:
    folder = host / ".scaffold/runtime/migration-executions"
    if not folder.is_dir():
        return []
    return [path for path in folder.iterdir() if path.is_dir()]


class P9FreshApplyAuthorityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        adopt(self.host)
        ensure_noscms_accepted_anchor(self.host)
        self.before_project = (self.host / ".scaffold/project.yaml").read_bytes()

    def tearDown(self):
        self._tmp.cleanup()

    def _assert_no_fresh_apply(self):
        self.assertEqual(
            (self.host / ".scaffold/project.yaml").read_bytes(),
            self.before_project,
        )
        self.assertFalse(_fresh_execution_dirs(self.host))
        self.assertFalse(existing_session_ids(self.host))

    def test_P9_Q01_no_approval_plans_and_routes_without_mutation(self):
        result = UnderstandEngine(self.host, distribution("2.1.0")).run(
            "compatibility",
            action="migrate",
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN", result.blockers)
        self.assertEqual(result.mutations, "none")
        self.assertIn("develop", result.next_route)
        self.assertIn("migration_plan", result.extras)
        self._assert_no_fresh_apply()

    def test_P9_Q02_plan_only_approval_is_not_application_authority(self):
        planned = UnderstandEngine(self.host, distribution("2.1.0")).run(
            "compatibility",
            action="migrate",
        )
        plan = planned.extras["migration_plan"]
        result = UnderstandEngine(self.host, distribution("2.1.0")).run(
            "compatibility",
            action="migrate",
            approval={
                "approved": True,
                "plan_id": plan["plan_id"],
                "plan_digest": plan["digest"],
            },
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN", result.blockers)
        self.assertEqual(result.mutations, "none")
        self.assertIn("develop", result.next_route)
        self.assertTrue(result.extras.get("plan_approval_is_not_application_authority"))
        self.assertNotEqual(result.outcome, "COMPLETED")
        self._assert_no_fresh_apply()

    def test_P9_Q03_no_task_cannot_complete_through_understand(self):
        tasks = self.host / ".scaffold/tasks"
        self.assertFalse(tasks.is_dir() and any(tasks.glob("*.yaml")))
        planned = UnderstandEngine(self.host, distribution("2.1.0")).run(
            "compatibility",
            action="migrate",
        )
        plan = planned.extras["migration_plan"]
        result = UnderstandEngine(self.host, distribution("2.1.0")).run(
            "compatibility",
            action="migrate",
            approval={
                "approved": True,
                "plan_id": plan["plan_id"],
                "plan_digest": plan["digest"],
            },
        )
        self.assertNotEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.mutations, "none")
        self._assert_no_fresh_apply()

    def test_P9_Q04_existing_task_does_not_grant_understand_bypass(self):
        write_task(self.host)
        before_task = _task_snapshot(self.host)
        planned = UnderstandEngine(self.host, distribution("2.1.0")).run(
            "compatibility",
            action="migrate",
        )
        plan = planned.extras["migration_plan"]
        result = UnderstandEngine(self.host, distribution("2.1.0")).run(
            "compatibility",
            action="migrate",
            approval={
                "approved": True,
                "plan_id": plan["plan_id"],
                "plan_digest": plan["digest"],
            },
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN", result.blockers)
        self.assertEqual(result.mutations, "none")
        self.assertEqual(_task_snapshot(self.host)["bytes"], before_task["bytes"])
        self._assert_no_fresh_apply()

    def test_P9_Q05_task_bound_develop_may_apply(self):
        write_task(self.host)
        preview = preview_migration(self.host)
        plan = preview.extras["migration"]["migration_plan"]
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval=bound_migration_approval(self.host, plan),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertEqual(project.get("project_contract_generation"), "3")

    def test_P9_Q06_recovery_remains_understand_owned(self):
        write_task(self.host)
        preview = preview_migration(self.host)
        plan = preview.extras["migration"]["migration_plan"]
        interrupted = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval=bound_migration_approval(self.host, plan),
            interrupt_after_migration="first_mutation",
        )
        self.assertEqual(interrupted.outcome, "BLOCKED", interrupted.blockers)
        view = reconstruct_migration_view(self.host)
        self.assertEqual(view["executions"][0].get("status"), "RECOVERY_REQUIRED")
        directory = Path(snapshot_host(self.host).migrations[0]["_dir"])
        stored = read_yaml(directory / "plan.yaml")
        resumed = UnderstandEngine(self.host, distribution("2.1.0")).run(
            "compatibility",
            action="migrate",
            approval={
                "approved": True,
                "plan_id": stored["plan_id"],
                "plan_digest": stored["digest"],
            },
        )
        self.assertEqual(resumed.outcome, "COMPLETED", resumed.blockers)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertEqual(project.get("lifecycle"), "ACTIVE")
        self.assertEqual(project.get("project_contract_generation"), "3")


if __name__ == "__main__":
    unittest.main()

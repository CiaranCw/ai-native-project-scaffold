from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from support import REPO, adopt, distribution, engine, write
from scaffold_p5.engine import UnderstandEngine
from scaffold_p5.host_state import durable_inventory, scm_baseline, snapshot_host
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p5.migration import derive_migration_target
from scaffold_p5.packages import load_package


class P5Rev2Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write(self.host, "README.md", "# Ordinary project\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _plan(self, version: str = "2.1.0"):
        preview = engine(self.host, version).run(
            "compatibility",
            action="migrate",
        )
        self.assertEqual(preview.outcome, "NEEDS_HUMAN")
        return preview.extras["migration_plan"]

    @staticmethod
    def _approval(plan):
        return {
            "approved": True,
            "plan_id": plan["plan_id"],
            "plan_digest": plan["digest"],
        }

    def _interrupt(self, checkpoint: str = "validating"):
        adopt(self.host)
        plan = self._plan()
        result = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
            approval=self._approval(plan),
            interrupt_after=checkpoint,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        return plan, result

    def _git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(self.host), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return completed.stdout.strip()

    def _init_git(self) -> str:
        self._git("init")
        self._git("add", "README.md")
        self._git(
            "-c",
            "user.name=P5 Test",
            "-c",
            "user.email=p5@example.invalid",
            "commit",
            "-m",
            "baseline",
        )
        return self._git("rev-parse", "HEAD")

    def _make_refresh_conflict(self):
        adopt(self.host)
        write(self.host, "docs/project/testing.md", "# Human testing\n")
        project_path = self.host / ".scaffold/project.yaml"
        project = read_yaml(project_path)
        project["ownership"]["docs/project/testing.md"] = "HUMAN_OWNED"
        write_yaml_atomic(project_path, project)
        write(self.host, "tests/test_new.py", "pass\n")
        return project["baseline"]

    def test_AA1_validating_interruption_resumes(self):
        plan, interrupted = self._interrupt()
        execution = interrupted.extras["migration"]
        self.assertEqual(execution["observed_expected_state"], "VALIDATING")
        self.assertEqual(
            execution["checkpoints_completed"],
            ["CONTRACT_GENERATION_UPDATED"],
        )
        resumed = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
            approval=self._approval(plan),
        )
        self.assertEqual(resumed.outcome, "COMPLETED")
        project = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertEqual(project["lifecycle"], "ACTIVE")
        self.assertEqual(project["project_contract_generation"], "2")

    def test_AA2_validating_divergence_blocks_resume(self):
        plan, _ = self._interrupt()
        path = self.host / ".scaffold/project.yaml"
        project = read_yaml(path)
        project["unexpected"] = "divergence"
        write_yaml_atomic(path, project)
        resumed = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
            approval=self._approval(plan),
        )
        self.assertEqual(resumed.outcome, "BLOCKED")
        self.assertTrue(any("diverged" in value for value in resumed.blockers))

    def test_AA3_recovery_blocks_lock_update(self):
        self._interrupt()
        package = load_package(
            REPO / "tests/fixtures/distribution/packages/understand-2.0.1"
        )
        result = engine(self.host, "2.0.1").run(
            "compatibility",
            action="lock_update",
            new_expected={
                "understand": {
                    "skill_version": package.ref.skill_version,
                    "package_digest": package.ref.package_digest,
                }
            },
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.extras["migration_recovery_isolation"])

    def test_AA4_recovery_blocks_second_migration(self):
        plan, _ = self._interrupt()
        result = engine(self.host, "2.1.1").run(
            "compatibility",
            action="migrate",
            approval=self._approval(plan),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        executions = list(
            (self.host / ".scaffold/runtime/migration-executions").glob(
                "*/execution.yaml"
            )
        )
        self.assertEqual(len(executions), 1)

    def test_AA5_recovery_compatibility_evaluation_is_read_only(self):
        self._interrupt()
        project_path = self.host / ".scaffold/project.yaml"
        lock_path = self.host / ".scaffold/skills.lock"
        before = (project_path.read_bytes(), lock_path.read_bytes())
        result = engine(self.host, "2.1.0").run("compatibility")
        after = (project_path.read_bytes(), lock_path.read_bytes())
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.mutations, "none")
        self.assertTrue(result.extras["read_only_during_recovery"])
        self.assertEqual(after, before)

    def test_AA6_generation_three_target_is_derived(self):
        adopt(self.host)
        plan = self._plan("3.0.0")
        self.assertEqual(plan["target_contract_generation"], "3")
        self.assertEqual(
            plan["compatibility_binding"][
                "target_project_contract_generation"
            ],
            "3",
        )

    def test_AA7_requested_target_cannot_override_evidence(self):
        adopt(self.host)
        result = engine(self.host, "3.0.0").run(
            "compatibility",
            action="migrate",
            target_generation="2",
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("conflicts" in value for value in result.blockers))

    def test_AA8_same_generation_packages_have_distinct_plans(self):
        adopt(self.host)
        plan_a = self._plan("2.1.0")
        plan_b = self._plan("2.1.1")
        self.assertNotEqual(plan_a["plan_id"], plan_b["plan_id"])
        self.assertNotEqual(
            plan_a["compatibility_binding"]["evaluation_digest"],
            plan_b["compatibility_binding"]["evaluation_digest"],
        )

    def test_AA9_package_change_rejects_previous_approval(self):
        adopt(self.host)
        plan_a = self._plan("2.1.0")
        result = engine(self.host, "2.1.1").run(
            "compatibility",
            action="migrate",
            approval=self._approval(plan_a),
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertNotEqual(
            result.extras["migration_plan"]["plan_id"],
            plan_a["plan_id"],
        )

    def test_AA10_resume_revalidates_target_package_binding(self):
        plan, _ = self._interrupt()
        result = engine(self.host, "2.1.1").run(
            "compatibility",
            action="migrate",
            approval=self._approval(plan),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(
            any("package/evaluation binding changed" in b for b in result.blockers)
        )

    def test_AA11_git_baseline_records_actual_revision(self):
        revision = self._init_git()
        baseline = engine(self.host).run("bootstrap").baseline
        self.assertEqual(baseline["kind"], "git")
        self.assertEqual(baseline["revision"], revision)
        self.assertNotEqual(baseline["revision"], "ref: refs/heads/main")

    def test_AA12_git_dirty_tracked_state_is_recorded(self):
        self._init_git()
        write(self.host, "README.md", "# Dirty ordinary project\n")
        baseline = scm_baseline(self.host)
        self.assertEqual(baseline["working_tree"], "dirty")
        self.assertEqual(baseline["tracked_changes"], "present")
        self.assertEqual(engine(self.host).run("bootstrap").outcome, "NEEDS_HUMAN")

    def test_AA13_git_untracked_state_is_recorded(self):
        self._init_git()
        write(self.host, "new.txt", "untracked\n")
        baseline = scm_baseline(self.host)
        self.assertEqual(baseline["working_tree"], "dirty")
        self.assertEqual(baseline["untracked_changes"], "present")

    def test_AA14_no_scm_has_portable_baseline(self):
        baseline = scm_baseline(self.host)
        self.assertEqual(baseline["kind"], "none")
        self.assertIsNone(baseline["revision"])
        self.assertTrue(baseline["filesystem"]["fingerprint"])
        self.assertNotIn("git_sha", baseline)

    def test_rev2_unborn_git_is_not_attached(self):
        self._git("init")
        baseline = scm_baseline(self.host)
        self.assertEqual(baseline["kind"], "git")
        self.assertIsNone(baseline["revision"])
        self.assertEqual(baseline["head_state"], "unborn")

    def test_rev2_target_respects_all_core_package_constraints(self):
        package = {
            "skill_id": "understand",
            "validity": "VALID",
            "result": "MIGRATION_REQUIRED",
            "expected_package": {"skill_id": "understand"},
            "actual_package": {"skill_id": "understand"},
            "evaluation_inputs": {
                "project_contract_generation": "1",
                "supported_project_contract_generations": ["2"],
                "record_schema_requirements": {},
                "record_schema_capabilities": {},
            },
            "migration_causes": [
                {
                    "kind": "project_contract_generation",
                    "current_generation": "1",
                    "supported_target_generations": ["2"],
                    "supported_by_bounded_action": True,
                }
            ],
        }
        other = {
            "skill_id": "develop",
            "validity": "VALID",
            "result": "EXACT",
            "expected_package": {"skill_id": "develop"},
            "actual_package": {"skill_id": "develop"},
            "evaluation_inputs": {
                "project_contract_generation": "1",
                "supported_project_contract_generations": ["1"],
                "record_schema_requirements": {},
                "record_schema_capabilities": {},
            },
            "migration_causes": [],
        }
        target, _, issues = derive_migration_target(
            {
                "overall": "MIGRATION_REQUIRED",
                "results": {
                    "understand": package,
                    "develop": other,
                },
            }
        )
        self.assertIsNone(target)
        self.assertTrue(issues)

    def test_AA15_refresh_updates_last_understood_baseline(self):
        adopt(self.host)
        before = read_yaml(self.host / ".scaffold/project.yaml")["baseline"]
        write(self.host, "src/app.py", "print('new')\n")
        result = engine(self.host).run("refresh")
        after = read_yaml(self.host / ".scaffold/project.yaml")["baseline"]
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertNotEqual(
            before["filesystem"]["fingerprint"],
            after["filesystem"]["fingerprint"],
        )
        self.assertEqual(result.baseline, after)

    def test_AA16_ordinary_docs_project_is_not_scaffold_identity(self):
        write(self.host, "docs/project/overview.md", "# Human overview\n")
        snap = snapshot_host(self.host)
        self.assertEqual(snap.host_class, "NOT_ADOPTED")
        self.assertEqual(snap.preflight_context, "PRE_ADOPTION_BOOTSTRAP")

    def test_AA17_existing_overview_is_planned_human_owned(self):
        write(self.host, "docs/project/overview.md", "# Human overview\n")
        result = engine(self.host).run("bootstrap")
        action = next(
            row
            for row in result.extras["plan"]["actions"]
            if row["target"] == "docs/project/overview.md"
        )
        self.assertEqual(action["action_class"], "PRESERVE")
        self.assertEqual(action["ownership"], "HUMAN_OWNED")

    def test_AA18_existing_canonical_human_docs_are_preserved(self):
        paths = {
            "docs/project/development.md": "# Human development\n",
            "docs/project/testing.md": "# Human testing\n",
            "docs/project/architecture.md": "# Human architecture\n",
        }
        for path, text in paths.items():
            write(self.host, path, text)
        write(self.host, "Makefile", "build:\n\t@echo build\n")
        write(self.host, "tests/test_x.py", "pass\n")
        before = {path: (self.host / path).read_bytes() for path in paths}
        result = adopt(self.host)
        self.assertEqual(result.outcome, "COMPLETED")
        project = read_yaml(self.host / ".scaffold/project.yaml")
        for path in paths:
            self.assertEqual((self.host / path).read_bytes(), before[path])
            self.assertEqual(project["ownership"][path], "HUMAN_OWNED")

    def test_AA19_human_canonical_strategy_is_explicit(self):
        for path in (
            "docs/project/development.md",
            "docs/project/testing.md",
            "docs/project/architecture.md",
            "docs/project/modules/src.md",
        ):
            write(self.host, path, f"# Human {Path(path).stem}\n")
        write(self.host, "src/app.py", "pass\n")
        write(self.host, "tests/test_x.py", "pass\n")
        write(self.host, "Makefile", "build:\n\t@echo build\n")
        plan = engine(self.host).run("bootstrap").extras["plan"]
        actions = {row["target"]: row for row in plan["actions"]}
        for path in (
            "docs/project/development.md",
            "docs/project/testing.md",
            "docs/project/architecture.md",
            "docs/project/modules/src.md",
        ):
            self.assertEqual(actions[path]["action_class"], "PRESERVE")
            self.assertEqual(actions[path]["ownership"], "HUMAN_OWNED")

    def test_AA20_activation_keeps_truthful_human_ownership(self):
        write(self.host, "docs/project/overview.md", "# Human overview\n")
        write(self.host, "docs/project/modules/src.md", "# Human source\n")
        write(self.host, "src/app.py", "pass\n")
        result = adopt(self.host)
        self.assertEqual(result.outcome, "COMPLETED")
        ownership = read_yaml(self.host / ".scaffold/project.yaml")["ownership"]
        self.assertEqual(
            ownership["docs/project/overview.md"],
            "HUMAN_OWNED",
        )
        self.assertEqual(
            ownership["docs/project/modules/src.md"],
            "HUMAN_OWNED",
        )

    def test_AA21_refresh_human_conflict_is_not_completed(self):
        self._make_refresh_conflict()
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertNotEqual(result.next_route, "continue")
        repeated = engine(self.host).run("refresh")
        self.assertEqual(repeated.outcome, "NEEDS_HUMAN")

    def test_AA22_refresh_conflict_is_in_blockers(self):
        self._make_refresh_conflict()
        result = engine(self.host).run("refresh")
        self.assertTrue(result.blockers)
        self.assertTrue(any("testing knowledge" in b for b in result.blockers))
        project = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertIn("NEEDS_REFRESH", project["maintenance"])

    def test_AA23_resolved_refresh_converges_and_updates_baseline(self):
        old_baseline = self._make_refresh_conflict()
        first = engine(self.host).run("refresh")
        self.assertEqual(first.outcome, "NEEDS_HUMAN")
        project_path = self.host / ".scaffold/project.yaml"
        project = read_yaml(project_path)
        project["ownership"]["docs/project/testing.md"] = "GENERATED"
        write_yaml_atomic(project_path, project)
        second = engine(self.host).run("refresh")
        converged = read_yaml(project_path)
        self.assertEqual(second.outcome, "COMPLETED")
        self.assertNotIn("NEEDS_REFRESH", converged["maintenance"])
        self.assertNotEqual(
            old_baseline["filesystem"]["fingerprint"],
            converged["baseline"]["filesystem"]["fingerprint"],
        )

    def test_rev2_broken_architecture_pointer_is_unresolved(self):
        write(self.host, "ARCHITECTURE.md", "# Human architecture\n")
        adopt(self.host)
        (self.host / "ARCHITECTURE.md").unlink()
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertTrue(any("architecture" in b for b in result.blockers))

    def test_rev2_project_ownership_blocks_before_refresh_writes(self):
        adopt(self.host)
        project_path = self.host / ".scaffold/project.yaml"
        project = read_yaml(project_path)
        project["ownership"][".scaffold/project.yaml"] = "HUMAN_OWNED"
        write_yaml_atomic(project_path, project)
        write(self.host, "src/new.py", "pass\n")
        before = durable_inventory(self.host)
        result = engine(self.host).run("refresh")
        after = durable_inventory(self.host)
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertEqual(result.mutations, "none")
        self.assertEqual(before, after)

    def test_rev2_managed_file_without_region_remains_conflicting(self):
        adopt(self.host)
        write(self.host, "tests/test_new.py", "pass\n")
        self.assertEqual(engine(self.host).run("refresh").outcome, "COMPLETED")
        project_path = self.host / ".scaffold/project.yaml"
        project = read_yaml(project_path)
        project["ownership"]["docs/project/testing.md"] = "MANAGED"
        write_yaml_atomic(project_path, project)
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertTrue(any("bounded managed region" in b for b in result.blockers))

    def test_AA24_existing_generation_two_pipeline_still_converges(self):
        adopt(self.host)
        plan = self._plan("2.1.0")
        migrated = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
            approval=self._approval(plan),
        )
        self.assertEqual(migrated.outcome, "COMPLETED")
        compatible = engine(self.host, "2.1.0").run("compatibility")
        self.assertEqual(compatible.compatibility, "COMPATIBLE")
        package = load_package(
            REPO / "tests/fixtures/distribution/packages/understand-2.1.0"
        )
        target = {
            "understand": {
                "skill_version": package.ref.skill_version,
                "package_digest": package.ref.package_digest,
                "package_format_version": package.ref.package_format_version,
            }
        }
        preview = engine(self.host, "2.1.0").run(
            "compatibility",
            action="lock_update",
            new_expected=target,
        )
        updated = engine(self.host, "2.1.0").run(
            "compatibility",
            action="lock_update",
            new_expected=target,
            approval={
                "approved": True,
                "plan_digest": preview.extras["lock_update_plan"]["digest"],
            },
        )
        self.assertEqual(updated.outcome, "COMPLETED")
        exact = engine(self.host, "2.1.0").run("compatibility")
        self.assertEqual(exact.compatibility, "EXACT")


if __name__ == "__main__":
    unittest.main()

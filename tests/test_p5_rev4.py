from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import get_args

from support import FIXTURE_DIST, REPO, adopt, engine, write
from scaffold_p5.adoption import (
    persist_session,
    plan_from_dict,
    validate_plan_content,
)
from scaffold_p5.host_state import durable_inventory, snapshot_host
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p5.models import (
    COMPAT_RESULTS,
    CORE_SKILLS,
    LIFECYCLES,
    OWNERSHIP_MODES,
    PreflightContext,
)
from scaffold_p5.packages import load_package
from scaffold_p5.schemas import adoption_plan_digest


class P5Rev4Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write(self.host, "README.md", "# Ordinary project\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _interrupt_adoption(self):
        preview = engine(self.host).run("bootstrap")
        plan = preview.extras["plan"]
        result = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
            interrupt_after="project_yaml",
        )
        self.assertEqual(result.outcome, "BLOCKED")
        session = next(
            (
                self.host / ".scaffold/runtime/adoption-sessions"
            ).glob("*/session.yaml")
        )
        return plan, session, session.parent / "plan.yaml"

    def _lock_target(self, version: str = "2.0.1"):
        package = load_package(
            FIXTURE_DIST / f"packages/understand-{version}"
        )
        return {
            "understand": {
                "skill_version": package.ref.skill_version,
                "package_digest": package.ref.package_digest,
                "package_format_version": package.ref.package_format_version,
            }
        }

    @staticmethod
    def _migration_approval(plan):
        return {
            "approved": True,
            "plan_id": plan["plan_id"],
            "plan_digest": plan["digest"],
        }

    def test_AC1_fresh_migration_plan_only_blocks_bootstrap(self):
        write(
            self.host,
            ".scaffold/runtime/migration-executions/m1/plan.yaml",
            "schema_version: \"1\"\nkind: migration_plan\n",
        )
        snap = snapshot_host(self.host)
        self.assertNotEqual(snap.host_class, "NOT_ADOPTED")
        result = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": "irrelevant"},
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse((self.host / ".scaffold/project.yaml").exists())

    def test_AC2_malformed_migration_recovery_blocks_bootstrap(self):
        write(
            self.host,
            ".scaffold/runtime/migration-executions/m1/execution.yaml",
            "- not-a-map\n",
        )
        write(
            self.host,
            ".scaffold/runtime/migration-executions/m1/plan.yaml",
            "- not-a-map\n",
        )
        result = engine(self.host).run("bootstrap")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(
            snapshot_host(self.host).migration_recovery["requires_isolation"]
        )

    def test_AC3_non_mapping_adoption_session_blocks_bootstrap(self):
        write(
            self.host,
            ".scaffold/runtime/adoption-sessions/a1/session.yaml",
            "- not-a-map\n",
        )
        write(
            self.host,
            ".scaffold/runtime/adoption-sessions/a1/plan.yaml",
            "- not-a-map\n",
        )
        snap = snapshot_host(self.host)
        self.assertEqual(
            snap.adoption_recovery["entries"][0]["classification"],
            "MALFORMED_SESSION",
        )
        self.assertEqual(engine(self.host).run("bootstrap").outcome, "BLOCKED")

    def test_AC4_adoption_plan_without_session_blocks_bootstrap(self):
        write(
            self.host,
            ".scaffold/runtime/adoption-sessions/a1/plan.yaml",
            "schema_version: \"1\"\n",
        )
        snap = snapshot_host(self.host)
        self.assertEqual(
            snap.adoption_recovery["entries"][0]["classification"],
            "PLAN_WITHOUT_SESSION",
        )
        self.assertEqual(engine(self.host).run("bootstrap").outcome, "BLOCKED")

    def test_AC5_orphan_adoption_directory_blocks_without_mutation(self):
        orphan = self.host / ".scaffold/runtime/adoption-sessions/a1"
        orphan.mkdir(parents=True)
        before = durable_inventory(self.host)
        result = engine(self.host).run("bootstrap")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(before, durable_inventory(self.host))
        self.assertFalse((self.host / ".scaffold/project.yaml").exists())

    def test_AC6_non_mapping_project_is_identity_and_is_preserved(self):
        path = self.host / ".scaffold/project.yaml"
        write(self.host, ".scaffold/project.yaml", "- not-a-map\n")
        before = path.read_bytes()
        snap = snapshot_host(self.host)
        self.assertEqual(snap.project_view.status, "MALFORMED")
        self.assertNotEqual(snap.host_class, "NOT_ADOPTED")
        self.assertEqual(engine(self.host).run("bootstrap").outcome, "BLOCKED")
        self.assertEqual(path.read_bytes(), before)

    def test_AC7_unsupported_project_schema_blocks_without_overwrite(self):
        path = self.host / ".scaffold/project.yaml"
        write(
            self.host,
            ".scaffold/project.yaml",
            "schema_version: \"999\"\nlifecycle: ACTIVE\n",
        )
        before = path.read_bytes()
        snap = snapshot_host(self.host)
        self.assertEqual(snap.project_view.status, "UNSUPPORTED")
        self.assertEqual(engine(self.host).run("bootstrap").outcome, "BLOCKED")
        self.assertEqual(path.read_bytes(), before)

    def test_AC8_docs_project_only_remains_fresh_candidate(self):
        write(self.host, "docs/project/overview.md", "# Human overview\n")
        snap = snapshot_host(self.host)
        self.assertEqual(snap.host_class, "NOT_ADOPTED")
        self.assertEqual(snap.preflight_context, "PRE_ADOPTION_BOOTSTRAP")

    def test_AC9_active_schema_one_compatibility_remains_valid(self):
        self.assertEqual(adopt(self.host).outcome, "COMPLETED")
        result = engine(self.host).run("compatibility")
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.compatibility, "EXACT")

    def test_AC10_unsupported_project_schema_blocks_compatibility(self):
        adopt(self.host)
        path = self.host / ".scaffold/project.yaml"
        project = read_yaml(path)
        project["schema_version"] = "999"
        write_yaml_atomic(path, project)
        result = engine(self.host).run("compatibility")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertIsNone(result.compatibility)

    def test_AC11_unsupported_project_schema_blocks_refresh_mutation(self):
        adopt(self.host)
        path = self.host / ".scaffold/project.yaml"
        project = read_yaml(path)
        project["schema_version"] = "999"
        write_yaml_atomic(path, project)
        before = durable_inventory(self.host)
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.mutations, "none")
        self.assertEqual(before, durable_inventory(self.host))

    def test_AC12_unsupported_project_schema_blocks_lock_update(self):
        adopt(self.host)
        project_path = self.host / ".scaffold/project.yaml"
        project = read_yaml(project_path)
        project["schema_version"] = "999"
        write_yaml_atomic(project_path, project)
        lock_path = self.host / ".scaffold/skills.lock"
        before = lock_path.read_bytes()
        result = engine(self.host, "2.0.1").run(
            "compatibility",
            action="lock_update",
            new_expected=self._lock_target(),
            approval={"approved": True, "plan_digest": "irrelevant"},
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(lock_path.read_bytes(), before)

    def test_AC13_unsupported_project_schema_blocks_migration_start(self):
        adopt(self.host)
        project_path = self.host / ".scaffold/project.yaml"
        project = read_yaml(project_path)
        project["schema_version"] = "999"
        write_yaml_atomic(project_path, project)
        result = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
            approval={
                "approved": True,
                "plan_id": "irrelevant",
                "plan_digest": "irrelevant",
            },
        )
        self.assertEqual(result.outcome, "BLOCKED")
        executions = self.host / ".scaffold/runtime/migration-executions"
        self.assertFalse(executions.exists())

    def test_AC14_unsupported_session_schema_blocks_recovery(self):
        plan, session_path, _ = self._interrupt_adoption()
        session = read_yaml(session_path)
        session["schema_version"] = "999"
        write_yaml_atomic(session_path, session)
        before = (self.host / ".scaffold/project.yaml").read_bytes()
        result = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(
            (self.host / ".scaffold/project.yaml").read_bytes(),
            before,
        )

    def test_AC15_incomplete_session_blocks_without_fresh_fallback(self):
        plan, session_path, _ = self._interrupt_adoption()
        session = read_yaml(session_path)
        session.pop("intended_lock")
        write_yaml_atomic(session_path, session)
        result = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertNotEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")

    def test_AC16_changed_plan_schema_fails_content_validation(self):
        _, _, plan_path = self._interrupt_adoption()
        plan = read_yaml(plan_path)
        plan["schema_version"] = "999"
        issues = validate_plan_content(plan)
        self.assertTrue(any("schema_version" in issue for issue in issues))
        self.assertTrue(any("digest" in issue for issue in issues))

    def test_AC17_plan_schema_is_bound_to_digest_and_identity(self):
        plan = engine(self.host).run("bootstrap").extras["plan"]
        changed = dict(plan)
        changed["schema_version"] = "999"
        self.assertNotEqual(adoption_plan_digest(plan), adoption_plan_digest(changed))
        self.assertTrue(validate_plan_content(changed))
        self.assertNotEqual(
            f"plan-{adoption_plan_digest(changed)[:16]}",
            plan["plan_id"],
        )

    def test_AC18_old_approval_cannot_authorize_unsupported_plan(self):
        plan, _, plan_path = self._interrupt_adoption()
        persisted = read_yaml(plan_path)
        persisted["schema_version"] = "999"
        write_yaml_atomic(plan_path, persisted)
        result = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(plan_path.exists())

    def test_AC19_non_mapping_modules_never_throws_on_refresh(self):
        adopt(self.host)
        write(self.host, ".scaffold/modules.yaml", "- not-a-map\n")
        result = engine(self.host).run("refresh")
        self.assertIn(result.outcome, {"COMPLETED", "NEEDS_HUMAN", "BLOCKED"})
        (self.host / ".scaffold/modules.yaml").write_bytes(b"\xff")
        unreadable = engine(self.host).run("refresh")
        self.assertEqual(unreadable.outcome, "COMPLETED")

    def test_AC20_generated_malformed_modules_is_repaired(self):
        adopt(self.host)
        write(self.host, ".scaffold/modules.yaml", "- not-a-map\n")
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "COMPLETED")
        modules = read_yaml(self.host / ".scaffold/modules.yaml")
        self.assertEqual(modules["schema_version"], "1")
        self.assertIsInstance(modules["modules"], list)
        self.assertIn(".scaffold/modules.yaml", result.artifacts)

    def test_AC21_human_owned_malformed_modules_is_preserved(self):
        adopt(self.host)
        project_path = self.host / ".scaffold/project.yaml"
        project = read_yaml(project_path)
        project["ownership"][".scaffold/modules.yaml"] = "HUMAN_OWNED"
        write_yaml_atomic(project_path, project)
        modules_path = self.host / ".scaffold/modules.yaml"
        write(self.host, ".scaffold/modules.yaml", "- human-non-map\n")
        before = modules_path.read_bytes()
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertEqual(modules_path.read_bytes(), before)

    def test_AC22_commands_and_tests_malformed_are_ownership_aware(self):
        adopt(self.host)
        project_path = self.host / ".scaffold/project.yaml"
        project = read_yaml(project_path)
        project["ownership"][".scaffold/commands.yaml"] = "HUMAN_OWNED"
        project["ownership"][".scaffold/tests.yaml"] = "MANAGED"
        write_yaml_atomic(project_path, project)
        commands = self.host / ".scaffold/commands.yaml"
        tests = self.host / ".scaffold/tests.yaml"
        write(self.host, ".scaffold/commands.yaml", "- human\n")
        write(self.host, ".scaffold/tests.yaml", "schema_version: \"999\"\nprofiles: []\n")
        before = (commands.read_bytes(), tests.read_bytes())
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertEqual((commands.read_bytes(), tests.read_bytes()), before)
        self.assertTrue(any("bounded managed region" in b for b in result.blockers))

    def test_AC23_valid_machine_indexes_keep_refresh_convergence(self):
        adopt(self.host)
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "COMPLETED")
        for name in ("modules", "commands", "tests"):
            value = read_yaml(self.host / f".scaffold/{name}.yaml")
            self.assertEqual(value["schema_version"], "1")

    def test_AC24_no_scm_host_remains_supported(self):
        self.assertFalse((self.host / ".git").exists())
        result = adopt(self.host)
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.baseline["kind"], "none")

    def test_AC25_complete_migration_and_lock_update_flow_remains(self):
        adopt(self.host)
        preview = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
        )
        plan = preview.extras["migration_plan"]
        migrated = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
            approval=self._migration_approval(plan),
        )
        self.assertEqual(migrated.outcome, "COMPLETED")
        self.assertEqual(
            engine(self.host, "2.1.0").run("compatibility").compatibility,
            "COMPATIBLE",
        )
        target = self._lock_target("2.1.0")
        update_plan = engine(self.host, "2.1.0").run(
            "compatibility",
            action="lock_update",
            new_expected=target,
        ).extras["lock_update_plan"]
        updated = engine(self.host, "2.1.0").run(
            "compatibility",
            action="lock_update",
            new_expected=target,
            approval={
                "approved": True,
                "plan_digest": update_plan["digest"],
            },
        )
        self.assertEqual(updated.outcome, "COMPLETED")
        self.assertEqual(
            engine(self.host, "2.1.0").run("compatibility").compatibility,
            "EXACT",
        )

    def test_AC26_adoption_crash_gap_and_provenance_remain(self):
        plan, session_path, _ = self._interrupt_adoption()
        session = read_yaml(session_path)
        session["applied_mutation_summary"] = []
        write_yaml_atomic(session_path, session)
        result = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
        )
        self.assertEqual(result.outcome, "COMPLETED")

    def test_AC27_orphan_migration_recovery_isolation_remains(self):
        adopt(self.host)
        lock_path = self.host / ".scaffold/skills.lock"
        before = lock_path.read_bytes()
        write(
            self.host,
            ".scaffold/runtime/migration-executions/m1/plan.yaml",
            "schema_version: \"1\"\nkind: migration_plan\n",
        )
        result = engine(self.host, "2.0.1").run(
            "compatibility",
            action="lock_update",
            new_expected=self._lock_target(),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(lock_path.read_bytes(), before)

    def test_AC28_exactly_two_preflight_contexts_remain(self):
        self.assertEqual(
            set(get_args(PreflightContext)),
            {"PRE_ADOPTION_BOOTSTRAP", "HOST_COMPATIBILITY"},
        )

    def test_AC29_exactly_five_compatibility_results_remain(self):
        self.assertEqual(
            set(COMPAT_RESULTS),
            {
                "EXACT",
                "COMPATIBLE",
                "MIGRATION_REQUIRED",
                "INCOMPATIBLE",
                "UNKNOWN",
            },
        )

    def test_AC30_foundation_taxonomies_and_product_scope_remain(self):
        self.assertEqual(
            CORE_SKILLS,
            ("understand", "develop", "test", "submit"),
        )
        self.assertEqual(
            set(LIFECYCLES),
            {"NOT_ADOPTED", "ADOPTING", "ACTIVE", "RECOVERY_REQUIRED"},
        )
        self.assertEqual(
            set(OWNERSHIP_MODES),
            {"GENERATED", "MANAGED", "HUMAN_OWNED"},
        )
        self.assertTrue((REPO / "src/scaffold_p6").is_dir())
        self.assertTrue((REPO / "skills/test").is_dir())
        self.assertTrue((REPO / "src/scaffold_p7").is_dir())
        self.assertFalse((REPO / "src/scaffold_p8").exists())
        self.assertTrue((REPO / "skills/develop").is_dir())
        self.assertFalse((REPO / "skills/submit").exists())

    def test_rev4_session_before_project_is_recoverable(self):
        plan_data = engine(self.host).run("bootstrap").extras["plan"]
        plan = plan_from_dict(plan_data)
        persist_session(
            self.host,
            plan,
            status="OPEN",
            steps=["B1", "B2", "B3", "B4"],
            checkpoints=[],
            mutations=[],
            observed_approved=True,
        )
        snap = snapshot_host(self.host)
        self.assertEqual(snap.host_class, "INTERRUPTED_INITIAL_ADOPTION")
        result = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan.digest},
        )
        self.assertEqual(result.outcome, "COMPLETED")

    def test_rev4_migration_recovery_root_file_blocks_controlled(self):
        write(
            self.host,
            ".scaffold/runtime/migration-executions",
            "orphan recovery entry\n",
        )
        snap = snapshot_host(self.host)
        self.assertTrue(snap.migration_recovery["requires_isolation"])
        self.assertNotEqual(snap.host_class, "NOT_ADOPTED")
        self.assertEqual(engine(self.host).run("bootstrap").outcome, "BLOCKED")

    def test_rev4_nested_project_shapes_block_controlled(self):
        write(
            self.host,
            ".scaffold/project.yaml",
            "schema_version: \"1\"\n"
            "project_contract_generation: \"1\"\n"
            "lifecycle:\n"
            "  - ACTIVE\n"
            "maintenance: []\n",
        )
        snap = snapshot_host(self.host)
        self.assertIn(snap.project_view.status, {"UNSUPPORTED", "INCOMPLETE"})
        self.assertEqual(engine(self.host).run("bootstrap").outcome, "BLOCKED")

        self.host = Path(self._tmp.name) / "active"
        self.host.mkdir()
        write(self.host, "README.md", "# Ordinary project\n")
        adopt(self.host)
        project_path = self.host / ".scaffold/project.yaml"
        project = read_yaml(project_path)
        project["facts"] = [
            {
                "name": [],
                "value": None,
                "confidence": "UNKNOWN",
                "critical": False,
            }
        ]
        write_yaml_atomic(project_path, project)
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "BLOCKED")

    def test_rev4_mixed_adoption_and_migration_recovery_blocks(self):
        plan_data = engine(self.host).run("bootstrap").extras["plan"]
        plan = plan_from_dict(plan_data)
        persist_session(
            self.host,
            plan,
            status="OPEN",
            steps=["B1", "B2", "B3", "B4"],
            checkpoints=[],
            mutations=[],
            observed_approved=True,
        )
        write(
            self.host,
            ".scaffold/runtime/migration-executions/m1/plan.yaml",
            "schema_version: \"1\"\nkind: migration_plan\n",
        )
        snap = snapshot_host(self.host)
        self.assertNotEqual(snap.host_class, "INTERRUPTED_INITIAL_ADOPTION")
        result = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan.digest},
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse((self.host / ".scaffold/project.yaml").exists())

        self.host = Path(self._tmp.name) / "active-mixed"
        self.host.mkdir()
        write(self.host, "README.md", "# Ordinary project\n")
        active_plan = engine(self.host).run("bootstrap").extras["plan"]
        interrupted = engine(self.host).run(
            "bootstrap",
            approval={
                "approved": True,
                "plan_digest": active_plan["digest"],
            },
            interrupt_after="active_before_cleanup",
        )
        self.assertEqual(interrupted.outcome, "BLOCKED")
        write(
            self.host,
            ".scaffold/runtime/migration-executions/m1/plan.yaml",
            "schema_version: \"1\"\nkind: migration_plan\n",
        )
        active_snapshot = snapshot_host(self.host)
        self.assertNotEqual(
            active_snapshot.host_class,
            "INTERRUPTED_INITIAL_ADOPTION",
        )
        active_result = engine(self.host).run(
            "bootstrap",
            approval={
                "approved": True,
                "plan_digest": active_plan["digest"],
            },
        )
        self.assertEqual(active_result.outcome, "BLOCKED")

    def test_rev4_nested_baseline_and_module_rows_are_controlled(self):
        adopt(self.host)
        project_path = self.host / ".scaffold/project.yaml"
        project = read_yaml(project_path)
        project["baseline"]["filesystem"]["project_state"] = []
        write_yaml_atomic(project_path, project)
        self.assertEqual(
            snapshot_host(self.host).project_view.status,
            "INCOMPLETE",
        )
        self.assertEqual(engine(self.host).run("refresh").outcome, "BLOCKED")

        self.host = Path(self._tmp.name) / "modules"
        self.host.mkdir()
        write(self.host, "README.md", "# Ordinary project\n")
        adopt(self.host)
        write_yaml_atomic(
            self.host / ".scaffold/modules.yaml",
            {
                "schema_version": "1",
                "modules": [{"id": "bad", "path": []}],
            },
        )
        repaired = engine(self.host).run("refresh")
        self.assertEqual(repaired.outcome, "COMPLETED")
        self.assertEqual(
            read_yaml(self.host / ".scaffold/modules.yaml")["modules"],
            [],
        )

    def test_rev4_malformed_refresh_conflicts_blocks_controlled(self):
        adopt(self.host)
        project_path = self.host / ".scaffold/project.yaml"
        project = read_yaml(project_path)
        project["refresh_conflicts"] = 1
        write_yaml_atomic(project_path, project)
        self.assertEqual(
            snapshot_host(self.host).project_view.status,
            "INCOMPLETE",
        )
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.mutations, "none")

    def test_rev4_machine_index_directory_blocks_controlled(self):
        adopt(self.host)
        modules_path = self.host / ".scaffold/modules.yaml"
        modules_path.unlink()
        modules_path.mkdir()
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertTrue(
            any("not a regular file" in blocker for blocker in result.blockers)
        )
        self.assertTrue(modules_path.is_dir())


if __name__ == "__main__":
    unittest.main()

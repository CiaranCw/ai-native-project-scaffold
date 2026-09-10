from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from support import FIXTURE_DIST, REPO, REPO_UNDERSTAND, adopt, apply_fresh_migration, engine, write
from scaffold_p5.compatibility import evaluate_package
from scaffold_p5.distribution import Distribution
from scaffold_p5.engine import UnderstandEngine
from scaffold_p5.full import GENERATED_AGENTS, GENERATED_OVERVIEW
from scaffold_p5.host_state import scm_baseline, snapshot_host
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p5.models import CORE_SKILLS, SelectedRelease
from scaffold_p5.packages import PackageIndex, load_package


class P5Rev3Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.host = self.root / "host"
        self.host.mkdir()
        write(self.host, "README.md", "# Ordinary project\n")

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _approval(plan):
        return {
            "approved": True,
            "plan_id": plan["plan_id"],
            "plan_digest": plan["digest"],
        }

    def _migration_plan(self, version: str = "2.1.0"):
        preview = engine(self.host, version).run(
            "compatibility",
            action="migrate",
        )
        self.assertEqual(preview.outcome, "NEEDS_HUMAN")
        return preview.extras["migration_plan"]

    def _interrupt_migration(self):
        adopt(self.host)
        plan = self._migration_plan()
        result = apply_fresh_migration(
            self.host,
            plan,
            interrupt_after="validating",
        )
        self.assertEqual(result.outcome, "BLOCKED")
        execution = next(
            (
                self.host
                / ".scaffold/runtime/migration-executions"
            ).glob("*/execution.yaml")
        )
        return plan, execution

    def _adoption_interruption(self, **opts):
        preview_opts = {
            key: opts[key]
            for key in ("extra_facts", "derived_copy")
            if key in opts
        }
        preview = engine(self.host).run("bootstrap", **preview_opts)
        plan = preview.extras["plan"]
        result = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
            interrupt_after="project_yaml",
            **preview_opts,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        session = next(
            (
                self.host / ".scaffold/runtime/adoption-sessions"
            ).glob("*/session.yaml")
        )
        return plan, session

    def _make_package(
        self,
        skill_id: str,
        version: str,
        provides: list[str],
        requires: list[str],
        name: str,
    ):
        path = self.root / name
        path.mkdir()
        write(path, "SKILL.md", f"# {skill_id.title()} fixture\n")
        write_yaml_atomic(
            path / "skill.yaml",
            {
                "skill_id": skill_id,
                "skill_version": version,
                "package_format_version": "1",
                "entry": "SKILL.md",
                "modes": [],
                "provides": provides,
                "requires": requires,
            },
        )
        return load_package(path)

    def _distribution(
        self,
        replacements: dict[str, object] | None = None,
        unrelated: list[object] | None = None,
    ):
        packages = {
            "understand": load_package(REPO_UNDERSTAND),
            "develop": load_package(
                FIXTURE_DIST / "packages/develop-2.0.0"
            ),
            "test": load_package(FIXTURE_DIST / "packages/test-2.0.0"),
            "submit": load_package(
                FIXTURE_DIST / "packages/submit-2.0.0"
            ),
        }
        packages.update(replacements or {})
        release = SelectedRelease(
            release_id="rel-custom",
            core={skill: packages[skill].ref for skill in CORE_SKILLS},
        )
        indexed = list(packages.values()) + list(unrelated or [])
        return Distribution(
            releases={release.release_id: release},
            index=PackageIndex(indexed),
            selected_release_id=release.release_id,
            actual_understand=packages["understand"],
        )

    def _lock_update_target(self):
        package = load_package(
            FIXTURE_DIST / "packages/understand-2.0.1"
        )
        return {
            "understand": {
                "skill_version": package.ref.skill_version,
                "package_digest": package.ref.package_digest,
                "package_format_version": package.ref.package_format_version,
            }
        }

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.host), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout.strip()

    def test_AB1_missing_execution_blocks_lock_update(self):
        _, execution = self._interrupt_migration()
        execution.unlink()
        result = engine(self.host, "2.0.1").run(
            "compatibility",
            action="lock_update",
            new_expected=self._lock_update_target(),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.extras["migration_recovery_isolation"])

    def test_AB2_malformed_execution_blocks_persistent_action(self):
        _, execution = self._interrupt_migration()
        for content in ("- not-a-map\n", "[malformed\n"):
            write(self.host, str(execution.relative_to(self.host)), content)
            result = engine(self.host, "2.0.1").run(
                "compatibility",
                action="lock_update",
                new_expected=self._lock_update_target(),
            )
            self.assertEqual(result.outcome, "BLOCKED")
            self.assertTrue(result.extras["migration_recovery_isolation"])

    def test_AB3_plan_without_execution_blocks_second_migration(self):
        _, execution = self._interrupt_migration()
        execution.unlink()
        before = list(execution.parent.parent.iterdir())
        result = engine(self.host, "3.0.0").run(
            "compatibility",
            action="migrate",
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(list(execution.parent.parent.iterdir()), before)

    def test_AB4_incoherent_recovery_evaluation_is_read_only(self):
        _, execution = self._interrupt_migration()
        execution.unlink()
        project = self.host / ".scaffold/project.yaml"
        lock = self.host / ".scaffold/skills.lock"
        before = (project.read_bytes(), lock.read_bytes())
        result = engine(self.host, "2.1.0").run("compatibility")
        self.assertEqual(result.mutations, "none")
        self.assertTrue(result.extras["read_only_during_recovery"])
        self.assertEqual((project.read_bytes(), lock.read_bytes()), before)

    def test_AB5_valid_execution_still_resumes(self):
        plan, _ = self._interrupt_migration()
        result = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
            approval=self._approval(plan),
        )
        self.assertEqual(result.outcome, "COMPLETED")

    def test_AB6_modules_change_invalidates_migration_approval(self):
        adopt(self.host)
        plan = self._migration_plan()
        modules = self.host / ".scaffold/modules.yaml"
        data = read_yaml(modules)
        data["material_change"] = True
        write_yaml_atomic(modules, data)
        result = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
            approval=self._approval(plan),
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertEqual(
            read_yaml(self.host / ".scaffold/project.yaml")[
                "project_contract_generation"
            ],
            "1",
        )

    def test_AB7_commands_change_invalidates_migration_approval(self):
        adopt(self.host)
        plan = self._migration_plan()
        commands = self.host / ".scaffold/commands.yaml"
        data = read_yaml(commands)
        data["material_change"] = True
        write_yaml_atomic(commands, data)
        result = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
            approval=self._approval(plan),
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN")

    def test_AB8_runtime_bookkeeping_does_not_invalidate_plan(self):
        adopt(self.host)
        plan = self._migration_plan()
        write(
            self.host,
            ".scaffold/runtime/bookkeeping.yaml",
            "ephemeral: true\n",
        )
        preview = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
            approval=self._approval(plan),
        )
        self.assertEqual(preview.outcome, "NEEDS_HUMAN")
        self.assertEqual(preview.extras["migration_plan"]["plan_id"], plan["plan_id"])
        self.assertEqual(preview.extras["migration_plan"]["digest"], plan["digest"])
        result = apply_fresh_migration(self.host, plan)
        self.assertEqual(result.outcome, "COMPLETED")

    def test_AB9_unproven_agents_inside_envelope_blocks_resume(self):
        plan, _ = self._adoption_interruption()
        content = "# Human router created during interruption\n"
        write(self.host, "AGENTS.md", content)
        result = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(
            (self.host / "AGENTS.md").read_text(encoding="utf-8"),
            content,
        )

    def test_AB10_unproven_canonical_docs_block_resume(self):
        write(self.host, "Makefile", "build:\n\t@echo build\n")
        write(self.host, "tests/test_x.py", "pass\n")
        write(self.host, "src/app.py", "pass\n")
        plan, _ = self._adoption_interruption()
        human = {
            "docs/project/development.md": "# Human development\n",
            "docs/project/testing.md": "# Human testing\n",
            "docs/project/modules/src.md": "# Human source\n",
        }
        for path, content in human.items():
            write(self.host, path, content)
        result = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
        )
        self.assertEqual(result.outcome, "BLOCKED")
        for path, content in human.items():
            self.assertEqual(
                (self.host / path).read_text(encoding="utf-8"),
                content,
            )

    def test_AB11_expected_write_crash_gap_reconciles(self):
        plan, session = self._adoption_interruption()
        data = read_yaml(session)
        data["applied_mutation_summary"] = []
        write_yaml_atomic(session, data)
        result = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
        )
        self.assertEqual(result.outcome, "COMPLETED")

    def test_AB12_recorded_matching_progress_resumes(self):
        preview = engine(self.host).run("bootstrap")
        plan = preview.extras["plan"]
        interrupted = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
            interrupt_after="before_lock",
        )
        self.assertEqual(interrupted.outcome, "BLOCKED")
        resumed = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
        )
        self.assertEqual(resumed.outcome, "COMPLETED")

    def test_AB13_replan_preserves_human_development_doc(self):
        self._adoption_interruption()
        write(self.host, "Makefile", "build:\n\t@echo build\n")
        content = "# Human development\n"
        write(self.host, "docs/project/development.md", content)
        result = engine(self.host).run("bootstrap", replan=True)
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        action = next(
            row
            for row in result.extras["plan"]["actions"]
            if row["target"] == "docs/project/development.md"
        )
        self.assertEqual(action["action_class"], "PRESERVE")
        self.assertEqual(action["ownership"], "HUMAN_OWNED")

    def test_AB14_replan_preserves_human_testing_and_module_docs(self):
        self._adoption_interruption()
        write(self.host, "tests/test_x.py", "pass\n")
        write(self.host, "src/app.py", "pass\n")
        paths = (
            "docs/project/testing.md",
            "docs/project/modules/src.md",
        )
        for path in paths:
            write(self.host, path, "# Human knowledge\n")
        result = engine(self.host).run("bootstrap", replan=True)
        actions = {row["target"]: row for row in result.extras["plan"]["actions"]}
        for path in paths:
            self.assertEqual(actions[path]["action_class"], "PRESERVE")
            self.assertEqual(actions[path]["ownership"], "HUMAN_OWNED")

    def test_AB15_replan_retains_proven_generated_ownership(self):
        self._adoption_interruption()
        result = engine(self.host).run("bootstrap", replan=True)
        action = next(
            row
            for row in result.extras["plan"]["actions"]
            if row["target"] == ".scaffold/project.yaml"
        )
        self.assertEqual(action["action_class"], "MANAGED_UPDATE")
        self.assertEqual(action["ownership"], "GENERATED")

    def test_AB16_refresh_repairs_missing_generated_agents(self):
        adopt(self.host)
        (self.host / "AGENTS.md").unlink()
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(
            (self.host / "AGENTS.md").read_text(encoding="utf-8"),
            GENERATED_AGENTS,
        )

    def test_AB17_refresh_restores_stale_generated_agents(self):
        adopt(self.host)
        write(self.host, "AGENTS.md", "# Stale generated router\n")
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(
            (self.host / "AGENTS.md").read_text(encoding="utf-8"),
            GENERATED_AGENTS,
        )

    def test_AB18_refresh_preserves_incoherent_human_agents(self):
        bridge = (
            "Read `.scaffold/project.yaml`, `docs/project/overview.md`, "
            "and `.scaffold/skills.lock`.\n"
        )
        write(self.host, "AGENTS.md", bridge)
        adopt(self.host)
        content = "# Human router no longer routes\n"
        write(self.host, "AGENTS.md", content)
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertEqual(
            (self.host / "AGENTS.md").read_text(encoding="utf-8"),
            content,
        )
        self.assertTrue(any("AGENTS.md" in value for value in result.blockers))

    def test_AB19_refresh_repairs_missing_generated_overview(self):
        adopt(self.host)
        (self.host / "docs/project/overview.md").unlink()
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(
            (self.host / "docs/project/overview.md").read_text(
                encoding="utf-8"
            ),
            GENERATED_OVERVIEW,
        )

    def test_AB20_refresh_does_not_replace_human_overview(self):
        write(self.host, "docs/project/overview.md", "# Human overview\n")
        adopt(self.host)
        (self.host / "docs/project/overview.md").unlink()
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertFalse((self.host / "docs/project/overview.md").exists())

    def test_AB21_primary_repairs_converge_and_advance_baseline(self):
        adopt(self.host)
        project_path = self.host / ".scaffold/project.yaml"
        before = read_yaml(project_path)["baseline"]
        write(self.host, "src/new.py", "pass\n")
        (self.host / "AGENTS.md").unlink()
        (self.host / "docs/project/overview.md").unlink()
        result = engine(self.host).run("refresh")
        project = read_yaml(project_path)
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertNotIn("NEEDS_REFRESH", project["maintenance"])
        self.assertNotEqual(
            before["filesystem"]["fingerprint"],
            project["baseline"]["filesystem"]["fingerprint"],
        )

    def test_AB22_two_node_dependency_cycle_blocks_release(self):
        develop = self._make_package(
            "develop",
            "9.0.0",
            ["develop.normal_task"],
            ["test.scoped_verification"],
            "develop-cycle",
        )
        test = self._make_package(
            "test",
            "9.0.0",
            ["test.scoped_verification"],
            ["develop.normal_task"],
            "test-cycle",
        )
        dist = self._distribution({"develop": develop, "test": test})
        issues = dist.release_issues(dist.selected_release)
        self.assertTrue(any("cycle" in issue for issue in issues))
        self.assertEqual(
            UnderstandEngine(self.host, dist).run("bootstrap").outcome,
            "BLOCKED",
        )

    def test_AB23_longer_core_dependency_cycle_blocks(self):
        develop = self._make_package(
            "develop", "9.1.0", ["develop.normal_task"], ["test.run"], "dev-long"
        )
        test = self._make_package(
            "test", "9.1.0", ["test.run"], ["submit.review"], "test-long"
        )
        submit = self._make_package(
            "submit",
            "9.1.0",
            ["submit.review"],
            ["develop.normal_task"],
            "submit-long",
        )
        dist = self._distribution(
            {"develop": develop, "test": test, "submit": submit}
        )
        self.assertTrue(
            any("cycle" in issue for issue in dist.release_issues(dist.selected_release))
        )

    def test_AB24_forbidden_dependency_edge_is_invalid(self):
        package = self._make_package(
            "test",
            "9.2.0",
            ["test.run"],
            ["develop.normal_task"],
            "test-forbidden",
        )
        self.assertEqual(package.validity, "INVALID")
        self.assertTrue(
            any("forbidden core dependency edge" in reason for reason in package.validity_reasons)
        )

    def test_AB25_legal_acyclic_dependency_is_valid(self):
        develop = self._make_package(
            "develop",
            "9.3.0",
            ["develop.normal_task"],
            ["test.run"],
            "develop-legal",
        )
        test = self._make_package(
            "test", "9.3.0", ["test.run"], [], "test-provider"
        )
        dist = self._distribution({"develop": develop, "test": test})
        self.assertEqual(develop.validity, "VALID")
        self.assertEqual(dist.release_issues(dist.selected_release), [])

    def test_AB26_legal_missing_dependency_is_resolution_problem(self):
        develop = self._make_package(
            "develop",
            "9.4.0",
            ["develop.normal_task"],
            ["test.missing"],
            "develop-missing",
        )
        test = self._make_package(
            "test", "9.4.0", ["test.other"], [], "test-other"
        )
        dist = self._distribution({"develop": develop, "test": test})
        self.assertEqual(develop.validity, "VALID")
        self.assertEqual(dist.release_issues(dist.selected_release), [])
        result = evaluate_package(
            develop.ref,
            develop,
            project={"project_contract_generation": "1"},
            distribution=dist,
            applicable_packages=dist.selected_packages(),
        )
        self.assertEqual(result["validity"], "VALID")
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_AB27_unrelated_index_package_cannot_satisfy_release(self):
        develop = self._make_package(
            "develop",
            "9.5.0",
            ["develop.normal_task"],
            ["test.special"],
            "develop-scoped",
        )
        selected_test = self._make_package(
            "test", "9.5.0", ["test.other"], [], "test-selected"
        )
        unrelated = self._make_package(
            "test", "9.5.1", ["test.special"], [], "test-unrelated"
        )
        dist = self._distribution(
            {"develop": develop, "test": selected_test},
            [unrelated],
        )
        self.assertFalse(
            dist.satisfies("test.special", dist.selected_packages())
        )
        self.assertEqual(
            UnderstandEngine(self.host, dist).run("bootstrap").outcome,
            "BLOCKED",
        )

    def test_AB28_complete_migration_pipeline_still_converges(self):
        adopt(self.host)
        plan = self._migration_plan()
        migrated = apply_fresh_migration(self.host, plan)
        self.assertEqual(migrated.outcome, "COMPLETED")
        self.assertEqual(
            engine(self.host, "2.1.0").run("compatibility").compatibility,
            "COMPATIBLE",
        )
        target = {
            "understand": {
                "skill_version": "2.1.0",
                "package_digest": load_package(
                    FIXTURE_DIST / "packages/understand-2.1.0"
                ).ref.package_digest,
                "package_format_version": "1",
            }
        }
        preview = engine(self.host, "2.1.0").run(
            "compatibility", action="lock_update", new_expected=target
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
        self.assertEqual(
            engine(self.host, "2.1.0").run("compatibility").compatibility,
            "EXACT",
        )

    def test_AB29_git_and_no_scm_baselines_remain_supported(self):
        no_scm = scm_baseline(self.host)
        self.assertEqual(no_scm["kind"], "none")
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
        git = scm_baseline(self.host)
        self.assertEqual(git["kind"], "git")
        self.assertEqual(git["revision"], self._git("rev-parse", "HEAD"))

    def test_AB30_human_testing_conflict_remains_needs_human(self):
        adopt(self.host)
        write(self.host, "docs/project/testing.md", "# Human testing\n")
        project_path = self.host / ".scaffold/project.yaml"
        project = read_yaml(project_path)
        project["ownership"]["docs/project/testing.md"] = "HUMAN_OWNED"
        write_yaml_atomic(project_path, project)
        write(self.host, "tests/test_new.py", "pass\n")
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertTrue(any("testing knowledge" in value for value in result.blockers))

    def test_rev3_contradictory_terminal_execution_stays_isolated(self):
        _, execution = self._interrupt_migration()
        data = read_yaml(execution)
        data["status"] = "COMPLETED"
        data["checkpoints_completed"] = []
        data["checkpoints_remaining"] = []
        data["observed_expected_state"] = "VALIDATION_PASSED"
        write_yaml_atomic(execution, data)
        snap = snapshot_host(self.host)
        self.assertTrue(snap.migration_recovery["requires_isolation"])
        result = engine(self.host, "2.0.1").run(
            "compatibility",
            action="lock_update",
            new_expected=self._lock_update_target(),
        )
        self.assertEqual(result.outcome, "BLOCKED")

    def test_rev3_malformed_checkpoint_type_blocks_controlled(self):
        plan, execution = self._interrupt_migration()
        data = read_yaml(execution)
        data["checkpoints_completed"] = 1
        write_yaml_atomic(execution, data)
        result = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
            approval=self._approval(plan),
        )
        self.assertEqual(result.outcome, "BLOCKED")

    def test_rev3_managed_directory_change_invalidates_migration_plan(self):
        adopt(self.host)
        write(self.host, ".cursor/rules/a.md", "before\n")
        project_path = self.host / ".scaffold/project.yaml"
        project = read_yaml(project_path)
        project["ownership"][".cursor/rules"] = "MANAGED"
        write_yaml_atomic(project_path, project)
        plan = self._migration_plan()
        write(self.host, ".cursor/rules/a.md", "after\n")
        result = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
            approval=self._approval(plan),
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN")

    def test_rev3_lock_update_blocks_unsatisfied_final_dependency(self):
        adopt(self.host)
        target = self._make_package(
            "develop",
            "9.6.0",
            ["develop.normal_task"],
            ["test.missing"],
            "develop-lock-target",
        )
        dist = self._distribution(unrelated=[target])
        result = UnderstandEngine(self.host, dist).run(
            "compatibility",
            action="lock_update",
            new_expected={
                "develop": {
                    "skill_version": target.ref.skill_version,
                    "package_digest": target.ref.package_digest,
                    "package_format_version": target.ref.package_format_version,
                }
            },
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(
            any("final lock compatibility" in value for value in result.blockers)
        )

    def test_rev3_negated_router_tokens_do_not_verify(self):
        bridge = (
            "Read `.scaffold/project.yaml`, `docs/project/overview.md`, "
            "and `.scaffold/skills.lock`.\n"
        )
        write(self.host, "AGENTS.md", bridge)
        adopt(self.host)
        content = (
            "Do not read `.scaffold/project.yaml`; "
            "`docs/project/overview.md` and `.scaffold/skills.lock` are legacy.\n"
        )
        write(self.host, "AGENTS.md", content)
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertEqual(
            (self.host / "AGENTS.md").read_text(encoding="utf-8"),
            content,
        )

    def test_rev3_human_router_repair_can_converge(self):
        bridge = (
            "Read `.scaffold/project.yaml`, `docs/project/overview.md`, "
            "and `.scaffold/skills.lock`.\n"
        )
        write(self.host, "AGENTS.md", bridge)
        adopt(self.host)
        write(self.host, "AGENTS.md", "# Incoherent\n")
        self.assertEqual(
            engine(self.host).run("refresh").outcome,
            "NEEDS_HUMAN",
        )
        write(self.host, "AGENTS.md", bridge)
        repaired = engine(self.host).run("refresh")
        self.assertEqual(repaired.outcome, "COMPLETED")

    def test_rev3_client_index_reconciles_current_clients(self):
        write(self.host, "CLAUDE.md", "human client\n")
        adopt(self.host)
        (self.host / "CLAUDE.md").unlink()
        write(self.host, "CODEX.md", "new human client\n")
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "COMPLETED")
        clients = read_yaml(self.host / ".scaffold/project.yaml")["clients"]
        paths = {row["path"] for row in clients}
        self.assertNotIn("CLAUDE.md", paths)
        self.assertIn("CODEX.md", paths)

    def test_rev3_repeated_replan_retains_generated_lineage(self):
        self._adoption_interruption()
        replacement = engine(self.host).run("bootstrap", replan=True)
        plan = replacement.extras["plan"]
        interrupted = engine(self.host).run(
            "bootstrap",
            replan=True,
            approval={"approved": True, "plan_digest": plan["digest"]},
            interrupt_after="before_lock",
        )
        self.assertEqual(interrupted.outcome, "BLOCKED")
        second = engine(self.host).run("bootstrap", replan=True)
        project_action = next(
            row
            for row in second.extras["plan"]["actions"]
            if row["target"] == ".scaffold/project.yaml"
        )
        self.assertEqual(project_action["ownership"], "GENERATED")


if __name__ == "__main__":
    unittest.main()

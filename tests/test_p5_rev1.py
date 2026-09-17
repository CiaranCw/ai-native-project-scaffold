from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from support import (
    FIXTURE_DIST,
    REPO,
    REPO_UNDERSTAND,
    adopt,
    apply_fresh_migration,
    distribution,
    engine,
    write,
)
from scaffold_p5 import yaml_lite
from scaffold_p5.compatibility import evaluate_package
from scaffold_p5.distribution import Distribution
from scaffold_p5.host_state import inspect_lock, snapshot_host
from scaffold_p5.io_util import read_text, read_yaml, write_text_atomic, write_yaml_atomic
from scaffold_p5.packages import load_package
from scaffold_p5.preflight import run_preflight


class P5Rev1Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.host = self.root / "host"
        self.host.mkdir()
        write(self.host, "README.md", "# Ordinary project\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _interrupt_adoption(self, checkpoint: str = "project_yaml"):
        result = adopt(self.host, interrupt_after=checkpoint)
        session = next(
            (self.host / ".scaffold/runtime/adoption-sessions").glob("*/session.yaml")
        )
        plan = read_yaml(session.parent / "plan.yaml")
        return result, session, plan

    def _migration_preview(self):
        adopt(self.host)
        preview = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
        )
        self.assertEqual(preview.outcome, "NEEDS_HUMAN")
        return preview.extras["migration_plan"]

    def _copy_package(self, source: Path, name: str) -> Path:
        target = self.root / name
        shutil.copytree(source, target)
        return target

    def test_Z1_two_current_recoverable_adoption_sessions_block(self):
        _, session, _ = self._interrupt_adoption()
        duplicate = session.parent.parent / "adopt-duplicate"
        shutil.copytree(session.parent, duplicate)
        decision = run_preflight(snapshot_host(self.host), distribution())
        self.assertFalse(decision.allowed)
        self.assertIsNone(decision.authority)
        self.assertTrue(any("ambiguous" in value for value in decision.blockers))

    def test_Z2_unexpected_durable_mutation_blocks_plan_recovery_authority(self):
        _, _, plan = self._interrupt_adoption()
        write(self.host, "unexpected.txt", "not approved\n")
        result = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertIsNone(result.extras.get("authority"))
        self.assertTrue(any("outside envelope" in value for value in result.blockers))
        self.assertIn("re-plan", result.next_route)

    def test_Z3_expected_partial_progress_resumes_with_same_plan_approval(self):
        _, _, plan = self._interrupt_adoption("before_lock")
        result = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.extras["authority"], "skills.lock")

    def test_Z4_b7_failure_is_recoverable_and_has_replan_route(self):
        from scaffold_p5.models import DiscoveryFact

        failed = adopt(
            self.host,
            extra_facts=[
                DiscoveryFact("authority_collision", True, "CONFLICTING", True)
            ],
        )
        self.assertEqual(failed.outcome, "FAILED")
        snap = snapshot_host(self.host)
        self.assertEqual(snap.host_class, "INTERRUPTED_INITIAL_ADOPTION")
        self.assertEqual(snap.lock.status, "complete_candidate")
        replacement = engine(self.host).run("bootstrap", replan=True)
        self.assertEqual(replacement.outcome, "NEEDS_HUMAN")
        self.assertIn("replacement", replacement.blockers[0])
        completed = engine(self.host).run(
            "bootstrap",
            replan=True,
            approval={
                "approved": True,
                "plan_digest": replacement.extras["plan"]["digest"],
            },
        )
        self.assertEqual(completed.outcome, "COMPLETED")

    def test_Z5_lock_authority_to_active_interruption_resumes(self):
        first, session, plan = self._interrupt_adoption("lock_written_before_checkpoint")
        self.assertEqual(first.extras["authority"], "skills.lock")
        self.assertNotIn(
            "LOCK_AUTHORITY_ESTABLISHED",
            read_yaml(session)["checkpoints"],
        )
        snap = snapshot_host(self.host)
        self.assertEqual(snap.host_class, "INTERRUPTED_INITIAL_ADOPTION")
        self.assertTrue(snap.lock.complete_authoritative)
        decision = run_preflight(snap, distribution())
        self.assertEqual(decision.authority, "skills.lock")
        resumed = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
        )
        self.assertEqual(resumed.outcome, "COMPLETED")
        self.assertEqual(read_yaml(self.host / ".scaffold/project.yaml")["lifecycle"], "ACTIVE")

    def test_Z6_same_version_modified_content_fails_release_identity(self):
        changed = self._copy_package(REPO_UNDERSTAND, "changed-understand")
        skill = changed / "SKILL.md"
        write_text_atomic(skill, read_text(skill) + "\nMaterially modified.\n")
        dist = distribution()
        dist.actual_understand = load_package(changed)
        result = self._run_with_distribution(dist, "bootstrap")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("identity mismatch" in value for value in result.blockers))

    def test_Z7_malformed_semantic_version_is_invalid(self):
        changed = self._copy_package(REPO_UNDERSTAND, "bad-semver")
        current = load_package(changed).ref.skill_version
        self.assertTrue(current)
        write_text_atomic(
            changed / "skill.yaml",
            read_text(changed / "skill.yaml").replace(
                f"skill_version: {current}",
                "skill_version: 2.x.0",
                1,
            ),
        )
        write_text_atomic(
            changed / "SKILL.md",
            read_text(changed / "SKILL.md").replace(
                f"- `skill_version`: `{current}`",
                "- `skill_version`: `2.x.0`",
                1,
            ),
        )
        package = load_package(changed)
        self.assertEqual(package.validity, "INVALID")
        self.assertTrue(any("MAJOR.MINOR.PATCH" in value for value in package.validity_reasons))
        self.assertFalse(
            any("contradiction" in value for value in package.validity_reasons)
        )

    def test_Z8_missing_or_malformed_package_format_is_invalid(self):
        missing = self._copy_package(REPO_UNDERSTAND, "missing-format")
        manifest = missing / "skill.yaml"
        write_text_atomic(
            manifest,
            read_text(manifest).replace('package_format_version: "1"\n', ""),
        )
        malformed = self._copy_package(REPO_UNDERSTAND, "malformed-format")
        malformed_manifest = malformed / "skill.yaml"
        write_text_atomic(
            malformed_manifest,
            read_text(malformed_manifest).replace(
                'package_format_version: "1"',
                'package_format_version: "x"',
            ),
        )
        self.assertEqual(load_package(missing).validity, "INVALID")
        self.assertEqual(load_package(malformed).validity, "INVALID")

    def test_Z9_unsupported_well_formed_format_is_not_exact(self):
        changed = self._copy_package(REPO_UNDERSTAND, "format-2")
        manifest = changed / "skill.yaml"
        write_text_atomic(
            manifest,
            read_text(manifest).replace(
                'package_format_version: "1"',
                'package_format_version: "2"',
            ),
        )
        package = load_package(changed)
        self.assertEqual(package.validity, "VALID")
        result = evaluate_package(
            package.ref,
            package,
            project={"project_contract_generation": "2"},
            distribution=distribution(),
        )
        self.assertEqual(result["result"], "INCOMPATIBLE")
        self.assertNotEqual(result["result"], "EXACT")

    def test_Z10_invalid_core_package_blocks_overall_exact(self):
        adopt(self.host)
        dist = distribution()
        dist.actual_understand = load_package(
            REPO / "tests/fixtures/distribution/packages/understand-invalid"
        )
        result = self._run_with_distribution(dist, "compatibility")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertIsNone(result.compatibility)
        self.assertIsNone(result.extras["evaluation"]["overall"])
        refresh = self._run_with_distribution(dist, "refresh")
        self.assertEqual(refresh.outcome, "BLOCKED")

    def test_Z11_unproven_or_false_authoritative_lock_is_not_authority(self):
        adopt(self.host)
        path = self.host / ".scaffold/skills.lock"
        lock = read_yaml(path)
        lock.pop("authoritative")
        write_yaml_atomic(path, lock)
        self.assertFalse(inspect_lock(path).complete_authoritative)
        lock["authoritative"] = False
        write_yaml_atomic(path, lock)
        self.assertFalse(inspect_lock(path).complete_authoritative)

    def test_Z12_lock_with_fifth_skill_is_not_authority(self):
        adopt(self.host)
        path = self.host / ".scaffold/skills.lock"
        lock = read_yaml(path)
        lock["skills"]["foo"] = dict(lock["skills"]["understand"])
        write_yaml_atomic(path, lock)
        view = inspect_lock(path)
        self.assertFalse(view.complete_authoritative)
        self.assertTrue(any("non-core" in value for value in view.reasons))

    def test_Z13_unknown_lock_update_identity_blocks(self):
        adopt(self.host)
        result = engine(self.host).run(
            "compatibility",
            action="lock_update",
            new_expected={
                "understand": {
                    "skill_version": "99.99.99",
                    "package_digest": "d" * 64,
                }
            },
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("not uniquely resolvable" in value for value in result.blockers))

    def test_Z14_lock_update_cannot_add_fifth_skill(self):
        adopt(self.host)
        result = engine(self.host).run(
            "compatibility",
            action="lock_update",
            new_expected={
                "foo": {
                    "skill_version": "1.0.0",
                    "package_digest": "d" * 64,
                }
            },
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("non-core" in value for value in result.blockers))

    def test_Z15_unknown_tests_remain_unknown_in_machine_state(self):
        adopt(self.host)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        tests = read_yaml(self.host / ".scaffold/tests.yaml")
        self.assertEqual(project["knowledge"]["testing"], "unknown")
        self.assertEqual(tests["applicability"], "UNKNOWN")
        self.assertIsNone(tests["applicable"])

    def test_Z16_build_workflow_and_module_have_knowledge_entries(self):
        write(self.host, "Makefile", "build:\n\t@echo build\n")
        write(self.host, "src/main.py", "print('x')\n")
        write(self.host, "ARCHITECTURE.md", "# Human architecture\n")
        result = adopt(self.host)
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue((self.host / "docs/project/development.md").exists())
        self.assertTrue((self.host / "docs/project/modules/src.md").exists())
        architecture = (self.host / "docs/project/architecture.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("`ARCHITECTURE.md`", architecture)
        self.assertEqual(
            (self.host / "ARCHITECTURE.md").read_text(encoding="utf-8"),
            "# Human architecture\n",
        )
        modules = read_yaml(self.host / ".scaffold/modules.yaml")
        self.assertEqual(
            modules["modules"][0]["knowledge_entry"],
            "docs/project/modules/src.md",
        )

    def test_Z17_observed_tests_have_coherent_testing_entry(self):
        write(self.host, "tests/test_sample.py", "pass\n")
        adopt(self.host)
        tests = read_yaml(self.host / ".scaffold/tests.yaml")
        project = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertEqual(tests["applicability"], "APPLICABLE")
        self.assertEqual(project["knowledge"]["testing"], "present")
        self.assertTrue((self.host / "docs/project/testing.md").exists())

    def test_Z18_refresh_after_tests_appear_converges_all_knowledge(self):
        adopt(self.host)
        write(self.host, "tests/test_new.py", "pass\n")
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "COMPLETED")
        tests = read_yaml(self.host / ".scaffold/tests.yaml")
        project = read_yaml(self.host / ".scaffold/project.yaml")
        fact = next(value for value in project["facts"] if value["name"] == "test_tree")
        self.assertEqual(fact["confidence"], "VERIFIED")
        self.assertEqual(tests["confidence"], "VERIFIED")
        self.assertEqual(tests["applicability"], "APPLICABLE")
        self.assertEqual(project["knowledge"]["testing"], "present")
        self.assertTrue((self.host / "docs/project/testing.md").exists())

    def test_Z19_non_bridge_agents_is_deferred_and_blocks_activation(self):
        write(self.host, "AGENTS.md", "Do not use scaffold metadata.\n")
        result = adopt(self.host)
        self.assertEqual(result.outcome, "FAILED")
        agents_action = next(
            action
            for action in result.extras["plan"]["actions"]
            if action["target"] == "AGENTS.md"
        )
        self.assertEqual(agents_action["client_strategy"], "DEFER")
        self.assertNotEqual(agents_action["client_strategy"], "THIN_BRIDGE")
        self.assertEqual(read_yaml(self.host / ".scaffold/project.yaml")["lifecycle"], "ADOPTING")

    def test_Z20_genuine_existing_thin_bridge_can_be_preserved(self):
        content = (
            "# Existing bridge\n"
            "Read `.scaffold/project.yaml`, `docs/project/overview.md`, and "
            "`.scaffold/skills.lock`.\n"
        )
        write(self.host, "AGENTS.md", content)
        result = adopt(self.host)
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual((self.host / "AGENTS.md").read_text(encoding="utf-8"), content)
        clients = read_yaml(self.host / ".scaffold/project.yaml")["clients"]
        agents = next(value for value in clients if value["path"] == "AGENTS.md")
        self.assertEqual(agents["strategy"], "THIN_BRIDGE")

    def test_Z21_migration_resume_blocks_unexpected_lock_change(self):
        plan = self._migration_preview()
        approval = {
            "approved": True,
            "plan_id": plan["plan_id"],
            "plan_digest": plan["digest"],
        }
        interrupted = apply_fresh_migration(
            self.host,
            plan,
            interrupt_after="first_mutation",
        )
        self.assertEqual(interrupted.outcome, "BLOCKED")
        lock_path = self.host / ".scaffold/skills.lock"
        lock = read_yaml(lock_path)
        lock["skills"]["submit"]["skill_version"] = "2.0.1"
        write_yaml_atomic(lock_path, lock)
        resumed = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
            approval=approval,
        )
        self.assertEqual(resumed.outcome, "BLOCKED")
        self.assertTrue(any("skills.lock diverged" in value for value in resumed.blockers))

    def test_Z22_expected_migration_checkpoint_resumes(self):
        plan = self._migration_preview()
        approval = {
            "approved": True,
            "plan_id": plan["plan_id"],
            "plan_digest": plan["digest"],
        }
        apply_fresh_migration(
            self.host,
            plan,
            interrupt_after="first_mutation",
        )
        resumed = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
            approval=approval,
        )
        self.assertEqual(resumed.outcome, "COMPLETED")
        self.assertEqual(read_yaml(self.host / ".scaffold/project.yaml")["lifecycle"], "ACTIVE")

    def test_Z23_successful_migration_converges_to_compatible(self):
        plan = self._migration_preview()
        done = apply_fresh_migration(self.host, plan)
        self.assertEqual(done.outcome, "COMPLETED")
        result = engine(self.host, "2.1.0").run("compatibility")
        self.assertEqual(result.compatibility, "COMPATIBLE")
        project = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertNotIn("NEEDS_MIGRATION", project["maintenance"])

    def test_Z24_post_migration_lock_update_then_exact(self):
        plan = self._migration_preview()
        approval = {
            "approved": True,
            "plan_id": plan["plan_id"],
            "plan_digest": plan["digest"],
        }
        apply_fresh_migration(self.host, plan)
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
        self.assertEqual(preview.outcome, "NEEDS_HUMAN")
        self.assertFalse(preview.extras["lock_update_plan"]["migration_required"])
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

    def test_Z25_needs_migration_persistence_is_reported_as_mutation(self):
        adopt(self.host)
        first = engine(self.host, "2.1.0").run("compatibility")
        self.assertEqual(first.compatibility, "MIGRATION_REQUIRED")
        self.assertEqual(first.mutations, "bounded")
        self.assertEqual(first.artifacts, [".scaffold/project.yaml"])
        second = engine(self.host, "2.1.0").run("compatibility")
        self.assertEqual(second.mutations, "none")

    def _run_with_distribution(self, dist: Distribution, mode: str, **opts):
        from scaffold_p5.engine import UnderstandEngine

        return UnderstandEngine(self.host, dist).run(mode, **opts)


if __name__ == "__main__":
    unittest.main()

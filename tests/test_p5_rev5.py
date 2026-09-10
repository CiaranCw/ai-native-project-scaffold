from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import get_args

from support import FIXTURE_DIST, REPO, REPO_UNDERSTAND, adopt, apply_fresh_migration, engine, write
from scaffold_p5.adoption import validate_plan_content
from scaffold_p5.host_state import durable_inventory, snapshot_host
from scaffold_p5.io_util import read_text, read_yaml, write_yaml_atomic
from scaffold_p5.models import COMPAT_RESULTS, CORE_SKILLS, PreflightContext
from scaffold_p5.packages import load_package
from scaffold_p5.schemas import (
    CORE_MACHINE_ARTIFACTS,
    validate_project_data,
    whole_file_mutation_allowed,
)
from scaffold_p5 import yaml_lite


class P5Rev5Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write(self.host, "README.md", "# Ordinary project\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _append(self, rel: str, extra: str) -> Path:
        path = self.host / rel
        path.write_text(path.read_text(encoding="utf-8") + extra, encoding="utf-8")
        return path

    def _set_ownership(self, rel: str, mode: str) -> dict:
        project_path = self.host / ".scaffold/project.yaml"
        project = read_yaml(project_path)
        project["ownership"][rel] = mode
        write_yaml_atomic(project_path, project)
        return project

    def _lock_target(self, version: str = "2.1.0"):
        package = load_package(FIXTURE_DIST / f"packages/understand-{version}")
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

    def test_AD1_trailing_list_makes_project_malformed(self):
        adopt(self.host)
        path = self._append(".scaffold/project.yaml", "- trailing-junk\n")
        before = path.read_bytes()
        snap = snapshot_host(self.host)
        self.assertEqual(snap.project_view.status, "MALFORMED")
        self.assertFalse(snap.project_view.valid)
        result = engine(self.host).run("compatibility")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertIsNone(result.compatibility)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(engine(self.host).run("bootstrap").outcome, "BLOCKED")
        self.assertEqual(path.read_bytes(), before)

    def test_AD2_mapping_line_without_colon_is_malformed(self):
        with self.assertRaises(ValueError) as raised:
            yaml_lite.load("schema_version: \"1\"\nthis line has no colon\n")
        self.assertIn("delimiter", str(raised.exception))
        adopt(self.host)
        path = self._append(".scaffold/project.yaml", "this line has no colon\n")
        before = path.read_bytes()
        snap = snapshot_host(self.host)
        self.assertEqual(snap.project_view.status, "MALFORMED")
        self.assertFalse(snap.project_view.valid)
        self.assertEqual(engine(self.host).run("compatibility").outcome, "BLOCKED")
        self.assertEqual(path.read_bytes(), before)

    def test_AD3_duplicate_mapping_key_is_rejected(self):
        with self.assertRaises(ValueError) as raised:
            yaml_lite.load(
                "schema_version: \"1\"\nlifecycle: ACTIVE\nschema_version: \"1\"\n"
            )
        self.assertIn("duplicate", str(raised.exception))
        adopt(self.host)
        path = self.host / ".scaffold/project.yaml"
        text = path.read_text(encoding="utf-8")
        path.write_text(text + "lifecycle: ACTIVE\n", encoding="utf-8")
        snap = snapshot_host(self.host)
        self.assertEqual(snap.project_view.status, "MALFORMED")

    def test_AD4_canonical_dump_load_roundtrip(self):
        sample = {
            "schema_version": "1",
            "nested": {"list": [{"name": "a", "ok": True}, {"name": "b", "ok": False}]},
            "empty_map": {},
            "empty_list": [],
            "count": 2,
            "missing": None,
            "flag": True,
        }
        self.assertEqual(yaml_lite.load(yaml_lite.dump(sample)), sample)
        adopt(self.host)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertEqual(
            yaml_lite.load(yaml_lite.dump(project)),
            project,
        )

    def test_AD5_trailing_plan_content_blocks_resume(self):
        preview = engine(self.host).run("bootstrap")
        plan = preview.extras["plan"]
        interrupted = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
            interrupt_after="project_yaml",
        )
        self.assertEqual(interrupted.outcome, "BLOCKED")
        plan_path = next(
            (self.host / ".scaffold/runtime/adoption-sessions").glob("*/plan.yaml")
        )
        self._append(
            str(plan_path.relative_to(self.host)).replace("\\", "/"),
            "- trailing-junk\n",
        )
        snap = snapshot_host(self.host)
        self.assertEqual(
            snap.adoption_recovery["entries"][0]["classification"],
            "MALFORMED_PLAN",
        )
        self.assertEqual(snap.adoption_recovery["resumable"], [])
        result = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertNotEqual(
            read_yaml(self.host / ".scaffold/project.yaml").get("lifecycle"),
            "ACTIVE",
        )

    def test_AD6_trailing_session_content_blocks_recovery(self):
        preview = engine(self.host).run("bootstrap")
        plan = preview.extras["plan"]
        engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
            interrupt_after="project_yaml",
        )
        session_path = next(
            (self.host / ".scaffold/runtime/adoption-sessions").glob("*/session.yaml")
        )
        self._append(
            str(session_path.relative_to(self.host)).replace("\\", "/"),
            "- trailing-junk\n",
        )
        snap = snapshot_host(self.host)
        self.assertEqual(
            snap.adoption_recovery["entries"][0]["classification"],
            "MALFORMED_SESSION",
        )
        self.assertEqual(engine(self.host).run("bootstrap").outcome, "BLOCKED")

    def test_AD7_trailing_migration_content_fails_closed(self):
        adopt(self.host)
        preview = engine(self.host, "2.1.0").run("compatibility", action="migrate")
        plan = preview.extras["migration_plan"]
        interrupted = apply_fresh_migration(
            self.host,
            plan,
            interrupt_after="first_mutation",
        )
        self.assertEqual(interrupted.outcome, "BLOCKED")
        exec_path = next(
            (self.host / ".scaffold/runtime/migration-executions").glob(
                "*/execution.yaml"
            )
        )
        self._append(
            str(exec_path.relative_to(self.host)).replace("\\", "/"),
            "- trailing-junk\n",
        )
        before = (self.host / ".scaffold/project.yaml").read_bytes()
        snap = snapshot_host(self.host)
        self.assertTrue(snap.migration_recovery["requires_isolation"])
        self.assertNotEqual(
            snap.migration_recovery["classification"],
            "ONE_VALID_UNRESOLVED",
        )
        result = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
            approval=self._migration_approval(plan),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual((self.host / ".scaffold/project.yaml").read_bytes(), before)

    def test_AD8_trailing_skill_yaml_is_invalid(self):
        package_dir = Path(self._tmp.name) / "pkg"
        package_dir.mkdir()
        write(
            package_dir,
            "skill.yaml",
            read_text(REPO_UNDERSTAND / "skill.yaml") + "- trailing-junk\n",
        )
        write(package_dir, "SKILL.md", read_text(REPO_UNDERSTAND / "SKILL.md"))
        loaded = load_package(package_dir)
        self.assertEqual(loaded.validity, "INVALID")
        self.assertTrue(
            any("malformed" in reason.lower() for reason in loaded.validity_reasons)
        )

    def test_AD9_current_release_fixtures_remain_valid(self):
        release = yaml_lite.load(
            read_text(FIXTURE_DIST / "releases/rel-r1.yaml")
        )
        self.assertEqual(release["release_id"], "rel-r1")
        self.assertEqual(load_package(REPO_UNDERSTAND).validity, "VALID")
        for name in (
            "understand-2.0.1",
            "understand-2.1.0",
            "understand-2.1.1",
            "understand-2.2.0",
            "understand-3.0.0",
            "develop-2.0.0",
            "test-2.0.0",
            "submit-2.0.0",
        ):
            loaded = load_package(FIXTURE_DIST / "packages" / name)
            self.assertEqual(loaded.validity, "VALID", name)

    def test_AD10_human_owned_project_blocks_maintenance_write(self):
        adopt(self.host)
        path = self.host / ".scaffold/project.yaml"
        self._set_ownership(".scaffold/project.yaml", "HUMAN_OWNED")
        before = path.read_bytes()
        snap = snapshot_host(self.host)
        self.assertFalse(snap.project_view.valid)
        self.assertTrue(
            any("HUMAN_OWNED" in reason for reason in snap.project_view.reasons)
        )
        result = engine(self.host, "2.1.0").run("compatibility")
        self.assertIn(result.outcome, {"BLOCKED", "NEEDS_HUMAN"})
        self.assertEqual(result.mutations, "none")
        self.assertEqual(path.read_bytes(), before)

    def test_AD11_managed_project_blocks_needs_migration_persist(self):
        adopt(self.host)
        path = self.host / ".scaffold/project.yaml"
        self._set_ownership(".scaffold/project.yaml", "MANAGED")
        before = path.read_bytes()
        snap = snapshot_host(self.host)
        self.assertTrue(snap.project_view.valid)
        result = engine(self.host, "2.1.0").run("compatibility")
        self.assertEqual(result.compatibility, "MIGRATION_REQUIRED")
        self.assertIn(result.outcome, {"BLOCKED", "NEEDS_HUMAN"})
        self.assertEqual(result.mutations, "none")
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn(
            "NEEDS_MIGRATION",
            read_yaml(path).get("maintenance") or [],
        )

    def test_AD12_human_owned_project_blocks_migration_write(self):
        adopt(self.host)
        path = self.host / ".scaffold/project.yaml"
        self._set_ownership(".scaffold/project.yaml", "HUMAN_OWNED")
        before = path.read_bytes()
        preview = engine(self.host, "2.1.0").run("compatibility", action="migrate")
        result = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
            approval=self._migration_approval(
                preview.extras.get("migration_plan") or {"plan_id": "x", "digest": "y"}
            ),
        )
        self.assertNotEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.mutations, "none")
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(
            (self.host / ".scaffold/runtime/migration-executions").exists()
            and any((self.host / ".scaffold/runtime/migration-executions").iterdir())
        )

    def test_AD13_managed_project_blocks_migration_whole_file(self):
        adopt(self.host)
        path = self.host / ".scaffold/project.yaml"
        self._set_ownership(".scaffold/project.yaml", "MANAGED")
        before = path.read_bytes()
        preview = engine(self.host, "2.1.0").run("compatibility", action="migrate")
        plan = preview.extras["migration_plan"]
        result = engine(self.host, "2.1.0").run(
            "compatibility",
            action="migrate",
            approval=self._migration_approval(plan),
        )
        self.assertIn(result.outcome, {"BLOCKED", "NEEDS_HUMAN"})
        self.assertEqual(result.mutations, "none")
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(
            any((self.host / ".scaffold/runtime/migration-executions").rglob("*"))
            if (self.host / ".scaffold/runtime/migration-executions").exists()
            else False
        )

    def test_AD14_human_owned_lock_update_is_blocked(self):
        adopt(self.host)
        lock = self.host / ".scaffold/skills.lock"
        self._set_ownership(".scaffold/skills.lock", "HUMAN_OWNED")
        before = lock.read_bytes()
        target = self._lock_target("2.0.1")
        preview = engine(self.host).run(
            "compatibility",
            action="lock_update",
            new_expected=target,
        )
        result = engine(self.host).run(
            "compatibility",
            action="lock_update",
            new_expected=target,
            approval={
                "approved": True,
                "plan_digest": (preview.extras.get("lock_update_plan") or {}).get(
                    "digest"
                ),
            },
        )
        self.assertIn(result.outcome, {"BLOCKED", "NEEDS_HUMAN"})
        self.assertEqual(lock.read_bytes(), before)

    def test_AD15_managed_lock_update_is_blocked(self):
        adopt(self.host)
        lock = self.host / ".scaffold/skills.lock"
        self._set_ownership(".scaffold/skills.lock", "MANAGED")
        before = lock.read_bytes()
        target = self._lock_target("2.0.1")
        preview = engine(self.host).run(
            "compatibility",
            action="lock_update",
            new_expected=target,
        )
        plan = preview.extras["lock_update_plan"]
        self.assertFalse(plan["valid"])
        result = engine(self.host).run(
            "compatibility",
            action="lock_update",
            new_expected=target,
            approval={"approved": True, "plan_digest": plan["digest"]},
        )
        self.assertIn(result.outcome, {"BLOCKED", "NEEDS_HUMAN"})
        self.assertEqual(lock.read_bytes(), before)

    def test_AD16_missing_core_ownership_is_non_executable(self):
        adopt(self.host)
        project_path = self.host / ".scaffold/project.yaml"
        project = read_yaml(project_path)
        project["ownership"].pop(".scaffold/skills.lock")
        write_yaml_atomic(project_path, project)
        snap = snapshot_host(self.host)
        self.assertEqual(snap.project_view.status, "INCOMPLETE")
        self.assertTrue(
            any("skills.lock" in reason for reason in snap.project_view.reasons)
        )
        result = engine(self.host).run("compatibility")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(snap.project_view.valid)

    def test_AD17_human_owned_machine_indexes_are_rejected(self):
        adopt(self.host)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        for name in ("modules", "commands", "tests"):
            project["ownership"][f".scaffold/{name}.yaml"] = "HUMAN_OWNED"
            write(self.host, f".scaffold/{name}.yaml", f"- human-{name}\n")
        status, reasons = validate_project_data(project)
        self.assertEqual(status, "INCOMPLETE")
        self.assertTrue(any("modules.yaml" in reason for reason in reasons))
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        before = {
            name: (self.host / f".scaffold/{name}.yaml").read_bytes()
            for name in ("modules", "commands", "tests")
        }
        result = engine(self.host).run("refresh")
        self.assertIn(result.outcome, {"NEEDS_HUMAN", "BLOCKED"})
        for name, payload in before.items():
            self.assertEqual(
                (self.host / f".scaffold/{name}.yaml").read_bytes(),
                payload,
            )

    def test_AD18_human_owned_agents_remains_valid(self):
        content = (
            "# Existing bridge\n"
            "Read `.scaffold/project.yaml`, `docs/project/overview.md`, and "
            "`.scaffold/skills.lock`.\n"
        )
        write(self.host, "AGENTS.md", content)
        self.assertEqual(adopt(self.host).outcome, "COMPLETED")
        ownership = read_yaml(self.host / ".scaffold/project.yaml")["ownership"]
        self.assertEqual(ownership["AGENTS.md"], "HUMAN_OWNED")
        snap = snapshot_host(self.host)
        self.assertTrue(snap.project_view.valid)
        self.assertEqual((self.host / "AGENTS.md").read_text(encoding="utf-8"), content)
        self.assertEqual(engine(self.host).run("compatibility").compatibility, "EXACT")

    def test_AD19_human_owned_architecture_is_preserved(self):
        write(self.host, "docs/project/architecture.md", "# Human architecture\n")
        adopt(self.host)
        path = self.host / "docs/project/architecture.md"
        before = path.read_bytes()
        ownership = read_yaml(self.host / ".scaffold/project.yaml")["ownership"]
        self.assertEqual(ownership["docs/project/architecture.md"], "HUMAN_OWNED")
        result = engine(self.host).run("refresh")
        self.assertIn(result.outcome, {"COMPLETED", "NEEDS_HUMAN"})
        self.assertEqual(path.read_bytes(), before)

    def test_AD20_generated_exact_compatibility_still_works(self):
        self.assertEqual(adopt(self.host).outcome, "COMPLETED")
        result = engine(self.host).run("compatibility")
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.compatibility, "EXACT")
        ownership = read_yaml(self.host / ".scaffold/project.yaml")["ownership"]
        for path in CORE_MACHINE_ARTIFACTS:
            self.assertEqual(ownership[path], "GENERATED", path)

    def test_AD21_generated_migration_then_lock_update_still_works(self):
        adopt(self.host)
        preview = engine(self.host, "2.1.0").run("compatibility", action="migrate")
        plan = preview.extras["migration_plan"]
        migrated = apply_fresh_migration(self.host, plan)
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
            approval={"approved": True, "plan_digest": update_plan["digest"]},
        )
        self.assertEqual(updated.outcome, "COMPLETED")
        self.assertEqual(
            engine(self.host, "2.1.0").run("compatibility").compatibility,
            "EXACT",
        )

    def test_AD22_generated_refresh_repairs_machine_index(self):
        adopt(self.host)
        write(self.host, ".scaffold/modules.yaml", "- not-a-map\n")
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "COMPLETED")
        modules = read_yaml(self.host / ".scaffold/modules.yaml")
        self.assertEqual(modules["schema_version"], "1")
        self.assertIsInstance(modules["modules"], list)

    def test_AD23_adoption_crash_recovery_remains(self):
        preview = engine(self.host).run("bootstrap")
        plan = preview.extras["plan"]
        interrupted = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
            interrupt_after="project_yaml",
        )
        self.assertEqual(interrupted.outcome, "BLOCKED")
        resumed = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
        )
        self.assertEqual(resumed.outcome, "COMPLETED")
        self.assertEqual(
            read_yaml(self.host / ".scaffold/project.yaml")["lifecycle"],
            "ACTIVE",
        )

    def test_AD24_orphan_recovery_isolation_remains(self):
        orphan = self.host / ".scaffold/runtime/adoption-sessions/a1"
        orphan.mkdir(parents=True)
        before = durable_inventory(self.host)
        result = engine(self.host).run("bootstrap")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(before, durable_inventory(self.host))
        self.assertFalse((self.host / ".scaffold/project.yaml").exists())

    def test_rev5_empty_mapping_key_is_rejected(self):
        with self.assertRaises(ValueError):
            yaml_lite.load(": value\n")

    def test_rev5_valid_plan_still_validates(self):
        preview = engine(self.host).run("bootstrap")
        issues = validate_plan_content(preview.extras["plan"])
        self.assertEqual(issues, [])

    def test_rev5_mutation_authority_matrix(self):
        ownership = {path: "GENERATED" for path in CORE_MACHINE_ARTIFACTS}
        allowed, _ = whole_file_mutation_allowed(
            ownership, ".scaffold/project.yaml"
        )
        self.assertTrue(allowed)
        ownership[".scaffold/project.yaml"] = "HUMAN_OWNED"
        allowed, reason = whole_file_mutation_allowed(
            ownership, ".scaffold/project.yaml"
        )
        self.assertFalse(allowed)
        self.assertIn("HUMAN_OWNED", reason)
        ownership[".scaffold/skills.lock"] = "MANAGED"
        allowed, reason = whole_file_mutation_allowed(
            ownership, ".scaffold/skills.lock"
        )
        self.assertFalse(allowed)
        self.assertIn("bounded managed region", reason)
        allowed, reason = whole_file_mutation_allowed({}, ".scaffold/modules.yaml")
        self.assertFalse(allowed)
        self.assertIn("missing ownership", reason)

    def test_rev5_taxonomies_remain(self):
        self.assertEqual(
            set(get_args(PreflightContext)),
            {"PRE_ADOPTION_BOOTSTRAP", "HOST_COMPATIBILITY"},
        )
        self.assertEqual(len(COMPAT_RESULTS), 5)
        self.assertEqual(CORE_SKILLS, ("understand", "develop", "test", "submit"))
        self.assertTrue((REPO / "src/scaffold_p6").is_dir())
        self.assertTrue((REPO / "skills/test").is_dir())
        self.assertTrue((REPO / "src/scaffold_p7").is_dir())
        self.assertTrue((REPO / "src/scaffold_p8").is_dir())

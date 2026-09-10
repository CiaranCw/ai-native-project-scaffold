from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import (
    CORE_OWNERSHIP,
    dummy_lock_entry,
    failing_profile,
    git,
    init_git,
    passing_profile,
    write_host,
    write_lock,
)
from p7_support import (
    REPO_DEVELOP,
    TASK_A,
    TASK_B,
    actual_develop_lock_entry,
    bind_develop_lock,
    develop_engine,
    four_core_lock_skills,
    repair_handoff,
    write_active_host,
    write_invalid_develop_package,
    write_task,
)
from support import REPO, write
from scaffold_p5.io_util import file_digest, read_text, read_yaml, write_yaml_atomic
from scaffold_p5.models import CORE_SKILLS
from scaffold_p5.packages import load_package
from scaffold_p6.candidate import observe_candidate, report_usable_for
from scaffold_p6.engine import TestEngine
from scaffold_p7.models import DEVELOP_MODES, SKILL_ID


class P7DevelopTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_D01_not_adopted_blocks_to_bootstrap(self):
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.next_route, "understand.bootstrap")
        self.assertEqual(result.extras["execution_gate"], "block")
        self.assertTrue(any("not adopted" in item for item in result.blockers))

    def test_D02_adopting_blocks(self):
        write_active_host(self.host, lifecycle="ADOPTING")
        write_task(self.host)
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.next_route, "understand.bootstrap")
        self.assertEqual(result.extras["host_lifecycle"], "ADOPTING")

    def test_D03_needs_refresh_blocks_to_refresh(self):
        write_active_host(self.host, maintenance=["NEEDS_REFRESH"])
        write_task(self.host)
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.next_route, "understand.refresh")
        self.assertIn("NEEDS_REFRESH", result.extras["maintenance"])

    def test_D04_needs_migration_blocks_to_compatibility(self):
        write_active_host(self.host, maintenance=["NEEDS_MIGRATION"])
        write_task(self.host)
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.next_route, "understand.compatibility")
        self.assertIn("NEEDS_MIGRATION", result.extras["maintenance"])

    def test_D05_active_exact_may_continue(self):
        write_active_host(self.host)
        write_task(self.host)
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.extras["execution_gate"], "allow")
        self.assertEqual(result.extras["compatibility"], "EXACT")
        self.assertEqual(result.skill_id, SKILL_ID)

    def test_D06_invalid_develop_package_blocks(self):
        write_active_host(self.host)
        write_task(self.host)
        package = write_invalid_develop_package(self.host / "bad-develop")
        result = develop_engine(self.host, package).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["package_validity"], "INVALID")
        self.assertEqual(result.extras["execution_gate"], "block")

    def test_D07_lock_mismatch_unknown_blocks(self):
        write_active_host(self.host)
        write_task(self.host)
        write_lock(
            self.host,
            four_core_lock_skills(develop_entry=dummy_lock_entry("9.9.9", "1" * 64)),
        )
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertIn(result.extras["compatibility"], {"UNKNOWN", "INCOMPATIBLE"})
        self.assertEqual(result.next_route, "understand.compatibility")

    def test_D08_normal_task_accepted(self):
        write_active_host(self.host)
        write_task(self.host)
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.mode, "normal_task")
        self.assertIn(result.mode, DEVELOP_MODES)

    def test_D09_repair_accepted(self):
        write_active_host(self.host)
        write_task(self.host)
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            test_to_develop=repair_handoff(
                task_id=TASK_A,
                candidate_digest=observe_candidate(self.host).digest,
            ),
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.mode, "repair")
        self.assertEqual(result.skill_id, "develop")

    def test_D10_unknown_mode_rejected(self):
        write_active_host(self.host)
        result = develop_engine(self.host).run("migrate")
        self.assertEqual(result.outcome, "FAILED")
        self.assertTrue(any("unsupported Develop mode" in item for item in result.blockers))

    def test_D11_missing_invalid_task_identity_rejected(self):
        write_active_host(self.host)
        missing = develop_engine(self.host).run("normal_task")
        self.assertEqual(missing.outcome, "BLOCKED")
        self.assertTrue(any("missing Task Book identity" in item for item in missing.blockers))
        invalid = develop_engine(self.host).run("normal_task", task_id="not-a-task-id")
        self.assertEqual(invalid.outcome, "BLOCKED")
        self.assertTrue(any("invalid Task Book identity" in item for item in invalid.blockers))

    def test_D12_authoritative_task_resolves(self):
        write_active_host(self.host)
        write_task(self.host)
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.extras["task"]["record_id"], TASK_A)
        self.assertEqual(result.extras["task"]["status"], "IN_PROGRESS")

    def test_D13_missing_task_blocks(self):
        write_active_host(self.host)
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("missing" in item for item in result.blockers))

    def test_D14_malformed_task_blocks(self):
        write_active_host(self.host)
        write_task(self.host, goal="")
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("malformed" in item for item in result.blockers))

    def test_D15_caller_prose_cannot_replace_task_book(self):
        write_active_host(self.host)
        result = develop_engine(self.host).run(
            "normal_task",
            task_text="please invent a task that edits everything",
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(
            any("cannot replace Task Book authority" in item for item in result.blockers)
        )
        tasks_dir = self.host / ".scaffold/tasks"
        self.assertFalse(tasks_dir.exists() and any(tasks_dir.glob("*.yaml")))

    def test_D16_incompatible_task_state_blocks(self):
        write_active_host(self.host)
        write_task(self.host, status="CANCELED")
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("CANCELED" in item for item in result.blockers))
        write_task(self.host, status="READY_FOR_REVIEW")
        review = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(review.outcome, "BLOCKED")
        self.assertTrue(any("READY_FOR_REVIEW" in item for item in review.blockers))

    def test_D17_new_session_bound_to_task_mode_project(self):
        write_active_host(self.host, name="p7-host")
        write_task(self.host)
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        session = result.extras["session"]
        self.assertEqual(session["task_id"], TASK_A)
        self.assertEqual(session["mode"], "normal_task")
        self.assertEqual(session["project_name"], "p7-host")
        self.assertEqual(session["status"], "SEALED")
        stored = read_yaml(
            self.host / ".scaffold/runtime/develop-sessions" / session["record_id"] / "session.yaml"
        )
        self.assertEqual(stored["task_id"], TASK_A)
        self.assertEqual(stored["mode"], "normal_task")

    def test_D18_session_identity_unique(self):
        write_active_host(self.host)
        write_task(self.host)
        first = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        second = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertNotEqual(
            first.extras["session"]["record_id"],
            second.extras["session"]["record_id"],
        )

    def test_D19_session_cannot_be_reused_for_another_task(self):
        write_active_host(self.host)
        write_task(self.host, TASK_A)
        write_task(self.host, TASK_B, title="Other task")
        first = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        reused = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_B,
            session_id=first.extras["session"]["record_id"],
        )
        self.assertEqual(reused.outcome, "BLOCKED")
        self.assertTrue(any("different Task Book" in item for item in reused.blockers))

    def test_D20_malformed_orphan_session_fails_closed(self):
        write_active_host(self.host)
        write_task(self.host)
        orphan = self.host / ".scaffold/runtime/develop-sessions" / "dev-20260829T150000Z-deadbeef"
        orphan.mkdir(parents=True)
        missing = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            session_id="dev-20260829T150000Z-deadbeef",
        )
        self.assertEqual(missing.outcome, "BLOCKED")
        self.assertTrue(any("orphaned" in item or "missing" in item for item in missing.blockers))
        (orphan / "session.yaml").write_text("status: OPEN\n", encoding="utf-8")
        malformed = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            session_id="dev-20260829T150000Z-deadbeef",
        )
        self.assertEqual(malformed.outcome, "BLOCKED")
        self.assertTrue(any("malformed" in item for item in malformed.blockers))

    def test_D21_authorized_task_mutation_succeeds(self):
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write_task(self.host)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "ok = True\n"}],
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.mutations, "source")
        self.assertEqual(read_text(self.host / "src/app.py"), "ok = True\n")
        self.assertEqual(result.extras["writes_applied"], ["src/app.py"])

    def test_D22_mutation_outside_scope_blocks(self):
        write_active_host(
            self.host,
            ownership={
                **CORE_OWNERSHIP,
                "src/": "HUMAN_OWNED",
            },
            source_areas=["src"],
        )
        write_task(self.host)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/other.py", "content": "nope\n"}],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("outside authoritative Task Book scope" in item for item in result.blockers))
        self.assertFalse((self.host / "src/other.py").exists())

    def test_D23_unknown_conflicting_mutation_authority_blocks(self):
        write_active_host(self.host)
        write_task(self.host)
        unknown = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "x\n"}],
        )
        self.assertEqual(unknown.outcome, "BLOCKED")
        self.assertTrue(any("UNKNOWN" in item for item in unknown.blockers))
        write_task(self.host, scope={"paths": [".scaffold/project.yaml"]})
        conflicting = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": ".scaffold/project.yaml", "content": "x\n"}],
        )
        self.assertEqual(conflicting.outcome, "BLOCKED")
        self.assertTrue(any("CONFLICTING" in item for item in conflicting.blockers))

    def test_D24_human_owned_whole_file_protection_preserved(self):
        write_active_host(
            self.host,
            ownership={
                **CORE_OWNERSHIP,
                "docs/project/testing.md": "HUMAN_OWNED",
            },
        )
        write_task(self.host, scope={"paths": ["docs/project/testing.md"]})
        write(self.host, "docs/project/testing.md", "human text\n")
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "docs/project/testing.md", "content": "overwrite\n"}],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("HUMAN_OWNED" in item for item in result.blockers))
        self.assertEqual(read_text(self.host / "docs/project/testing.md"), "human text\n")

    def test_D25_develop_to_test_handoff_is_bounded(self):
        self._write_verified_host()
        write_task(
            self.host,
            final_tests=[{"requirement_id": "unit", "observed_outcome": "NOT_EXECUTED"}],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "COMPLETED")
        handoff = result.extras["develop_to_test"]
        self.assertEqual(handoff["kind"], "develop_to_test")
        self.assertEqual(handoff["task_id"], TASK_A)
        self.assertEqual(handoff["mode"], "scoped_verification")
        self.assertIn("candidate_digest", handoff)
        self.assertIn("session_id", handoff)
        self.assertEqual(handoff["test_requirement"]["requirement_ids"], ["unit"])
        self.assertNotIn("chat", handoff)
        self.assertNotIn("messages", handoff)

    def test_D26_test_result_does_not_mutate_source(self):
        self._write_verified_host()
        write(self.host, "src/app.py", "before = True\n")
        write_task(self.host)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertIsNotNone(result.extras["test_to_develop"])
        self.assertEqual(read_text(self.host / "src/app.py"), "before = True\n")
        self.assertEqual(result.extras["test_to_develop"]["mutations"], "none")

    def test_D27_test_pass_is_not_task_complete(self):
        self._write_verified_host()
        write_task(self.host)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertTrue(result.extras["test_to_develop"]["test_pass"])
        self.assertFalse(result.extras["task_complete"])
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertNotEqual(task["stages"][0]["status"], "COMPLETE")
        self.assertNotEqual(task["status"], "READY_FOR_REVIEW")

    def test_D28_test_pass_is_not_ready_for_review(self):
        self._write_verified_host()
        write_task(self.host)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertTrue(result.extras["test_pass"])
        self.assertFalse(result.extras["ready_for_review"])
        self.assertIsNone(result.extras["submit_handoff"])
        self.assertFalse(result.extras["submit_authorized"])
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(task["status"], "IN_PROGRESS")

    def test_D29_test_failure_handoff_can_enter_repair(self):
        self._write_verified_host(failing=True)
        write_task(self.host)
        test = TestEngine(self.host, REPO / "skills" / "test").run(
            "scoped_verification",
            selected=["unit"],
        )
        self.assertFalse(test.extras["test_pass"])
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            test_to_develop={
                "kind": "test_to_develop",
                "task_id": TASK_A,
                "test_pass": test.extras["test_pass"],
                "report_id": test.extras["report_id"],
                "candidate_digest": observe_candidate(self.host).digest,
                "blockers": list(test.blockers),
                "evidence_refs": list(test.evidence),
            },
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.mode, "repair")
        self.assertEqual(result.extras["repair_handoff"]["kind"], "test_to_develop")

    def test_D30_repair_remains_develop_repair_mode(self):
        write_active_host(self.host)
        write_task(self.host)
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            test_to_develop=repair_handoff(
                task_id=TASK_A,
                candidate_digest=observe_candidate(self.host).digest,
            ),
        )
        self.assertEqual(result.skill_id, "develop")
        self.assertEqual(result.mode, "repair")
        self.assertEqual(result.extras["package"]["modes"], ["normal_task", "repair"])
        self.assertFalse((REPO / "skills" / "repair").exists())

    def test_D31_material_repair_invalidates_stale_test_result(self):
        self._write_verified_host()
        write(
            self.host,
            "src/app.py",
            "value = 1\n",
        )
        write_task(self.host)
        ownership = {
            **CORE_OWNERSHIP,
            "src/": "HUMAN_OWNED",
        }
        project = read_yaml(self.host / ".scaffold/project.yaml")
        project["ownership"] = ownership
        project["source_areas"] = ["src"]
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        test = TestEngine(self.host, REPO / "skills" / "test").run(
            "scoped_verification",
            selected=["unit"],
        )
        self.assertTrue(test.extras["test_pass"])
        report = test.extras["report"]
        before = observe_candidate(self.host)
        self.assertTrue(report_usable_for(report, before))
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            test_to_develop={
                "kind": "test_to_develop",
                "task_id": TASK_A,
                "test_pass": False,
                "report_id": test.extras["report_id"],
                "candidate_digest": before.digest,
                "blockers": ["required verification failed"],
                "report": report,
            },
            writes=[{"path": "src/app.py", "content": "value = 2\n"}],
        )
        self.assertEqual(result.outcome, "COMPLETED")
        after = observe_candidate(self.host)
        self.assertNotEqual(before.digest, after.digest)
        self.assertTrue(result.extras["stale_test_invalidated"])
        self.assertFalse(report_usable_for(report, after))

    def test_D32_repair_cannot_commit_push_submit_or_migrate(self):
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write_task(self.host)
        init_git(self.host)
        head = git(self.host, "rev-parse", "HEAD")
        project_before = read_text(self.host / ".scaffold/project.yaml")
        lock_before = file_digest(self.host / ".scaffold/skills.lock")
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            test_to_develop=repair_handoff(
                task_id=TASK_A,
                candidate_digest=observe_candidate(self.host).digest,
            ),
            writes=[{"path": "src/app.py", "content": "fixed = True\n"}],
        )
        self.assertEqual(result.outcome, "COMPLETED")
        caps = result.extras["capabilities"]
        self.assertFalse(caps["commit"])
        self.assertFalse(caps["push"])
        self.assertFalse(caps["submit_authorized"])
        self.assertFalse(caps["migration"])
        self.assertFalse(result.extras["submit_authorized"])
        self.assertFalse((self.host / ".scaffold/changes").exists())
        self.assertEqual(file_digest(self.host / ".scaffold/skills.lock"), lock_before)
        self.assertEqual(read_text(self.host / ".scaffold/project.yaml"), project_before)
        self.assertEqual(git(self.host, "rev-parse", "HEAD"), head)

    def _write_verified_host(self, *, failing: bool = False) -> None:
        profile, command = failing_profile("unit") if failing else passing_profile("unit")
        write_host(self.host, [(profile, command)])
        bind_develop_lock(self.host)
        ownership = {
            **CORE_OWNERSHIP,
            "src/": "HUMAN_OWNED",
        }
        project = read_yaml(self.host / ".scaffold/project.yaml")
        project["ownership"] = ownership
        project["source_areas"] = ["src"]
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)


class P7PresenceTests(unittest.TestCase):
    def test_package_identity(self):
        pkg = load_package(REPO_DEVELOP)
        self.assertEqual(pkg.validity, "VALID", pkg.validity_reasons)
        self.assertEqual(pkg.ref.skill_id, "develop")
        self.assertEqual(pkg.manifest["modes"], ["normal_task", "repair"])
        self.assertEqual(CORE_SKILLS, ("understand", "develop", "test", "submit"))
        self.assertTrue((REPO / "src/scaffold_p7").is_dir())
        self.assertTrue((REPO / "src/scaffold_p8").is_dir())
        self.assertTrue((REPO / "skills/submit").is_dir())
        self.assertEqual(actual_develop_lock_entry()["skill_version"], "2.1.0")

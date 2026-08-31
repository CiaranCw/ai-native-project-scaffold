from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import (
    CORE_OWNERSHIP,
    failing_profile,
    git,
    passing_profile,
    write_host,
    write_tests,
)
from p7_support import TASK_A, write_task
from p8_support import (
    REPO_SUBMIT,
    bind_submit_lock,
    init_submit_git,
    submit_engine,
    write_ready_task,
    write_submit_host,
)
from support import REPO, write
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p5.models import CORE_SKILLS
from scaffold_p5.packages import load_package
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.engine import TestEngine
from scaffold_p7.models import SESSIONS_DIR
from scaffold_p8.models import CHANGES_DIR, FINALIZATIONS_DIR, PROVIDES, REQUIRES, SKILL_ID
from scaffold_p8.schemas import validate_change_record


class P8SubmitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_S01_ready_for_review_task_accepted(self):
        write_submit_host(self.host)
        result = submit_engine(self.host).run(task_id=TASK_A)
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.extras["task"]["status"], "READY_FOR_REVIEW")
        self.assertEqual(result.extras["stages"], [f"S{i}" for i in range(1, 13)])

    def test_S02_in_progress_task_rejected(self):
        write_submit_host(self.host)
        write_task(self.host, TASK_A, status="IN_PROGRESS")
        result = submit_engine(self.host).run(task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("IN_PROGRESS" in item for item in result.blockers))

    def test_S03_missing_task_rejected(self):
        write_submit_host(self.host)
        (self.host / ".scaffold/tasks" / f"{TASK_A}.yaml").unlink()
        result = submit_engine(self.host).run(task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("missing" in item for item in result.blockers))

    def test_S04_malformed_task_rejected(self):
        write_submit_host(self.host)
        write_task(self.host, TASK_A, status="READY_FOR_REVIEW", scope={"paths": {"src/app.py": False}})
        result = submit_engine(self.host).run(task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("malformed" in item for item in result.blockers))

    def test_S05_invalid_host_blocked(self):
        result = submit_engine(self.host).run(task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.next_route, "understand.bootstrap")

    def test_S06_maintenance_compatibility_routed(self):
        write_submit_host(self.host, maintenance=["NEEDS_MIGRATION"])
        result = submit_engine(self.host).run(task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.next_route, "understand.compatibility")

    def test_S07_workspace_diff_wins_over_session_memory(self):
        write_submit_host(self.host)
        self._write_sealed_session(["src/remembered.py"])
        result = submit_engine(self.host).run(task_id=TASK_A)
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue(result.extras["delta"]["session_memory_overridden"])
        self.assertNotIn("src/remembered.py", result.extras["delta"]["paths"])

    def test_S08_incomplete_attribution_keeps_real_diff(self):
        write_submit_host(self.host)
        result = submit_engine(self.host).run(task_id=TASK_A)
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertIn("src/app.py", result.extras["delta"]["paths"])
        self.assertFalse(result.extras["delta"]["attribution_complete"])
        self.assertEqual(result.extras["delta"]["classes"]["src/app.py"], "UNATTRIBUTED")

    def test_S09_structural_blocker_prevents_progression(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        lock = read_yaml(self.host / ".scaffold/skills.lock")
        lock["authoritative"] = lock.get("authoritative", True)
        lock["schema_version"] = "1"
        write_yaml_atomic(self.host / ".scaffold/skills.lock", {**lock, "tampered": True})
        result = submit_engine(self.host).run(task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S3")
        self.assertFalse(result.extras["structural"]["structural_review_pass"])

    def test_S10_repair_requirement_emits_develop_handoff(self):
        write_submit_host(self.host)
        (self.host / "src/app.py").unlink()
        result = submit_engine(self.host).run(task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.next_route, "develop.repair")
        handoff = result.extras["repair_handoff"]
        self.assertEqual(handoff["kind"], "submit_to_develop")
        self.assertEqual(handoff["task_id"], TASK_A)
        self.assertFalse(handoff["submit_authorized"])
        self.assertFalse(handoff["capabilities"]["commit"])

    def test_S11_stale_knowledge_requires_understand(self):
        write_submit_host(self.host, maintenance=["NEEDS_REFRESH"])
        result = submit_engine(self.host).run(task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.next_route, "understand.refresh")
        self.assertEqual(result.extras["stage"], "S4")

    def test_S12_non_material_knowledge_check_continues(self):
        write_submit_host(self.host, maintenance=[])
        result = submit_engine(self.host).run(task_id=TASK_A)
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue(result.extras["knowledge"]["knowledge_consistent"])

    def test_S13_material_refresh_invalidates_prior_review(self):
        write_submit_host(self.host)

        def mutate():
            write(self.host, "README.md", "# refreshed\n")

        result = submit_engine(self.host).run(task_id=TASK_A, after_s4=mutate)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["loop"], "S8→S3/S4/S5/S6")
        self.assertFalse(result.extras["submit_authorized"])
        self.assertNotEqual(
            result.extras["prior_candidate"],
            result.extras["current_candidate"],
        )

    def test_S14_test_pass_alone_is_not_test_complete(self):
        write_submit_host(self.host)
        extra, command = passing_profile("extra", required=False)
        unit_p, unit_c = passing_profile("unit")
        write_host(self.host, [(unit_p, unit_c), (extra, command)])
        bind_submit_lock(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        project = read_yaml(self.host / ".scaffold/project.yaml")
        project["ownership"] = {**CORE_OWNERSHIP, "src/app.py": "GENERATED"}
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        write_ready_task(self.host)
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["extra"],
        )
        self.assertTrue(result.extras.get("test_pass") or result.outcome == "BLOCKED")
        if result.outcome == "BLOCKED":
            self.assertFalse(result.extras["completeness"]["test_complete"])
        else:
            self.assertFalse(result.extras["test_complete"])

    def test_S15_complete_pass_required_coverage_accepted(self):
        write_submit_host(self.host)
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue(result.extras["test_pass"])
        self.assertTrue(result.extras["test_complete"])

    def test_S16_required_fail_can_be_complete_but_blocks_s10(self):
        profile, command = failing_profile("unit")
        write_host(self.host, [(profile, command)])
        bind_submit_lock(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        project = read_yaml(self.host / ".scaffold/project.yaml")
        project["ownership"] = {**CORE_OWNERSHIP, "src/app.py": "GENERATED"}
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        write_ready_task(self.host)
        digest = observe_candidate(self.host).digest
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.extras["completeness"]["test_complete"])
        self.assertFalse(result.extras["completeness"]["test_pass"])
        self.assertFalse(result.extras["s10"]["durable"])

    def test_S17_missing_required_coverage_routes_test(self):
        write_submit_host(self.host)
        result = submit_engine(self.host).run(task_id=TASK_A)
        self.assertIn(result.next_route, {"human", "test.scoped_verification", "caller"})
        if result.extras.get("test_complete"):
            self.skipTest("fixture already complete")
        blocked = submit_engine(self.host).run(task_id=TASK_A, finalize=True)
        self.assertEqual(blocked.outcome, "BLOCKED")
        self.assertIn(
            blocked.next_route,
            {"test.scoped_verification", "human"},
        )

    def test_S18_stale_test_report_rejected(self):
        write_submit_host(self.host)
        test = TestEngine(self.host, REPO / "skills" / "test").run(
            "scoped_verification", selected=["unit"]
        )
        report = test.extras["report"]
        write(self.host, "src/app.py", "value = 2\n")
        result = submit_engine(self.host).run(task_id=TASK_A, report=report)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.extras["completeness"]["stale_report"])

    def test_S19_zero_required_uses_p6_semantics(self):
        extra, command = passing_profile("note", required=False)
        write_host(self.host, [(extra, command)])
        bind_submit_lock(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        project = read_yaml(self.host / ".scaffold/project.yaml")
        project["ownership"] = {**CORE_OWNERSHIP, "src/app.py": "GENERATED"}
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        write_ready_task(self.host, final_tests=[], stages=[{
            "stage_id": "stage-1",
            "goal": "Write the fixture source.",
            "acceptance": "src/app.py has the expected content.",
            "status": "COMPLETE",
            "required_tests": [],
        }])
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["note"],
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue(result.extras["completeness"]["zero_required"] or result.extras["test_complete"])

    def test_S20_missing_submit_authorized_blocks_s10(self):
        write_submit_host(self.host)
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("SUBMIT_AUTHORIZED" in item for item in result.blockers))
        self.assertFalse(result.extras["s10"]["durable"])

    def test_S21_authorization_bound_to_current_candidate_accepted(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue(result.extras["s10"]["ok"])

    def test_S22_candidate_change_invalidates_authorization(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        write(self.host, "README.md", "# changed after grant\n")
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("C1 authorization is unusable for C2" in item for item in result.blockers))

    def test_S23_authorization_not_manufactured_from_test_pass(self):
        write_submit_host(self.host)
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertTrue(result.extras["test_pass"])
        self.assertFalse(result.extras["submit_authorized"])
        self.assertFalse(result.extras["submit_authorized_persisted"])

    def test_S24_no_material_sync_change_continues(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
            before_s7=lambda: None,
        )
        self.assertEqual(result.outcome, "COMPLETED")

    def test_S25_material_sync_returns_to_s3(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest

        def sync():
            write(self.host, "README.md", "# synced\n")

        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
            before_s7=sync,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S8")
        self.assertIsNone(result.extras.get("change_record"))

    def test_S26_material_change_requires_fresh_s6(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest

        def sync():
            write(self.host, "src/app.py", "value = 9\n")

        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
            before_s7=sync,
        )
        self.assertFalse(result.extras["submit_authorized"])
        self.assertEqual(result.extras["loop"], "S8→S3/S4/S5/S6")

    def test_S27_c1_authorization_unusable_for_c2(self):
        write_submit_host(self.host)
        c1 = observe_candidate(self.host).digest
        write(self.host, "src/app.py", "value = 3\n")
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": c1},
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("C2" in item for item in result.blockers))

    def test_S28_change_record_uses_p3_schema(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
        )
        record = result.extras["change_record"]
        self.assertEqual(validate_change_record(record, expected_id=record["record_id"]), [])
        self.assertEqual(record["record_type"], "change_record")
        self.assertNotIn("commit_sha", record)
        self.assertNotIn("submit_authorized", record)
        self.assertNotIn("submitted", record)

    def test_S29_malformed_change_record_fails_closed(self):
        from scaffold_p8.records import persist_candidate_change

        write_submit_host(self.host)
        ok, blockers, _path = persist_candidate_change(
            self.host, {"record_type": "change_record", "record_id": "not-valid"}
        )
        self.assertFalse(ok)
        self.assertTrue(blockers)

    def test_S30_s9_does_not_claim_durable_s10(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
            fail_s10=True,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["s9_durable"])
        self.assertFalse(result.extras["s10"]["durable"])
        self.assertTrue(any((self.host / CHANGES_DIR).glob("*.yaml")))

    def test_S31_historical_durable_change_record_not_rewritten(self):
        from scaffold_p8.finalize import finalize_s10
        from scaffold_p8.records import persist_candidate_change

        write_submit_host(self.host)
        record_id = "change-20260830T120000Z-abcd1234"
        record = self._valid_change_record(record_id)
        ok, _blockers, path = persist_candidate_change(self.host, record)
        self.assertTrue(ok)
        digest = observe_candidate(self.host).digest
        finalized = finalize_s10(
            self.host,
            record_id=record_id,
            change_rel=path.relative_to(self.host).as_posix(),
            reviewed_paths=[],
            expected_digest=digest,
            scm_kind="none",
        )
        self.assertTrue(finalized["durable"])
        record["summary"] = "rewrite"
        ok, blockers, _path = persist_candidate_change(self.host, record)
        self.assertFalse(ok)
        self.assertTrue(any("must not be rewritten" in item for item in blockers))

    def test_S32_current_candidate_and_auth_may_enter_s10(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        digest = observe_candidate(self.host).digest
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue(result.extras["s10"]["ok"])
        self.assertEqual(result.extras["s10"]["kind"], "git")

    def test_S33_candidate_change_immediately_before_s10_blocks(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest

        def mutate():
            write(self.host, "src/app.py", "value = 99\n")

        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
            before_s10=mutate,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("immediately before S10" in item for item in result.blockers))

    def test_S34_unrelated_file_cannot_enter_finalization_set(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        digest = observe_candidate(self.host).digest

        def sneak():
            write(self.host, "secrets.env", "token=1\n")
            git(self.host, "add", "secrets.env")

        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
            before_s10=sneak,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(
            any(
                "immediately before S10" in item or "unrelated file" in item
                for item in result.blockers
            )
        )

    def test_S35_successful_commit_identity_matches(self):
        write_submit_host(self.host)
        parent = init_submit_git(self.host)
        digest = observe_candidate(self.host).digest
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.extras["s10"]["commit"], git(self.host, "rev-parse", "HEAD"))
        self.assertEqual(result.extras["s10"]["tree"], git(self.host, "rev-parse", "HEAD^{tree}"))
        self.assertEqual(git(self.host, "rev-parse", "HEAD^"), parent)

    def test_S36_commit_failure_leaves_change_record_non_durable(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
            fail_s10=True,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.mutations, "change_record")
        self.assertFalse(result.extras["s10"]["durable"])
        records = list((self.host / CHANGES_DIR).glob("*.yaml"))
        self.assertTrue(records)
        self.assertFalse((self.host / FINALIZATIONS_DIR / f"{records[0].stem}.yaml").exists())

    def test_S37_noscms_authorized_finalization_succeeds(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.extras["s10"]["kind"], "none")
        self.assertTrue(result.extras["s10"]["durable"])

    def test_S38_noscms_publication_conflict_fails_closed(self):
        from scaffold_p5.io_util import file_digest
        from scaffold_p8.finalize import build_finalization_marker

        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        change_id = "change-20260830T150000Z-ffff9999"

        def compete():
            record_path = self.host / CHANGES_DIR / f"{change_id}.yaml"
            write_yaml_atomic(
                self.host / FINALIZATIONS_DIR / f"{change_id}.yaml",
                build_finalization_marker(
                    record_id=change_id,
                    candidate_digest="0" * 64,
                    change_record_digest=file_digest(record_path),
                ),
            )

        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            change_id=change_id,
            submit_authorized={"granted": True, "candidate_digest": digest},
            before_s10=compete,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("conflict" in item.lower() for item in result.blockers))

    def test_S39_s10_without_push_authorization_is_valid(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        digest = observe_candidate(self.host).digest
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue(result.extras["s10"]["ok"])
        self.assertFalse(result.extras["push"]["performed"])

    def test_S40_push_authorization_is_separate(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
            push_authorized={"granted": True, "candidate_digest": digest},
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue(result.extras["submit_authorized"])
        self.assertIn("push", result.extras)

    def test_S41_no_push_without_explicit_authorization(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
        )
        self.assertFalse(result.extras["push"].get("performed"))

    def test_S42_push_failure_does_not_erase_s10(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        digest = observe_candidate(self.host).digest
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
            push_authorized={"granted": True, "candidate_digest": digest},
            fail_push=True,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.extras["s10"]["ok"])
        self.assertFalse(result.extras["push"]["ok"])
        self.assertTrue(result.blockers)
        self.assertEqual(result.extras["s10"]["commit"], git(self.host, "rev-parse", "HEAD"))

    def test_S43_no_session_cleanup_before_s10(self):
        write_submit_host(self.host)
        session_id = self._write_sealed_session(["src/app.py"])
        result = submit_engine(self.host).run(task_id=TASK_A)
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertFalse(result.extras["cleanup"]["performed"])
        self.assertTrue((self.host / SESSIONS_DIR / session_id).is_dir())

    def test_S44_successful_finalization_cleans_linked_sealed_sessions(self):
        write_submit_host(self.host)
        session_id = self._write_sealed_session(["src/app.py"])
        digest = observe_candidate(self.host).digest
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertIn(session_id, result.extras["cleanup"]["cleaned"])
        self.assertFalse((self.host / SESSIONS_DIR / session_id).exists())

    def test_S45_unrelated_session_retained(self):
        write_submit_host(self.host)
        other = self._write_sealed_session(["src/other.py"], session_id="dev-20260830T120000Z-eeeeeeee", task_id="task-20260830T120000Z-eeeeeeee")
        digest = observe_candidate(self.host).digest
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertIn(other, result.extras["cleanup"]["retained"])
        self.assertTrue((self.host / SESSIONS_DIR / other).is_dir())

    def test_S46_durable_artifacts_retained(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue((self.host / ".scaffold/tasks" / f"{TASK_A}.yaml").is_file())
        self.assertTrue(any((self.host / CHANGES_DIR).glob("*.yaml")))
        self.assertTrue((self.host / "src/app.py").is_file())

    def test_S47_submit_never_silently_edits_source(self):
        write_submit_host(self.host)
        before = (self.host / "src/app.py").read_text(encoding="utf-8")
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "hacked\n"}],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual((self.host / "src/app.py").read_text(encoding="utf-8"), before)

    def test_S48_repair_handoff_does_not_escalate_permissions(self):
        write_submit_host(self.host)
        (self.host / "src/app.py").unlink()
        result = submit_engine(self.host).run(task_id=TASK_A)
        handoff = result.extras["repair_handoff"]
        self.assertFalse(handoff["capabilities"]["commit"])
        self.assertFalse(handoff["capabilities"]["push"])
        self.assertFalse(handoff["capabilities"]["submit_authorized"])
        self.assertNotIn("chat", handoff)
        self.assertFalse(result.extras["capabilities"]["commit"])

    def test_package_identity(self):
        pkg = load_package(REPO_SUBMIT)
        self.assertEqual(pkg.validity, "VALID", pkg.validity_reasons)
        self.assertEqual(pkg.ref.skill_id, SKILL_ID)
        self.assertEqual(pkg.manifest["modes"], [])
        self.assertEqual(pkg.manifest["provides"], list(PROVIDES))
        self.assertEqual(pkg.manifest["requires"], list(REQUIRES))
        self.assertEqual(CORE_SKILLS, ("understand", "develop", "test", "submit"))
        self.assertTrue((REPO / "src/scaffold_p8").is_dir())
        self.assertFalse((REPO / "src/scaffold_p9").exists())

    def _write_sealed_session(
        self,
        files: list[str],
        *,
        session_id: str = "dev-20260830T180000Z-abcd1234",
        task_id: str = TASK_A,
    ) -> str:
        directory = self.host / SESSIONS_DIR / session_id
        directory.mkdir(parents=True, exist_ok=True)
        write_yaml_atomic(
            directory / "session.yaml",
            {
                "record_type": "develop_session",
                "schema_version": "1",
                "record_id": session_id,
                "created_at": "2026-08-30T18:00:00Z",
                "updated_at": "2026-08-30T18:00:00Z",
                "status": "SEALED",
                "task_id": task_id,
                "mode": "normal_task",
                "project_name": self.host.name,
                "baseline": {"kind": "none", "value": None},
                "workspace_overlay_s0": {"coverage": "unavailable", "paths": []},
                "observed_candidate_digest": observe_candidate(self.host).digest,
            },
        )
        write_yaml_atomic(
            directory / "files.yaml",
            {"files": [{"path": path} for path in files]},
        )
        if task_id == TASK_A:
            write_ready_task(self.host, develop_session_ids=[session_id])
        return session_id

    @staticmethod
    def _valid_change_record(record_id: str) -> dict:
        return {
            "record_type": "change_record",
            "schema_version": "1",
            "record_id": record_id,
            "created_at": "2026-08-30T12:00:00Z",
            "summary": "fixture",
            "base": {"kind": "none", "value": None},
            "affected": {"modules": [], "areas": []},
            "path_summary": {
                "representation": "exact",
                "total_changed_paths": 0,
                "paths": [],
            },
            "structural_summary": "ok",
            "knowledge_updates": "ok",
            "verification": {"summary": "n/a", "evidence_refs": []},
            "understand_involvement": {
                "refresh": False,
                "compatibility": False,
            },
            "task_book_ids": [],
            "provenance": {
                "relevant_develop_session_count": 0,
                "classes": {
                    name: {"path_count": 0}
                    for name in (
                        "DEVELOP_KNOWN",
                        "MIXED_CHANGE",
                        "PREEXISTING_CHANGE",
                        "POST_DEVELOP_ADDITIONAL",
                        "UNATTRIBUTED",
                    )
                },
            },
            "limitations": [],
        }


class P8PresenceTests(unittest.TestCase):
    def test_submit_package_is_present(self):
        self.assertTrue((REPO / "skills" / "submit").is_dir())
        self.assertTrue((REPO / "src" / "scaffold_p8").is_dir())
        self.assertFalse((REPO / "skills" / "repair").exists())

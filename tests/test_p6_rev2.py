from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import (
    failing_profile,
    git,
    init_git,
    passing_profile,
    py_command,
    test_engine,
    write_commands,
    write_host,
    write_modules,
    write_project,
    write_tests,
)
from support import REPO, write
from scaffold_p5.io_util import file_digest, read_yaml, write_yaml_atomic
from scaffold_p5.models import COMPAT_RESULTS, CORE_SKILLS
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.contract import working_directory_declaration_valid
from scaffold_p6.engine import TestEngine
from scaffold_p6.schemas import validate_report
from scaffold_p6.storage import (
    cleanup_incomplete_test_runs,
    cleanup_test_run,
    is_completed_pass_report,
    load_completed_report,
    run_dir,
)


class P6Rev2Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_V01_unadopted_host_does_not_execute(self):
        profile, command = passing_profile()
        write(self.host, "README.md", "# raw\n")
        write_commands(self.host, [command])
        write_tests(self.host, [profile])
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertEqual(result.next_route, "understand.bootstrap")

    def test_V02_adopting_host_blocked(self):
        write_host(self.host, [passing_profile()], lifecycle="ADOPTING")
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertEqual(result.next_route, "understand.bootstrap")

    def test_V03_recovery_required_blocked(self):
        write_host(self.host, [passing_profile()], lifecycle="RECOVERY_REQUIRED")
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)

    def test_V04_needs_refresh_routes_refresh(self):
        write_host(self.host, [passing_profile()], maintenance=["NEEDS_REFRESH"])
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertEqual(result.next_route, "understand.refresh")

    def test_V05_needs_migration_routes_compatibility(self):
        write_host(self.host, [passing_profile()], maintenance=["NEEDS_MIGRATION"])
        project_before = file_digest(self.host / ".scaffold/project.yaml")
        lock_before = file_digest(self.host / ".scaffold/skills.lock")
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertEqual(result.next_route, "understand.compatibility")
        self.assertEqual(file_digest(self.host / ".scaffold/project.yaml"), project_before)
        self.assertEqual(file_digest(self.host / ".scaffold/skills.lock"), lock_before)
        self.assertIn("NEEDS_MIGRATION", read_yaml(self.host / ".scaffold/project.yaml")["maintenance"])

    def test_V06_normal_active_exact_still_executes(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue(result.extras["test_pass"])
        self.assertEqual(result.compatibility, "EXACT")

    def test_V07_inferred_empty_required_set_not_complete(self):
        write(self.host, "README.md", "# inferred\n")
        write_project(self.host)
        write_commands(self.host, [])
        write_tests(self.host, [], confidence="INFERRED")
        c = test_engine(self.host).run().extras["completeness"]
        self.assertFalse(c["required_set_authoritative"])
        self.assertFalse(c["test_complete"])

    def test_V08_authoritative_zero_required_set(self):
        write(self.host, "README.md", "# none\n")
        write_project(self.host)
        write_commands(self.host, [])
        write_tests(self.host, [], applicable=False, applicability="NOT_APPLICABLE")
        c = test_engine(self.host).run().extras["completeness"]
        self.assertTrue(c["required_set_authoritative"])
        self.assertTrue(c["test_complete"])
        self.assertFalse(c["test_pass"])

    def test_V09_applicable_wrong_type_blocks(self):
        write(self.host, "README.md", "# type\n")
        write_project(self.host)
        write_commands(self.host, [])
        write_yaml_atomic(
            self.host / ".scaffold/tests.yaml",
            {
                "schema_version": "1",
                "applicable": "false",
                "applicability": "NOT_APPLICABLE",
                "confidence": "VERIFIED",
                "profiles": [],
            },
        )
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertTrue(any("applicable" in item for item in result.blockers))

    def test_V10_applicable_applicability_contradiction(self):
        write(self.host, "README.md", "# conflict\n")
        write_project(self.host)
        write_commands(self.host, [])
        write_tests(self.host, [], applicable=False, applicability="APPLICABLE")
        result = test_engine(self.host).run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("contradicts" in item for item in result.blockers))

    def test_V11_required_not_applicable_conflicts(self):
        profile, command = passing_profile("na")
        profile["applicability"] = "NOT_APPLICABLE"
        write_host(self.host, [(profile, command)])
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)

    def test_V12_required_applicability_unknown_blocked(self):
        profile, command = passing_profile("unk")
        profile["applicability"] = "UNKNOWN"
        write_host(self.host, [(profile, command)])
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)

    def test_V13_required_applicability_conflicting_blocked(self):
        profile, command = passing_profile("cf")
        profile["applicability"] = "CONFLICTING"
        write_host(self.host, [(profile, command)])
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)

    def test_V14_malformed_success_exit_code_is_contract_blocker(self):
        profile, command = passing_profile("bad-success")
        profile["success"] = {"exit_code": True}
        write_host(self.host, [(profile, command)])
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertTrue(any("exit_code" in item for item in result.blockers))

    def test_V15_unknown_selected_profile_blocks(self):
        write_host(self.host, [passing_profile()])
        engine = test_engine(self.host)
        result = engine.run(selected=["missing"])
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertTrue(any("unknown selected" in item for item in result.blockers))

    def test_V16_selected_string_is_not_split(self):
        write_host(self.host, [passing_profile("unit")])
        engine = test_engine(self.host)
        result = engine.run(selected="unit")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertTrue(any("not a string" in item for item in result.blockers))

    def test_V17_generated_outputs_cannot_hide_tracked_source(self):
        profile, command = passing_profile("src")
        command["argv"] = py_command(
            "from pathlib import Path; Path('src/app.py').write_text('VALUE=2\\n', encoding='utf-8')"
        )
        write_host(self.host, [(profile, command)], generated_outputs=["src"])
        write(self.host, "src/app.py", "VALUE=1\n")
        init_git(self.host)
        result = test_engine(self.host).run()
        self.assertFalse(result.extras["completeness"]["candidate_match"])
        self.assertFalse(result.extras["test_pass"])

    def test_V18_core_authority_cannot_be_excluded(self):
        profile, command = passing_profile("auth")
        command["argv"] = py_command(
            "from pathlib import Path; "
            "p=Path('.scaffold/project.yaml'); "
            "p.write_text(p.read_text(encoding='utf-8') + '\\n# x\\n', encoding='utf-8')"
        )
        write_host(self.host, [(profile, command)], generated_outputs=[".scaffold"])
        result = test_engine(self.host).run()
        self.assertFalse(result.extras["completeness"]["candidate_match"])

    def test_V19_classified_generated_output_can_be_excluded(self):
        profile, command = passing_profile("gen")
        command["argv"] = py_command(
            "from pathlib import Path; "
            "p=Path('build/out.txt'); p.parent.mkdir(parents=True, exist_ok=True); "
            "p.write_text('built\\n', encoding='utf-8'); print('P6_PASS')"
        )
        write_host(self.host, [(profile, command)], generated_outputs=["build"])
        write_modules(
            self.host,
            [{"id": "build", "path": "build", "kind": "generated", "confidence": "VERIFIED"}],
        )
        result = test_engine(self.host).run()
        self.assertTrue(result.extras["completeness"]["candidate_match"])
        self.assertTrue(result.extras["test_pass"])

    def test_V20_dirty_rename_without_mutation_is_stable(self):
        write_host(self.host, [passing_profile()])
        write(self.host, "src/a.py", "VALUE=1\n")
        init_git(self.host)
        git(self.host, "mv", "src/a.py", "src/b.py")
        result = test_engine(self.host).run()
        self.assertTrue((self.host / "src/b.py").exists())
        self.assertTrue(result.extras["completeness"]["candidate_match"])

    def test_V21_dirty_rename_target_mutation_mismatches(self):
        profile, command = passing_profile("rename")
        command["argv"] = py_command(
            "from pathlib import Path; Path('src/b.py').write_text('VALUE=2\\n', encoding='utf-8')"
        )
        write_host(self.host, [(profile, command)])
        write(self.host, "src/a.py", "VALUE=1\n")
        init_git(self.host)
        git(self.host, "mv", "src/a.py", "src/b.py")
        result = test_engine(self.host).run()
        self.assertFalse(result.extras["completeness"]["candidate_match"])

    def test_V22_external_without_supply_does_not_run_local(self):
        profile, command = passing_profile("ext")
        profile["provenance"] = "EXTERNAL_RESULT"
        write_host(self.host, [(profile, command)])
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "BLOCKED")

    def test_V23_ci_without_supply_does_not_run_local(self):
        profile, command = passing_profile("ci")
        profile["provenance"] = "CI_RESULT"
        write_host(self.host, [(profile, command)])
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "BLOCKED")

    def test_V24_local_profile_rejects_external_supply(self):
        write_host(self.host, [passing_profile("loc")])
        digest = observe_candidate(self.host).digest
        engine = test_engine(self.host)
        result = engine.run(
            supplied_evidence=[
                {
                    "profile_id": "loc",
                    "provenance": "EXTERNAL_RESULT",
                    "kind": "structured_assertion",
                    "result": "PASS",
                    "candidate_digest": digest,
                    "summary": "imported",
                }
            ]
        )
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "BLOCKED")
        self.assertFalse(result.extras["test_pass"])

    def test_V25_two_supplied_items_are_retained(self):
        profile, command = passing_profile("multi")
        profile["provenance"] = "EXTERNAL_RESULT"
        profile["evidence_required"] = ["structured_assertion", "visual_checkpoint"]
        write_host(self.host, [(profile, command)])
        digest = observe_candidate(self.host).digest
        result = test_engine(self.host).run(
            supplied_evidence=[
                {
                    "profile_id": "multi",
                    "provenance": "EXTERNAL_RESULT",
                    "kind": "structured_assertion",
                    "result": "PASS",
                    "candidate_digest": digest,
                    "summary": "asserted",
                },
                {
                    "profile_id": "multi",
                    "provenance": "EXTERNAL_RESULT",
                    "kind": "visual_checkpoint",
                    "result": "PASS",
                    "candidate_digest": digest,
                    "locator": "shots/main.png",
                },
            ]
        )
        kinds = [item["kind"] for item in result.extras["report"]["evidence"]]
        self.assertIn("structured_assertion", kinds)
        self.assertIn("visual_checkpoint", kinds)

    def test_V26_two_required_kinds_complete_when_both_supplied(self):
        profile, command = passing_profile("both")
        profile["provenance"] = "EXTERNAL_RESULT"
        profile["evidence_required"] = ["structured_assertion", "visual_checkpoint"]
        write_host(self.host, [(profile, command)])
        digest = observe_candidate(self.host).digest
        result = test_engine(self.host).run(
            supplied_evidence=[
                {
                    "profile_id": "both",
                    "provenance": "EXTERNAL_RESULT",
                    "kind": "structured_assertion",
                    "result": "PASS",
                    "candidate_digest": digest,
                    "summary": "asserted",
                },
                {
                    "profile_id": "both",
                    "provenance": "EXTERNAL_RESULT",
                    "kind": "visual_checkpoint",
                    "result": "PASS",
                    "candidate_digest": digest,
                    "locator": "shots/main.png",
                },
            ]
        )
        self.assertTrue(result.extras["completeness"]["evidence_complete"])
        self.assertTrue(result.extras["test_complete"])

    def test_V27_conflicting_supplied_results_block(self):
        profile, command = passing_profile("conflict")
        profile["provenance"] = "EXTERNAL_RESULT"
        write_host(self.host, [(profile, command)])
        digest = observe_candidate(self.host).digest
        result = test_engine(self.host).run(
            supplied_evidence=[
                {
                    "profile_id": "conflict",
                    "provenance": "EXTERNAL_RESULT",
                    "kind": "structured_assertion",
                    "result": "PASS",
                    "candidate_digest": digest,
                    "summary": "pass",
                },
                {
                    "profile_id": "conflict",
                    "provenance": "EXTERNAL_RESULT",
                    "kind": "visual_checkpoint",
                    "result": "FAIL",
                    "candidate_digest": digest,
                    "locator": "shots/main.png",
                },
            ]
        )
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "BLOCKED")
        self.assertFalse(result.extras["test_pass"])

    def test_V28_empty_visual_checkpoint_unusable(self):
        profile, command = passing_profile("vis")
        profile["provenance"] = "EXTERNAL_RESULT"
        profile["evidence_required"] = ["visual_checkpoint"]
        write_host(self.host, [(profile, command)])
        digest = observe_candidate(self.host).digest
        result = test_engine(self.host).run(
            supplied_evidence=[
                {
                    "profile_id": "vis",
                    "provenance": "EXTERNAL_RESULT",
                    "kind": "visual_checkpoint",
                    "result": "PASS",
                    "candidate_digest": digest,
                    "summary": "",
                    "locator": "",
                }
            ]
        )
        self.assertFalse(result.extras["completeness"]["evidence_complete"])
        self.assertFalse(result.extras["test_complete"])

    def test_V29_human_observation_without_content_unusable(self):
        profile, command = passing_profile("human")
        profile["provenance"] = "HUMAN_OBSERVATION"
        profile["evidence_required"] = ["human_observation"]
        write_host(self.host, [(profile, command)])
        result = test_engine(self.host).run(
            supplied_evidence=[
                {
                    "profile_id": "human",
                    "provenance": "HUMAN_OBSERVATION",
                    "kind": "human_observation",
                    "result": "PASS",
                    "summary": "",
                }
            ]
        )
        self.assertFalse(result.extras["completeness"]["evidence_complete"])

    def test_V30_file_artifact_without_locator_unusable(self):
        profile, command = passing_profile("file")
        profile["provenance"] = "EXTERNAL_RESULT"
        profile["evidence_required"] = ["file_artifact"]
        write_host(self.host, [(profile, command)])
        digest = observe_candidate(self.host).digest
        result = test_engine(self.host).run(
            supplied_evidence=[
                {
                    "profile_id": "file",
                    "provenance": "EXTERNAL_RESULT",
                    "kind": "file_artifact",
                    "result": "PASS",
                    "candidate_digest": digest,
                    "summary": "missing file",
                }
            ]
        )
        self.assertFalse(result.extras["completeness"]["evidence_complete"])

    def test_V31_invalid_required_item_not_hidden_by_valid_item(self):
        profile, command = passing_profile("hide")
        profile["provenance"] = "EXTERNAL_RESULT"
        profile["evidence_required"] = ["structured_assertion", "visual_checkpoint"]
        write_host(self.host, [(profile, command)])
        digest = observe_candidate(self.host).digest
        result = test_engine(self.host).run(
            supplied_evidence=[
                {
                    "profile_id": "hide",
                    "provenance": "EXTERNAL_RESULT",
                    "kind": "structured_assertion",
                    "result": "PASS",
                    "candidate_digest": digest,
                    "summary": "ok",
                },
                {
                    "profile_id": "hide",
                    "provenance": "EXTERNAL_RESULT",
                    "kind": "visual_checkpoint",
                    "result": "PASS",
                    "candidate_digest": digest,
                    "summary": "",
                    "locator": "",
                },
            ]
        )
        self.assertFalse(result.extras["completeness"]["evidence_complete"])
        self.assertFalse(result.extras["test_complete"])

    def test_V32_missing_local_ref_makes_completed_report_unusable(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        run_id = result.extras["report_id"]
        dest = run_dir(self.host, run_id)
        refs = result.extras["report"]["evidence_refs"]
        self.assertTrue(refs)
        locator = refs[0]["locator"]
        path = self.host / ".scaffold/runtime" / locator
        self.assertTrue(path.exists())
        path.unlink()
        self.assertIsNone(load_completed_report(self.host, run_id))
        self.assertFalse(is_completed_pass_report(dest / "report.yaml"))

    def test_V33_evidence_digest_mismatch_unusable(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        run_id = result.extras["report_id"]
        dest = run_dir(self.host, run_id)
        locator = result.extras["report"]["evidence_refs"][0]["locator"]
        path = self.host / ".scaffold/runtime" / locator
        path.write_text("CORRUPTED\n", encoding="utf-8")
        self.assertIsNone(load_completed_report(self.host, run_id))
        self.assertFalse(is_completed_pass_report(dest / "report.yaml"))

    def test_V34_fail_profile_with_test_pass_true_rejected(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        report = result.extras["report"]
        report["profiles"][0]["result"] = "FAIL"
        self.assertNotEqual(validate_report(report)[0], "VALID")

    def test_V35_verification_pass_mismatch_rejected(self):
        write_host(self.host, [passing_profile()])
        report = test_engine(self.host).run().extras["report"]
        report["verification"]["test_pass"] = False
        self.assertNotEqual(validate_report(report)[0], "VALID")

    def test_V36_verification_complete_mismatch_rejected(self):
        write_host(self.host, [passing_profile()])
        report = test_engine(self.host).run().extras["report"]
        report["verification"]["test_complete"] = False
        self.assertNotEqual(validate_report(report)[0], "VALID")

    def test_V37_report_id_mismatch_rejected(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        run_id = result.extras["report_id"]
        dest = run_dir(self.host, run_id)
        report = read_yaml(dest / "report.yaml")
        report["report_id"] = "testrun-other"
        write_yaml_atomic(dest / "report.yaml", report)
        self.assertIsNone(load_completed_report(self.host, run_id))

    def test_V38_evidence_ref_binding_mismatch_rejected(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        run_id = result.extras["report_id"]
        dest = run_dir(self.host, run_id)
        report = read_yaml(dest / "report.yaml")
        report["evidence_refs"][0]["candidate_digest"] = "0" * 64
        write_yaml_atomic(dest / "report.yaml", report)
        self.assertIsNone(load_completed_report(self.host, run_id))

    def test_V39_valid_completed_pass_report_still_loads(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        loaded = test_engine(self.host).load_report(result.extras["report_id"])
        self.assertIsNotNone(loaded)
        self.assertTrue(loaded["verification"]["test_pass"])

    def test_V40_project_relative_dot_is_valid(self):
        ok, reason = working_directory_declaration_valid(".")
        self.assertTrue(ok, reason)

    def test_V41_absolute_working_directory_rejected_without_execution(self):
        ok, reason = working_directory_declaration_valid("C:/Windows")
        self.assertFalse(ok)
        self.assertIn("project-relative", reason)
        engine = TestEngine(self.host)
        self.assertEqual(engine.adapter_invocations, 0)

    def test_V42_exact_run_cleanup_removes_only_requested_run(self):
        write_host(self.host, [passing_profile()])
        first = test_engine(self.host).run()
        second = test_engine(self.host).run()
        self.assertTrue(cleanup_test_run(self.host, first.extras["report_id"]))
        self.assertFalse(run_dir(self.host, first.extras["report_id"]).exists())
        self.assertTrue(run_dir(self.host, second.extras["report_id"]).exists())

    def test_V43_cleanup_leaves_other_completed_run(self):
        write_host(self.host, [passing_profile()])
        keep = test_engine(self.host).run()
        drop = test_engine(self.host).run()
        cleanup_test_run(self.host, drop.extras["report_id"])
        self.assertIsNotNone(load_completed_report(self.host, keep.extras["report_id"]))

    def test_V44_abandoned_incomplete_run_can_be_cleaned(self):
        write_host(self.host, [passing_profile()])
        dest = run_dir(self.host, "testrun-abandoned")
        (dest / "incomplete").mkdir(parents=True)
        write_yaml_atomic(dest / "incomplete" / "run.yaml", {"status": "PREPARING"})
        removed = cleanup_incomplete_test_runs(self.host)
        self.assertIn("testrun-abandoned", removed)
        self.assertFalse(dest.exists())

    def test_V45_completed_report_is_not_automatically_deleted(self):
        write_host(self.host, [passing_profile()])
        first = test_engine(self.host).run()
        test_engine(self.host).run()
        self.assertTrue(run_dir(self.host, first.extras["report_id"]).exists())
        self.assertIsNotNone(load_completed_report(self.host, first.extras["report_id"]))

    def test_V46_p5_suite_still_collects_184(self):
        loader = unittest.defaultTestLoader
        suite = loader.discover(str(REPO / "tests"), pattern="test_p5*.py")
        self.assertEqual(suite.countTestCases(), 184)
        self.assertEqual(len(COMPAT_RESULTS), 5)
        self.assertEqual(CORE_SKILLS, ("understand", "develop", "test", "submit"))

    def test_V47_previous_p6_suite_still_collects_106(self):
        loader = unittest.defaultTestLoader
        original = loader.discover(str(REPO / "tests"), pattern="test_p6_test.py")
        rev1 = loader.discover(str(REPO / "tests"), pattern="test_p6_rev1.py")
        self.assertEqual(original.countTestCases() + rev1.countTestCases(), 106)


if __name__ == "__main__":
    unittest.main()

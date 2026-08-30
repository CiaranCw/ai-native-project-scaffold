from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import (
    REPO_TEST,
    failing_profile,
    git,
    init_git,
    passing_profile,
    py_command,
    test_engine,
    write_commands,
    write_host,
    write_project,
    write_tests,
)
from support import REPO, write
from scaffold_p5.io_util import file_digest, read_text, read_yaml, write_yaml_atomic
from scaffold_p5.models import COMPAT_RESULTS, CORE_SKILLS
from scaffold_p5.packages import load_package
from scaffold_p5.schemas import validate_project_data
from scaffold_p6.adapter import LocalTargetAdapter
from scaffold_p6.candidate import observe_candidate, report_usable_for
from scaffold_p6.evidence import preserve_verification_truth
from scaffold_p6.models import PROVIDES, REQUIRES, SKILL_ID, SKILL_VERSION, TEST_MODES
from scaffold_p6.schemas import reports_equal, roundtrip, validate_report
from scaffold_p6.storage import is_completed_pass_report, list_completed_reports, resolve_evidence_ref


class P6TestSkillTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_T01_package_identity(self):
        pkg = load_package(REPO_TEST)
        self.assertEqual(pkg.validity, "VALID", pkg.validity_reasons)
        self.assertEqual(pkg.ref.skill_id, "test")
        self.assertEqual(pkg.ref.skill_version, "2.0.0")
        self.assertEqual(pkg.manifest["modes"], ["scoped_verification"])
        self.assertEqual(pkg.manifest["provides"], ["test.scoped_verification"])
        self.assertEqual(pkg.manifest["requires"], [])
        self.assertEqual(SKILL_ID, "test")
        self.assertEqual(SKILL_VERSION, "2.0.0")
        self.assertEqual(TEST_MODES, ("scoped_verification",))
        self.assertEqual(PROVIDES, ("test.scoped_verification",))
        self.assertEqual(REQUIRES, ())

    def test_T02_four_skills_only_two_implemented(self):
        self.assertEqual(CORE_SKILLS, ("understand", "develop", "test", "submit"))
        self.assertTrue((REPO / "skills" / "understand").is_dir())
        self.assertTrue((REPO / "skills" / "test").is_dir())
        self.assertFalse((REPO / "skills" / "develop").exists())
        self.assertFalse((REPO / "skills" / "submit").exists())
        self.assertFalse((REPO / "src" / "scaffold_p7").exists())
        self.assertFalse((REPO / "src" / "scaffold_p8").exists())

    def test_T03_noscms_passing_profile(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue(result.extras["test_pass"])
        self.assertTrue(result.extras["test_complete"])
        self.assertEqual(observe_candidate(self.host).kind, "none")

    def test_T04_git_clean_passing_profile(self):
        write_host(self.host, [passing_profile()])
        init_git(self.host)
        result = test_engine(self.host).run()
        self.assertTrue(result.extras["test_pass"])
        identity = observe_candidate(self.host)
        self.assertEqual(identity.kind, "git")
        self.assertEqual(identity.data["working_tree"], "clean")

    def test_T05_git_dirty_tracked_distinct_from_head(self):
        write_host(self.host, [passing_profile()])
        revision = init_git(self.host)
        clean = observe_candidate(self.host)
        write(self.host, "README.md", "# dirty tracked\n")
        dirty = observe_candidate(self.host)
        self.assertEqual(dirty.data["revision"], revision)
        self.assertEqual(dirty.data["working_tree"], "dirty")
        self.assertEqual(dirty.data["tracked_changes"], "present")
        self.assertNotEqual(clean.digest, dirty.digest)
        self.assertNotEqual(dirty.digest, revision)

    def test_T06_git_untracked_contributes(self):
        write_host(self.host, [passing_profile()])
        revision = init_git(self.host)
        clean = observe_candidate(self.host)
        write(self.host, "extra_untracked.txt", "untracked\n")
        dirty = observe_candidate(self.host)
        self.assertEqual(dirty.data["revision"], revision)
        self.assertEqual(dirty.data["untracked_changes"], "present")
        self.assertNotEqual(clean.digest, dirty.digest)

    def test_T07_same_head_different_workspace(self):
        write_host(self.host, [passing_profile()])
        revision = init_git(self.host)
        a = observe_candidate(self.host)
        write(self.host, "workspace-a.txt", "A\n")
        git(self.host, "add", "workspace-a.txt")
        write(self.host, "workspace-a.txt", "B\n")
        b = observe_candidate(self.host)
        self.assertEqual(a.data["revision"], revision)
        self.assertEqual(b.data["revision"], revision)
        self.assertNotEqual(a.digest, b.digest)

    def test_T08_required_pass_is_test_pass(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        report = result.extras["report"]
        self.assertEqual(report["profiles"][0]["result"], "PASS")
        self.assertTrue(result.extras["test_pass"])
        self.assertTrue(result.extras["completeness"]["evidence_complete"])
        self.assertTrue(any(item["kind"] == "command_result" for item in report["evidence"]))

    def test_T09_required_fail_is_not_skill_crash(self):
        write_host(self.host, [failing_profile()])
        result = test_engine(self.host).run()
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertFalse(result.extras["test_pass"])
        self.assertTrue(result.extras["test_complete"])
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "FAIL")
        self.assertTrue((self.host / ".scaffold/runtime/test-runs" / result.extras["report_id"] / "report.yaml").exists())

    def test_T10_pass_plus_fail_complete_not_pass(self):
        write_host(self.host, [passing_profile("ok"), failing_profile("bad")])
        result = test_engine(self.host).run()
        c = result.extras["completeness"]
        self.assertEqual(c["required_pass"], 1)
        self.assertEqual(c["required_fail"], 1)
        self.assertTrue(c["test_complete"])
        self.assertFalse(c["test_pass"])

    def test_T11_required_not_run_incomplete(self):
        write_host(self.host, [passing_profile("ok"), passing_profile("other")])
        result = test_engine(self.host).run(selected=["ok"])
        c = result.extras["completeness"]
        self.assertEqual(c["required_not_run"], 1)
        self.assertTrue(c["test_pass"])
        self.assertFalse(c["test_complete"])

    def test_T12_required_blocked_incomplete(self):
        profile, _command = passing_profile("blocked")
        write_host(self.host, [(profile, {"id": "other", "argv": py_command("print(1)")})])
        result = test_engine(self.host).run()
        c = result.extras["completeness"]
        self.assertEqual(c["required_blocked"], 1)
        self.assertFalse(c["test_complete"])
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "BLOCKED")

    def test_T13_optional_not_run_does_not_block_required(self):
        required, req_cmd = passing_profile("req")
        optional, opt_cmd = passing_profile("opt", required=False)
        write_host(self.host, [(required, req_cmd), (optional, opt_cmd)])
        result = test_engine(self.host).run()
        c = result.extras["completeness"]
        self.assertEqual(c["optional_total"], 1)
        self.assertNotIn("opt", c["selected"])
        opt = next(row for row in result.extras["report"]["profiles"] if row["id"] == "opt")
        self.assertEqual(opt["result"], "NOT_RUN")
        self.assertTrue(c["test_complete"])
        self.assertTrue(c["test_pass"])

    def test_T14_verified_no_required_tests(self):
        write(self.host, "README.md", "# none\n")
        write_project(self.host)
        write_commands(self.host, [])
        write_tests(self.host, [], applicable=False, applicability="NOT_APPLICABLE")
        result = test_engine(self.host).run()
        c = result.extras["completeness"]
        self.assertEqual(c["required_total"], 0)
        self.assertTrue(c["test_complete"])
        self.assertFalse(c["test_pass"])
        self.assertTrue(c["verified_no_required_tests"])

    def test_T15_unknown_applicability(self):
        write(self.host, "README.md", "# unknown\n")
        write_project(self.host)
        write_commands(self.host, [])
        write_tests(self.host, [], applicable=None, applicability="UNKNOWN", confidence="UNKNOWN")
        result = test_engine(self.host).run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["test_complete"])
        self.assertFalse(result.extras["completeness"]["verified_no_required_tests"])
        self.assertEqual(result.next_route, "understand.refresh")

    def test_T16_conflicting_authority(self):
        write(self.host, "README.md", "# conflict\n")
        write_project(self.host)
        write_tests(
            self.host,
            [],
            applicable=True,
            applicability="CONFLICTING",
            confidence="CONFLICTING",
        )
        result = test_engine(self.host).run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("CONFLICTING" in item for item in result.blockers))

    def test_T17_malformed_tests_yaml(self):
        write(self.host, "README.md", "# malformed\n")
        write_project(self.host)
        write(self.host, ".scaffold/tests.yaml", "this line has no colon\n")
        result = test_engine(self.host).run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("malformed" in item.lower() for item in result.blockers))

    def test_T18_missing_tests_yaml_on_active(self):
        write(self.host, "README.md", "# missing\n")
        write_project(self.host)
        result = test_engine(self.host).run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("ACTIVE" in item for item in result.blockers))

    def test_T19_declared_command_missing(self):
        profile, _command = passing_profile("gone")
        write(self.host, "README.md", "# cmd\n")
        write_project(self.host)
        write_commands(self.host, [])
        write_tests(self.host, [profile])
        result = test_engine(self.host).run()
        row = result.extras["report"]["profiles"][0]
        self.assertEqual(row["result"], "BLOCKED")
        self.assertNotEqual(row["result"], "FAIL")
        self.assertNotEqual(row["result"], "PASS")

    def test_T20_unsupported_adapter(self):
        profile, command = passing_profile("remote")
        profile["adapter"] = "ssh"
        write_host(self.host, [(profile, command)])
        result = test_engine(self.host).run()
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "BLOCKED")
        self.assertTrue(any("unsupported target adapter" in item for item in result.blockers))

    def test_T21_local_adapter_captures_streams(self):
        adapter = LocalTargetAdapter()
        obs = adapter.execute(
            command=py_command("import sys; print('OUT'); print('ERR', file=sys.stderr)"),
            working_directory=self.host,
            timeout_seconds=10,
        )
        self.assertEqual(obs.exit_code, 0)
        self.assertIn("OUT", obs.stdout)
        self.assertIn("ERR", obs.stderr)
        self.assertGreaterEqual(obs.duration_ms, 0)
        self.assertEqual(obs.adapter_id, "local")

    def test_T22_required_evidence_missing(self):
        profile, command = passing_profile("need-visual")
        profile["evidence_required"] = ["visual_checkpoint"]
        write_host(self.host, [(profile, command)])
        result = test_engine(self.host).run()
        self.assertFalse(result.extras["test_complete"])
        self.assertFalse(result.extras["completeness"]["evidence_complete"])

    def test_T23_evidence_records_candidate_scenario_provenance(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        item = result.extras["report"]["evidence"][0]
        self.assertEqual(item["profile_id"], "unit")
        self.assertEqual(item["provenance"], "LOCAL_EXECUTION")
        self.assertEqual(item["candidate_digest"], observe_candidate(self.host).digest)
        self.assertTrue(item["observed_at"])

    def test_T24_external_result_stays_external(self):
        profile, command = passing_profile("ext")
        profile["provenance"] = "EXTERNAL_RESULT"
        write_host(self.host, [(profile, command)])
        digest = observe_candidate(self.host).digest
        result = test_engine(self.host).run(
            supplied_evidence=[
                {
                    "profile_id": "ext",
                    "provenance": "EXTERNAL_RESULT",
                    "kind": "structured_assertion",
                    "result": "PASS",
                    "candidate_digest": digest,
                    "summary": "imported",
                    "mechanism": "external_tool",
                }
            ]
        )
        row = result.extras["report"]["profiles"][0]
        self.assertEqual(row["provenance"], "EXTERNAL_RESULT")
        self.assertNotEqual(row["provenance"], "LOCAL_EXECUTION")

    def test_T25_human_observation_stays_human(self):
        profile, command = passing_profile("human")
        profile["provenance"] = "HUMAN_OBSERVATION"
        profile["evidence_required"] = ["human_observation"]
        write_host(self.host, [(profile, command)])
        digest = observe_candidate(self.host).digest
        result = test_engine(self.host).run(
            supplied_evidence=[
                {
                    "profile_id": "human",
                    "provenance": "HUMAN_OBSERVATION",
                    "kind": "human_observation",
                    "result": "PASS",
                    "candidate_digest": digest,
                    "summary": "seen by human",
                }
            ]
        )
        self.assertEqual(result.extras["report"]["profiles"][0]["provenance"], "HUMAN_OBSERVATION")
        self.assertNotEqual(result.extras["report"]["evidence"][0]["mechanism"], "local_target_adapter")

    def test_T26_ci_mismatch_cannot_satisfy(self):
        profile, command = passing_profile("ci")
        profile["provenance"] = "CI_RESULT"
        write_host(self.host, [(profile, command)])
        result = test_engine(self.host).run(
            supplied_evidence=[
                {
                    "profile_id": "ci",
                    "provenance": "CI_RESULT",
                    "kind": "external_ci",
                    "result": "PASS",
                    "candidate_digest": "0" * 64,
                    "summary": "other candidate",
                }
            ]
        )
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "BLOCKED")
        self.assertFalse(result.extras["test_complete"])

    def test_T27_candidate_change_during_run(self):
        profile, command = passing_profile("mutate")
        command["argv"] = py_command(
            "from pathlib import Path; Path('README.md').write_text('# changed\\n', encoding='utf-8')"
        )
        write_host(self.host, [(profile, command)])
        before = read_text(self.host / "README.md")
        result = test_engine(self.host).run()
        self.assertNotEqual(read_text(self.host / "README.md"), before)
        self.assertFalse(result.extras["completeness"]["candidate_match"])
        self.assertFalse(result.extras["test_complete"])
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "BLOCKED")

    def test_T28_excluded_runtime_output_not_mismatch(self):
        profile, command = passing_profile("runtime-out")
        command["argv"] = py_command(
            "from pathlib import Path; p=Path('.scaffold/runtime/tmp-out.txt'); p.parent.mkdir(parents=True, exist_ok=True); p.write_text('tmp\\n', encoding='utf-8'); print('ok')"
        )
        write_host(self.host, [(profile, command)])
        result = test_engine(self.host).run()
        self.assertTrue(result.extras["completeness"]["candidate_match"])
        self.assertTrue(result.extras["test_pass"])

    def test_T29_incomplete_run_is_not_pass_report(self):
        write_host(self.host, [passing_profile()])
        incomplete = self.host / ".scaffold/runtime/test-runs/testrun-incomplete"
        (incomplete / "incomplete").mkdir(parents=True)
        write_yaml_atomic(incomplete / "incomplete" / "run.yaml", {"status": "PREPARING"})
        self.assertFalse(is_completed_pass_report(incomplete / "report.yaml"))
        self.assertEqual(list_completed_reports(self.host), [])

    def test_T30_completed_report_survives_reread(self):
        write_host(self.host, [passing_profile()])
        first = test_engine(self.host).run()
        run_id = first.extras["report_id"]
        loaded = test_engine(self.host).load_report(run_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["report_id"], run_id)
        self.assertEqual(loaded["report_status"], "COMPLETED")

    def test_T31_report_schema_roundtrip(self):
        write_host(self.host, [passing_profile()])
        report = test_engine(self.host).run().extras["report"]
        self.assertEqual(validate_report(report)[0], "VALID")
        self.assertTrue(reports_equal(report, roundtrip(report)))

    def test_T32_evidence_ref_resolves(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        refs = result.extras["report"]["evidence_refs"]
        self.assertTrue(refs)
        ok, text, issues = resolve_evidence_ref(self.host, refs[0])
        self.assertTrue(ok, issues)
        self.assertIn("P6_PASS", text)

    def test_T33_large_stdout_is_referenced(self):
        profile, command = passing_profile("big")
        command["argv"] = py_command("print('X' * 8000)")
        write_host(self.host, [(profile, command)])
        result = test_engine(self.host).run()
        logs = [item for item in result.extras["report"]["evidence"] if item.get("stream") == "stdout"]
        self.assertTrue(logs[0]["truncated"])
        self.assertLess(len(logs[0]["inline"]), 8000)
        self.assertTrue(result.extras["report"]["evidence_refs"])

    def test_T34_no_environment_dump(self):
        write_host(self.host, [passing_profile()])
        dumped = str(test_engine(self.host).run().extras["report"])
        self.assertNotIn("os.environ", dumped)
        self.assertNotIn("SECRET_TOKEN", dumped)

    def test_T35_no_task_book_required(self):
        write_host(self.host, [passing_profile()])
        self.assertFalse((self.host / ".scaffold/tasks").exists())
        result = test_engine(self.host).run()
        self.assertTrue(result.extras["test_pass"])

    def test_T36_no_develop_session_required(self):
        write_host(self.host, [passing_profile()])
        self.assertFalse((self.host / ".scaffold/runtime/develop-sessions").exists())
        result = test_engine(self.host).run()
        self.assertTrue(result.extras["test_pass"])

    def test_T37_optional_refs_do_not_change_candidate(self):
        write_host(self.host, [passing_profile()])
        before = observe_candidate(self.host).digest
        test_engine(self.host).run(task_book="task-1", develop_session="dev-1")
        after = observe_candidate(self.host).digest
        self.assertEqual(before, after)

    def test_T38_never_submit_authorized(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        self.assertNotEqual(result.extras.get("submit_authorized"), True)
        self.assertNotIn("submit_authorized", result.extras["report"])
        self.assertNotIn("submit_authorized", result.extras["completeness"])

    def test_T39_never_finalizes_change_record(self):
        write_host(self.host, [passing_profile()])
        test_engine(self.host).run()
        self.assertFalse((self.host / ".scaffold/changes").exists())
        self.assertIsNone(test_engine(self.host).run().extras["report"]["change_record"])

    def test_T40_never_commits_or_pushes(self):
        write_host(self.host, [passing_profile()])
        init_git(self.host)
        before = git(self.host, "rev-parse", "HEAD")
        test_engine(self.host).run()
        self.assertEqual(git(self.host, "rev-parse", "HEAD"), before)
        log = git(self.host, "log", "-1", "--format=%s")
        self.assertEqual(log, "baseline")

    def test_T41_failure_routes_without_source_repair(self):
        write_host(self.host, [failing_profile()])
        write(self.host, "src/app.py", "VALUE=1\n")
        before = file_digest(self.host / "src/app.py")
        result = test_engine(self.host).run()
        self.assertEqual(result.next_route, "develop_or_human")
        self.assertEqual(file_digest(self.host / "src/app.py"), before)

    def test_T42_unknown_contract_routes_refresh(self):
        profile = {
            "id": "observed-tests",
            "paths": ["tests"],
            "policy": "observed",
            "required": True,
        }
        write(self.host, "README.md", "# observed\n")
        write_project(self.host)
        write_commands(self.host, [])
        write_tests(self.host, [profile], applicability="UNKNOWN", confidence="UNKNOWN")
        result = test_engine(self.host).run()
        self.assertEqual(result.next_route, "understand.refresh")
        self.assertFalse(result.extras["test_complete"])

    def test_T43_adapter_independent_of_orchestration(self):
        adapter = LocalTargetAdapter()
        self.assertEqual(adapter.identity, "local")
        obs = adapter.execute(
            command=py_command("print(7)"),
            working_directory=self.host,
            timeout_seconds=5,
        )
        self.assertEqual(obs.exit_code, 0)
        self.assertIn("7", obs.stdout)

    def test_T44_compiler_preserves_fail(self):
        self.assertEqual(preserve_verification_truth("FAIL"), "FAIL")
        self.assertEqual(preserve_verification_truth("PASS"), "PASS")
        write_host(self.host, [failing_profile()])
        result = test_engine(self.host).run()
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "FAIL")
        self.assertFalse(result.extras["test_pass"])

    def test_T45_pass_and_complete_independent(self):
        write_host(self.host, [passing_profile("ok"), failing_profile("bad")])
        mixed = test_engine(self.host).run().extras["completeness"]
        write_host(self.host, [passing_profile("only")])
        only = test_engine(self.host).run(selected=[]).extras["completeness"]
        self.assertTrue(mixed["test_complete"])
        self.assertFalse(mixed["test_pass"])
        self.assertFalse(only["test_complete"])
        self.assertFalse(only["test_pass"])

    def test_T46_complete_does_not_authorize_submit(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        self.assertTrue(result.extras["test_complete"])
        self.assertNotEqual(result.extras.get("submit_authorized"), True)
        self.assertNotIn("submit_authorized", result.extras["report"])

    def test_T47_required_fail_is_terminal_usable(self):
        write_host(self.host, [failing_profile()])
        c = test_engine(self.host).run().extras["completeness"]
        self.assertEqual(c["required_terminal_usable"], 1)
        self.assertEqual(c["required_fail"], 1)
        self.assertTrue(c["test_complete"])

    def test_T48_required_blocked_not_terminal_usable(self):
        profile, _command = passing_profile("gone")
        write(self.host, "README.md", "# gone\n")
        write_project(self.host)
        write_commands(self.host, [])
        write_tests(self.host, [profile])
        c = test_engine(self.host).run().extras["completeness"]
        self.assertEqual(c["required_blocked"], 1)
        self.assertEqual(c["required_terminal_usable"], 0)
        self.assertFalse(c["test_complete"])

    def test_T49_candidate_a_not_reusable_for_b(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        report = result.extras["report"]
        write(self.host, "src/changed.py", "print(2)\n")
        current = observe_candidate(self.host)
        self.assertFalse(report_usable_for(report, current))
        self.assertFalse(test_engine(self.host).report_usable_for_current(report))

    def test_T50_noscms_fingerprint_mismatch(self):
        write_host(self.host, [passing_profile()])
        a = observe_candidate(self.host)
        write(self.host, "other.txt", "B\n")
        b = observe_candidate(self.host)
        self.assertEqual(a.kind, "none")
        self.assertNotEqual(a.digest, b.digest)

    def test_T51_malformed_project_non_executable(self):
        write_host(self.host, [passing_profile()])
        write(self.host, ".scaffold/project.yaml", "not a mapping\n")
        result = test_engine(self.host).run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("non-executable" in item for item in result.blockers))

    def test_T52_illegal_core_ownership_non_executable(self):
        write_host(self.host, [passing_profile()])
        project = read_yaml(self.host / ".scaffold/project.yaml")
        project["ownership"][".scaffold/tests.yaml"] = "HUMAN_OWNED"
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        status, reasons = validate_project_data(project)
        self.assertEqual(status, "INCOMPLETE")
        self.assertTrue(any("HUMAN_OWNED" in item for item in reasons))
        result = test_engine(self.host).run()
        self.assertEqual(result.outcome, "BLOCKED")

    def test_T53_human_owned_docs_not_overwritten(self):
        write_host(self.host, [passing_profile()])
        write(self.host, "docs/project/testing.md", "# Human testing\n")
        project = read_yaml(self.host / ".scaffold/project.yaml")
        project["ownership"]["docs/project/testing.md"] = "HUMAN_OWNED"
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        before = file_digest(self.host / "docs/project/testing.md")
        test_engine(self.host).run()
        self.assertEqual(file_digest(self.host / "docs/project/testing.md"), before)

    def test_T54_project_yaml_not_rewritten_on_pass(self):
        write_host(self.host, [passing_profile()])
        before = file_digest(self.host / ".scaffold/project.yaml")
        result = test_engine(self.host).run()
        self.assertTrue(result.extras["test_pass"])
        self.assertEqual(file_digest(self.host / ".scaffold/project.yaml"), before)

    def test_T55_not_fourth_canonical_record(self):
        write_host(self.host, [passing_profile()])
        report = test_engine(self.host).run().extras["report"]
        self.assertEqual(report["record_class"], "support_artifact")
        self.assertEqual(report["kind"], "test_report")
        self.assertNotIn(report["record_class"], ("task_book", "develop_session", "change_record"))

    def test_T56_p5_suite_still_collects_184(self):
        loader = unittest.defaultTestLoader
        suite = loader.discover(str(REPO / "tests"), pattern="test_p5*.py")
        self.assertEqual(suite.countTestCases(), 184)
        self.assertEqual(len(COMPAT_RESULTS), 5)
        self.assertEqual(CORE_SKILLS, ("understand", "develop", "test", "submit"))


if __name__ == "__main__":
    unittest.main()

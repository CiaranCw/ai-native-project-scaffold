from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import (
    REPO_TEST,
    dummy_lock_entry,
    failing_profile,
    four_core_lock_skills,
    init_git,
    passing_profile,
    py_command,
    test_engine,
    write_commands,
    write_host,
    write_lock,
    write_project,
    write_modules,
    write_skill_package,
    write_tests,
)
from support import REPO, write
from scaffold_p5.io_util import file_digest, read_yaml
from scaffold_p5.models import COMPAT_RESULTS, CORE_SKILLS
from scaffold_p6.analysis import analyze
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.engine import TestEngine
from scaffold_p6.models import SKILL_VERSION, ScenarioResult
from scaffold_p6.schemas import validate_report
from scaffold_p6.storage import (
    is_completed_pass_report,
    load_completed_report,
    prepare_run,
    publish_completed_report,
    resolve_evidence_ref,
    write_evidence_blobs,
    write_summary,
)


class P6Rev1Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_U01_invalid_package_blocks(self):
        write_host(self.host, [passing_profile()])
        pkg = write_skill_package(
            Path(self._tmp.name) / "invalid-test",
            skill_version="not-a-version",
        )
        engine = TestEngine(self.host, pkg)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertFalse(result.extras["test_pass"])
        self.assertEqual(result.extras["package_validity"], "INVALID")
        self.assertEqual(result.skill_version, "not-a-version")
        self.assertNotEqual(result.skill_version, "2.0.0")

    def test_U02_active_missing_lock_blocks(self):
        write_host(self.host, [passing_profile()])
        (self.host / ".scaffold/skills.lock").unlink()
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertTrue(any("skills.lock" in item for item in result.blockers))

    def test_U03_active_lock_lacks_test_blocks(self):
        write_host(self.host, [passing_profile()])
        write_lock(
            self.host,
            {
                "understand": dummy_lock_entry("2.0.0", "0" * 64),
                "develop": dummy_lock_entry("2.0.0", "1" * 64),
                "submit": dummy_lock_entry("2.0.0", "3" * 64),
            },
        )
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)

    def test_U04_unresolvable_expected_package_blocks(self):
        write_host(self.host, [passing_profile()])
        skills = four_core_lock_skills(
            test_entry=dummy_lock_entry("9.9.9", "9" * 64)
        )
        write_lock(self.host, skills)
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertEqual(result.compatibility, "UNKNOWN")

    def test_U05_compatible_package_may_execute(self):
        write_host(self.host, [passing_profile()])
        lock_before = file_digest(self.host / ".scaffold/skills.lock")
        pkg = write_skill_package(
            Path(self._tmp.name) / "compat-test",
            skill_version="2.1.0",
            extra_manifest={
                "may_substitute_for": [
                    {"skill_id": "test", "skill_version": SKILL_VERSION}
                ]
            },
        )
        engine = TestEngine(self.host, pkg)
        result = engine.run()
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue(result.extras["test_pass"])
        self.assertEqual(result.skill_version, "2.1.0")
        self.assertEqual(result.compatibility, "COMPATIBLE")
        self.assertNotEqual(result.compatibility, "EXACT")
        self.assertEqual(result.extras["expected_package"]["skill_version"], SKILL_VERSION)
        self.assertEqual(result.extras["actual_package"]["skill_version"], "2.1.0")
        self.assertEqual(file_digest(self.host / ".scaffold/skills.lock"), lock_before)

    def test_U06_migration_required_blocks_without_mutation(self):
        write_host(
            self.host,
            [passing_profile()],
            project_contract_generation="2",
        )
        project_before = file_digest(self.host / ".scaffold/project.yaml")
        lock_before = file_digest(self.host / ".scaffold/skills.lock")
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.compatibility, "MIGRATION_REQUIRED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertEqual(file_digest(self.host / ".scaffold/project.yaml"), project_before)
        self.assertEqual(file_digest(self.host / ".scaffold/skills.lock"), lock_before)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertEqual(project.get("maintenance"), [])
        self.assertNotIn("NEEDS_MIGRATION", project.get("maintenance") or [])

    def test_U07_selected_pass_other_required_not_run(self):
        write_host(self.host, [passing_profile("ok"), passing_profile("other")])
        c = test_engine(self.host).run(selected=["ok"]).extras["completeness"]
        self.assertTrue(c["test_pass"])
        self.assertFalse(c["test_complete"])
        self.assertEqual(c["required_not_run"], 1)

    def test_U08_batch_pass_plus_fail(self):
        write_host(self.host, [passing_profile("ok"), failing_profile("bad")])
        c = test_engine(self.host).run().extras["completeness"]
        self.assertFalse(c["test_pass"])
        self.assertTrue(c["coverage_complete"])
        self.assertFalse(c["test_complete"])

    def test_U09_verified_zero_required_tests(self):
        write(self.host, "README.md", "# none\n")
        write_project(self.host)
        write_commands(self.host, [])
        write_tests(
            self.host,
            [],
            applicable=False,
            applicability="NOT_APPLICABLE",
            required_authority="VERIFIED",
        )
        c = test_engine(self.host).run().extras["completeness"]
        self.assertFalse(c["test_pass"])
        self.assertTrue(c["test_complete"])

    def test_U10_duplicate_profile_ids_block_before_execution(self):
        profile, command = passing_profile("dup")
        other, _cmd = passing_profile("dup")
        write_host(self.host, [(profile, command)])
        write_tests(self.host, [profile, other])
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertTrue(any("duplicate profile id" in item for item in result.blockers))

    def test_U11_empty_profile_id_blocks(self):
        profile, command = passing_profile("named")
        profile["id"] = ""
        write_host(self.host, [(profile, command)])
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertTrue(any("profile id" in item for item in result.blockers))

    def test_U12_required_string_true_blocks(self):
        profile, command = passing_profile("coerced")
        profile["required"] = "true"
        write_host(self.host, [(profile, command)])
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertTrue(any("required must be a boolean" in item for item in result.blockers))

    def test_U13_duplicate_command_ids_block(self):
        profile, command = passing_profile()
        write_host(self.host, [(profile, command)])
        write_commands(self.host, [command, dict(command)])
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertTrue(any("duplicate command id" in item for item in result.blockers))

    def test_U14_unknown_command_authority_not_executed(self):
        profile, command = passing_profile("unknown-cmd")
        command["confidence"] = "UNKNOWN"
        write_host(self.host, [(profile, command)])
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "BLOCKED")
        self.assertEqual(result.next_route, "understand.refresh")
        self.assertFalse(result.extras["test_pass"])

    def test_U15_conflicting_command_authority_not_executed(self):
        profile, command = passing_profile("conflict-cmd")
        command["confidence"] = "CONFLICTING"
        write_host(self.host, [(profile, command)])
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "BLOCKED")
        self.assertFalse(result.extras["test_pass"])

    def test_U16_inferred_only_required_is_not_authoritative(self):
        profile = {
            "id": "observed-required",
            "purpose": "detected tests",
            "required": True,
            "policy": "observed",
        }
        write(self.host, "README.md", "# observed\n")
        write_project(self.host)
        write_commands(self.host, [])
        write_tests(self.host, [profile], confidence="VERIFIED")
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertFalse(result.extras["test_complete"])
        self.assertEqual(result.next_route, "understand.refresh")
        self.assertTrue(
            any("authoritative" in item or "INFERRED" in item for item in result.blockers)
        )

    def test_U17_supplied_local_execution_rejected(self):
        write_host(self.host, [passing_profile("ext")])
        digest = observe_candidate(self.host).digest
        engine = test_engine(self.host)
        result = engine.run(
            supplied_evidence=[
                {
                    "profile_id": "ext",
                    "provenance": "LOCAL_EXECUTION",
                    "kind": "command_result",
                    "result": "PASS",
                    "candidate_digest": digest,
                }
            ]
        )
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "BLOCKED")
        self.assertFalse(result.extras["test_pass"])
        self.assertFalse(result.extras["report"]["evidence"])

    def test_U18_unsupported_supplied_provenance_rejected(self):
        write_host(self.host, [passing_profile("ext")])
        engine = test_engine(self.host)
        result = engine.run(
            supplied_evidence=[
                {
                    "profile_id": "ext",
                    "provenance": "NETWORK_RESULT",
                    "kind": "structured_assertion",
                    "result": "PASS",
                    "candidate_digest": observe_candidate(self.host).digest,
                }
            ]
        )
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "BLOCKED")
        self.assertFalse(result.extras["test_pass"])

    def test_U19_external_result_wrong_candidate_unusable(self):
        profile, command = passing_profile("ext")
        profile["provenance"] = "EXTERNAL_RESULT"
        write_host(self.host, [(profile, command)])
        other = observe_candidate(self.host).digest
        write(self.host, "other-candidate.txt", "B\n")
        result = test_engine(self.host).run(
            supplied_evidence=[
                {
                    "profile_id": "ext",
                    "provenance": "EXTERNAL_RESULT",
                    "kind": "structured_assertion",
                    "result": "PASS",
                    "candidate_digest": other,
                }
            ]
        )
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "BLOCKED")
        self.assertFalse(result.extras["test_complete"])
        self.assertFalse(result.extras["completeness"]["evidence_complete"])

    def test_U20_human_observation_mismatched_candidate_unusable(self):
        profile, command = passing_profile("human")
        profile["provenance"] = "HUMAN_OBSERVATION"
        write_host(self.host, [(profile, command)])
        result = test_engine(self.host).run(
            supplied_evidence=[
                {
                    "profile_id": "human",
                    "provenance": "HUMAN_OBSERVATION",
                    "kind": "human_observation",
                    "result": "PASS",
                    "candidate_digest": "a" * 64,
                }
            ]
        )
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "BLOCKED")
        self.assertFalse(result.extras["test_complete"])

    def test_U21_ci_result_mismatched_candidate_unusable(self):
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
                    "candidate_digest": "b" * 64,
                }
            ]
        )
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "BLOCKED")
        self.assertFalse(result.extras["test_complete"])

    def test_U22_required_visual_actual_structured_incomplete(self):
        profile, command = passing_profile("visual")
        profile["provenance"] = "EXTERNAL_RESULT"
        profile["evidence_required"] = ["visual_checkpoint"]
        write_host(self.host, [(profile, command)])
        digest = observe_candidate(self.host).digest
        result = test_engine(self.host).run(
            supplied_evidence=[
                {
                    "profile_id": "visual",
                    "provenance": "EXTERNAL_RESULT",
                    "kind": "structured_assertion",
                    "result": "PASS",
                    "candidate_digest": digest,
                }
            ]
        )
        self.assertFalse(result.extras["completeness"]["evidence_complete"])
        self.assertFalse(result.extras["test_complete"])

    def test_U23_multiple_required_evidence_kinds(self):
        profile, command = passing_profile("multi")
        profile["evidence_required"] = ["command_result", "visual_checkpoint"]
        write_host(self.host, [(profile, command)])
        result = test_engine(self.host).run()
        self.assertFalse(result.extras["completeness"]["evidence_complete"])
        self.assertFalse(result.extras["test_complete"])

    def test_U24_unsupported_evidence_kind_blocked(self):
        profile, command = passing_profile("kind")
        profile["provenance"] = "EXTERNAL_RESULT"
        write_host(self.host, [(profile, command)])
        result = test_engine(self.host).run(
            supplied_evidence=[
                {
                    "profile_id": "kind",
                    "provenance": "EXTERNAL_RESULT",
                    "kind": "memory_dump",
                    "result": "PASS",
                    "candidate_digest": observe_candidate(self.host).digest,
                }
            ]
        )
        self.assertEqual(result.extras["report"]["profiles"][0]["result"], "BLOCKED")
        self.assertFalse(result.extras["test_pass"])

    def test_U25_gitignored_pytest_cache_does_not_stale(self):
        profile, command = passing_profile("cache")
        command["argv"] = py_command(
            "from pathlib import Path; "
            "p=Path('.pytest_cache/state'); p.parent.mkdir(parents=True, exist_ok=True); "
            "p.write_text('cache\\n', encoding='utf-8'); print('P6_PASS')"
        )
        write_host(self.host, [(profile, command)])
        init_git(self.host)
        result = test_engine(self.host).run()
        self.assertTrue((self.host / ".pytest_cache/state").exists())
        self.assertTrue(result.extras["completeness"]["candidate_match"])
        self.assertTrue(result.extras["test_pass"])

    def test_U26_explicit_generated_output_no_false_mismatch(self):
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
        init_git(self.host)
        result = test_engine(self.host).run()
        self.assertTrue((self.host / "build/out.txt").exists())
        self.assertTrue(result.extras["completeness"]["candidate_match"])
        self.assertTrue(result.extras["test_pass"])

    def test_U27_tracked_source_change_mismatches(self):
        profile, command = passing_profile("src")
        command["argv"] = py_command(
            "from pathlib import Path; Path('README.md').write_text('# changed\\n', encoding='utf-8')"
        )
        write_host(self.host, [(profile, command)])
        init_git(self.host)
        result = test_engine(self.host).run()
        self.assertFalse(result.extras["completeness"]["candidate_match"])
        self.assertFalse(result.extras["test_pass"])

    def test_U28_project_yaml_change_mismatches(self):
        profile, command = passing_profile("proj")
        command["argv"] = py_command(
            "from pathlib import Path; "
            "p=Path('.scaffold/project.yaml'); "
            "p.write_text(p.read_text(encoding='utf-8') + '\\n# mutated\\n', encoding='utf-8'); "
            "print('P6_PASS')"
        )
        write_host(self.host, [(profile, command)])
        result = test_engine(self.host).run()
        self.assertFalse(result.extras["completeness"]["candidate_match"])
        self.assertFalse(result.extras["test_complete"])

    def test_U29_gitignored_generated_output_not_candidate(self):
        write_host(self.host, [passing_profile()])
        init_git(self.host)
        before = observe_candidate(self.host)
        write(self.host, ".pytest_cache/state", "ignored\n")
        after = observe_candidate(self.host)
        self.assertEqual(before.digest, after.digest)

    def test_U30_nonignored_untracked_source_changes_candidate(self):
        write_host(self.host, [passing_profile()])
        init_git(self.host)
        before = observe_candidate(self.host)
        write(self.host, "src/new_module.py", "VALUE=1\n")
        after = observe_candidate(self.host)
        self.assertNotEqual(before.digest, after.digest)

    def test_U31_noscms_generated_exclusion_and_source_mismatch(self):
        profile, command = passing_profile("noscms")
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
        self.assertEqual(observe_candidate(self.host).kind, "none")
        self.assertTrue(result.extras["completeness"]["candidate_match"])
        write(self.host, "src/app.py", "VALUE=2\n")
        self.assertNotEqual(
            result.extras["report"]["candidate"]["candidate_digest"],
            observe_candidate(self.host).digest,
        )

    def test_U32_same_candidate_runs_have_distinct_ids(self):
        write_host(self.host, [passing_profile()])
        first = test_engine(self.host).run()
        second = test_engine(self.host).run()
        self.assertNotEqual(first.extras["report_id"], second.extras["report_id"])
        self.assertRegex(first.extras["report_id"], r"^testrun-\d{8}T\d{6}Z-[0-9a-f]{8}$")
        self.assertRegex(second.extras["report_id"], r"^testrun-\d{8}T\d{6}Z-[0-9a-f]{8}$")

    def test_U33_interruption_before_final_report_is_not_completed(self):
        write_host(self.host, [passing_profile()])
        dest = prepare_run(self.host, "testrun-crashgap", {"status": "PREPARING"})
        write_evidence_blobs(dest, {"unit-stdout.txt": "P6_PASS\n"})
        write_summary(dest, "# incomplete summary\n")
        self.assertIsNone(load_completed_report(self.host, "testrun-crashgap"))
        self.assertFalse(is_completed_pass_report(dest / "report.yaml"))
        write(dest, "report.yaml", "report_status: COMPLETED\n")
        self.assertTrue((dest / "incomplete/run.yaml").exists())
        self.assertIsNone(load_completed_report(self.host, "testrun-crashgap"))
        self.assertFalse(is_completed_pass_report(dest / "report.yaml"))

    def test_U34_report_validated_before_completed_publication(self):
        dest = prepare_run(self.host, "testrun-invalid", {"status": "PREPARING"})
        bad = {
            "schema_version": "1",
            "kind": "test_report",
            "record_class": "support_artifact",
            "report_id": "testrun-invalid",
            "report_status": "COMPLETED",
            "skill_id": "test",
            "skill_version": "2.0.0",
            "mode": "scoped_verification",
            "candidate": {"candidate_digest": "c" * 64},
            "candidate_match": True,
            "profiles": [],
            "completeness": {"test_pass": True, "test_complete": False},
            "verification": {"test_pass": True, "test_complete": False},
            "created_at": "2026-01-01T00:00:00Z",
            "evidence": [
                {
                    "kind": "command_result",
                    "provenance": "FORGED",
                    "profile_id": "unit",
                    "candidate_digest": "c" * 64,
                }
            ],
        }
        self.assertNotEqual(validate_report(bad)[0], "VALID")
        published, issues = publish_completed_report(dest, bad, "# bad\n")
        self.assertFalse(published)
        self.assertTrue(issues)
        self.assertFalse((dest / "report.yaml").exists())
        self.assertTrue((dest / "incomplete/run.yaml").exists())
        self.assertIsNone(load_completed_report(self.host, "testrun-invalid"))

    def test_U35_completed_readback_resolves_evidence_refs(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        loaded = test_engine(self.host).load_report(result.extras["report_id"])
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["report_status"], "COMPLETED")
        for ref in loaded["evidence_refs"]:
            ok, _text, issues = resolve_evidence_ref(self.host, ref)
            self.assertTrue(ok, issues)

    def test_U36_p5_suite_still_collects_184(self):
        loader = unittest.defaultTestLoader
        suite = loader.discover(str(REPO / "tests"), pattern="test_p5*.py")
        self.assertEqual(suite.countTestCases(), 184)
        self.assertEqual(len(COMPAT_RESULTS), 5)
        self.assertEqual(CORE_SKILLS, ("understand", "develop", "test", "submit"))

    def test_U37_generic_result_reports_actual_version(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        self.assertEqual(result.skill_version, SKILL_VERSION)
        self.assertEqual(result.extras["actual_package"]["skill_version"], SKILL_VERSION)
        self.assertEqual(result.extras["package"]["skill_version"], SKILL_VERSION)

    def test_U38_compatible_path_does_not_update_lock(self):
        write_host(self.host, [passing_profile()])
        lock_before = read_yaml(self.host / ".scaffold/skills.lock")
        pkg = write_skill_package(
            Path(self._tmp.name) / "compat-lock",
            skill_version="2.1.0",
            extra_manifest={
                "may_substitute_for": [
                    {"skill_id": "test", "skill_version": SKILL_VERSION}
                ]
            },
        )
        result = TestEngine(self.host, pkg).run()
        self.assertEqual(result.compatibility, "COMPATIBLE")
        self.assertEqual(result.extras["expected_package"]["skill_version"], SKILL_VERSION)
        self.assertEqual(result.extras["actual_package"]["skill_version"], "2.1.0")
        self.assertEqual(read_yaml(self.host / ".scaffold/skills.lock"), lock_before)

    def test_U39_unknown_compatibility_does_not_execute_adapter(self):
        write_host(self.host, [passing_profile()])
        write_lock(
            self.host,
            four_core_lock_skills(test_entry=dummy_lock_entry("9.9.9", "9" * 64)),
        )
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.compatibility, "UNKNOWN")
        self.assertEqual(engine.adapter_invocations, 0)

    def test_U40_incompatible_does_not_execute_adapter(self):
        write_host(self.host, [passing_profile()])
        pkg = write_skill_package(
            Path(self._tmp.name) / "incompat-test",
            skill_version="2.1.0",
            extra_manifest={"incompatible_with": [SKILL_VERSION]},
        )
        engine = TestEngine(self.host, pkg)
        result = engine.run()
        self.assertEqual(result.compatibility, "INCOMPATIBLE")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)

    def test_U41_malformed_tests_yaml_blocks_before_adapter(self):
        write_host(self.host, [passing_profile()])
        write(self.host, ".scaffold/tests.yaml", "this line has no colon\n")
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)

    def test_U42_malformed_commands_yaml_blocks_before_adapter(self):
        write_host(self.host, [passing_profile()])
        write(self.host, ".scaffold/commands.yaml", "not: a: mapping: broken\n[")
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)

    def test_U43_duplicate_profile_cannot_hide_blocked(self):
        blocked = ScenarioResult(
            profile_id="dup",
            required=True,
            result="BLOCKED",
            provenance="",
            adapter="local",
            command_ref="cmd",
            evidence_complete=False,
        )
        passed = ScenarioResult(
            profile_id="dup",
            required=True,
            result="PASS",
            provenance="LOCAL_EXECUTION",
            adapter="local",
            command_ref="cmd",
            evidence_complete=True,
        )
        c = analyze(
            required_ids=["dup"],
            optional_ids=[],
            results=[blocked, passed],
            candidate_match=True,
            verified_no_required=False,
            contract_blockers=[],
        )
        self.assertEqual(c["required_blocked"], 1)
        self.assertFalse(c["test_pass"])
        self.assertFalse(c["test_complete"])
        write_host(self.host, [passing_profile("dup")])
        write_tests(
            self.host,
            [
                passing_profile("dup")[0],
                {**passing_profile("dup")[0], "purpose": "second"},
            ],
        )
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertEqual(result.outcome, "BLOCKED")

    def test_U44_evidence_mismatch_not_repaired_by_analysis(self):
        profile, command = passing_profile("ext")
        profile["provenance"] = "EXTERNAL_RESULT"
        write_host(self.host, [(profile, command)])
        other = observe_candidate(self.host).digest
        write(self.host, "moved.txt", "B\n")
        result = test_engine(self.host).run(
            supplied_evidence=[
                {
                    "profile_id": "ext",
                    "provenance": "EXTERNAL_RESULT",
                    "kind": "structured_assertion",
                    "result": "PASS",
                    "candidate_digest": other,
                }
            ]
        )
        c = result.extras["completeness"]
        self.assertFalse(c["test_pass"])
        self.assertFalse(c["test_complete"])
        self.assertEqual(c["required_blocked"], 1)

    def test_U45_required_fail_is_terminal_usable(self):
        write_host(self.host, [failing_profile()])
        c = test_engine(self.host).run().extras["completeness"]
        self.assertFalse(c["test_pass"])
        self.assertTrue(c["coverage_complete"])
        self.assertFalse(c["test_complete"])
        self.assertEqual(c["required_fail"], 1)
        self.assertEqual(c["required_terminal_usable"], 1)

    def test_U46_required_blocked_is_not_terminal_usable(self):
        profile, command = passing_profile("blocked")
        command["confidence"] = "UNKNOWN"
        write_host(self.host, [(profile, command)])
        c = test_engine(self.host).run().extras["completeness"]
        self.assertEqual(c["required_blocked"], 1)
        self.assertEqual(c["required_terminal_usable"], 0)
        self.assertFalse(c["test_complete"])

    def test_U47_test_never_writes_submit_authorization(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        self.assertNotEqual(result.extras.get("submit_authorized"), True)
        self.assertNotIn("submit_authorized", result.extras["report"])
        dumped = str(result.extras["report"])
        self.assertNotIn("submit_authorized: true", dumped)

    def test_U48_test_never_changes_business_source(self):
        write_host(self.host, [passing_profile()])
        write(self.host, "src/app.py", "VALUE=1\n")
        before = file_digest(self.host / "src/app.py")
        test_engine(self.host).run()
        self.assertEqual(file_digest(self.host / "src/app.py"), before)

    def test_U49_human_observation_without_digest_binds_synchronously(self):
        profile, command = passing_profile("human")
        profile["provenance"] = "HUMAN_OBSERVATION"
        profile["evidence_required"] = ["human_observation"]
        write_host(self.host, [(profile, command)])
        current = observe_candidate(self.host).digest
        result = test_engine(self.host).run(
            supplied_evidence=[
                {
                    "profile_id": "human",
                    "provenance": "HUMAN_OBSERVATION",
                    "kind": "human_observation",
                    "result": "PASS",
                    "summary": "seen now",
                }
            ]
        )
        item = result.extras["report"]["evidence"][0]
        self.assertEqual(item["binding_mechanism"], "synchronous_invocation")
        self.assertEqual(item["candidate_digest"], current)
        self.assertTrue(result.extras["test_pass"])

    def test_U50_non_authoritative_lock_blocks(self):
        write_host(self.host, [passing_profile()])
        write_lock(self.host, authoritative=False)
        engine = test_engine(self.host)
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)


if __name__ == "__main__":
    unittest.main()

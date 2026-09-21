from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import (
    REPO_TEST,
    dummy_lock_entry,
    failing_profile,
    four_core_lock_skills,
    git,
    init_git,
    passing_profile,
    test_engine,
    write_commands,
    write_host,
    write_lock,
    write_project,
    write_tests,
)
from p8_support import (
    run_submit,
    TASK_A,
    bind_submit_lock,
    rebind_noscms_baseline,
    submit_engine,
    write_ready_task,
    write_submit_host,
)
from support import adopt, write
from scaffold_p5.full import _tests_data
from scaffold_p5.io_util import file_digest, read_yaml, write_yaml_atomic
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.models import SKILL_VERSION
from scaffold_p8.completeness import evaluate_completeness


def _observed_passing(profile_id: str = "observed-tests"):
    profile, command = passing_profile(profile_id, required=False)
    profile.pop("required", None)
    profile["policy"] = "observed"
    profile["required_authority"] = "UNKNOWN"
    return profile, command


class FA2Batch3TestPolicyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_B3T01_observed_profile_required_policy_remains_unknown(self):
        write(self.host, "README.md", "Synthetic nested tests.\n")
        write(
            self.host,
            "package.json",
            '{"name":"demo","scripts":{"test":"vitest run"}}\n',
        )
        write(self.host, "src/__tests__/a.test.ts", "export {}\n")
        result = adopt(self.host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        tests = read_yaml(self.host / ".scaffold/tests.yaml")
        self.assertTrue(tests["profiles"])
        self.assertEqual(tests.get("required_authority"), "UNKNOWN")
        for profile in tests["profiles"]:
            self.assertEqual(profile.get("required_authority"), "UNKNOWN")
            self.assertNotEqual(profile.get("required"), True)
            self.assertNotEqual(profile.get("required_authority"), "VERIFIED")
            if profile.get("id") == "observed-tests":
                self.assertEqual(profile.get("policy"), "observed")
            else:
                self.assertEqual(profile.get("policy"), "discovered_command")
                self.assertIs(profile.get("required"), False)
        self.assertNotEqual(tests.get("required"), True)

    def test_B3T02_observed_pass_is_not_test_complete(self):
        write_host(self.host, [_observed_passing()])
        write_tests(
            self.host,
            [_observed_passing()[0]],
            required_authority="UNKNOWN",
        )
        result = test_engine(self.host).run(selected=["observed-tests"])
        c = result.extras["completeness"]
        self.assertTrue(c["test_pass"])
        self.assertEqual(c["required_policy"], "UNKNOWN")
        self.assertFalse(c["required_set_authoritative"])
        self.assertFalse(c["test_complete"])
        self.assertFalse(c["verified_no_required_tests"])

    def test_B3T03_authoritative_required_pass_may_complete(self):
        write_host(self.host, [passing_profile("unit")])
        result = test_engine(self.host).run(selected=["unit"])
        c = result.extras["completeness"]
        self.assertTrue(c["test_pass"])
        self.assertTrue(c["coverage_complete"])
        self.assertTrue(c["test_complete"])
        self.assertEqual(c["required_policy"], "VERIFIED")

    def test_B3T04_required_fail_is_not_test_complete(self):
        write_host(self.host, [failing_profile("unit")])
        c = test_engine(self.host).run().extras["completeness"]
        self.assertEqual(c["required_fail"], 1)
        self.assertEqual(c["required_terminal_usable"], 1)
        self.assertTrue(c["coverage_complete"])
        self.assertFalse(c["test_complete"])

    def test_B3T05_mixed_required_terminal_fail_is_not_complete(self):
        write_host(self.host, [passing_profile("ok"), failing_profile("bad")])
        c = test_engine(self.host).run().extras["completeness"]
        self.assertEqual(c["required_fail"], 1)
        self.assertEqual(c["required_terminal_usable"], 2)
        self.assertTrue(c["coverage_complete"])
        self.assertFalse(c["test_complete"])

    def test_B3T06_required_not_run_has_reason_and_is_incomplete(self):
        write_host(self.host, [passing_profile("ok"), passing_profile("other")])
        result = test_engine(self.host).run(selected=["ok"])
        c = result.extras["completeness"]
        skipped = next(
            row for row in result.extras["report"]["profiles"] if row["id"] == "other"
        )
        self.assertEqual(skipped["result"], "NOT_RUN")
        self.assertEqual(skipped["not_run_reason"], "not_selected")
        self.assertEqual(c["required_not_run"], 1)
        self.assertFalse(c["test_complete"])

    def test_B3T07_optional_not_run_is_not_failure_or_required_satisfaction(self):
        required, req_cmd = passing_profile("req")
        optional, opt_cmd = passing_profile("opt", required=False)
        write_host(self.host, [(required, req_cmd), (optional, opt_cmd)])
        result = test_engine(self.host).run()
        opt = next(
            row for row in result.extras["report"]["profiles"] if row["id"] == "opt"
        )
        c = result.extras["completeness"]
        self.assertEqual(opt["result"], "NOT_RUN")
        self.assertEqual(opt["not_run_reason"], "not_selected")
        self.assertNotEqual(opt["result"], "FAIL")
        self.assertTrue(c["test_complete"])
        self.assertTrue(c["test_pass"])

    def test_B3T08_authoritative_zero_required_is_not_unknown(self):
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
        zero = test_engine(self.host).run().extras["completeness"]
        write_tests(self.host, [], confidence="INFERRED")
        unknown = test_engine(self.host).run().extras["completeness"]
        self.assertTrue(zero["required_set_authoritative"])
        self.assertTrue(zero["verified_no_required_tests"])
        self.assertEqual(zero["required_policy"], "VERIFIED")
        self.assertTrue(zero["test_complete"])
        self.assertFalse(unknown["required_set_authoritative"])
        self.assertEqual(unknown["required_policy"], "UNKNOWN")
        self.assertFalse(unknown["test_complete"])
        self.assertNotEqual(zero["required_policy"], unknown["required_policy"])

    def test_B3T09_pf1_observed_fixture_is_not_authoritative_optional(self):
        write(self.host, "README.md", "Synthetic nested tests.\n")
        write(
            self.host,
            "package.json",
            '{"name":"demo","scripts":{"test":"vitest run"}}\n',
        )
        write(self.host, "src/__tests__/a.test.ts", "export {}\n")
        result = adopt(self.host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        tests = read_yaml(self.host / ".scaffold/tests.yaml")
        self.assertTrue(tests["profiles"])
        self.assertEqual(tests["profiles"][0]["id"], "observed-tests")
        self.assertIn("src/__tests__", tests["profiles"][0]["paths"])
        self.assertIsNot(tests["profiles"][0].get("required"), False)
        self.assertEqual(tests["profiles"][0].get("required_authority"), "UNKNOWN")

    def test_B3T10_p8_s5_blocks_required_fail(self):
        self._prepare_submit_profiles([failing_profile("unit")])
        digest = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["completeness"]["test_complete"])
        self.assertTrue(result.extras["completeness"]["coverage_complete"])
        self.assertFalse(result.extras["s10"]["durable"])
        self.assertNotEqual(result.next_route, "develop.repair")
        self.assertEqual(result.next_route, "human")
        self.assertTrue(
            any("repair target Stage mapping unresolved" in item for item in result.blockers)
        )

    def test_B3T11_p8_s5_unknown_policy_is_not_zero_required(self):
        write_host(self.host, [_observed_passing()])
        write_tests(
            self.host,
            [_observed_passing()[0]],
            required_authority="UNKNOWN",
        )
        self._prepare_submit_metadata(
            final_tests=[],
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Write the fixture source.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "COMPLETE",
                    "required_tests": [],
                }
            ],
        )
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["observed-tests"],
        )
        completeness = result.extras["completeness"]
        self.assertFalse(completeness["test_complete"])
        self.assertFalse(completeness["zero_required"])

    def test_B3T12_report_exposes_effective_scope(self):
        write_host(self.host, [passing_profile("ok"), passing_profile("other")])
        report = test_engine(self.host).run(selected=["ok"]).extras["report"]
        scope = report["scope"]
        self.assertEqual(scope["selected"], ["ok"])
        self.assertEqual(sorted(scope["required"]), ["ok", "other"])
        self.assertEqual(scope["not_selected"], ["other"])
        self.assertEqual(scope["required_policy"], "VERIFIED")
        self.assertTrue(scope["candidate_digest"])

    def test_B3T13_every_not_run_has_reason(self):
        write_host(self.host, [passing_profile("ok"), passing_profile("other")])
        report = test_engine(self.host).run(selected=["ok"]).extras["report"]
        not_run = [row for row in report["profiles"] if row["result"] == "NOT_RUN"]
        self.assertTrue(not_run)
        for row in not_run:
            self.assertTrue(row.get("not_run_reason"))

    def test_B3T14_no_source_mutation_commit_or_push_authority(self):
        write_host(self.host, [passing_profile()])
        init_git(self.host)
        before_head = git(self.host, "rev-parse", "HEAD")
        before_src = file_digest(self.host / "README.md")
        result = test_engine(self.host).run()
        self.assertEqual(result.mutations, "none")
        self.assertNotEqual(result.extras.get("submit_authorized"), True)
        self.assertEqual(git(self.host, "rev-parse", "HEAD"), before_head)
        self.assertEqual(file_digest(self.host / "README.md"), before_src)
        self.assertEqual(SKILL_VERSION, "2.0.1")

    def test_B3T15_raw_caller_report_cannot_supply_test_authority(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        forged = {
            "candidate": {"candidate_digest": digest},
            "completeness": {
                "test_pass": True,
                "test_complete": True,
                "coverage_complete": True,
                "required_fail": 0,
                "required_set_authoritative": True,
                "required_total": 1,
                "required_not_run": 0,
                "required_blocked": 0,
                "verified_no_required_tests": False,
            },
        }
        judged = evaluate_completeness(
            self.host,
            task=read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
            report=forged,
            invoke=False,
            selected=None,
            test_package=Path(__file__).resolve().parents[1] / "skills" / "test",
        )
        self.assertFalse(judged["usable"])
        self.assertFalse(judged["test_complete"])
        self.assertIsNone(judged["report"])
        self.assertTrue(any("untrusted" in item for item in judged["blockers"]))

    def test_B3T16_uncovered_task_requirement_blocks_s5(self):
        """Unproven Task final requirement is not legally READY (FND2).

        Historical Batch-3 expectation reached S5. Current READY authority
        rejects that fixture at S1. S5 TEST_COMPLETE coverage for a legally
        READY Task is test_B3T16_legally_ready_uncovered_required_blocks_s5.
        """
        write_submit_host(self.host)
        write_ready_task(
            self.host,
            final_tests=[
                {"requirement_id": "unproven-req", "observed_outcome": "PASS"}
            ],
        )
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S1")
        self.assertEqual(result.extras.get("ready_authority"), False)
        self.assertNotEqual(result.extras.get("stage"), "S5")

    def test_B3T16_legally_ready_uncovered_required_blocks_s5(self):
        """S5 still blocks incomplete required verification for a legally READY Task."""
        self._prepare_submit_profiles(
            [passing_profile("unit"), passing_profile("other")]
        )
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S5")
        self.assertEqual(result.next_route, "test.scoped_verification")
        completeness = result.extras["completeness"]
        self.assertIn("other", completeness["required_ids"])
        self.assertIn("other", completeness["uncovered_required_ids"])
        self.assertFalse(completeness["test_complete"])

    def test_B3R01_verified_test_absence_is_not_required_policy(self):
        generated = self._write_p5_verified_absence_host()
        self.assertIs(generated["applicable"], False)
        self.assertEqual(generated["applicability"], "NOT_APPLICABLE")
        self.assertEqual(generated["confidence"], "VERIFIED")
        self.assertEqual(generated["required_authority"], "UNKNOWN")

        completeness = test_engine(self.host).run().extras["completeness"]
        self.assertFalse(completeness["required_set_authoritative"])
        self.assertFalse(completeness["verified_no_required_tests"])
        self.assertFalse(completeness["test_complete"])

    def test_B3R02_p8_does_not_treat_discovered_absence_as_zero_required(self):
        self._write_p5_verified_absence_host()
        judged = evaluate_completeness(
            self.host,
            task={
                "record_id": TASK_A,
                "scope": {"paths": [], "modules": [], "exclude": []},
                "final_tests": [],
                "stages": [],
            },
            report=None,
            invoke=True,
            selected=[],
            test_package=REPO_TEST,
        )
        self.assertTrue(judged["usable"])
        self.assertFalse(judged["zero_required"])
        self.assertFalse(judged["test_complete"])

    def test_B3R03_explicit_zero_required_authority_is_preserved(self):
        write(self.host, "README.md", "# explicit zero-required policy\n")
        write_project(self.host)
        write_commands(self.host, [])
        write_tests(
            self.host,
            [],
            applicable=False,
            applicability="NOT_APPLICABLE",
            confidence="VERIFIED",
            required_authority="VERIFIED",
        )
        completeness = test_engine(self.host).run().extras["completeness"]
        self.assertTrue(completeness["required_set_authoritative"])
        self.assertTrue(completeness["verified_no_required_tests"])
        self.assertTrue(completeness["test_complete"])

    def test_B3R04_verified_empty_set_without_policy_authority_is_unknown(self):
        write(self.host, "README.md", "# availability-only absence\n")
        write_project(self.host)
        write_commands(self.host, [])
        write_tests(
            self.host,
            [],
            applicable=False,
            applicability="NOT_APPLICABLE",
            confidence="VERIFIED",
        )
        completeness = test_engine(self.host).run().extras["completeness"]
        self.assertFalse(completeness["required_set_authoritative"])
        self.assertFalse(completeness["verified_no_required_tests"])
        self.assertEqual(completeness["required_policy"], "UNKNOWN")
        self.assertFalse(completeness["test_complete"])

    def test_B3R05_pf1_observation_remains_unknown_to_p6(self):
        write(self.host, "README.md", "Synthetic nested tests.\n")
        write(
            self.host,
            "package.json",
            '{"name":"demo","scripts":{"test":"vitest run"}}\n',
        )
        write(self.host, "src/__tests__/a.test.ts", "export {}\n")
        adopted = adopt(self.host)
        self.assertEqual(adopted.outcome, "COMPLETED", adopted.blockers)
        tests = read_yaml(self.host / ".scaffold/tests.yaml")
        self.assertEqual(tests["required_authority"], "UNKNOWN")

        completeness = test_engine(self.host).run().extras["completeness"]
        self.assertFalse(completeness["required_set_authoritative"])
        self.assertFalse(completeness["verified_no_required_tests"])
        self.assertFalse(completeness["test_complete"])

    def test_B3R06_direct_test_report_retains_area_scope(self):
        write_host(self.host, [passing_profile("unit")])
        report = test_engine(self.host).run(
            selected=["unit"],
            scope_paths=["src/core"],
            scope_modules=["core"],
        ).extras["report"]
        self.assertEqual(report["scope"]["paths"], ["src/core"])
        self.assertEqual(report["scope"]["modules"], ["core"])

    def test_B3R07_empty_area_scope_remains_empty(self):
        write_host(self.host, [passing_profile("unit")])
        report = test_engine(self.host).run(
            selected=["unit"],
            scope_paths=[],
            scope_modules=[],
        ).extras["report"]
        self.assertEqual(report["scope"]["paths"], [])
        self.assertEqual(report["scope"]["modules"], [])

    def test_B3R08_p8_task_scope_is_retained_by_p6_report(self):
        write_submit_host(self.host)
        task = write_ready_task(
            self.host,
            scope={
                "paths": ["src/core"],
                "modules": ["core"],
                "exclude": [],
            },
        )
        judged = evaluate_completeness(
            self.host,
            task=task,
            report=None,
            invoke=True,
            selected=["unit"],
            test_package=REPO_TEST,
        )
        report = judged["report"]
        self.assertTrue(judged["usable"])
        self.assertEqual(report["scope"]["paths"], ["src/core"])
        self.assertEqual(report["scope"]["modules"], ["core"])

    def test_B3R09_shared_scope_excludes_machine_absolute_paths(self):
        write_host(self.host, [passing_profile("unit")])
        report = test_engine(self.host).run(
            selected=["unit"],
            scope_paths=["src/core", r"F:\private\workspace"],
            scope_modules=["core", r"C:\private\module"],
        ).extras["report"]
        scope = report["scope"]
        self.assertEqual(scope["paths"], ["src/core"])
        self.assertEqual(scope["modules"], ["core"])
        self.assertNotIn("F:", str(scope))
        self.assertNotIn("C:", str(scope))

    def test_B3R10_selected_optional_pass_is_terminally_covered(self):
        required, required_command = passing_profile("required")
        optional, optional_command = passing_profile("optional", required=False)
        write_host(
            self.host,
            [(required, required_command), (optional, optional_command)],
        )
        completeness = test_engine(self.host).run(
            selected=["required", "optional"]
        ).extras["completeness"]
        self.assertTrue(completeness["coverage_complete"])
        self.assertTrue(completeness["test_complete"])
        self.assertEqual(completeness["required_fail"], 0)

    def test_B3R11_selected_optional_blocked_breaks_coverage_not_obligation(self):
        required, required_command = passing_profile("required")
        optional, optional_command = passing_profile("optional", required=False)
        optional_command["confidence"] = "UNKNOWN"
        write_host(
            self.host,
            [(required, required_command), (optional, optional_command)],
        )
        result = test_engine(self.host).run(selected=["required", "optional"])
        completeness = result.extras["completeness"]
        optional_result = next(
            row for row in result.extras["report"]["profiles"]
            if row["id"] == "optional"
        )
        self.assertEqual(optional_result["result"], "BLOCKED")
        self.assertFalse(completeness["coverage_complete"])
        self.assertTrue(completeness["test_complete"])
        self.assertEqual(completeness["required_blocked"], 0)
        self.assertEqual(completeness["required_fail"], 0)

    def test_B3R12_unselected_optional_is_outside_selected_coverage(self):
        required, required_command = passing_profile("required")
        optional, optional_command = passing_profile("optional", required=False)
        write_host(
            self.host,
            [(required, required_command), (optional, optional_command)],
        )
        result = test_engine(self.host).run(selected=["required"])
        completeness = result.extras["completeness"]
        optional_result = next(
            row for row in result.extras["report"]["profiles"]
            if row["id"] == "optional"
        )
        self.assertTrue(completeness["coverage_complete"])
        self.assertTrue(completeness["test_complete"])
        self.assertNotIn("optional", completeness["selected"])
        self.assertIn("optional", completeness["not_selected"])
        self.assertEqual(optional_result["result"], "NOT_RUN")
        self.assertEqual(optional_result["not_run_reason"], "not_selected")

    def test_B3R13_test_201_substitutes_for_200_without_lock_rewrite(self):
        write_host(self.host, [passing_profile("unit")])
        write_lock(
            self.host,
            four_core_lock_skills(
                test_entry=dummy_lock_entry("2.0.0", "0" * 64)
            ),
        )
        lock_before = read_yaml(self.host / ".scaffold/skills.lock")
        result = test_engine(self.host).run(selected=["unit"])
        self.assertEqual(result.compatibility, "COMPATIBLE")
        self.assertEqual(
            result.extras["expected_package"]["skill_version"], "2.0.0"
        )
        self.assertEqual(
            result.extras["actual_package"]["skill_version"], "2.0.1"
        )
        self.assertEqual(
            read_yaml(self.host / ".scaffold/skills.lock"), lock_before
        )

    def test_B3R14_review_only_required_fail_stops_at_s5(self):
        self._prepare_submit_profiles([failing_profile("unit")])
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S5")
        self.assertNotEqual(result.next_route, "develop.repair")
        self.assertEqual(result.next_route, "human")
        self.assertFalse(result.extras["completeness"]["test_complete"])
        self.assertIsNone(result.extras["repair_handoff"])

    def test_B3R15_s5_failure_does_not_invoke_before_s7(self):
        self._prepare_submit_profiles([failing_profile("unit")])
        calls: list[str] = []
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            before_s7=lambda: calls.append("called"),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S5")
        self.assertEqual(calls, [])

    def test_B3R16_unknown_required_policy_stops_at_s5(self):
        self._write_p5_verified_absence_host()
        self._prepare_submit_metadata(
            final_tests=[],
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Review the no-test fixture.",
                    "acceptance": "Review remains policy-aware.",
                    "status": "COMPLETE",
                    "required_tests": [],
                }
            ],
        )
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=[],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S5")
        self.assertEqual(result.next_route, "test.scoped_verification")
        self.assertFalse(result.extras["completeness"]["test_complete"])
        self.assertFalse(result.extras["completeness"]["zero_required"])

    def test_B3R17_required_pass_review_only_may_reach_s6(self):
        write_submit_host(self.host)
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.extras["stage"], "S6")
        self.assertTrue(result.extras["completeness"]["test_complete"])

    def test_B3R18_optional_fail_is_not_a_required_s10_gate(self):
        required, required_command = passing_profile("unit")
        optional, optional_command = failing_profile("visual")
        optional["required"] = False
        self._prepare_submit_profiles(
            [(required, required_command), (optional, optional_command)]
        )
        test_result = test_engine(self.host).run(
            selected=["unit", "visual"]
        )
        completeness = test_result.extras["completeness"]
        report = test_result.extras["report"]
        self.assertFalse(completeness["test_pass"])
        self.assertEqual(completeness["required_fail"], 0)
        self.assertTrue(completeness["test_complete"])
        optional_result = next(
            row for row in report["profiles"] if row["id"] == "visual"
        )
        self.assertEqual(optional_result["result"], "FAIL")
        self.assertFalse(optional_result["required"])

        digest = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=test_result.extras["report_id"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras["s10"]["durable"])
        self.assertFalse(result.extras["test_pass"])
        self.assertTrue(result.extras["test_complete"])
        self.assertFalse(any(
            "TEST_PASS does not hold for required tests" in blocker
            for blocker in result.blockers
        ))

    def test_B3R19_required_fail_optional_pass_stops_at_s5(self):
        required, required_command = failing_profile("unit")
        optional, optional_command = passing_profile("visual", required=False)
        self._prepare_submit_profiles(
            [(required, required_command), (optional, optional_command)]
        )
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit", "visual"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S5")
        self.assertNotEqual(result.next_route, "develop.repair")
        self.assertEqual(result.next_route, "human")
        self.assertEqual(result.extras["completeness"]["required_fail"], 1)

    def test_B3R20_required_pass_s10_path_remains_unchanged(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras["test_complete"])
        self.assertTrue(result.extras["s10"]["durable"])

    def _write_p5_verified_absence_host(self) -> dict:
        write_host(self.host, [])
        generated = _tests_data([
            {
                "name": "test_tree",
                "value": None,
                "confidence": "VERIFIED",
            }
        ])
        write_yaml_atomic(self.host / ".scaffold/tests.yaml", generated)
        return generated

    def _prepare_submit_profiles(self, profiles) -> None:
        write_host(self.host, profiles)
        self._prepare_submit_metadata()

    def _prepare_submit_metadata(self, **task_overrides) -> None:
        bind_submit_lock(self.host)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        project["ownership"] = {
            **project["ownership"],
            ".scaffold/ext/test/": "GENERATED",
            ".scaffold/ext/submit/": "GENERATED",
            "src/": "HUMAN_OWNED",
        }
        project["source_areas"] = ["src"]
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        write_ready_task(self.host, **task_overrides)
        rebound = rebind_noscms_baseline(self.host)
        self.assertTrue(rebound.get("ok"), rebound)
        write(self.host, "src/app.py", "value = 1\n")


if __name__ == "__main__":
    unittest.main()

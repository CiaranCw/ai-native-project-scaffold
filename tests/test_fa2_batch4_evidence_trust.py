from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import unquote

from p6_support import (
    CORE_OWNERSHIP,
    REPO_TEST,
    failing_profile,
    git,
    passing_profile,
    write_host,
)
from p7_support import TASK_A
from p8_support import (
    run_submit,
    bind_ready_completion_authority,
    bind_submit_lock,
    init_submit_git,
    rebind_noscms_baseline,
    submit_engine,
    write_ready_task,
    write_submit_host,
)
from scaffold_p5.io_util import file_digest, read_yaml, write_yaml_atomic
from scaffold_p5.packages import load_package
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.engine import TestEngine
from scaffold_p6.storage import (
    cleanup_test_run,
    load_completed_report,
    materialization_path,
)
from scaffold_p8.completeness import evaluate_completeness
from scaffold_p8.records import durability_state
from support import write


class FA2Batch4EvidenceTrustTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_B4E01_fabricated_raw_report_cannot_authorize_s5(self):
        write_submit_host(self.host)
        forged = self._forged_report()
        result = run_submit(self.host, task_id=TASK_A, report=forged)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S5")
        self.assertFalse((self.host / ".scaffold/changes").exists())
        self.assertFalse((self.host / ".scaffold/finalizations").exists())

    def test_B4E02_raw_report_cannot_override_nonexistent_report_id(self):
        write_submit_host(self.host)
        result = run_submit(self.host, 
            task_id=TASK_A,
            report=self._forged_report(),
            report_id="testrun-20990101T000000Z-deadbeef",
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S5")
        self.assertTrue(any(
            "conflicts" in item for item in result.extras["completeness"]["blockers"]
        ))

    def test_B4E03_valid_completed_report_id_may_pass_s5(self):
        write_submit_host(self.host)
        test_result = self._test_engine().run(selected=["unit"])
        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=test_result.extras["report_id"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.extras["stage"], "S6")
        self.assertTrue(result.extras["test_complete"])

    def test_B4E04_corrupt_persisted_report_is_rejected(self):
        write_submit_host(self.host)
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        self._report_path(run_id).write_text("report: [\n", encoding="utf-8")
        result = run_submit(self.host, task_id=TASK_A, report_id=run_id)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S5")
        self.assertFalse(result.extras["completeness"]["usable"])

    def test_B4E05_missing_required_local_evidence_rejects_report(self):
        write_submit_host(self.host)
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        ref = self._local_ref(run_id)
        self._artifact_path(ref["locator"]).unlink()
        result = run_submit(self.host, task_id=TASK_A, report_id=run_id)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S5")

    def test_B4E06_evidence_digest_mismatch_rejects_report(self):
        write_submit_host(self.host)
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        ref = self._local_ref(run_id)
        self._artifact_path(ref["locator"]).write_text(
            "modified evidence\n", encoding="utf-8"
        )
        result = run_submit(self.host, task_id=TASK_A, report_id=run_id)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S5")

    def test_B4E07_candidate_change_stales_valid_report(self):
        write_submit_host(self.host)
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        write(self.host, "src/app.py", "value = 2\n")
        result = run_submit(self.host, task_id=TASK_A, report_id=run_id)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S5")
        self.assertTrue(result.extras["completeness"]["stale_report"])

    def test_B4E08_invoke_test_reloads_published_report(self):
        write_submit_host(self.host)
        with mock.patch(
            "scaffold_p6.published.load_completed_report",
            wraps=load_completed_report,
        ) as reader:
            result = run_submit(self.host, 
                task_id=TASK_A,
                invoke_test=True,
                selected=["unit"],
            )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        report_id = result.extras["completeness"]["report_id"]
        self.assertTrue(report_id)
        self.assertTrue(reader.called)
        self.assertGreaterEqual(reader.call_count, 1)
        reloaded_ids = [
            call.args[1]
            if len(call.args) > 1
            else call.kwargs.get("run_id")
            for call in reader.call_args_list
        ]
        self.assertIn(report_id, reloaded_ids, reader.call_args_list)

    def test_B4E09_task_only_requirement_missing_from_evidence_blocks(self):
        write_submit_host(self.host)
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        locator = self._profile_locator(run_id, "unit")
        task = self._task_with_refs([
            self._task_ref("unit", locator),
            {"requirement_id": "task-only", "observed_outcome": "PASS"},
        ])
        judged = self._judge(run_id, task)
        self.assertFalse(judged["test_complete"])
        self.assertIn("unit", judged["proven_required_ids"])
        self.assertIn("task-only", judged["uncovered_required_ids"])

    def test_B4E10_report_counters_cannot_hide_uncovered_task_requirement(self):
        write_submit_host(self.host)
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        report = load_completed_report(self.host, run_id)
        self.assertEqual(report["completeness"]["required_total"], 1)
        task = self._task_with_refs([
            {"requirement_id": "task-only", "observed_outcome": "PASS"}
        ])
        judged = self._judge(run_id, task)
        self.assertFalse(judged["test_complete"])
        self.assertIn("task-only", judged["uncovered_required_ids"])

    def test_B4E11_all_task_and_project_obligations_may_complete(self):
        write_submit_host(self.host)
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        locator = self._profile_locator(run_id, "unit")
        task = self._task_with_refs([
            self._task_ref("task-a", locator),
            self._task_ref("task-b", locator),
        ])
        judged = self._judge(run_id, task)
        self.assertTrue(judged["test_complete"], judged["blockers"])
        self.assertEqual(
            judged["proven_required_ids"], ["task-a", "task-b", "unit"]
        )

    def test_B4E12_resolved_required_fail_routes_develop(self):
        self._prepare_profiles([failing_profile("unit")])
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        locator = self._profile_locator(run_id, "unit")
        task = self._task_with_refs([self._task_ref("task-fail", locator, "FAIL")])
        judged = self._judge(run_id, task)
        self.assertFalse(judged["test_complete"])
        self.assertGreater(judged["required_fail"], 0)
        self.assertEqual(judged["route"], "develop.repair")

    def test_B4E13_required_not_run_remains_incomplete(self):
        unit, unit_command = passing_profile("unit")
        other, other_command = passing_profile("other", required=False)
        self._prepare_profiles([(unit, unit_command), (other, other_command)])
        run_id = self._test_engine().run(selected=["other"]).extras["report_id"]
        judged = self._judge(run_id)
        self.assertFalse(judged["test_complete"])
        self.assertIn("unit", judged["uncovered_required_ids"])
        self.assertEqual(judged["route"], "test.scoped_verification")

    def test_B4E14_task_obligation_defeats_zero_required_report(self):
        optional, command = passing_profile("note", required=False)
        self._prepare_profiles([(optional, command)])
        tests = read_yaml(self.host / ".scaffold/tests.yaml")
        tests["required_authority"] = "VERIFIED"
        write_yaml_atomic(self.host / ".scaffold/tests.yaml", tests)
        run_id = self._test_engine().run(selected=[]).extras["report_id"]
        task = self._task_with_refs([{"requirement_id": "task-only"}])
        judged = self._judge(run_id, task)
        self.assertFalse(judged["zero_required"])
        self.assertFalse(judged["test_complete"])

    def test_B4E15_duplicate_requirement_dedupes_only_coherent_binding(self):
        write_submit_host(self.host)
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        locator = self._profile_locator(run_id, "unit")
        ref = self._task_ref("same", locator)
        task = self._task_with_refs([ref], stage_refs=[dict(ref)])
        judged = self._judge(run_id, task)
        self.assertTrue(judged["test_complete"], judged["blockers"])
        self.assertEqual(judged["proven_required_ids"].count("same"), 1)

        conflicting = self._task_with_refs(
            [ref],
            stage_refs=[self._task_ref("same", locator + "-other")],
        )
        conflict = self._judge(run_id, conflicting)
        self.assertFalse(conflict["test_complete"])
        self.assertTrue(any("conflicting" in item for item in conflict["blockers"]))

    def test_B4E16_equal_names_do_not_replace_task_evidence_locator(self):
        write_submit_host(self.host)
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        task = self._task_with_refs([
            {"requirement_id": "unit", "observed_outcome": "PASS"}
        ])
        judged = self._judge(run_id, task)
        self.assertFalse(judged["test_complete"])
        self.assertIn("unit", judged["uncovered_required_ids"])
        self.assertTrue(any("no P6 Evidence locator" in item for item in judged["blockers"]))

    def test_B4E17_public_evidence_reference_round_trips(self):
        write_submit_host(self.host)
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        ref = self._test_engine().build_evidence_refs(run_id)[0]
        resolved, issues = self._test_engine().resolve_evidence(ref["locator"])
        self.assertEqual(issues, [])
        self.assertEqual(resolved["report_id"], run_id)
        self.assertEqual(resolved["result"], "PASS")

    def test_B4E18_change_record_copies_exact_p6_references(self):
        write_submit_host(self.host)
        engine = self._test_engine()
        run_id = engine.run(selected=["unit"]).extras["report_id"]
        expected = engine.build_evidence_refs(run_id)
        digest = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=run_id,
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        actual = result.extras["change_record"]["verification"]["evidence_refs"]
        self.assertEqual(actual, expected)

    def test_B4E19_change_record_never_emits_bare_run_id(self):
        write_submit_host(self.host)
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        refs = self._test_engine().build_evidence_refs(run_id)
        self.assertTrue(refs)
        for ref in refs:
            self.assertNotEqual(ref["locator"], run_id)
            self.assertTrue(ref["locator"].startswith(f"test-runs/{run_id}/"))

    def test_B4E20_missing_referenced_artifact_fails_resolution(self):
        write_submit_host(self.host)
        engine = self._test_engine()
        run_id = engine.run(selected=["unit"]).extras["report_id"]
        ref = engine.build_evidence_refs(run_id)[0]
        locator = ref["locator"]
        path_part, marker, encoded = locator.partition("#evidence/")
        if marker:
            report_path = self.host / ".scaffold/runtime" / path_part
            report = read_yaml(report_path)
            evidence_id = unquote(encoded)
            report["evidence"] = [
                item
                for item in report.get("evidence") or []
                if not (isinstance(item, dict) and item.get("evidence_id") == evidence_id)
            ]
            write_yaml_atomic(report_path, report)
        else:
            self._artifact_path(locator).unlink()
        resolved, issues = engine.resolve_evidence(locator)
        self.assertIsNone(resolved)
        self.assertTrue(issues)

    def test_B4E21_public_reference_is_portable(self):
        write_submit_host(self.host)
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        for ref in self._test_engine().build_evidence_refs(run_id):
            locator = ref["locator"]
            self.assertFalse(Path(locator).is_absolute())
            self.assertNotIn("\\", locator)
            self.assertNotIn(str(self.host), locator)

    def test_B4E22_s12_does_not_remove_referenced_test_artifact(self):
        write_submit_host(self.host)
        engine = self._test_engine()
        run_id = engine.run(selected=["unit"]).extras["report_id"]
        ref = engine.build_evidence_refs(run_id)[0]
        digest = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=run_id,
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras["cleanup"]["performed"])
        resolved, issues = engine.resolve_evidence(ref["locator"])
        self.assertEqual(issues, [])
        self.assertEqual(resolved["report_id"], run_id)

    def test_B4E23_supplied_evidence_types_round_trip_without_conversion(self):
        profiles = []
        supplied = []
        candidate_digest = ""
        definitions = [
            (
                "human",
                "HUMAN_OBSERVATION",
                "human_observation",
                {"summary": "Human checkpoint passed."},
            ),
            (
                "ci",
                "CI_RESULT",
                "external_ci",
                {"summary": "CI run passed."},
            ),
            (
                "external",
                "EXTERNAL_RESULT",
                "structured_assertion",
                {"assertion": {"passed": True}},
            ),
        ]
        for profile_id, provenance, kind, _payload in definitions:
            profile, command = passing_profile(profile_id)
            profile["provenance"] = provenance
            profile["evidence_required"] = [kind]
            profiles.append((profile, command))
        self._prepare_profiles(profiles)
        candidate_digest = observe_candidate(self.host).digest
        for profile_id, provenance, kind, payload in definitions:
            supplied.append({
                "profile_id": profile_id,
                "provenance": provenance,
                "kind": kind,
                "result": "PASS",
                "candidate_digest": candidate_digest,
                **payload,
            })
        engine = self._test_engine()
        result = engine.run(
            selected=["human", "ci", "external"],
            supplied_evidence=supplied,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        refs = engine.build_evidence_refs(result.extras["report_id"])
        resolved_kinds = set()
        for ref in refs:
            resolved, issues = engine.resolve_evidence(ref["locator"])
            self.assertEqual(issues, [])
            resolved_kinds.add(resolved["evidence"]["kind"])
        self.assertEqual(
            resolved_kinds,
            {"human_observation", "external_ci", "structured_assertion"},
        )
        self.assertNotIn("command_result", resolved_kinds)

    def test_B4R01_git_s10_binds_exact_change_record_and_support_set(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        write(self.host, "src/app.py", "value = 2\n")
        engine = self._test_engine()
        run_id = engine.run(selected=["unit"]).extras["report_id"]
        task_rel = f".scaffold/tasks/{TASK_A}.yaml"
        bind_ready_completion_authority(self.host, TASK_A)
        # Completion-decision bytes are P6-neutral, but Git HEAD is part of
        # candidate_digest. Committing the stamp would change HEAD and stale
        # READY. Keep the Git baseline Task Book and hide the control-plane
        # stamp from Git real Diff / S10.
        git(self.host, "update-index", "--skip-worktree", "--", task_rel)
        reviewed = observe_candidate(self.host).digest
        result = run_submit(
            self.host,
            task_id=TASK_A,
            report_id=run_id,
            finalize=True,
            bind_ready_authority=False,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        committed = set(
            git(self.host, "show", "--pretty=", "--name-only", "HEAD").splitlines()
        )
        support = {
            item["path"] for item in result.extras["s10"]["support_artifacts"]
        }
        change_path = (
            f".scaffold/changes/"
            f"{result.extras['change_record']['record_id']}.yaml"
        )
        self.assertEqual(committed, {"src/app.py", change_path, *support})
        reviewed_paths = {
            row["path"]
            for row in result.extras["change_record"]["path_summary"]["paths"]
        }
        self.assertTrue(support.isdisjoint(reviewed_paths))

    def test_B4R02_cleanup_removes_runtime_but_durable_locator_resolves(self):
        write_submit_host(self.host)
        engine = self._test_engine()
        run_id = engine.run(selected=["unit"]).extras["report_id"]
        locator = engine.build_evidence_refs(run_id)[0]["locator"]
        reviewed = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=run_id,
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        record_id = result.extras["change_record"]["record_id"]
        self.assertTrue(cleanup_test_run(self.host, run_id))
        self.assertEqual(
            durability_state(self.host, record_id)["state"], "durable"
        )
        resolved, issues = engine.resolve_evidence(locator)
        self.assertEqual(issues, [])
        self.assertEqual(resolved["resolution_source"], "durable")

    def test_B4R03_unreferenced_test_run_cleanup_creates_no_durable_copy(self):
        write_submit_host(self.host)
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        self.assertTrue(cleanup_test_run(self.host, run_id))
        self.assertFalse((self.host / ".scaffold/ext/test/evidence").exists())

    def test_B4R04_missing_generated_ownership_blocks_materialization(self):
        write_submit_host(self.host, noscms_working_diff=False)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        project["ownership"].pop(".scaffold/ext/test/", None)
        project["ownership"].pop(".scaffold/ext/test/evidence/", None)
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        rebound = rebind_noscms_baseline(self.host)
        self.assertTrue(rebound.get("ok"), rebound)
        write(self.host, "src/app.py", "value = 1\n")
        engine = self._test_engine()
        run_id = engine.run(selected=["unit"]).extras["report_id"]
        reviewed = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=run_id,
            finalize=True,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S9")
        self.assertTrue(any("ownership" in item for item in result.blockers))
        self.assertFalse((self.host / ".scaffold/ext/test/evidence").exists())

    def test_B4R05_changed_support_fails_closed_and_requires_recovery(self):
        write_submit_host(self.host)
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        reviewed = observe_candidate(self.host).digest

        def change_support() -> None:
            capsule = next(
                (self.host / ".scaffold/ext/test/evidence").rglob("*.yaml")
            )
            capsule.write_text("tampered: true\n", encoding="utf-8")

        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=run_id,
            finalize=True,
            before_s10=change_support,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["s10"]["durable"])
        self.assertTrue(any(
            "support" in item.lower() or "reconciliation" in item.lower()
            for item in result.blockers
        ))
        self.assertTrue(
            (self.host / ".scaffold/runtime/test-materializations").exists()
        )

    def test_B4R06_unexpected_ext_mutation_is_not_admitted_to_s10(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        write(self.host, "src/app.py", "value = 2\n")
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        reviewed = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=run_id,
            finalize=True,
            before_s10=lambda: write(
                self.host, ".scaffold/ext/unexpected.yaml", "unexpected: true\n"
            ),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["s10"]["durable"])
        self.assertTrue(any(
            "immediately before S10" in item for item in result.blockers
        ))

    def test_B4R07_non_durable_s10_failure_aborts_created_support(self):
        write_submit_host(self.host)
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        reviewed = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=run_id,
            finalize=True,
            fail_s10=True,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse((self.host / ".scaffold/ext/test/evidence").exists())
        self.assertFalse(
            (self.host / ".scaffold/runtime/test-materializations").exists()
        )

    def test_B4R08_abandoned_prepared_support_is_reconciled_before_s2(self):
        """Abandoned PREPARED support is reconciled before S2.

        Historical expectation continued to S6. Current READY currentness may
        correctly block at S1 after recovery changes the candidate. Continuation
        after a recovered legally READY candidate is
        test_B4R08_b_continuation_after_recovered_candidate_is_legally_ready.
        """
        write_submit_host(self.host)
        engine = self._test_engine()
        run_id = engine.run(selected=["unit"]).extras["report_id"]
        descriptor, issues = engine.materialize_evidence(
            engine.build_evidence_refs(run_id),
            coordination_id="change-abandoned",
        )
        self.assertEqual(issues, [])
        self.assertIsNotNone(descriptor)
        self.assertFalse(cleanup_test_run(self.host, run_id))
        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=run_id,
        )
        self.assertNotEqual(result.extras.get("stage"), "S2")
        self.assertIn(result.extras.get("stage"), {"S1"})
        self.assertFalse((self.host / ".scaffold/ext/test/evidence").exists())
        self.assertTrue(self._report_path(run_id).exists())
        self.assertFalse(
            (self.host / ".scaffold/runtime/test-materializations").exists()
        )

    def test_B4R08_b_continuation_after_recovered_candidate_is_legally_ready(self):
        write_submit_host(self.host)
        engine = self._test_engine()
        run_id = engine.run(selected=["unit"]).extras["report_id"]
        descriptor, issues = engine.materialize_evidence(
            engine.build_evidence_refs(run_id),
            coordination_id="change-abandoned",
        )
        self.assertEqual(issues, [])
        self.assertIsNotNone(descriptor)
        recovered = engine.abort_materialization("change-abandoned")
        self.assertTrue(recovered.get("ok"), recovered)
        self.assertFalse((self.host / ".scaffold/ext/test/evidence").exists())
        bind_ready_completion_authority(self.host, TASK_A)
        result = run_submit(
            self.host,
            task_id=TASK_A,
            report_id=run_id,
        )
        self.assertEqual(result.extras["stage"], "S6", result.blockers)
        self.assertFalse((self.host / ".scaffold/ext/test/evidence").exists())
        self.assertTrue(self._report_path(run_id).exists())

    def test_B4R09_durable_but_blocked_preserves_support_and_releases_hold(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        write(self.host, "src/app.py", "value = 2\n")
        engine = self._test_engine()
        run_id = engine.run(selected=["unit"]).extras["report_id"]
        locator = engine.build_evidence_refs(run_id)[0]["locator"]
        reviewed = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=run_id,
            finalize=True,
            after_s10_commit=lambda: write(
                self.host, "src/app.py", "dirty after commit\n"
            ),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.extras["s10"]["durable"])
        self.assertFalse(
            (self.host / ".scaffold/runtime/test-materializations").exists()
        )
        self.assertTrue(cleanup_test_run(self.host, run_id))
        resolved, issues = engine.resolve_evidence(locator)
        self.assertEqual(issues, [])
        self.assertEqual(resolved["resolution_source"], "durable")

    def test_B4R10_nonlocal_evidence_semantics_survive_durable_cleanup(self):
        definitions = [
            ("human", "HUMAN_OBSERVATION", "human_observation"),
            ("ci", "CI_RESULT", "external_ci"),
            ("external", "EXTERNAL_RESULT", "structured_assertion"),
        ]
        profiles = []
        for profile_id, provenance, kind in definitions:
            profile, command = passing_profile(profile_id)
            profile["provenance"] = provenance
            profile["evidence_required"] = [kind]
            profiles.append((profile, command))
        self._prepare_profiles(profiles)
        candidate = observe_candidate(self.host).digest
        supplied = [
            {
                "profile_id": profile_id,
                "provenance": provenance,
                "kind": kind,
                "result": "PASS",
                "candidate_digest": candidate,
                "summary": f"{profile_id} passed",
                **({"assertion": {"passed": True}} if kind == "structured_assertion" else {}),
            }
            for profile_id, provenance, kind in definitions
        ]
        engine = self._test_engine()
        tested = engine.run(
            selected=[item[0] for item in definitions],
            supplied_evidence=supplied,
        )
        run_id = tested.extras["report_id"]
        refs = engine.build_evidence_refs(run_id)
        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=run_id,
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(cleanup_test_run(self.host, run_id))
        kinds = set()
        for ref in refs:
            resolved, issues = engine.resolve_evidence(ref["locator"])
            self.assertEqual(issues, [])
            kinds.add(resolved["evidence"]["kind"])
        self.assertEqual(
            kinds, {"human_observation", "external_ci", "structured_assertion"}
        )

    def test_B4R11_durable_support_paths_and_locators_are_portable(self):
        write_submit_host(self.host)
        engine = self._test_engine()
        run_id = engine.run(selected=["unit"]).extras["report_id"]
        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=run_id,
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        for item in result.extras["s10"]["support_artifacts"]:
            self.assertTrue(item["path"].startswith(".scaffold/ext/test/"))
            self.assertNotIn("\\", item["path"])
            self.assertNotIn(str(self.host), item["path"])
        for ref in result.extras["change_record"]["verification"]["evidence_refs"]:
            self.assertNotIn(str(self.host), ref["locator"])

    def test_B4R12_materialization_is_minimal_and_has_no_new_timestamp(self):
        write_submit_host(self.host)
        engine = self._test_engine()
        run_id = engine.run(selected=["unit"]).extras["report_id"]
        refs = engine.build_evidence_refs(run_id)
        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=run_id,
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        capsules = list(
            (self.host / ".scaffold/ext/test/evidence" / run_id).glob("*.yaml")
        )
        self.assertEqual(len(capsules), len(refs))
        self.assertFalse(any(path.name == "report.yaml" for path in capsules))
        record_id = result.extras["change_record"]["record_id"]
        for path in capsules:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(record_id, text)
            self.assertNotIn("observed_at:", text)
            self.assertNotIn("started_at:", text)
            self.assertNotIn("ended_at:", text)
            self.assertNotIn(str(self.host), text)
            self.assertNotIn(str(self.host).replace("\\", "\\\\"), text)

    def test_B4R13_corrupt_runtime_cannot_shadow_durable_resolution(self):
        write_submit_host(self.host)
        engine = self._test_engine()
        run_id = engine.run(selected=["unit"]).extras["report_id"]
        locator = engine.build_evidence_refs(run_id)[0]["locator"]
        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=run_id,
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self._report_path(run_id).write_text("report: [\n", encoding="utf-8")
        resolved, issues = engine.resolve_evidence(locator)
        self.assertEqual(issues, [])
        self.assertEqual(resolved["resolution_source"], "durable")
        self.assertIsNone(load_completed_report(self.host, run_id))

    def test_B4R14_reviewed_c_and_finalization_f_are_distinct(self):
        write_submit_host(self.host)
        engine = self._test_engine()
        run_id = engine.run(selected=["unit"]).extras["report_id"]
        reviewed = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=run_id,
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(
            result.extras["s10"]["reviewed_candidate_digest"], reviewed
        )
        self.assertNotEqual(
            result.extras["s10"]["finalization_candidate_digest"], reviewed
        )
        report = load_completed_report(self.host, run_id)
        self.assertEqual(report["candidate"]["candidate_digest"], reviewed)

    def test_B4R15_extra_mutation_beyond_c_plus_bundle_invalidates_s10(self):
        write_submit_host(self.host)
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        reviewed = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=run_id,
            finalize=True,
            before_s10=lambda: write(self.host, "src/extra.py", "extra = True\n"),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["s10"]["durable"])
        self.assertEqual(
            result.extras["s10"]["reviewed_candidate_digest"], reviewed
        )
        self.assertTrue(any(
            "immediately before S10" in item for item in result.blockers
        ))

    def test_B4R16_prepared_capsule_is_not_durable_authority(self):
        write_submit_host(self.host)
        engine = self._test_engine()
        run_id = engine.run(selected=["unit"]).extras["report_id"]
        locator = engine.build_evidence_refs(run_id)[0]["locator"]
        coordination_id = "change-20990101T000000Z-16161616"
        prepared, issues = engine.materialize_evidence(
            [{"locator": locator}],
            coordination_id=coordination_id,
        )
        self.assertEqual(issues, [])
        self.assertIsNotNone(prepared)
        self.assertTrue(
            materialization_path(self.host, coordination_id).is_file()
        )

        runtime, issues = engine.resolve_evidence(locator)
        self.assertEqual(issues, [])
        self.assertEqual(runtime["resolution_source"], "runtime")
        self.assertNotEqual(
            (runtime.get("report") or {}).get("durable_evidence"), True
        )

        self._report_path(run_id).write_text("report: [\n", encoding="utf-8")
        unresolved, issues = engine.resolve_evidence(locator)
        self.assertIsNone(unresolved)
        self.assertTrue(any(
            "PREPARED" in item and "P8 durability reconciliation" in item
            for item in issues
        ))
        self.assertIsNone(load_completed_report(self.host, run_id))

        released = engine.release_materialization(coordination_id)
        self.assertTrue(released["ok"], released["blockers"])
        durable, issues = engine.resolve_evidence(locator)
        self.assertEqual(issues, [])
        self.assertEqual(durable["resolution_source"], "durable")
        self.assertTrue(durable["report"]["durable_evidence"])
        self.assertIsNone(load_completed_report(self.host, run_id))

    def test_B4R17_identity_failure_leaves_exact_prior_index(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        write(self.host, "src/app.py", "preexisting staged value\n")
        git(self.host, "add", "--", "src/app.py")
        write(self.host, "src/app.py", "reviewed working value\n")
        engine = self._test_engine()
        run_id = engine.run(selected=["unit"]).extras["report_id"]
        reviewed = observe_candidate(self.host).digest
        head_before = git(self.host, "rev-parse", "HEAD")
        index_before = self._index_bytes()
        git(self.host, "config", "--unset-all", "user.name")
        git(self.host, "config", "--unset-all", "user.email")
        empty_config = self.host / ".git/empty-git-config"
        empty_config.write_text("", encoding="utf-8")
        environment = {
            "GIT_CONFIG_GLOBAL": str(empty_config),
            "GIT_CONFIG_SYSTEM": str(empty_config),
            "GIT_AUTHOR_NAME": "",
            "GIT_AUTHOR_EMAIL": "",
            "GIT_COMMITTER_NAME": "",
            "GIT_COMMITTER_EMAIL": "",
        }
        with mock.patch.dict(os.environ, environment, clear=False):
            result = run_submit(self.host, 
                task_id=TASK_A,
                report_id=run_id,
                finalize=True,
            )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["s10"]["durable"])
        self.assertEqual(git(self.host, "rev-parse", "HEAD"), head_before)
        self.assertEqual(self._index_bytes(), index_before)
        staged = set(
            git(self.host, "diff", "--cached", "--name-only").splitlines()
        )
        self.assertEqual(staged, {"src/app.py"})
        self.assertFalse(any(
            path.startswith(".scaffold/changes/")
            or path.startswith(".scaffold/ext/test/")
            for path in staged
        ))
        self.assertFalse((self.host / ".scaffold/ext/test/evidence").exists())
        self.assertFalse(
            (self.host / ".scaffold/runtime/test-materializations").exists()
        )
        fresh_run = engine.run(selected=["unit"]).extras["report_id"]
        follow_up = run_submit(self.host, 
            task_id=TASK_A,
            report_id=fresh_run,
        )
        self.assertEqual(follow_up.extras["stage"], "S6")

    def test_B4R18_commit_hook_failure_rolls_back_exact_prior_index(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        write(self.host, "src/app.py", "preexisting staged value\n")
        git(self.host, "add", "--", "src/app.py")
        write(self.host, "src/app.py", "reviewed working value\n")
        engine = self._test_engine()
        run_id = engine.run(selected=["unit"]).extras["report_id"]
        reviewed = observe_candidate(self.host).digest
        head_before = git(self.host, "rev-parse", "HEAD")
        index_before = self._index_bytes()
        hook_raw = git(self.host, "rev-parse", "--git-path", "hooks/pre-commit")
        hook = Path(hook_raw)
        if not hook.is_absolute():
            hook = self.host / hook
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8", newline="\n")
        hook.chmod(0o755)

        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=run_id,
            finalize=True,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["s10"]["durable"])
        rollback = result.extras["s10"]["index_rollback"]
        self.assertTrue(rollback["required"])
        self.assertTrue(rollback["ok"], rollback["blockers"])
        self.assertTrue(rollback["restored"])
        self.assertEqual(git(self.host, "rev-parse", "HEAD"), head_before)
        self.assertEqual(self._index_bytes(), index_before)
        staged = set(
            git(self.host, "diff", "--cached", "--name-only").splitlines()
        )
        self.assertEqual(staged, {"src/app.py"})
        self.assertFalse(any(
            path.startswith(".scaffold/changes/")
            or path.startswith(".scaffold/ext/test/")
            for path in staged
        ))
        self.assertFalse((self.host / ".scaffold/ext/test/evidence").exists())
        self.assertFalse(
            (self.host / ".scaffold/runtime/test-materializations").exists()
        )
        self.assertFalse(
            (self.host / ".scaffold/runtime/submit-index-recovery").exists()
        )
        hook.unlink()
        fresh_run = engine.run(selected=["unit"]).extras["report_id"]
        follow_up = run_submit(self.host, 
            task_id=TASK_A,
            report_id=fresh_run,
        )
        self.assertEqual(follow_up.extras["stage"], "S6")

    def test_B4V01_direct_submit_21_compatibility_keeps_20_lock(self):
        write_submit_host(self.host, noscms_working_diff=False)
        lock_path = self.host / ".scaffold/skills.lock"
        lock = read_yaml(lock_path)
        lock["skills"]["submit"]["skill_version"] = "2.0.0"
        lock["skills"]["submit"]["package_digest"] = "9" * 64
        write_yaml_atomic(lock_path, lock)
        rebound = rebind_noscms_baseline(self.host)
        self.assertTrue(rebound.get("ok"), rebound)
        write(self.host, "src/app.py", "value = 1\n")
        before = file_digest(lock_path)
        run_id = self._test_engine().run(selected=["unit"]).extras["report_id"]
        result = run_submit(self.host, 
            task_id=TASK_A,
            report_id=run_id,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.skill_version, "2.1.0")
        self.assertEqual(result.extras["compatibility"], "COMPATIBLE")
        self.assertEqual(file_digest(lock_path), before)
        package = load_package(Path(__file__).resolve().parents[1] / "skills/submit")
        self.assertEqual(package.ref.skill_version, "2.1.0")
        self.assertTrue(any(
            item.get("skill_version") == "2.0.0"
            for item in package.may_substitute_for
        ))

    def test_B4V02_c_min_005_remains_explicitly_open(self):
        note = (
            Path(__file__).resolve().parents[1]
            / "docs/implementation/FA2_BATCH4_EVIDENCE_TRUST.md"
        ).read_text(encoding="utf-8")
        normalized = " ".join(note.split())
        self.assertIn("C-MIN-005 remains reproducible and open", normalized)
        self.assertIn(
            "does not make generic non-Understand compatible-substitution "
            "selection reachable",
            normalized,
        )

    def _forged_report(self) -> dict:
        return {
            "report_id": "testrun-forged",
            "candidate": {"candidate_digest": observe_candidate(self.host).digest},
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

    def _test_engine(self) -> TestEngine:
        return TestEngine(self.host, REPO_TEST)

    def _report_path(self, run_id: str) -> Path:
        return self.host / ".scaffold/runtime/test-runs" / run_id / "report.yaml"

    def _artifact_path(self, locator: str) -> Path:
        return self.host / ".scaffold/runtime" / locator

    def _index_bytes(self) -> bytes:
        staged = git(self.host, "ls-files", "--stage", "-z")
        flags = git(self.host, "ls-files", "-v", "-z")
        return (staged + "\n--flags--\n" + flags).encode(
            "utf-8", "surrogateescape"
        )

    def _local_ref(self, run_id: str) -> dict:
        report = load_completed_report(self.host, run_id)
        return next(
            ref for ref in report["evidence_refs"]
            if ref.get("resolvable") is True
        )

    def _profile_locator(self, run_id: str, profile_id: str) -> str:
        engine = self._test_engine()
        for ref in engine.build_evidence_refs(run_id):
            resolved, _issues = engine.resolve_evidence(ref["locator"])
            if resolved and resolved["profile"]["id"] == profile_id:
                return ref["locator"]
        self.fail(f"no published Evidence locator for {profile_id}")

    def _judge(self, run_id: str, task: dict | None = None) -> dict:
        return evaluate_completeness(
            self.host,
            task=task or read_yaml(
                self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
            ),
            report=None,
            invoke=False,
            selected=None,
            test_package=REPO_TEST,
            report_id=run_id,
        )

    def _task_with_refs(
        self,
        final_refs: list[dict],
        *,
        stage_refs: list[dict] | None = None,
    ) -> dict:
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        task["final_tests"] = final_refs
        task["stages"][0]["required_tests"] = stage_refs or []
        return task

    @staticmethod
    def _task_ref(
        requirement_id: str,
        locator: str,
        outcome: str = "PASS",
    ) -> dict:
        return {
            "requirement_id": requirement_id,
            "evidence_ref": {"locator": locator},
            "observed_outcome": outcome,
        }

    def _prepare_profiles(self, profiles) -> None:
        write_host(self.host, profiles)
        bind_submit_lock(self.host)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        project["ownership"] = {
            **CORE_OWNERSHIP,
            ".scaffold/ext/test/": "GENERATED",
            "src/": "HUMAN_OWNED",
        }
        project["source_areas"] = ["src"]
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        write_ready_task(self.host)
        rebound = rebind_noscms_baseline(self.host)
        self.assertTrue(rebound.get("ok"), rebound)
        write(self.host, "src/app.py", "value = 1\n")


if __name__ == "__main__":
    unittest.main()

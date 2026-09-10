from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from p6_support import (
    CORE_OWNERSHIP,
    passing_profile,
    test_engine,
    write_commands,
    write_host,
    write_tests,
)
from p7_support import TASK_A, develop_engine
from p8_support import (
    init_submit_git,
    publish_knowledge_outcomes,
    run_submit,
    write_ready_task,
    write_submit_host,
)
from p10_support import persist_currentness_without_completion
from scaffold_p5.currentness import evaluate_understanding_currentness
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p5.ownership import P6_DURABLE_EVIDENCE_AREA
from scaffold_p6.candidate import observe_candidate
from scaffold_p8.models import CHANGES_DIR
from scaffold_p8.records import persist_candidate_change
from support import adopt, engine, write


def _legacy_ownership(**extra) -> dict[str, str]:
    ownership = {
        key: value
        for key, value in CORE_OWNERSHIP.items()
        if key != P6_DURABLE_EVIDENCE_AREA
    }
    ownership["src/"] = "HUMAN_OWNED"
    ownership[".scaffold/ext/submit/"] = "GENERATED"
    ownership.update(extra)
    return ownership


def _change_files(host: Path) -> list[Path]:
    root = host / CHANGES_DIR
    if not root.is_dir():
        return []
    return sorted(root.glob("change-*.yaml"))


def _valid_change_record(record_id: str, *, kind: str = "none", value=None) -> dict:
    return {
        "record_type": "change_record",
        "schema_version": "1",
        "record_id": record_id,
        "created_at": "2026-08-30T12:00:00Z",
        "summary": "fixture",
        "base": {"kind": kind, "value": value},
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
            "relevant_develop_session_ids": [],
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


class Maj010AdoptionOwnershipTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write(self.host, "README.md", "# Ordinary project\n")
        write(self.host, "src/app.py", "value = 1\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_RP4_O01_fresh_adoption_plan_declares_p6_evidence_area(self):
        result = engine(self.host).run("bootstrap")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        actions = result.extras["plan"]["actions"]
        match = [
            row
            for row in actions
            if row.get("target") == P6_DURABLE_EVIDENCE_AREA
        ]
        self.assertEqual(len(match), 1, actions)
        self.assertEqual(match[0]["ownership"], "GENERATED")
        self.assertEqual(match[0]["action_class"], "CREATE")
        presentation = result.extras["ownership_presentation"]
        self.assertEqual(
            presentation["p6_durable_evidence_area"],
            P6_DURABLE_EVIDENCE_AREA,
        )
        self.assertTrue(
            any(
                row.get("target") == P6_DURABLE_EVIDENCE_AREA
                for row in presentation.get("generated_areas") or []
            )
        )

    def test_RP4_O02_approved_fresh_adoption_persists_generated_area(self):
        adopt(self.host)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertEqual(
            project["ownership"].get(P6_DURABLE_EVIDENCE_AREA),
            "GENERATED",
        )
        self.assertFalse((self.host / P6_DURABLE_EVIDENCE_AREA).exists())

    def test_RP4_O03_fresh_adopted_host_can_materialize_p6_evidence(self):
        adopt(self.host)
        profile, command = passing_profile("unit")
        write_tests(self.host, [profile])
        write_commands(self.host, [command])
        published = test_engine(self.host).run(selected=["unit"])
        self.assertEqual(published.outcome, "COMPLETED", published.blockers)
        refs = test_engine(self.host).build_evidence_refs(
            published.extras["report_id"]
        )
        materialization, issues = test_engine(self.host).materialize_evidence(
            refs,
            coordination_id="change-20260908T030000Z-abcd1234",
        )
        self.assertEqual(issues, [])
        self.assertIsNotNone(materialization)
        self.assertTrue((self.host / ".scaffold/ext/test/evidence").exists())

    def test_RP4_O04_does_not_broaden_ownership_to_scaffold_ext(self):
        preview = engine(self.host).run("bootstrap")
        targets = [row.get("target") for row in preview.extras["plan"]["actions"]]
        self.assertNotIn(".scaffold/ext/", targets)
        adopt(self.host)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertNotIn(".scaffold/ext/", project["ownership"])
        self.assertNotIn(".scaffold/ext", project["ownership"])


class Maj010LegacyOwnershipUpdateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write_submit_host(
            self.host,
            noscms_working_diff=False,
            ownership=_legacy_ownership(),
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _plan(self, **opts):
        return engine(self.host).run(
            "compatibility",
            action="ownership_update",
            **opts,
        )

    def test_RP4_O05_legacy_missing_ownership_is_plan_needs_human_only(self):
        before = read_yaml(self.host / ".scaffold/project.yaml")
        result = self._plan()
        self.assertEqual(result.outcome, "NEEDS_HUMAN", result.blockers)
        self.assertEqual(result.mutations, "none")
        plan = result.extras["ownership_update_plan"]
        self.assertTrue(plan["valid"], plan.get("blockers"))
        self.assertEqual(plan["mutation_envelope"], [".scaffold/project.yaml"])
        after = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertEqual(after["ownership"], before["ownership"])

    def test_RP4_O06_approved_update_adds_only_p6_area(self):
        planned = self._plan()
        digest = planned.extras["ownership_update_plan"]["digest"]
        before = dict(read_yaml(self.host / ".scaffold/project.yaml")["ownership"])
        result = self._plan(approval={"approved": True, "plan_digest": digest})
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        after = dict(read_yaml(self.host / ".scaffold/project.yaml")["ownership"])
        self.assertEqual(after.get(P6_DURABLE_EVIDENCE_AREA), "GENERATED")
        self.assertEqual(
            {key: value for key, value in after.items() if key != P6_DURABLE_EVIDENCE_AREA},
            before,
        )
        self.assertNotIn(".scaffold/ext/", after)

    def test_RP4_O07_human_owned_covering_declaration_blocks(self):
        write_submit_host(
            self.host,
            noscms_working_diff=False,
            ownership=_legacy_ownership(**{".scaffold/ext/": "HUMAN_OWNED"}),
        )
        result = self._plan()
        self.assertEqual(result.outcome, "BLOCKED", result.blockers)
        self.assertEqual(result.mutations, "none")
        self.assertTrue(any("HUMAN_OWNED" in item for item in result.blockers))

    def test_RP4_O08_conflicting_ownership_blocks(self):
        write_submit_host(
            self.host,
            noscms_working_diff=False,
            ownership=_legacy_ownership(
                **{
                    ".scaffold/ext/": "HUMAN_OWNED",
                    "./.scaffold/ext/": "GENERATED",
                }
            ),
        )
        result = self._plan()
        self.assertEqual(result.outcome, "BLOCKED", result.blockers)
        self.assertEqual(result.mutations, "none")

    def test_RP4_O09_more_specific_conflicting_ownership_blocks(self):
        write_submit_host(
            self.host,
            noscms_working_diff=False,
            ownership=_legacy_ownership(
                **{".scaffold/ext/test/evidence/legacy.yaml": "HUMAN_OWNED"}
            ),
        )
        result = self._plan()
        self.assertEqual(result.outcome, "BLOCKED", result.blockers)
        self.assertEqual(result.mutations, "none")
        self.assertTrue(any("more-specific" in item for item in result.blockers))

    def test_RP4_O10_ownership_update_invalidates_understanding_currentness(self):
        write_host(self.host, [passing_profile("unit")], ownership=_legacy_ownership())
        persisted = persist_currentness_without_completion(self.host)
        self.assertTrue(persisted.get("ok"), persisted)
        before = evaluate_understanding_currentness(self.host)
        self.assertEqual(before["currentness"], "CURRENT")
        planned = engine(self.host).run("compatibility", action="ownership_update")
        digest = planned.extras["ownership_update_plan"]["digest"]
        candidate_before = observe_candidate(self.host).digest
        applied = engine(self.host).run(
            "compatibility",
            action="ownership_update",
            approval={"approved": True, "plan_digest": digest},
        )
        self.assertEqual(applied.outcome, "COMPLETED", applied.blockers)
        self.assertNotEqual(observe_candidate(self.host).digest, candidate_before)
        after = evaluate_understanding_currentness(self.host)
        self.assertNotEqual(after["currentness"], "CURRENT")


class Maj011PreDurableS9Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_RP4_S01_ownership_failure_persists_no_change_record(self):
        write_submit_host(
            self.host,
            noscms_working_diff=False,
            ownership=_legacy_ownership(),
        )
        reviewed = observe_candidate(self.host).digest
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S9")
        self.assertEqual(_change_files(self.host), [])
        self.assertFalse((self.host / ".scaffold/ext/test/evidence").exists())
        self.assertEqual(observe_candidate(self.host).digest, reviewed)
        self.assertTrue(result.extras.get("pre_durable_abort", {}).get("ok"))

    def test_RP4_S02_locator_materialization_failure_persists_no_change_record(self):
        write_submit_host(self.host, noscms_working_diff=False)
        reviewed = observe_candidate(self.host).digest

        def drop_report() -> None:
            runs = self.host / ".scaffold/runtime/test-runs"
            if runs.is_dir():
                shutil.rmtree(runs)

        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            before_s9_materialization=drop_report,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S9")
        self.assertEqual(_change_files(self.host), [])
        self.assertEqual(observe_candidate(self.host).digest, reviewed)

    def test_RP4_S03_persist_failure_aborts_prepared_and_restores_candidate(self):
        write_submit_host(self.host, noscms_working_diff=False)
        reviewed = observe_candidate(self.host).digest
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            fail_change_record_persist=True,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S9")
        self.assertEqual(_change_files(self.host), [])
        self.assertFalse((self.host / ".scaffold/ext/test/evidence").exists())
        self.assertEqual(observe_candidate(self.host).digest, reviewed)
        self.assertTrue(result.extras.get("pre_durable_abort", {}).get("ok"))

    def test_RP4_S04_pre_s10_authorization_failure_does_not_strand_candidate(self):
        write_submit_host(self.host, noscms_working_diff=False)
        reviewed = observe_candidate(self.host).digest
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            fail_pre_s10_authorization=True,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertIn(result.extras.get("stage"), {"S9", "S10"})
        self.assertEqual(_change_files(self.host), [])
        self.assertFalse((self.host / ".scaffold/ext/test/evidence").exists())
        self.assertEqual(observe_candidate(self.host).digest, reviewed)
        recovery = result.extras.get("pre_durable_abort") or {}
        self.assertTrue(
            recovery.get("ok") or result.extras.get("finalization_recovery_required")
        )

    def test_RP4_S05_successful_path_creates_change_record_and_durable_p6(self):
        write_submit_host(self.host, noscms_working_diff=False)
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras["s10"]["ok"])
        self.assertTrue(_change_files(self.host))
        self.assertTrue((self.host / ".scaffold/ext/test/evidence").exists())

    def test_RP4_S06_retry_after_aborted_s9_is_idempotent(self):
        write_submit_host(
            self.host,
            noscms_working_diff=False,
            ownership=_legacy_ownership(),
        )
        first = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        second = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(first.outcome, "BLOCKED")
        self.assertEqual(second.outcome, "BLOCKED")
        self.assertEqual(_change_files(self.host), [])
        self.assertEqual(first.extras.get("stage"), second.extras.get("stage"))


class Maj011OrphanRecoveryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write_submit_host(self.host, noscms_working_diff=False)

    def tearDown(self):
        self._tmp.cleanup()

    def _submit(self):
        from scaffold_p8.engine import SubmitEngine
        from support import REPO

        return SubmitEngine(self.host, REPO / "skills" / "submit")

    def test_RP4_S07_orphan_recovery_without_approval_does_not_mutate(self):
        record_id = "change-20260908T022157Z-2bd20ab5"
        persist_candidate_change(
            self.host,
            _valid_change_record(record_id),
        )
        before = (self.host / CHANGES_DIR / f"{record_id}.yaml").read_bytes()
        result = self._submit().run(
            abandon_pre_durable_change={"change_id": record_id}
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN", result.blockers)
        self.assertEqual(result.mutations, "none")
        self.assertEqual(
            (self.host / CHANGES_DIR / f"{record_id}.yaml").read_bytes(),
            before,
        )

    def test_RP4_S08_approved_orphan_recovery_removes_only_exact_record(self):
        record_id = "change-20260908T022157Z-2bd20ab5"
        persist_candidate_change(
            self.host,
            _valid_change_record(record_id),
        )
        other = "change-20260908T022200Z-aaaaaaaa"
        persist_candidate_change(
            self.host,
            _valid_change_record(other),
        )
        # Two non-durable records must block; isolate the exact record.
        (self.host / CHANGES_DIR / f"{other}.yaml").unlink()
        planned = self._submit().run(
            abandon_pre_durable_change={"change_id": record_id}
        )
        digest = planned.extras["abandon_pre_durable_plan"]["digest"]
        result = self._submit().run(
            abandon_pre_durable_change={
                "change_id": record_id,
                "approval": {"approved": True, "plan_digest": digest},
            }
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertFalse((self.host / CHANGES_DIR / f"{record_id}.yaml").exists())
        self.assertEqual(result.artifacts, [f"{CHANGES_DIR}/{record_id}.yaml"])

    def test_RP4_S09_post_recovery_candidate_equals_projected_predecessor(self):
        record_id = "change-20260908T022157Z-2bd20ab5"
        before = observe_candidate(self.host).digest
        persist_candidate_change(
            self.host,
            _valid_change_record(record_id),
        )
        planned = self._submit().run(
            abandon_pre_durable_change={"change_id": record_id}
        )
        projected = planned.extras["abandon_pre_durable_plan"][
            "projected_candidate_digest"
        ]
        self.assertEqual(projected, before)
        digest = planned.extras["abandon_pre_durable_plan"]["digest"]
        result = self._submit().run(
            abandon_pre_durable_change={
                "change_id": record_id,
                "approval": {"approved": True, "plan_digest": digest},
            }
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(observe_candidate(self.host).digest, projected)

    def test_RP4_S10_durable_change_record_cannot_be_abandoned(self):
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        record_id = result.extras["change_record"]["record_id"]
        abandoned = self._submit().run(
            abandon_pre_durable_change={"change_id": record_id}
        )
        self.assertEqual(abandoned.outcome, "BLOCKED")
        self.assertTrue((self.host / CHANGES_DIR / f"{record_id}.yaml").exists())
        self.assertTrue(
            any("durable" in item.lower() for item in abandoned.blockers)
        )

    def test_RP4_S11_tampered_orphan_record_blocks_recovery(self):
        record_id = "change-20260908T022157Z-2bd20ab5"
        persist_candidate_change(
            self.host,
            _valid_change_record(record_id),
        )
        planned = self._submit().run(
            abandon_pre_durable_change={"change_id": record_id}
        )
        digest = planned.extras["abandon_pre_durable_plan"]["digest"]
        path = self.host / CHANGES_DIR / f"{record_id}.yaml"
        data = read_yaml(path)
        data["summary"] = "tampered"
        write_yaml_atomic(path, data)
        result = self._submit().run(
            abandon_pre_durable_change={
                "change_id": record_id,
                "approval": {"approved": True, "plan_digest": digest},
            }
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(path.exists())

    def test_RP4_S12_multiple_orphan_recovery_blocks(self):
        first = "change-20260908T022157Z-2bd20ab5"
        second = "change-20260908T022158Z-cccccccc"
        persist_candidate_change(self.host, _valid_change_record(first))
        persist_candidate_change(self.host, _valid_change_record(second))
        result = self._submit().run(
            abandon_pre_durable_change={"change_id": first}
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("multiple" in item for item in result.blockers))
        self.assertTrue((self.host / CHANGES_DIR / f"{first}.yaml").exists())
        self.assertTrue((self.host / CHANGES_DIR / f"{second}.yaml").exists())


class DiveShapedE2ETests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_RP4_E01_dive_shaped_s9_then_ownership_update_then_s10(self):
        write_submit_host(
            self.host,
            noscms_working_diff=False,
            ownership=_legacy_ownership(),
        )
        init_submit_git(self.host)
        write(self.host, "src/app.py", "value = 2\n")
        write_ready_task(self.host)
        reviewed = observe_candidate(self.host).digest
        blocked = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(blocked.outcome, "BLOCKED")
        self.assertEqual(blocked.extras.get("stage"), "S9")
        self.assertEqual(_change_files(self.host), [])
        self.assertEqual(observe_candidate(self.host).digest, reviewed)

        planned = engine(self.host).run("compatibility", action="ownership_update")
        self.assertEqual(planned.outcome, "NEEDS_HUMAN", planned.blockers)
        digest = planned.extras["ownership_update_plan"]["digest"]
        updated = engine(self.host).run(
            "compatibility",
            action="ownership_update",
            approval={"approved": True, "plan_digest": digest},
        )
        self.assertEqual(updated.outcome, "COMPLETED", updated.blockers)
        persisted = persist_currentness_without_completion(self.host)
        self.assertTrue(persisted.get("ok"), persisted)
        published = test_engine(self.host).run(selected=["unit"])
        self.assertEqual(published.outcome, "COMPLETED", published.blockers)
        refreshed = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            refresh_ready_authority=True,
            published_test_report_id=published.extras["report_id"],
        )
        self.assertEqual(refreshed.outcome, "COMPLETED", refreshed.blockers)
        preview = run_submit(
            self.host,
            task_id=TASK_A,
            report_id=published.extras["report_id"],
        )
        structural = preview.extras.get("structural") or {}
        if structural.get("impacts"):
            knowledge = publish_knowledge_outcomes(self.host, structural)
            self.assertTrue(knowledge.get("ok"), knowledge)
        final = run_submit(
            self.host,
            task_id=TASK_A,
            report_id=published.extras["report_id"],
            finalize=True,
        )
        self.assertEqual(final.outcome, "COMPLETED", final.blockers)
        self.assertTrue(final.extras["s10"]["ok"])
        self.assertTrue(_change_files(self.host))
        self.assertTrue((self.host / ".scaffold/ext/test/evidence").exists())


if __name__ == "__main__":
    unittest.main()

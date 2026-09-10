from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import (
    dummy_lock_entry,
    failing_profile,
    passing_profile,
    test_engine,
    write_host,
    write_lock,
)
from p7_support import (
    TASK_A,
    bind_develop_lock,
    develop_engine,
    four_core_lock_skills,
    ready_lifecycle_opts,
    write_task,
)
from p8_support import bind_ready_completion_authority, run_submit, write_ready_task
from p10_support import persist_currentness_without_completion
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.published import consume_published_report
from scaffold_p6.sav import (
    publish_sav_plan,
    reconstruct_sav_plan,
    task_contract_digest,
)
from support import write


REQUIREMENT = "inspect-step-distance"
PROFILE = "npm-test"
PLAN_ID = "sav-20260907T220000Z-abcdef01"


def _verified_develop_host(host: Path, *, failing: bool = False) -> None:
    profile, command = failing_profile("unit") if failing else passing_profile("unit")
    write_host(host, [(profile, command)])
    bind_develop_lock(host)
    write(host, "src/app.py", "value = 0\n")


def _bound_task(**overrides) -> dict:
    data = {
        "title": "inspect-step-distance",
        "final_tests": [
            {
                "requirement_id": REQUIREMENT,
                "execution_binding": {"kind": "test_profile", "profile_id": PROFILE},
            }
        ],
        "stages": [
            {
                "stage_id": "stage-1",
                "goal": "Write the fixture source.",
                "acceptance": "src/app.py has the expected content.",
                "status": "IN_PROGRESS",
                "required_tests": [
                    {
                        "requirement_id": REQUIREMENT,
                        "execution_binding": {
                            "kind": "test_profile",
                            "profile_id": PROFILE,
                        },
                    }
                ],
            }
        ],
    }
    data.update(overrides)
    return data


def _inspect_plan(*, task_revision: int = 1, candidate_digest: str | None = None) -> dict:
    plan = {
        "record_type": "test_scenario_aware_plan",
        "schema_version": "1",
        "supporting": True,
        "canonical": False,
        "plan_id": PLAN_ID,
        "task_id": TASK_A,
        "task_revision": task_revision,
        "requirement_id": REQUIREMENT,
        "binding": {"kind": "test_profile", "profile_id": PROFILE},
        "scenario": {
            "initial_state": "inspect tile is available",
            "action": "inspect a tile",
            "expected_result": "distance overlay is exact",
        },
        "proof_obligations": [
            {
                "po_id": "PO-1",
                "obligation": "player tile distance 0",
                "required": True,
                "observable_signals": ["inspect overlay"],
                "execution_strategy": "structured_assertion",
                "assertions": ["player tile distance is 0"],
                "evidence_requirements": ["structured_assertion"],
                "observability_status": "SUFFICIENT",
            }
        ],
    }
    if candidate_digest:
        plan["candidate_digest"] = candidate_digest
    return plan


def _assertion(host: Path, po_id: str = "PO-1", *, passed: bool = True) -> dict:
    return {
        "kind": "structured_assertion",
        "po_id": po_id,
        "profile_id": PROFILE,
        "summary": f"{po_id} structured assertion",
        "assertion": {"po_id": po_id, "pass": passed},
        "pass": passed,
        "result": "PASS" if passed else "FAIL",
        "provenance": "EXTERNAL_RESULT",
        "mechanism": "verifier_execution",
        "candidate_digest": observe_candidate(host).digest,
        "locator": f"ext/sav/{po_id}.json",
        "digest": "ab" * 32,
    }


def _bump_lock_candidate(host: Path) -> None:
    skills = four_core_lock_skills()
    skills["understand"] = dummy_lock_entry("2.0.0", "ab" * 32)
    write_lock(host, skills)


def _publish_unit_report(host: Path, **opts):
    return test_engine(host).run("scoped_verification", selected=["unit"], **opts)


def _stale_ready_after_lock_bump(host: Path) -> tuple[str, str]:
    _verified_develop_host(host)
    write_ready_task(host)
    before = observe_candidate(host).digest
    _bump_lock_candidate(host)
    after = observe_candidate(host).digest
    assert before != after
    return before, after


class TaskContractSavCurrentnessTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write_host(self.host, [passing_profile(PROFILE)])
        write_task(self.host, **_bound_task())

    def tearDown(self):
        self._tmp.cleanup()

    def test_RP3_S01_new_sav_current_when_revision_and_contract_match(self):
        published = publish_sav_plan(self.host, _inspect_plan())
        self.assertTrue(published.get("ok"), published)
        self.assertTrue(published.get("plan", {}).get("task_contract_digest"))
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertTrue(reconstructed.get("current"), reconstructed)

    def test_RP3_S02_completion_decision_revision_keeps_new_sav_current(self):
        publish_sav_plan(self.host, _inspect_plan())
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        contract = task_contract_digest(task)
        task["record_revision"] = 2
        task["task_completion_decision"] = {
            "outcome": "SATISFIED",
            "candidate_digest": observe_candidate(self.host).digest,
            "rationale": "completion only",
            "basis": [{"kind": "task_fact", "summary": "acceptance holds"}],
        }
        write_yaml_atomic(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml", task)
        self.assertEqual(task_contract_digest(task), contract)
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertTrue(reconstructed.get("current"), reconstructed)

    def test_RP3_S03_ready_publication_keeps_new_sav_current(self):
        publish_sav_plan(self.host, _inspect_plan())
        write_task(
            self.host,
            record_revision=2,
            status="READY_FOR_REVIEW",
            **_bound_task(
                stages=[
                    {
                        "stage_id": "stage-1",
                        "goal": "Write the fixture source.",
                        "acceptance": "src/app.py has the expected content.",
                        "status": "COMPLETE",
                        "required_tests": [
                            {
                                "requirement_id": REQUIREMENT,
                                "execution_binding": {
                                    "kind": "test_profile",
                                    "profile_id": PROFILE,
                                },
                            }
                        ],
                    }
                ]
            ),
        )
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertTrue(reconstructed.get("current"), reconstructed)

    def test_RP3_S04_session_link_keeps_new_sav_current(self):
        publish_sav_plan(self.host, _inspect_plan())
        write_task(
            self.host,
            record_revision=2,
            develop_session_ids=["dev-20260907T220000Z-abcd1234"],
            **_bound_task(),
        )
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertTrue(reconstructed.get("current"), reconstructed)

    def test_RP3_S05_requirement_change_stales_sav(self):
        publish_sav_plan(self.host, _inspect_plan())
        write_task(self.host, **_bound_task(final_tests=[], stages=[{
            "stage_id": "stage-1",
            "goal": "Write the fixture source.",
            "acceptance": "src/app.py has the expected content.",
            "status": "IN_PROGRESS",
            "required_tests": [],
        }]))
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertFalse(reconstructed.get("current"))

    def test_RP3_S06_execution_binding_change_stales_sav(self):
        publish_sav_plan(self.host, _inspect_plan())
        write_task(
            self.host,
            **_bound_task(
                final_tests=[
                    {
                        "requirement_id": REQUIREMENT,
                        "execution_binding": {
                            "kind": "test_profile",
                            "profile_id": "other-profile",
                        },
                    }
                ]
            ),
        )
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertFalse(reconstructed.get("current"))
        self.assertTrue(
            any("profile" in item or "contract" in item for item in reconstructed.get("blockers") or [])
        )

    def test_RP3_S07_stage_acceptance_change_stales_sav(self):
        publish_sav_plan(self.host, _inspect_plan())
        write_task(
            self.host,
            **_bound_task(
                stages=[
                    {
                        "stage_id": "stage-1",
                        "goal": "Write the fixture source.",
                        "acceptance": "acceptance changed",
                        "status": "IN_PROGRESS",
                        "required_tests": [
                            {
                                "requirement_id": REQUIREMENT,
                                "execution_binding": {
                                    "kind": "test_profile",
                                    "profile_id": PROFILE,
                                },
                            }
                        ],
                    }
                ]
            ),
        )
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertFalse(reconstructed.get("current"))
        self.assertTrue(
            any("contract" in item for item in reconstructed.get("blockers") or [])
        )

    def test_RP3_S08_scope_change_stales_sav(self):
        publish_sav_plan(self.host, _inspect_plan())
        write_task(self.host, scope={"paths": ["src/other.py"], "modules": [], "exclude": []}, **_bound_task())
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertFalse(reconstructed.get("current"))
        self.assertTrue(
            any("contract" in item for item in reconstructed.get("blockers") or [])
        )

    def test_RP3_S09_candidate_change_stales_sav(self):
        candidate = observe_candidate(self.host)
        publish_sav_plan(
            self.host, _inspect_plan(candidate_digest=candidate.digest)
        )
        write(self.host, "README.md", "# candidate changed\n")
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertFalse(reconstructed.get("current"))
        self.assertTrue(
            any("candidate" in item for item in reconstructed.get("blockers") or [])
        )

    def test_RP3_S10_legacy_plan_without_digest_uses_strict_revision(self):
        publish_sav_plan(
            self.host, _inspect_plan(task_revision=1), bind_task_contract=False
        )
        write_task(self.host, record_revision=2, **_bound_task())
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertFalse(reconstructed.get("current"))
        self.assertTrue(
            any("revision" in item for item in reconstructed.get("blockers") or [])
        )

    def test_RP3_S11_fresh_process_reconstructs_same_currentness(self):
        publish_sav_plan(self.host, _inspect_plan())
        first = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        write_task(self.host, record_revision=2, **_bound_task())
        second = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertEqual(first.get("current"), True)
        self.assertEqual(second.get("current"), True)
        self.assertEqual(first.get("current"), second.get("current"))

    def test_RP3_S12_published_report_survives_completion_only_revision(self):
        publish_sav_plan(self.host, _inspect_plan())
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[_assertion(self.host)],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        write_task(self.host, record_revision=2, **_bound_task())
        loaded = consume_published_report(
            self.host,
            result.extras["report_id"],
            task=read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
        )
        self.assertTrue(loaded.get("ok"), loaded)


class ReadyAuthorityRefreshTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _refresh(self, **opts):
        return develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            refresh_ready_authority=True,
            **opts,
        )

    def test_RP3_R01_stale_ready_refresh_succeeds(self):
        _stale_ready_after_lock_bump(self.host)
        published = _publish_unit_report(self.host)
        result = self._refresh(published_test_report_id=published.extras["report_id"])
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras.get("ready_authority_refresh"))

    def test_RP3_R02_task_remains_ready(self):
        _stale_ready_after_lock_bump(self.host)
        published = _publish_unit_report(self.host)
        self._refresh(published_test_report_id=published.extras["report_id"])
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(task["status"], "READY_FOR_REVIEW")

    def test_RP3_R03_stages_remain_complete(self):
        _stale_ready_after_lock_bump(self.host)
        published = _publish_unit_report(self.host)
        self._refresh(published_test_report_id=published.extras["report_id"])
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertTrue(all(row.get("status") == "COMPLETE" for row in task["stages"]))

    def test_RP3_R04_new_decisions_bind_current_candidate(self):
        _stale_ready_after_lock_bump(self.host)
        current = observe_candidate(self.host).digest
        published = _publish_unit_report(self.host)
        self._refresh(published_test_report_id=published.extras["report_id"])
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(task["task_completion_decision"]["candidate_digest"], current)
        self.assertEqual(
            task["stages"][0]["completion_decision"]["candidate_digest"], current
        )
        self.assertEqual(task["task_completion_decision"]["outcome"], "SATISFIED")

    def test_RP3_R05_no_develop_session_created(self):
        _stale_ready_after_lock_bump(self.host)
        published = _publish_unit_report(self.host)
        result = self._refresh(published_test_report_id=published.extras["report_id"])
        self.assertIsNone(result.extras.get("session"))
        sessions = self.host / ".scaffold/runtime/develop-sessions"
        self.assertFalse(sessions.exists() and any(sessions.iterdir()))

    def test_RP3_R06_task_contract_digest_unchanged(self):
        _stale_ready_after_lock_bump(self.host)
        before = task_contract_digest(
            read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        )
        published = _publish_unit_report(self.host)
        result = self._refresh(published_test_report_id=published.extras["report_id"])
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        after = task_contract_digest(
            read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        )
        self.assertEqual(before, after)
        self.assertEqual(result.extras.get("task_contract_digest"), before)

    def test_RP3_R07_sav_remains_current_after_refresh_revision(self):
        write_host(self.host, [passing_profile(PROFILE)])
        bind_develop_lock(self.host)
        write(self.host, "src/app.py", "value = 0\n")
        write_task(self.host, status="READY_FOR_REVIEW", **_bound_task(stages=[{
            "stage_id": "stage-1",
            "goal": "Write the fixture source.",
            "acceptance": "src/app.py has the expected content.",
            "status": "COMPLETE",
            "required_tests": [
                {
                    "requirement_id": REQUIREMENT,
                    "execution_binding": {"kind": "test_profile", "profile_id": PROFILE},
                }
            ],
        }]))
        bind_ready_completion_authority(self.host, TASK_A)
        publish_sav_plan(
            self.host,
            _inspect_plan(candidate_digest=observe_candidate(self.host).digest),
        )
        _bump_lock_candidate(self.host)
        publish_sav_plan(
            self.host,
            {
                **_inspect_plan(candidate_digest=observe_candidate(self.host).digest),
                "plan_id": "sav-20260907T221000Z-abcdef02",
            },
        )
        published = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[_assertion(self.host)],
        )
        result = self._refresh(published_test_report_id=published.extras["report_id"])
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertTrue(reconstructed.get("current"), reconstructed)

    def test_RP3_R08_published_report_consumable_after_refresh(self):
        _stale_ready_after_lock_bump(self.host)
        published = _publish_unit_report(self.host)
        report_id = published.extras["report_id"]
        result = self._refresh(published_test_report_id=report_id)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        loaded = consume_published_report(
            self.host,
            report_id,
            task=read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
        )
        self.assertTrue(loaded.get("ok"), loaded)

    def test_RP3_R09_submit_s1_passes_after_refresh(self):
        _stale_ready_after_lock_bump(self.host)
        published = _publish_unit_report(self.host)
        refreshed = self._refresh(published_test_report_id=published.extras["report_id"])
        self.assertEqual(refreshed.outcome, "COMPLETED", refreshed.blockers)
        submit = run_submit(self.host)
        self.assertFalse(
            any(
                "not current completion authority" in str(item)
                for item in (submit.blockers or [])
            )
        )
        self.assertNotEqual((submit.extras or {}).get("stage"), "S1")

    def test_RP3_R10_source_write_blocks(self):
        _stale_ready_after_lock_bump(self.host)
        published = _publish_unit_report(self.host)
        result = self._refresh(
            published_test_report_id=published.extras["report_id"],
            writes=[{"path": "src/app.py", "content": "value = 9\n"}],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("source writes" in item for item in result.blockers))

    def test_RP3_R11_contract_change_blocks(self):
        _stale_ready_after_lock_bump(self.host)
        published = _publish_unit_report(self.host)
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        task["scope"] = {"paths": ["src/other.py"], "modules": [], "exclude": []}
        write_yaml_atomic(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml", task)
        result = self._refresh(published_test_report_id=published.extras["report_id"])
        self.assertEqual(result.outcome, "BLOCKED")

    def test_RP3_R12_stale_candidate_report_blocks(self):
        _verified_develop_host(self.host)
        write_ready_task(self.host)
        published = _publish_unit_report(self.host)
        _bump_lock_candidate(self.host)
        result = self._refresh(published_test_report_id=published.extras["report_id"])
        self.assertEqual(result.outcome, "BLOCKED")

    def test_RP3_R13_test_pass_false_blocks(self):
        _verified_develop_host(self.host, failing=True)
        write_ready_task(self.host)
        before = observe_candidate(self.host).digest
        _bump_lock_candidate(self.host)
        published = _publish_unit_report(self.host)
        self.assertFalse(published.extras.get("test_pass"))
        result = self._refresh(published_test_report_id=published.extras["report_id"])
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("TEST_PASS" in item for item in result.blockers))
        self.assertNotEqual(before, observe_candidate(self.host).digest)

    def test_RP3_R14_test_complete_false_blocks(self):
        _stale_ready_after_lock_bump(self.host)
        published = _publish_unit_report(self.host)
        report_id = published.extras["report_id"]
        path = self.host / ".scaffold/runtime/test-runs" / report_id / "report.yaml"
        data = read_yaml(path)
        completeness = dict(data.get("completeness") or {})
        completeness["test_complete"] = False
        data["completeness"] = completeness
        verification = dict(data.get("verification") or {})
        verification["test_complete"] = False
        data["verification"] = verification
        write_yaml_atomic(path, data)
        result = self._refresh(published_test_report_id=report_id)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("TEST_COMPLETE" in item for item in result.blockers))

    def test_RP3_R15_non_complete_stage_blocks(self):
        _stale_ready_after_lock_bump(self.host)
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        task["stages"][0]["status"] = "IN_PROGRESS"
        write_yaml_atomic(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml", task)
        published = _publish_unit_report(self.host)
        result = self._refresh(published_test_report_id=published.extras["report_id"])
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("COMPLETE" in item for item in result.blockers))

    def test_RP3_R16_raw_report_cannot_substitute(self):
        _stale_ready_after_lock_bump(self.host)
        published = _publish_unit_report(self.host)
        result = self._refresh(report=published.extras.get("report"))
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("untrusted" in item for item in result.blockers))


class DiveShapedReadyRefreshE2ETests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_RP3_E01_c1_ready_c2_retest_ready_refresh(self):
        write_host(self.host, [passing_profile(PROFILE)])
        bind_develop_lock(self.host)
        write(self.host, "src/app.py", "value = 0\n")
        write_task(self.host, **_bound_task())
        persist_currentness_without_completion(self.host)
        c1 = observe_candidate(self.host).digest
        publish_sav_plan(self.host, _inspect_plan(candidate_digest=c1))
        first = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[_assertion(self.host)],
        )
        self.assertEqual(first.outcome, "COMPLETED", first.blockers)
        ready = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            published_test_report_id=first.extras["report_id"],
            request_stage_complete=True,
            request_ready_for_review=True,
            **ready_lifecycle_opts(),
        )
        self.assertEqual(ready.outcome, "COMPLETED", ready.blockers)
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(task["status"], "READY_FOR_REVIEW")
        self.assertGreater(int(task["record_revision"]), 1)
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertTrue(reconstructed.get("current"), reconstructed)
        _bump_lock_candidate(self.host)
        persist_currentness_without_completion(self.host)
        c2 = observe_candidate(self.host).digest
        self.assertNotEqual(c1, c2)
        publish_sav_plan(
            self.host,
            {
                **_inspect_plan(candidate_digest=c2),
                "plan_id": "sav-20260907T222000Z-abcdef03",
            },
        )
        second = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[_assertion(self.host)],
        )
        self.assertEqual(second.outcome, "COMPLETED", second.blockers)
        refresh = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            refresh_ready_authority=True,
            published_test_report_id=second.extras["report_id"],
        )
        self.assertEqual(refresh.outcome, "COMPLETED", refresh.blockers)
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(task["status"], "READY_FOR_REVIEW")
        self.assertEqual(task["stages"][0]["status"], "COMPLETE")
        self.assertEqual(task["task_completion_decision"]["candidate_digest"], c2)
        self.assertTrue(
            reconstruct_sav_plan(
                self.host, task_id=TASK_A, requirement_id=REQUIREMENT
            ).get("current")
        )
        submit = run_submit(self.host)
        self.assertFalse(
            any(
                "not current completion authority" in str(item)
                for item in (submit.blockers or [])
            )
        )


if __name__ == "__main__":
    unittest.main()

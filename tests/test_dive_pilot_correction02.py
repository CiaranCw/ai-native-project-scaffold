from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from p6_support import (
    CORE_OWNERSHIP,
    failing_profile,
    passing_profile,
    test_engine,
    write_host,
)
from p7_support import (
    TASK_A,
    bind_develop_lock,
    develop_engine,
    ready_lifecycle_opts,
    write_active_host,
    write_task,
)
from p8_support import (
    init_submit_git,
    run_submit,
    write_ready_task,
    write_submit_host,
)
from p10_support import persist_currentness_without_completion, resume
from scaffold_p5.host_state import inspect_lock
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p5.resume import inspect_sessions
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.sav import publish_sav_plan
from scaffold_p7.engine import invoke_test
from scaffold_p7.schemas import validate_develop_session
from scaffold_p7.session import operational_project_name
from support import write


LOCK = ".scaffold/skills.lock"
SESSION_ID = "dev-20260907T120000Z-abcd1234"
REQUIREMENT = "inspect-step-distance"
PROFILE = "npm-test"


def _commit_without_lock(host: Path) -> None:
    lock_path = host / LOCK
    payload = lock_path.read_bytes()
    lock_path.unlink()
    init_submit_git(host)
    lock_path.write_bytes(payload)


def _first_adoption_host(host: Path, *, understand: bool = True) -> None:
    write_submit_host(host)
    _commit_without_lock(host)
    write(host, "src/app.py", "value = 1\n")
    if understand:
        persist_currentness_without_completion(host)
    write_ready_task(host)


def _authority(result) -> dict:
    return (result.extras.get("structural") or {}).get(
        "skills_lock_review_authority"
    ) or {}


def _verified_develop_host(host: Path, *, failing: bool = False) -> None:
    profile, command = failing_profile("unit") if failing else passing_profile("unit")
    write_host(host, [(profile, command)])
    bind_develop_lock(host)
    write(host, "src/app.py", "value = 0\n")
    payload = read_yaml(host / ".scaffold/project.yaml")
    payload["ownership"] = {**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"}
    payload["source_areas"] = ["src"]
    write_yaml_atomic(host / ".scaffold/project.yaml", payload)


def _publish_unit_report(host: Path, **opts):
    result = test_engine(host).run("scoped_verification", selected=["unit"], **opts)
    return result


def _legacy_session(
    host: Path,
    *,
    session_id: str = SESSION_ID,
    project_name: object = "",
    include_name: bool = True,
    files: list[dict] | None = None,
    status: str = "SEALED",
) -> None:
    directory = host / ".scaffold/runtime/develop-sessions" / session_id
    directory.mkdir(parents=True, exist_ok=True)
    session = {
        "record_type": "develop_session",
        "schema_version": "1",
        "record_id": session_id,
        "created_at": "2026-09-07T12:00:00Z",
        "updated_at": "2026-09-07T12:00:01Z",
        "status": status,
        "task_id": TASK_A,
        "mode": "normal_task",
        "baseline": {"kind": "unavailable", "value": None},
        "workspace_overlay_s0": {"coverage": "unavailable", "paths": []},
        "observed_candidate_digest": observe_candidate(host).digest or "sha256:" + ("ab" * 32),
    }
    if include_name:
        session["project_name"] = project_name
    write_yaml_atomic(directory / "session.yaml", session)
    write_yaml_atomic(directory / "files.yaml", {"files": list(files or [])})


def _inspect_plan() -> dict:
    return {
        "record_type": "test_scenario_aware_plan",
        "schema_version": "1",
        "supporting": True,
        "canonical": False,
        "plan_id": "sav-20260907T120000Z-abcdef01",
        "task_id": TASK_A,
        "task_revision": 1,
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
            },
            {
                "po_id": "PO-2",
                "obligation": "non-player Manhattan distance",
                "required": True,
                "observable_signals": ["inspect overlay"],
                "execution_strategy": "structured_assertion",
                "assertions": ["non-player Manhattan distance is exact"],
                "evidence_requirements": ["structured_assertion"],
                "observability_status": "SUFFICIENT",
            },
            {
                "po_id": "PO-3",
                "obligation": "existing inspect rows preserved",
                "required": True,
                "observable_signals": ["inspect row labels"],
                "execution_strategy": "structured_assertion",
                "assertions": ["existing inspect rows remain"],
                "evidence_requirements": ["structured_assertion"],
                "observability_status": "SUFFICIENT",
            },
            {
                "po_id": "PO-4",
                "obligation": "bound profile remains green",
                "required": True,
                "observable_signals": ["bound profile command_result"],
                "execution_strategy": "regression",
                "assertions": ["bound profile PASS"],
                "evidence_requirements": ["command_result"],
                "observability_status": "SUFFICIENT",
            },
        ],
    }


def _external_assertion(host: Path, po_id: str, *, passed: bool = True) -> dict:
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


class FirstAdoptionLockReviewTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_RP2_L01_initial_untracked_lock_does_not_block_s3(self):
        _first_adoption_host(self.host)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertNotEqual(result.extras.get("stage"), "S3", result.blockers)
        structural = result.extras.get("structural") or {}
        self.assertTrue(structural.get("structural_review_pass"), structural)
        authority = _authority(result)
        self.assertEqual(authority.get("kind"), "initial_adoption_lock_creation")
        self.assertTrue(authority.get("lawful"))
        self.assertEqual(inspect_lock(self.host / LOCK).status, "complete_authoritative")

    def test_RP2_L02_stale_understanding_blocks_initial_lock(self):
        _first_adoption_host(self.host, understand=False)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S3")
        self.assertTrue(
            any("Understanding is not CURRENT" in item for item in result.blockers)
        )
        self.assertFalse(_authority(result).get("lawful"))

    def test_RP2_L03_lock_digest_mismatch_blocks(self):
        _first_adoption_host(self.host)
        lock = read_yaml(self.host / LOCK)
        lock["skills"]["understand"]["package_digest"] = "f" * 64
        write_yaml_atomic(self.host / LOCK, lock)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S3")
        self.assertTrue(
            any(
                "skills.lock digest does not match current Understand structural authority"
                in item
                for item in result.blockers
            )
        )

    def test_RP2_L04_malformed_lock_blocks(self):
        _first_adoption_host(self.host)
        write_yaml_atomic(self.host / LOCK, {"schema_version": "1"})
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertNotEqual(inspect_lock(self.host / LOCK).status, "complete_authoritative")

    def test_RP2_L05_unknown_or_conflicting_lock_ownership_blocks(self):
        write_submit_host(self.host)
        payload = read_yaml(self.host / ".scaffold/project.yaml")
        ownership = dict(payload.get("ownership") or {})
        ownership[LOCK] = "MANAGED"
        payload["ownership"] = ownership
        write_yaml_atomic(self.host / ".scaffold/project.yaml", payload)
        _commit_without_lock(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        persist_currentness_without_completion(self.host)
        write_ready_task(self.host)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        joined = " ".join(result.blockers)
        self.assertTrue(
            "GENERATED" in joined or "UNKNOWN" in joined or "ownership" in joined,
            result.blockers,
        )

    def test_RP2_L06_tracked_existing_lock_modification_blocks(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        persist_currentness_without_completion(self.host)
        write_ready_task(self.host)
        lock = read_yaml(self.host / LOCK)
        lock["skills"]["understand"]["package_digest"] = "e" * 64
        write_yaml_atomic(self.host / LOCK, lock)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S3")
        self.assertTrue(
            any("core skills.lock change requires Understand compatibility review" in item for item in result.blockers)
        )
        self.assertEqual(_authority(result).get("kind"), "ordinary_lock_change")

    def test_RP2_L07_tracked_existing_lock_deletion_blocks(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        persist_currentness_without_completion(self.host)
        write_ready_task(self.host)
        (self.host / LOCK).unlink()
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        joined = " ".join(result.blockers)
        self.assertTrue(
            "deletion" in joined or "skills.lock" in joined,
            result.blockers,
        )

    def test_RP2_L08_initial_lock_stays_visible_as_scaffold_structure(self):
        _first_adoption_host(self.host)
        result = run_submit(self.host, task_id=TASK_A)
        paths = (result.extras.get("delta") or {}).get("paths") or []
        self.assertIn(LOCK, paths)
        structural = result.extras.get("structural") or {}
        self.assertIn("SCAFFOLD_STRUCTURE", structural.get("impact_classes") or [])
        self.assertIn(LOCK, structural.get("reviewed_paths") or [])

    def test_RP2_L09_dive_shaped_first_submit_proceeds_beyond_s3(self):
        _first_adoption_host(self.host)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertNotEqual(result.extras.get("stage"), "S3", result.blockers)
        self.assertTrue(
            (result.extras.get("structural") or {}).get("structural_review_pass")
        )


class OperationalSessionIdentityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_RP2_I01_conflicting_empty_project_name_is_executable(self):
        write_active_host(
            self.host,
            name="",
            facts=[
                {
                    "name": "project_name",
                    "value": {
                        "package": "concept-roguelike-demo",
                        "title": "概念 Roguelike — 规则原型",
                    },
                    "confidence": "CONFLICTING",
                    "critical": False,
                }
            ],
        )
        write_task(self.host)
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)

    def test_RP2_I02_new_session_uses_stable_nonempty_fallback(self):
        write_active_host(self.host, name="")
        write_task(self.host)
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        name = result.extras["session"]["project_name"]
        self.assertTrue(name)
        self.assertEqual(name, operational_project_name({"name": ""}, self.host))
        self.assertEqual(name, self.host.name)

    def test_RP2_I03_conflicting_project_name_fact_remains_conflicting(self):
        facts = [
            {
                "name": "project_name",
                "value": {
                    "package": "concept-roguelike-demo",
                    "title": "概念 Roguelike — 规则原型",
                },
                "confidence": "CONFLICTING",
                "critical": False,
            }
        ]
        write_active_host(self.host, name="", facts=facts)
        write_task(self.host)
        develop_engine(self.host).run("normal_task", task_id=TASK_A)
        stored = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertEqual(stored.get("name"), "")
        project_facts = [
            row
            for row in (stored.get("facts") or [])
            if isinstance(row, dict) and row.get("name") == "project_name"
        ]
        self.assertTrue(project_facts)
        self.assertEqual(project_facts[0].get("confidence"), "CONFLICTING")

    def test_RP2_I04_legacy_empty_session_project_name_reconstructs(self):
        write_active_host(self.host, name="")
        write_task(self.host)
        _legacy_session(self.host, project_name="")
        issues = validate_develop_session(
            read_yaml(
                self.host
                / ".scaffold/runtime/develop-sessions"
                / SESSION_ID
                / "session.yaml"
            ),
            expected_id=SESSION_ID,
        )
        self.assertEqual(issues, [])
        rows, blockers = inspect_sessions(self.host)
        self.assertFalse(any(SESSION_ID in item for item in blockers))
        matched = [row for row in rows if row.get("record_id") == SESSION_ID]
        self.assertEqual(matched[0].get("reconstruction"), "VALID")

    def test_RP2_I05_missing_project_name_remains_malformed(self):
        write_active_host(self.host)
        write_task(self.host)
        _legacy_session(self.host, include_name=False)
        issues = validate_develop_session(
            read_yaml(
                self.host
                / ".scaffold/runtime/develop-sessions"
                / SESSION_ID
                / "session.yaml"
            ),
            expected_id=SESSION_ID,
        )
        self.assertTrue(any("project_name is required" in item for item in issues))
        rows, blockers = inspect_sessions(self.host)
        matched = [row for row in rows if row.get("record_id") == SESSION_ID]
        self.assertEqual(matched[0].get("reconstruction"), "MALFORMED")
        self.assertTrue(any(SESSION_ID in item for item in blockers))

    def test_RP2_I06_non_string_project_name_remains_malformed(self):
        write_active_host(self.host)
        write_task(self.host)
        _legacy_session(self.host, project_name=12)
        issues = validate_develop_session(
            read_yaml(
                self.host
                / ".scaffold/runtime/develop-sessions"
                / SESSION_ID
                / "session.yaml"
            ),
            expected_id=SESSION_ID,
        )
        self.assertTrue(any("must be a string" in item for item in issues))

    def test_RP2_I07_resume_does_not_route_human_for_legacy_empty_name(self):
        write_active_host(self.host, name="")
        persist_currentness_without_completion(self.host)
        write_task(self.host)
        _legacy_session(self.host, project_name="")
        result = resume(self.host)
        self.assertNotEqual(result.next_route, "human", result.extras)
        rows, blockers = inspect_sessions(self.host)
        self.assertFalse(any("malformed" in item.lower() for item in blockers))
        matched = [row for row in rows if row.get("record_id") == SESSION_ID]
        self.assertEqual(matched[0].get("reconstruction"), "VALID")

    def test_RP2_I08_submit_s2_recovers_develop_known_from_legacy_session(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        persist_currentness_without_completion(self.host)
        from scaffold_p5.io_util import file_digest

        before_digest = "sha256:" + file_digest(self.host / "src/app.py")
        write(self.host, "src/app.py", "value = 2\n")
        after_digest = "sha256:" + file_digest(self.host / "src/app.py")
        _legacy_session(
            self.host,
            project_name="",
            files=[
                {
                    "path": "src/app.py",
                    "change_kind": "modified",
                    "was_preexisting_dirty": False,
                    "before_kind": "regular_file",
                    "after_kind": "regular_file",
                    "before_digest": before_digest,
                    "after_digest": after_digest,
                    "stage_ids": ["stage-1"],
                }
            ],
        )
        write_ready_task(self.host, develop_session_ids=[SESSION_ID])
        from scaffold_p8.delta import classify_delta, load_sealed_sessions, observe_real_diff

        observed = observe_real_diff(self.host)
        self.assertTrue(observed.get("ok"), observed)
        sessions = load_sealed_sessions(self.host, linked_ids={SESSION_ID})
        self.assertEqual(len(sessions), 1)
        delta = classify_delta(
            self.host,
            real_paths=list(observed.get("paths") or []),
            sessions=sessions,
            entries=list(observed.get("entries") or []),
        )
        self.assertEqual(delta["classes"].get("src/app.py"), "DEVELOP_KNOWN", delta)
        result = run_submit(self.host, task_id=TASK_A)
        extras_delta = result.extras.get("delta") or {}
        if extras_delta.get("classes"):
            self.assertEqual(extras_delta["classes"].get("src/app.py"), "DEVELOP_KNOWN")


class PublishedReportConsumptionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_RP2_R01_in_progress_can_bind_published_pass_without_reexecution(self):
        _verified_develop_host(self.host)
        write_task(self.host)
        published = _publish_unit_report(self.host)
        self.assertEqual(published.outcome, "COMPLETED", published.blockers)
        report_id = published.extras["report_id"]
        with patch("scaffold_p7.engine.invoke_test", wraps=invoke_test) as mocked:
            result = develop_engine(self.host).run(
                "normal_task",
                task_id=TASK_A,
                published_test_report_id=report_id,
            )
        mocked.assert_not_called()
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras.get("consumed_published_report"))
        self.assertIsNone(result.extras.get("develop_to_test"))
        self.assertEqual(result.extras["test_to_develop"]["report_id"], report_id)
        self.assertTrue(result.extras["test_to_develop"]["test_pass"])

    def test_RP2_R02_missing_published_report_blocks(self):
        _verified_develop_host(self.host)
        write_task(self.host)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            published_test_report_id="testrun-19990101T000000Z-deadbeef",
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("missing" in item for item in result.blockers))

    def test_RP2_R03_malformed_published_report_blocks(self):
        _verified_develop_host(self.host)
        write_task(self.host)
        published = _publish_unit_report(self.host)
        report_id = published.extras["report_id"]
        path = (
            self.host
            / ".scaffold/runtime/test-runs"
            / report_id
            / "report.yaml"
        )
        path.write_text("not: [valid\n", encoding="utf-8")
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            published_test_report_id=report_id,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("malformed" in item for item in result.blockers))

    def test_RP2_R04_stale_published_report_blocks(self):
        _verified_develop_host(self.host)
        write_task(self.host)
        published = _publish_unit_report(self.host)
        write(self.host, "README.md", "# drifted candidate\n")
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            published_test_report_id=published.extras["report_id"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("stale" in item for item in result.blockers))

    def test_RP2_R05_candidate_match_false_blocks(self):
        _verified_develop_host(self.host)
        write_task(self.host)
        published = _publish_unit_report(self.host)
        report_id = published.extras["report_id"]
        path = (
            self.host
            / ".scaffold/runtime/test-runs"
            / report_id
            / "report.yaml"
        )
        data = read_yaml(path)
        data["candidate_match"] = False
        completeness = dict(data.get("completeness") or {})
        completeness["candidate_match"] = False
        completeness["test_pass"] = False
        completeness["test_complete"] = False
        completeness["coverage_complete"] = False
        data["completeness"] = completeness
        verification = dict(data.get("verification") or {})
        verification["test_pass"] = False
        verification["test_complete"] = False
        data["verification"] = verification
        write_yaml_atomic(path, data)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            published_test_report_id=report_id,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(
            any("candidate_match" in item for item in result.blockers)
        )

    def test_RP2_R06_test_pass_false_cannot_support_satisfied(self):
        _verified_develop_host(self.host, failing=True)
        write_task(
            self.host,
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Write the fixture source.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "IN_PROGRESS",
                    "required_tests": [],
                }
            ],
        )
        published = _publish_unit_report(self.host)
        self.assertFalse(published.extras.get("test_pass"))
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            published_test_report_id=published.extras["report_id"],
            **ready_lifecycle_opts(),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(
            any("TEST_PASS is false" in item for item in result.blockers)
        )

    def test_RP2_R07_test_complete_false_cannot_support_ready(self):
        _verified_develop_host(self.host)
        write_task(
            self.host,
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Write the fixture source.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "IN_PROGRESS",
                    "required_tests": [],
                }
            ],
        )
        published = _publish_unit_report(self.host)
        report_id = published.extras["report_id"]
        path = (
            self.host
            / ".scaffold/runtime/test-runs"
            / report_id
            / "report.yaml"
        )
        data = read_yaml(path)
        completeness = dict(data.get("completeness") or {})
        completeness["test_complete"] = False
        data["completeness"] = completeness
        verification = dict(data.get("verification") or {})
        verification["test_complete"] = False
        data["verification"] = verification
        write_yaml_atomic(path, data)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            published_test_report_id=report_id,
            request_stage_complete=True,
            request_ready_for_review=True,
            **ready_lifecycle_opts(),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(
            any("TEST_COMPLETE is false" in item for item in result.blockers)
        )

    def test_RP2_R08_raw_report_dict_cannot_substitute_for_report_id(self):
        _verified_develop_host(self.host)
        write_task(self.host)
        published = _publish_unit_report(self.host)
        report = published.extras.get("report")
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            report=report,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("untrusted" in item for item in result.blockers))
        evidence = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            evidence=[{"kind": "command_result", "pass": True}],
        )
        self.assertEqual(evidence.outcome, "BLOCKED")
        self.assertTrue(any("evidence" in item for item in evidence.blockers))

    def test_RP2_R09_external_result_provenance_is_preserved(self):
        write_host(self.host, [passing_profile(PROFILE)])
        bind_develop_lock(self.host)
        write_task(
            self.host,
            final_tests=[
                {
                    "requirement_id": REQUIREMENT,
                    "execution_binding": {
                        "kind": "test_profile",
                        "profile_id": PROFILE,
                    },
                }
            ],
        )
        published_plan = publish_sav_plan(self.host, _inspect_plan())
        self.assertTrue(published_plan.get("ok"), published_plan)
        test = test_engine(self.host).run(
            "scoped_verification",
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[
                _external_assertion(self.host, "PO-1"),
                _external_assertion(self.host, "PO-2"),
                _external_assertion(self.host, "PO-3"),
            ],
        )
        self.assertEqual(test.outcome, "COMPLETED", test.blockers)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            published_test_report_id=test.extras["report_id"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        report = test_engine(self.host).load_report(test.extras["report_id"]) or {}
        assertions = [
            item
            for item in (report.get("evidence") or [])
            if isinstance(item, dict) and item.get("kind") == "structured_assertion"
        ]
        self.assertTrue(assertions)
        self.assertTrue(all(item.get("provenance") == "EXTERNAL_RESULT" for item in assertions))
        self.assertFalse(any(item.get("provenance") == "LOCAL_EXECUTION" for item in assertions))

    def test_RP2_R10_ready_no_write_revalidation_routes_to_submit(self):
        _verified_develop_host(self.host)
        write_ready_task(self.host)
        published = _publish_unit_report(self.host)
        from p8_support import bind_ready_completion_authority

        bind_ready_completion_authority(self.host, TASK_A)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            published_test_report_id=published.extras["report_id"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.mutations, "none")
        self.assertEqual(result.next_route, "submit")
        self.assertTrue(result.extras.get("ready_revalidation"))
        self.assertIsNone(result.extras.get("session"))
        sessions = self.host / ".scaffold/runtime/develop-sessions"
        self.assertFalse(sessions.exists() and any(sessions.iterdir()))

    def test_RP2_R11_ready_stale_report_blocks(self):
        _verified_develop_host(self.host)
        write_ready_task(self.host)
        published = _publish_unit_report(self.host)
        write(self.host, "README.md", "# stale after report\n")
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            published_test_report_id=published.extras["report_id"],
        )
        self.assertEqual(result.outcome, "BLOCKED")

    def test_RP2_R12_dive_shaped_ready_without_invoke_test_monkeypatch(self):
        _verified_develop_host(self.host)
        write_task(
            self.host,
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Write the fixture source.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "IN_PROGRESS",
                    "required_tests": [],
                }
            ],
        )
        published = _publish_unit_report(self.host)
        with patch("scaffold_p7.engine.invoke_test", wraps=invoke_test) as mocked:
            result = develop_engine(self.host).run(
                "normal_task",
                task_id=TASK_A,
                published_test_report_id=published.extras["report_id"],
                request_stage_complete=True,
                request_ready_for_review=True,
                **ready_lifecycle_opts(),
            )
        mocked.assert_not_called()
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras.get("ready_for_review"))
        self.assertEqual(result.next_route, "submit")
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(task["status"], "READY_FOR_REVIEW")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p7_support import TASK_A, TASK_B
from p8_support import (
    init_submit_git,
    run_submit,
    write_ready_task,
    write_submit_host,
)
from p10_support import persist_understanding, resume, subprocess_resume
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p5.packages import load_package
from scaffold_p6.candidate import observe_candidate
from scaffold_p7.repair_state import persist_repair_state
from scaffold_p7.session import create_session
from scaffold_p8.finalize import finalize_s10
from scaffold_p8.models import CHANGES_DIR
from scaffold_p8.records import (
    change_path,
    durable_task_finalization,
    persist_candidate_change,
)
from support import REPO, live_understand_distribution


TASK_C = "task-20260829T120400Z-ccc55555"
RECORD_A = "change-20260830T120000Z-aaa11111"
RECORD_B = "change-20260830T120100Z-bbb22222"
RECORD_BAD = "change-20260830T120300Z-dddd4444"

EXPECTED_PACKAGES = {
    "understand": (
        "2.1.0",
        "0f04f61cd1de48846e8619a2e05d75f4f06479a8576c03dd924d462c9b0283d8",
    ),
    "develop": (
        "2.1.0",
        "0a35bd95894e3baffcee802171b08759db3d00eb60a33db8028784fe6ec9583c",
    ),
    "test": (
        "2.0.1",
        "c90af65699a323a1ff3597051f310a12edd8c72583015d7934e17d717a5366f8",
    ),
    "submit": (
        "2.1.0",
        "672c6ea522792b4cec1e57b9c32c44b3af165519fa905b388e7aa4938e0452ef",
    ),
}


def _valid_change_record(record_id: str, *, task_book_ids: list[str] | None = None) -> dict:
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
        "task_book_ids": list(task_book_ids or []),
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


def _task_path(host: Path, task_id: str = TASK_A) -> Path:
    return host / ".scaffold" / "tasks" / f"{task_id}.yaml"


def _host_bytes(host: Path) -> dict[str, bytes]:
    payload: dict[str, bytes] = {}
    for path in sorted(host.rglob("*")):
        if path.is_file():
            payload[path.relative_to(host).as_posix()] = path.read_bytes()
    return payload


def _bind_resume_compatible_lock(host: Path) -> None:
    """Pin lock identities the live Understand distribution can resolve.

    write_submit_host uses live Develop/Test/Submit digests that the fixture
    index cannot resolve, which makes HOST_COMPATIBILITY UNKNOWN and blocks
    official understanding persist. Resume itself does not require this pin.
    """
    dist = live_understand_distribution()
    release = dist.selected_release
    if release is None:
        raise AssertionError("live Understand distribution has no selected release")
    path = host / ".scaffold" / "skills.lock"
    lock = read_yaml(path)
    skills = {}
    for skill_id in ("understand", "develop", "test", "submit"):
        pinned = release.pinned(skill_id)
        skills[skill_id] = {
            "skill_version": pinned.skill_version,
            "package_digest": pinned.package_digest,
            "package_format_version": pinned.package_format_version,
        }
    lock["skills"] = skills
    write_yaml_atomic(path, lock)


def _durable_finalize(host: Path, record_id: str, task_ids: list[str]) -> None:
    record = _valid_change_record(record_id, task_book_ids=task_ids)
    ok, blockers, path = persist_candidate_change(host, record)
    if not ok or path is None:
        raise AssertionError(blockers)
    digest = observe_candidate(host).digest
    finalized = finalize_s10(
        host,
        record_id=record_id,
        change_rel=path.relative_to(host).as_posix(),
        reviewed_paths=[],
        expected_digest=digest,
        scm_kind="none",
    )
    if not finalized.get("durable"):
        raise AssertionError(finalized)


def _work(result) -> dict:
    return result.extras.get("work") or {}


def _task_row(result, task_id: str = TASK_A) -> dict:
    for row in _work(result).get("tasks") or []:
        if row.get("record_id") == task_id:
            return row
    raise AssertionError(f"missing Task {task_id}")


class Correction05PackageIdentityTests(unittest.TestCase):
    def test_skill_package_identities_unchanged_from_correction_03(self):
        for skill_id, (version, digest) in EXPECTED_PACKAGES.items():
            pkg = load_package(REPO / "skills" / skill_id)
            self.assertEqual(pkg.ref.skill_version, version, skill_id)
            self.assertEqual(pkg.ref.package_digest, digest, skill_id)


class Maj012ResumeRoutingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write_submit_host(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def test_R01_ready_task_without_change_record_is_continuable_submit(self):
        result = resume(self.host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.mutations, "none")
        work = _work(result)
        self.assertEqual(work["ready_task_ids"], [TASK_A])
        self.assertEqual(work["durably_finalized_task_ids"], [])
        self.assertEqual(work["continuable_ready_task_ids"], [TASK_A])
        self.assertEqual(result.next_route, "submit")
        self.assertFalse(result.extras["submit"]["recovery"])

    def test_R02_non_durable_change_record_does_not_retire_ready_task(self):
        ok, blockers, _path = persist_candidate_change(
            self.host,
            _valid_change_record(RECORD_A, task_book_ids=[TASK_A]),
        )
        self.assertTrue(ok, blockers)
        result = resume(self.host)
        work = _work(result)
        self.assertEqual(work["durably_finalized_task_ids"], [])
        self.assertEqual(work["continuable_ready_task_ids"], [TASK_A])
        self.assertEqual(result.next_route, "submit")
        self.assertEqual(read_yaml(_task_path(self.host))["status"], "READY_FOR_REVIEW")

    def test_R03_durable_s10_change_record_retires_ready_task_from_routing(self):
        _durable_finalize(self.host, RECORD_A, [TASK_A])
        result = resume(self.host)
        work = _work(result)
        self.assertEqual(work["ready_task_ids"], [TASK_A])
        self.assertEqual(work["durably_finalized_task_ids"], [TASK_A])
        self.assertEqual(work["continuable_ready_task_ids"], [])
        self.assertNotEqual(result.next_route, "submit")
        row = _task_row(result)
        self.assertEqual(row["status"], "READY_FOR_REVIEW")
        self.assertTrue(row["durably_finalized"])
        self.assertFalse(row["continuable"])

    def test_R04_task_book_remains_physically_ready(self):
        _durable_finalize(self.host, RECORD_A, [TASK_A])
        resume(self.host)
        self.assertEqual(read_yaml(_task_path(self.host))["status"], "READY_FOR_REVIEW")

    def test_R05_resume_mutates_nothing(self):
        _durable_finalize(self.host, RECORD_A, [TASK_A])
        before = _host_bytes(self.host)
        result = resume(self.host)
        self.assertEqual(result.mutations, "none")
        self.assertEqual(_host_bytes(self.host), before)

    def test_R06_durable_record_for_another_task_does_not_retire_current(self):
        _durable_finalize(self.host, RECORD_B, [TASK_B])
        result = resume(self.host)
        work = _work(result)
        self.assertEqual(work["ready_task_ids"], [TASK_A])
        self.assertEqual(work["durably_finalized_task_ids"], [TASK_B])
        self.assertEqual(work["continuable_ready_task_ids"], [TASK_A])
        self.assertEqual(result.next_route, "submit")

    def test_R07_malformed_task_book_ids_fails_closed(self):
        (self.host / CHANGES_DIR).mkdir(parents=True, exist_ok=True)
        write_yaml_atomic(
            change_path(self.host, RECORD_BAD),
            _valid_change_record(RECORD_BAD, task_book_ids=["not-a-task-id"]),
        )
        result = resume(self.host)
        work = _work(result)
        self.assertEqual(work["durably_finalized_task_ids"], [])
        self.assertEqual(work["continuable_ready_task_ids"], [TASK_A])
        self.assertTrue(work["finalization_blockers"])
        self.assertEqual(result.next_route, "human")
        self.assertNotEqual(result.next_route, "submit")
        self.assertEqual(read_yaml(_task_path(self.host))["status"], "READY_FOR_REVIEW")

    def test_R08_conflicting_durable_finalization_fails_closed(self):
        _durable_finalize(self.host, RECORD_A, [TASK_A])
        _durable_finalize(self.host, RECORD_B, [TASK_A])
        result = resume(self.host)
        work = _work(result)
        self.assertNotIn(TASK_A, work["durably_finalized_task_ids"])
        self.assertTrue(work["finalization_blockers"])
        self.assertEqual(result.next_route, "human")
        self.assertNotEqual(result.next_route, "submit")
        view = durable_task_finalization(self.host)
        self.assertTrue(view["blockers"])
        self.assertNotIn(TASK_A, view["durably_finalized_task_ids"])

    def test_R09_one_finalized_and_one_unfinished_ready_routes_unfinished(self):
        write_ready_task(self.host, record_id=TASK_B)
        _durable_finalize(self.host, RECORD_A, [TASK_A])
        result = resume(self.host)
        work = _work(result)
        self.assertEqual(set(work["ready_task_ids"]), {TASK_A, TASK_B})
        self.assertEqual(work["durably_finalized_task_ids"], [TASK_A])
        self.assertEqual(work["continuable_ready_task_ids"], [TASK_B])
        self.assertEqual(result.next_route, "submit")
        self.assertEqual(result.extras.get("ambiguous_task_ids") or [], [])

    def test_R10_two_finalized_ready_tasks_do_not_route_submit(self):
        write_ready_task(self.host, record_id=TASK_B)
        _durable_finalize(self.host, RECORD_A, [TASK_A])
        _durable_finalize(self.host, RECORD_B, [TASK_B])
        result = resume(self.host)
        work = _work(result)
        self.assertEqual(set(work["ready_task_ids"]), {TASK_A, TASK_B})
        self.assertEqual(set(work["durably_finalized_task_ids"]), {TASK_A, TASK_B})
        self.assertEqual(work["continuable_ready_task_ids"], [])
        self.assertNotEqual(result.next_route, "submit")

    def test_R11_one_finalized_and_two_unfinished_human_on_unfinished_only(self):
        write_ready_task(self.host, record_id=TASK_B)
        write_ready_task(self.host, record_id=TASK_C)
        _durable_finalize(self.host, RECORD_A, [TASK_A])
        result = resume(self.host)
        work = _work(result)
        self.assertEqual(work["durably_finalized_task_ids"], [TASK_A])
        self.assertEqual(set(work["continuable_ready_task_ids"]), {TASK_B, TASK_C})
        self.assertEqual(result.next_route, "human")
        self.assertEqual(set(result.extras["ambiguous_task_ids"]), {TASK_B, TASK_C})
        self.assertNotIn(TASK_A, result.extras["ambiguous_task_ids"])

    def test_R12_fresh_process_deterministic_reconstruction(self):
        _durable_finalize(self.host, RECORD_A, [TASK_A])
        first = subprocess_resume(self.host)
        second = subprocess_resume(self.host)
        self.assertEqual(first, second)
        self.assertEqual(first["ready_task_ids"], [TASK_A])
        self.assertEqual(first["durably_finalized_task_ids"], [TASK_A])
        self.assertEqual(first["continuable_ready_task_ids"], [])
        self.assertNotEqual(first["next_route"], "submit")

    def test_R13_dive_shaped_post_s12_git_resume_is_none(self):
        _bind_resume_compatible_lock(self.host)
        init_submit_git(self.host)
        submitted = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(submitted.outcome, "COMPLETED", submitted.blockers)
        self.assertTrue(submitted.extras["s10"]["durable"])
        refreshed = persist_understanding(self.host)
        self.assertEqual(refreshed.outcome, "COMPLETED", refreshed.blockers)
        before = _host_bytes(self.host)
        result = resume(self.host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.mutations, "none")
        self.assertEqual(_host_bytes(self.host), before)
        work = _work(result)
        self.assertEqual(work["ready_task_ids"], [TASK_A])
        self.assertEqual(work["durably_finalized_task_ids"], [TASK_A])
        self.assertEqual(work["continuable_ready_task_ids"], [])
        self.assertFalse(result.extras["submit"]["recovery"])
        self.assertEqual(result.next_route, "none")
        self.assertEqual(read_yaml(_task_path(self.host))["status"], "READY_FOR_REVIEW")
        self.assertEqual(
            result.extras["understanding"]["currentness"],
            "CURRENT",
        )

    def test_R14_stale_repair_on_finalized_task_does_not_route_repair(self):
        _durable_finalize(self.host, RECORD_A, [TASK_A])
        persist_repair_state(
            self.host,
            {
                "task_id": TASK_A,
                "status": "pending",
                "target_stage_ids": ["stage-1"],
                "blockers": ["stale leftover"],
                "reason": "supporting state after durable S10",
            },
        )
        result = resume(self.host)
        self.assertTrue(_work(result).get("repair"))
        self.assertNotEqual(result.next_route, "develop.repair")
        self.assertNotEqual(result.next_route, "submit")

    def test_R15_stale_test_failure_on_finalized_task_does_not_route_test(self):
        _durable_finalize(self.host, RECORD_A, [TASK_A])
        persist_repair_state(
            self.host,
            {
                "task_id": TASK_A,
                "status": "recorded",
                "fail_ids": ["unit"],
                "reason": "historical required failure",
            },
        )
        result = resume(self.host)
        self.assertTrue(result.extras["test"]["required_failures"])
        self.assertNotEqual(result.next_route, "test")
        self.assertNotEqual(result.next_route, "submit")

    def test_R16_open_session_on_finalized_task_does_not_continue(self):
        _durable_finalize(self.host, RECORD_A, [TASK_A])
        created = create_session(
            self.host,
            task_id=TASK_A,
            mode="normal_task",
            project_name="host",
            candidate_digest=observe_candidate(self.host).digest,
        )
        self.assertTrue(created.ok, created.blockers)
        result = resume(self.host)
        self.assertEqual(result.extras["work"]["sessions"][0]["status"], "OPEN")
        self.assertNotEqual(result.next_route, "develop.continue")
        self.assertNotEqual(result.next_route, "submit")

    def test_R17_explicit_finalized_task_id_does_not_submit(self):
        _durable_finalize(self.host, RECORD_A, [TASK_A])
        result = resume(self.host, task_id=TASK_A)
        self.assertEqual(_work(result)["durably_finalized_task_ids"], [TASK_A])
        self.assertEqual(_work(result)["continuable_ready_task_ids"], [])
        self.assertNotEqual(result.next_route, "submit")

    def test_R18_unfinished_task_repair_still_routes_repair(self):
        write_ready_task(self.host, record_id=TASK_B)
        _durable_finalize(self.host, RECORD_A, [TASK_A])
        persist_repair_state(
            self.host,
            {
                "task_id": TASK_B,
                "status": "pending",
                "target_stage_ids": ["stage-1"],
                "blockers": ["current blocker"],
                "reason": "unfinished Task still needs Repair",
            },
        )
        result = resume(self.host)
        self.assertEqual(result.next_route, "develop.repair")
        self.assertNotEqual(result.next_route, "submit")

    def test_R19_git_history_reconstructs_deleted_live_change_record(self):
        _bind_resume_compatible_lock(self.host)
        init_submit_git(self.host)
        submitted = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(submitted.outcome, "COMPLETED", submitted.blockers)
        records = list((self.host / CHANGES_DIR).glob("change-*.yaml"))
        self.assertTrue(records)
        records[0].unlink()
        self.assertFalse(records[0].exists())
        result = resume(self.host)
        work = _work(result)
        self.assertEqual(work["durably_finalized_task_ids"], [TASK_A])
        self.assertEqual(work["continuable_ready_task_ids"], [])
        self.assertNotEqual(result.next_route, "submit")
        self.assertEqual(read_yaml(_task_path(self.host))["status"], "READY_FOR_REVIEW")

    def test_R20_noscms_missing_live_record_with_publication_fails_closed(self):
        _durable_finalize(self.host, RECORD_A, [TASK_A])
        path = change_path(self.host, RECORD_A)
        self.assertTrue(path.is_file())
        path.unlink()
        result = resume(self.host)
        work = _work(result)
        self.assertNotIn(TASK_A, work["durably_finalized_task_ids"])
        self.assertTrue(work["finalization_blockers"])
        self.assertEqual(result.next_route, "human")
        self.assertNotEqual(result.next_route, "submit")
        self.assertEqual(read_yaml(_task_path(self.host))["status"], "READY_FOR_REVIEW")

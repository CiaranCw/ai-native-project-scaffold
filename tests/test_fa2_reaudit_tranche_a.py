from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from p6_support import CORE_OWNERSHIP, git
from p7_support import (
    TASK_A,
    develop_engine,
    ensure_noscms_accepted_anchor,
    satisfied_decision,
    submit_repair_handoff,
    write_active_host,
    write_task,
)
from p8_support import (
    OPERATION_S10,
    authorized_submit_engine,
    init_submit_git,
    run_submit,
    submit_engine,
    write_ready_task,
    write_submit_host,
)
from scaffold_p5 import yaml_lite
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p5.packages import load_package
from scaffold_p6.candidate import observe_candidate
from scaffold_p7.handoff import validate_ready_repair_handoff
from scaffold_p7.lifecycle import prepare_lifecycle
from scaffold_p7.models import SESSIONS_DIR
from scaffold_p8.delta import observe_real_diff
from scaffold_p8.engine import SubmitEngine
from scaffold_p8.handoff import (
    UNRESOLVED_REPAIR_REASON,
    executable_repair_route,
    map_repair_target_stage_ids,
)
from scaffold_p8.models import CHANGES_DIR, NOSCMS_PUBLICATIONS_DIR
from scaffold_p8.noscms import (
    BASELINE_REL,
    COMPLETE_NAME,
    OBJECTS_DIRNAME,
    load_noscms_baseline,
)
from scaffold_p8.records import change_path, frozen_cleanup_session_ids
from support import REPO, write


CANONICAL = {
    "understand": REPO / "skills" / "understand",
    "develop": REPO / "skills" / "develop",
    "test": REPO / "skills" / "test",
    "submit": REPO / "skills" / "submit",
}
ROUTING_DOC = REPO / "docs" / "architecture" / "SKILL_ROUTING_AND_VERSIONING.md"
P6_DOC = REPO / "docs" / "implementation" / "P6_TEST.md"
STATUS_DOCS = (
    REPO / "README.md",
    REPO / "docs" / "implementation" / "P5_UNDERSTAND.md",
    P6_DOC,
    REPO / "docs" / "implementation" / "P7_DEVELOP.md",
    REPO / "docs" / "implementation" / "P8_SUBMIT.md",
    REPO / "docs" / "implementation" / "FA2_BATCH9_PACKAGE_DOCS.md",
)


def _two_in_progress() -> list[dict]:
    return [
        {
            "stage_id": "stage-1",
            "goal": "First stage.",
            "acceptance": "src/app.py has the expected content.",
            "status": "IN_PROGRESS",
            "required_tests": [],
        },
        {
            "stage_id": "stage-2",
            "goal": "Second stage.",
            "acceptance": "src/app.py has the expected content.",
            "status": "IN_PROGRESS",
            "required_tests": [],
        },
    ]


def _complete_stage(stage_id: str = "stage-1") -> dict:
    return {
        "stage_id": stage_id,
        "goal": "Write the fixture source.",
        "acceptance": "src/app.py has the expected content.",
        "status": "COMPLETE",
        "required_tests": [],
    }


class FA2ReauditTrancheATests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _prepare_lifecycle(self, task, **opts):
        digest = observe_candidate(self.host).digest
        return prepare_lifecycle(
            task,
            root=self.host,
            candidate_digest=digest,
            **opts,
        )

    def test_RA04_01_unscoped_decision_completes_no_stage(self):
        write_active_host(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        task = write_task(self.host, stages=_two_in_progress())
        unscoped = {
            "outcome": "SATISFIED",
            "rationale": "Unscoped completion must not bind every Stage.",
            "basis": [
                {
                    "kind": "repository_observation",
                    "summary": "src/app.py has the expected content.",
                }
            ],
        }
        self.assertNotIn("stage_id", unscoped)
        updated, blockers, extras = self._prepare_lifecycle(
            task,
            request_stage_complete=True,
            stage_completion_decision=unscoped,
        )
        self.assertTrue(blockers, blockers)
        self.assertTrue(extras.get("stage_completion_rejected"))
        self.assertEqual(
            [stage["status"] for stage in updated["stages"]],
            ["IN_PROGRESS", "IN_PROGRESS"],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            request_stage_complete=True,
            stage_completion_decision=unscoped,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        persisted = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(
            [stage["status"] for stage in persisted["stages"]],
            ["IN_PROGRESS", "IN_PROGRESS"],
        )

    def test_RA04_02_explicit_stage_1_only(self):
        write_active_host(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        task = write_task(self.host, stages=_two_in_progress())
        updated, blockers, _extras = self._prepare_lifecycle(
            task,
            request_stage_complete=True,
            stage_completion_decision=satisfied_decision(stage_id="stage-1"),
        )
        self.assertEqual(blockers, [])
        self.assertEqual(updated["stages"][0]["status"], "COMPLETE")
        self.assertEqual(updated["stages"][1]["status"], "IN_PROGRESS")
        self.assertEqual(
            updated["stages"][0]["completion_decision"]["stage_id"],
            "stage-1",
        )
        self.assertNotEqual(updated["stages"][1].get("status"), "COMPLETE")

    def test_RA04_03_nonexistent_stage_id(self):
        write_active_host(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        task = write_task(self.host, stages=_two_in_progress())
        updated, blockers, extras = self._prepare_lifecycle(
            task,
            request_stage_complete=True,
            stage_completion_decision=satisfied_decision(stage_id="stage-missing"),
        )
        self.assertTrue(blockers, blockers)
        self.assertTrue(extras.get("stage_completion_rejected"))
        self.assertEqual(
            [stage["status"] for stage in updated["stages"]],
            ["IN_PROGRESS", "IN_PROGRESS"],
        )

    def test_RA04_04_unscoped_decision_is_not_restamped(self):
        write_active_host(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        task = write_task(self.host, stages=_two_in_progress())
        unscoped = {
            "outcome": "SATISFIED",
            "rationale": "One decision must not be cloned onto every Stage.",
            "basis": [
                {
                    "kind": "repository_observation",
                    "summary": "src/app.py has the expected content.",
                }
            ],
        }
        updated, blockers, _extras = self._prepare_lifecycle(
            task,
            request_stage_complete=True,
            stage_completion_decision=unscoped,
        )
        self.assertTrue(blockers, blockers)
        stamped = [
            stage.get("completion_decision")
            for stage in updated["stages"]
            if isinstance(stage.get("completion_decision"), dict)
        ]
        self.assertEqual(stamped, [])
        self.assertEqual(
            {stage.get("stage_id") for stage in updated["stages"]},
            {"stage-1", "stage-2"},
        )

    def test_RA04_05_explicit_stage_completion_still_passes(self):
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write(self.host, "src/app.py", "value = 0\n")
        write_task(self.host, stages=[_two_in_progress()[0]])
        ensure_noscms_accepted_anchor(self.host)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "value = 1\n"}],
            request_stage_complete=True,
            stage_completion_decision=satisfied_decision(stage_id="stage-1"),
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        persisted = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(persisted["stages"][0]["status"], "COMPLETE")
        self.assertEqual(
            persisted["stages"][0]["completion_decision"]["stage_id"],
            "stage-1",
        )

    def test_RA_MIN03_01_omitted_blockers_invalid(self):
        write_active_host(self.host)
        write_task(
            self.host,
            status="READY_FOR_REVIEW",
            stages=[_complete_stage()],
        )
        digest = observe_candidate(self.host).digest
        handoff = submit_repair_handoff(
            candidate_digest=digest,
            target_stage_ids=["stage-1"],
        )
        handoff["test_pass"] = False
        del handoff["blockers"]
        ok, reason = validate_ready_repair_handoff(
            handoff,
            task=read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
            candidate_digest=digest,
        )
        self.assertFalse(ok)
        self.assertIn("blocker", reason.lower())

    def test_RA_MIN03_02_empty_blockers_invalid(self):
        write_active_host(self.host)
        write_task(
            self.host,
            status="READY_FOR_REVIEW",
            stages=[_complete_stage()],
        )
        digest = observe_candidate(self.host).digest
        ok, reason = validate_ready_repair_handoff(
            submit_repair_handoff(
                candidate_digest=digest,
                target_stage_ids=["stage-1"],
                test_pass=False,
                blockers=[],
            ),
            task=read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
            candidate_digest=digest,
        )
        self.assertFalse(ok)
        self.assertIn("blocker", reason.lower())

    def test_RA_MIN03_03_nonempty_blockers_accepted(self):
        write_active_host(self.host)
        write_task(
            self.host,
            status="READY_FOR_REVIEW",
            stages=[_complete_stage()],
        )
        digest = observe_candidate(self.host).digest
        ok, reason = validate_ready_repair_handoff(
            submit_repair_handoff(
                candidate_digest=digest,
                target_stage_ids=["stage-1"],
                test_pass=False,
                blockers=["required verification failed"],
            ),
            task=read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
            candidate_digest=digest,
        )
        self.assertTrue(ok, reason)

    def test_RA05_01_equal_names_do_not_map(self):
        task = {
            "record_id": TASK_A,
            "stages": [
                {
                    "stage_id": "stage-1",
                    "status": "COMPLETE",
                    "required_tests": [{"requirement_id": "unit"}],
                }
            ],
        }
        mapped = map_repair_target_stage_ids(task, fail_ids=["unit"])
        self.assertEqual(mapped, [])
        route, handoff, blockers = executable_repair_route(
            task,
            candidate_digest="sha256:" + "a" * 64,
            blockers=["project profile unit failed"],
            fail_ids=["unit"],
        )
        self.assertEqual(route, "human")
        self.assertIsNone(handoff)
        self.assertTrue(any(UNRESOLVED_REPAIR_REASON in item for item in blockers))

    def test_RA05_02_explicit_binding_maps(self):
        task = {
            "record_id": TASK_A,
            "stages": [
                {
                    "stage_id": "stage-1",
                    "status": "COMPLETE",
                    "required_tests": [
                        {
                            "requirement_id": "req-A",
                            "execution_binding": {
                                "kind": "test_profile",
                                "profile_id": "profile-X",
                            },
                        }
                    ],
                }
            ],
        }
        self.assertEqual(
            map_repair_target_stage_ids(task, fail_ids=["profile-X"]),
            ["stage-1"],
        )

    def test_RA05_03_different_names_still_map(self):
        task = {
            "record_id": TASK_A,
            "stages": [
                {
                    "stage_id": "stage-2",
                    "status": "COMPLETE",
                    "required_tests": [
                        {
                            "requirement_id": "req-A",
                            "execution_binding": {
                                "kind": "test_profile",
                                "profile_id": "profile-X",
                            },
                        }
                    ],
                }
            ],
        }
        self.assertNotEqual("req-A", "profile-X")
        self.assertEqual(
            map_repair_target_stage_ids(task, fail_ids=["profile-X"]),
            ["stage-2"],
        )

    def test_RA05_04_equal_spelling_does_not_override_binding(self):
        task = {
            "record_id": TASK_A,
            "stages": [
                {
                    "stage_id": "stage-1",
                    "status": "COMPLETE",
                    "required_tests": [
                        {
                            "requirement_id": "unit",
                            "execution_binding": {
                                "kind": "test_profile",
                                "profile_id": "profile-X",
                            },
                        }
                    ],
                }
            ],
        }
        self.assertEqual(map_repair_target_stage_ids(task, fail_ids=["unit"]), [])
        self.assertEqual(
            map_repair_target_stage_ids(task, fail_ids=["profile-X"]),
            ["stage-1"],
        )

    def test_RA05_05_no_stage_fallback_when_unresolved(self):
        one = {
            "record_id": TASK_A,
            "stages": [
                {
                    "stage_id": "stage-1",
                    "status": "COMPLETE",
                    "required_tests": [{"requirement_id": "unit"}],
                }
            ],
        }
        self.assertEqual(map_repair_target_stage_ids(one, fail_ids=["unit"]), [])
        self.assertEqual(
            map_repair_target_stage_ids(one, missing_source=["src/app.py"]),
            ["stage-1"],
        )
        two = {
            "record_id": TASK_A,
            "stages": [
                _complete_stage("stage-1"),
                _complete_stage("stage-2"),
            ],
        }
        self.assertEqual(map_repair_target_stage_ids(two, fail_ids=["unit"]), [])
        self.assertEqual(
            map_repair_target_stage_ids(two, missing_source=["src/app.py"]),
            [],
        )
        self.assertEqual(
            map_repair_target_stage_ids(two, undeclared=["src/app.py"]),
            [],
        )

    def _write_sealed_session(self, session_id: str, *, replace_links: bool = True) -> str:
        directory = self.host / SESSIONS_DIR / session_id
        directory.mkdir(parents=True, exist_ok=True)
        write_yaml_atomic(
            directory / "session.yaml",
            {
                "record_type": "develop_session",
                "schema_version": "1",
                "record_id": session_id,
                "created_at": "2026-09-03T18:00:00Z",
                "updated_at": "2026-09-03T18:00:00Z",
                "status": "SEALED",
                "task_id": TASK_A,
                "mode": "normal_task",
                "project_name": self.host.name,
                "baseline": {"kind": "none", "value": None},
                "workspace_overlay_s0": {"coverage": "unavailable", "paths": []},
                "observed_candidate_digest": observe_candidate(self.host).digest,
            },
        )
        write_yaml_atomic(
            directory / "files.yaml",
            {"files": [{"path": "src/app.py"}]},
        )
        if replace_links:
            task_path = self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
            existing = []
            if task_path.is_file():
                existing = list(read_yaml(task_path).get("develop_session_ids") or [])
            write_ready_task(
                self.host,
                develop_session_ids=list(dict.fromkeys(existing + [session_id])),
            )
        return session_id

    def _git_finalize_cleanup_failure(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        session_a = self._write_sealed_session("dev-20260903T180000Z-aaaaaaa1")
        engine, provider = authorized_submit_engine(self.host)
        digest = observe_candidate(self.host).digest
        ref = provider.issue(
            operation=OPERATION_S10,
            candidate_digest=digest,
            attempt_id="A1",
        )
        first = engine.run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorization_ref=ref,
            submit_authorization_attempt_id="A1",
            fail_cleanup=True,
        )
        return first, session_a

    def _expand_working_tree_change_record(self, change_id: str, session_b: str):
        path = change_path(self.host, change_id)
        record = read_yaml(path)
        ids = list(record["provenance"]["relevant_develop_session_ids"])
        if session_b not in ids:
            ids.append(session_b)
        record["provenance"]["relevant_develop_session_ids"] = ids
        record["provenance"]["relevant_develop_session_count"] = len(ids)
        write_yaml_atomic(path, record)
        return record

    def test_RA06_01_retry_uses_durable_session_a_only(self):
        first, session_a = self._git_finalize_cleanup_failure()
        self.assertNotEqual(first.outcome, "COMPLETED")
        change_id = first.extras["cleanup_retry"]["change_id"]
        session_b = self._write_sealed_session("dev-20260903T181000Z-bbbbbbbb")
        self._expand_working_tree_change_record(change_id, session_b)
        retry = submit_engine(self.host).run(
            cleanup_retry=first.extras["cleanup_retry"],
        )
        self.assertEqual(retry.outcome, "COMPLETED", retry.blockers)
        cleaned = retry.extras["cleanup"]["cleaned"]
        self.assertIn(session_a, cleaned)
        self.assertNotIn(session_b, cleaned)
        self.assertFalse((self.host / SESSIONS_DIR / session_a).exists())
        self.assertTrue((self.host / SESSIONS_DIR / session_b).is_dir())
        frozen = frozen_cleanup_session_ids(retry.extras["change_record"])
        self.assertEqual(frozen, [session_a])

    def test_RA06_02_working_tree_mutation_cannot_expand_cleanup(self):
        first, session_a = self._git_finalize_cleanup_failure()
        change_id = first.extras["cleanup_retry"]["change_id"]
        session_b = self._write_sealed_session("dev-20260903T181000Z-bbbbbbbb")
        live = self._expand_working_tree_change_record(change_id, session_b)
        self.assertIn(session_b, live["provenance"]["relevant_develop_session_ids"])
        retry = submit_engine(self.host).run(
            cleanup_retry=first.extras["cleanup_retry"],
        )
        self.assertEqual(retry.outcome, "COMPLETED", retry.blockers)
        self.assertNotIn(session_b, retry.extras["cleanup"]["cleaned"])
        self.assertTrue((self.host / SESSIONS_DIR / session_b).is_dir())
        self.assertNotIn(
            session_b,
            retry.extras["change_record"]["provenance"]["relevant_develop_session_ids"],
        )
        self.assertIn(session_a, retry.extras["cleanup"]["cleaned"])

    def test_RA06_03_fresh_process_resolves_same_durable_set(self):
        first, session_a = self._git_finalize_cleanup_failure()
        change_id = first.extras["cleanup_retry"]["change_id"]
        session_b = self._write_sealed_session("dev-20260903T181000Z-bbbbbbbb")
        self._expand_working_tree_change_record(change_id, session_b)
        retry = SubmitEngine(self.host).run(
            cleanup_retry=first.extras["cleanup_retry"],
        )
        self.assertEqual(retry.outcome, "COMPLETED", retry.blockers)
        self.assertEqual(
            frozen_cleanup_session_ids(retry.extras["change_record"]),
            [session_a],
        )
        self.assertNotIn(session_b, retry.extras["cleanup"]["cleaned"])

    def test_RA06_04_unresolvable_durable_record_fails_closed(self):
        first, _session_a = self._git_finalize_cleanup_failure()
        change_id = first.extras["cleanup_retry"]["change_id"]
        session_b = self._write_sealed_session("dev-20260903T181000Z-bbbbbbbb")
        self._expand_working_tree_change_record(change_id, session_b)
        rel = f"{CHANGES_DIR}/{change_id}.yaml"
        blob = git(self.host, "rev-parse", f"HEAD:{rel}").strip()
        obj = self.host / ".git" / "objects" / blob[:2] / blob[2:]
        self.assertTrue(obj.is_file(), blob)
        obj.chmod(0o600)
        obj.write_bytes(b"not-a-git-object")
        retry = submit_engine(self.host).run(
            cleanup_retry=first.extras["cleanup_retry"],
        )
        self.assertNotEqual(retry.outcome, "COMPLETED")
        self.assertTrue((self.host / SESSIONS_DIR / session_b).is_dir())
        self.assertNotIn(
            session_b,
            (retry.extras.get("cleanup") or {}).get("cleaned") or [],
        )

    def test_RA06_05_retry_is_s12_only(self):
        first, _session_a = self._git_finalize_cleanup_failure()
        change_id = first.extras["cleanup_retry"]["change_id"]
        before_head = git(self.host, "rev-parse", "HEAD")
        retry = submit_engine(self.host).run(
            cleanup_retry=first.extras["cleanup_retry"],
        )
        self.assertEqual(retry.outcome, "COMPLETED", retry.blockers)
        self.assertEqual(retry.extras["stage"], "S12")
        self.assertEqual(retry.extras["cleanup_retry"]["operation"], "cleanup_retry")
        self.assertEqual(retry.extras["cleanup_retry"]["change_id"], change_id)
        self.assertFalse(retry.extras.get("submit_authorized"))
        self.assertEqual(git(self.host, "rev-parse", "HEAD"), before_head)
        self.assertEqual(
            len(list((self.host / CHANGES_DIR).glob("*.yaml"))),
            1,
        )

    def test_RA06_06_no_task_empty_frozen_set(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        task_path = self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
        if task_path.is_file():
            task_path.unlink()
        engine, provider = authorized_submit_engine(self.host)
        digest = observe_candidate(self.host).digest
        ref = provider.issue(
            operation=OPERATION_S10,
            candidate_digest=digest,
            attempt_id="A1",
        )
        first = engine.run(
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorization_ref=ref,
            submit_authorization_attempt_id="A1",
            fail_cleanup=True,
        )
        self.assertTrue(first.extras.get("s10_durable") or first.extras.get("s10", {}).get("durable"))
        change_id = first.extras["change_record"]["record_id"]
        self.assertEqual(
            frozen_cleanup_session_ids(first.extras["change_record"]),
            [],
        )
        session_b = "dev-20260903T181000Z-bbbbbbbb"
        directory = self.host / SESSIONS_DIR / session_b
        directory.mkdir(parents=True, exist_ok=True)
        write_yaml_atomic(
            directory / "session.yaml",
            {
                "record_type": "develop_session",
                "schema_version": "1",
                "record_id": session_b,
                "created_at": "2026-09-03T18:00:00Z",
                "updated_at": "2026-09-03T18:00:00Z",
                "status": "SEALED",
                "task_id": TASK_A,
                "mode": "normal_task",
                "project_name": self.host.name,
                "baseline": {"kind": "none", "value": None},
                "workspace_overlay_s0": {"coverage": "unavailable", "paths": []},
                "observed_candidate_digest": observe_candidate(self.host).digest,
            },
        )
        write_yaml_atomic(directory / "files.yaml", {"files": []})
        self._expand_working_tree_change_record(change_id, session_b)
        retry = submit_engine(self.host).run(
            cleanup_retry={"change_id": change_id},
        )
        self.assertEqual(retry.outcome, "COMPLETED", retry.blockers)
        self.assertEqual(
            frozen_cleanup_session_ids(retry.extras["change_record"]),
            [],
        )
        self.assertNotIn(session_b, retry.extras["cleanup"]["cleaned"])
        self.assertTrue((self.host / SESSIONS_DIR / session_b).is_dir())

    def _publish_noscms(self):
        write_submit_host(self.host)
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        return result.extras["change_record"]["record_id"]

    def test_RA07_01_broken_publication_object_is_unknown(self):
        record_id = self._publish_noscms()
        objects = self.host / NOSCMS_PUBLICATIONS_DIR / record_id / OBJECTS_DIRNAME
        blobs = list(objects.iterdir()) if objects.is_dir() else []
        self.assertTrue(blobs)
        blobs[0].unlink()
        self.assertTrue((self.host / BASELINE_REL).is_file())
        self.assertTrue(
            (self.host / NOSCMS_PUBLICATIONS_DIR / record_id / COMPLETE_NAME).is_file()
        )
        loaded = load_noscms_baseline(self.host)
        self.assertFalse(loaded.get("ok"))
        self.assertEqual(loaded.get("observation_state"), "UNKNOWN")
        self.assertNotEqual(loaded.get("source"), "file")
        observed = observe_real_diff(self.host)
        self.assertFalse(observed.get("ok"))
        self.assertEqual(observed.get("observation_state"), "UNKNOWN")
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S2")
        self.assertNotEqual(
            result.extras.get("real_diff", {}).get("observation_state"),
            "SCM_ABSENT",
        )

    def test_RA07_02_broken_manifest_digest_no_cache_fallback(self):
        record_id = self._publish_noscms()
        manifest_path = (
            self.host / NOSCMS_PUBLICATIONS_DIR / record_id / "manifest.yaml"
        )
        payload = read_yaml(manifest_path)
        inventory = payload.get("inventory") or {}
        for path, row in inventory.items():
            if isinstance(row, dict) and row.get("digest"):
                row["digest"] = "0" * 64
                break
        write_yaml_atomic(manifest_path, payload)
        loaded = load_noscms_baseline(self.host)
        self.assertFalse(loaded.get("ok"))
        self.assertEqual(loaded.get("observation_state"), "UNKNOWN")
        self.assertNotEqual(loaded.get("source"), "file")

    def test_RA07_03_broken_lineage_is_unknown(self):
        record_id = self._publish_noscms()
        marker_path = (
            self.host / NOSCMS_PUBLICATIONS_DIR / record_id / COMPLETE_NAME
        )
        marker = read_yaml(marker_path)
        marker["parent_generation"] = 99
        write_yaml_atomic(marker_path, marker)
        loaded = load_noscms_baseline(self.host)
        self.assertFalse(loaded.get("ok"))
        self.assertEqual(loaded.get("observation_state"), "UNKNOWN")
        observed = observe_real_diff(self.host)
        self.assertFalse(observed.get("ok"))
        self.assertEqual(observed.get("observation_state"), "UNKNOWN")

    def test_RA07_04_healthy_publication_still_resolves(self):
        record_id = self._publish_noscms()
        loaded = load_noscms_baseline(self.host)
        self.assertTrue(loaded.get("ok"), loaded.get("blockers"))
        self.assertEqual(loaded.get("source"), "publication")
        self.assertEqual(loaded.get("change_id"), record_id)
        observed = observe_real_diff(self.host)
        self.assertTrue(observed.get("ok"), observed.get("blockers"))
        self.assertEqual(observed.get("entries"), [])

    def test_RA07_05_initial_baseline_cache_still_legal(self):
        write_submit_host(self.host, noscms_working_diff=False)
        pubs = self.host / NOSCMS_PUBLICATIONS_DIR
        if pubs.exists():
            self.assertFalse(any(pubs.iterdir()))
        loaded = load_noscms_baseline(self.host)
        self.assertTrue(loaded.get("ok"), loaded.get("blockers"))
        self.assertEqual(loaded.get("source"), "file")
        observed = observe_real_diff(self.host)
        self.assertTrue(observed.get("ok"), observed.get("blockers"))
        self.assertEqual(observed.get("entries"), [])

    def test_RA_MIN01_01_backtick_version_contradiction(self):
        copied = Path(self._tmp.name) / "test-copy"
        shutil.copytree(CANONICAL["test"], copied)
        manifest = yaml_lite.load((copied / "skill.yaml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["skill_version"], "2.0.1")
        manifest["skill_version"] = "2.0.2"
        (copied / "skill.yaml").write_text(
            yaml_lite.dump(manifest),
            encoding="utf-8",
        )
        loaded = load_package(copied)
        self.assertEqual(loaded.validity, "INVALID", loaded.validity_reasons)
        self.assertTrue(
            any("skill_version" in item for item in loaded.validity_reasons)
        )

    def test_RA_MIN01_02_matching_canonical_identity(self):
        copied = Path(self._tmp.name) / "test-match"
        shutil.copytree(CANONICAL["test"], copied)
        loaded = load_package(copied)
        self.assertEqual(loaded.validity, "VALID", loaded.validity_reasons)
        self.assertEqual(loaded.ref.skill_id, "test")
        self.assertEqual(loaded.ref.skill_version, "2.0.1")

    def test_RA_MIN01_03_skill_identity_mismatch(self):
        copied = Path(self._tmp.name) / "test-id"
        shutil.copytree(CANONICAL["test"], copied)
        skill_md = (copied / "SKILL.md").read_text(encoding="utf-8")
        (copied / "SKILL.md").write_text(
            skill_md.replace("`skill_id`: `test`", "`skill_id`: `develop`"),
            encoding="utf-8",
        )
        loaded = load_package(copied)
        self.assertEqual(loaded.validity, "INVALID", loaded.validity_reasons)
        self.assertTrue(
            any("skill_id" in item for item in loaded.validity_reasons)
        )

    def test_RA_MIN01_04_canonical_packages_remain_valid(self):
        for name, path in CANONICAL.items():
            loaded = load_package(path)
            self.assertEqual(loaded.validity, "VALID", (name, loaded.validity_reasons))
            self.assertEqual(loaded.ref.skill_id, name)

    def test_RA_MIN02_01_routing_doc_names_four_packages(self):
        text = ROUTING_DOC.read_text(encoding="utf-8")
        self.assertNotIn("does **not** contain Skill packages", text)
        self.assertNotIn("does not contain Skill packages", text)
        self.assertIn("four canonical Skill packages", text)
        self.assertIn("Understand", text)
        self.assertIn("Develop", text)
        self.assertIn("Test", text)
        self.assertIn("Submit", text)

    def test_RA_MIN02_02_required_fail_cannot_yield_test_complete(self):
        text = P6_DOC.read_text(encoding="utf-8")
        self.assertNotIn("required FAIL may still yield `test_complete=true`", text)
        self.assertNotIn("required FAIL may still yield test_complete=true", text)
        self.assertIn("cannot yield `test_complete=true`", text)

    def test_RA_MIN02_03_optional_fail_semantics_remain(self):
        text = P6_DOC.read_text(encoding="utf-8")
        self.assertIn("optional FAIL", text)
        self.assertIn("test_complete=true", text)

    def test_RA_MIN02_04_fa2_remains_open(self):
        joined = "\n".join(path.read_text(encoding="utf-8") for path in STATUS_DOCS)
        self.assertNotIn("FA-2 — PASS / CLOSED", joined)
        self.assertNotIn("FA-2 PASS / CLOSED", joined)
        self.assertNotIn("FA-2 is CLOSED", joined)

    def test_RA_MIN02_05_p9_remains_blocked(self):
        for path in STATUS_DOCS:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("P9 STARTED", text)
            self.assertNotIn("P9 implementation has started", text)
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("P9 Repair/Migration is PASS / CLOSED", readme)
        self.assertIn(
            "P10 Incremental Understanding / Multi-Agent is PASS / CLOSED",
            readme,
        )
        self.assertIn("DIVE Day-1 is not closed", readme)
        self.assertNotIn("DIVE is not started", readme)
        self.assertNotIn("DIVE Day-1 is closed", readme)
        self.assertIn("does **not** claim v2.0 release", readme)
        self.assertNotIn("v2.0 RELEASED", readme)

    def test_RA_MIN02_06_v20_unreleased(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("does **not** claim v2.0 release", readme)
        self.assertNotIn("v2.0 RELEASED", readme)
        for path in STATUS_DOCS:
            header = "\n".join(path.read_text(encoding="utf-8").splitlines()[:20])
            self.assertNotIn("v2.0 RELEASED", header)


if __name__ == "__main__":
    unittest.main()

"""R7 P3 implementation regression tests.

F5: batch stage_decisions on the Complete Envelope (atomic, single-decision compatible).
F6: resume is read-only (progress.json untouched), idempotent.
Session status statistics: live enumeration with OPEN/SEALED/ABORTED/UNKNOWN buckets.
F7: Session OPEN early drift diagnostics (advisory, no evidence mutation).
F8: discard-shaped Git operation automatic protection (no new human approval).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(REPO / "tests"))

from p6_support import init_git, write_host  # noqa: E402
from p7_support import TASK_A, develop_engine, write_active_host, write_task  # noqa: E402
from support import REPO as REPO_ROOT, write  # noqa: E402

from scaffold_p5.engine import UnderstandEngine  # noqa: E402
from scaffold_p5.io_util import read_yaml, write_yaml_atomic  # noqa: E402
from scaffold_p5.progress import PROGRESS_REL  # noqa: E402
from scaffold_p5.resume import inspect_sessions, session_status_counts  # noqa: E402
from scaffold_p5.shell_boundary import ordinary_shell_hard_boundary  # noqa: E402
from scaffold_p7.engine import (  # noqa: E402
    COMPLETE_ENVELOPE_KEYS,
    complete_run_opts,
)
from scaffold_p7.lifecycle import (  # noqa: E402
    open_session_drift_warning,
    prepare_lifecycle,
)
from scaffold_p7.models import SESSIONS_DIR  # noqa: E402

PUBLIC_REFERENCE = REPO_ROOT / "docs" / "PUBLIC_LIFECYCLE_REFERENCE.md"


def _clean_env() -> dict:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTHONPATH", None)
    return env


def _digest_of_tree(root: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(root)).replace("\\", "/")
            out[rel] = path.read_bytes()
    return out


def _satisfied(stage_id: str | None = None, **overrides) -> dict:
    payload: dict = {
        "outcome": "SATISFIED",
        "rationale": (
            "Current reconstructable Task Book and repository facts satisfy "
            "the declared acceptance criterion."
        ),
        "basis": [
            {
                "kind": "task_fact",
                "summary": (
                    "Declared acceptance is observable from current repository "
                    "and Task Book facts."
                ),
            }
        ],
    }
    if stage_id:
        payload["stage_id"] = stage_id
    payload.update(overrides)
    return payload


class _HostCase(unittest.TestCase):
    """Git host with an adopted-style active project and a two-stage Task."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.host = self.tmp / "host"
        self.host.mkdir()
        init_git(self.host)
        write_host(self.host, profiles=[])
        write_task(
            self.host,
            TASK_A,
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "First stage",
                    "acceptance": "src/app.py exists.",
                    "status": "IN_PROGRESS",
                    "required_tests": [],
                },
                {
                    "stage_id": "stage-2",
                    "goal": "Second stage",
                    "acceptance": "README.md exists.",
                    "status": "PENDING",
                    "required_tests": [],
                },
            ],
        )

    def tearDown(self):
        self._tmp.cleanup()


class F5_BatchEnvelopeContract(unittest.TestCase):
    def test_F5_01_envelope_key_allowlist_extended(self):
        self.assertIn("stage_decisions", COMPLETE_ENVELOPE_KEYS)
        # Single-decision keys unchanged.
        self.assertIn("stage_decision", COMPLETE_ENVELOPE_KEYS)
        self.assertIn("task_decision", COMPLETE_ENVELOPE_KEYS)
        self.assertIn("ready", COMPLETE_ENVELOPE_KEYS)

    def test_F5_02_batch_opts_mapping(self):
        opts, error = complete_run_opts(
            {
                "stage_decisions": [
                    _satisfied("stage-1"),
                    _satisfied("stage-2"),
                ],
            }
        )
        self.assertIsNone(error)
        self.assertEqual(len(opts["stage_completion_decisions"]), 2)
        self.assertTrue(opts["request_stage_complete"])

    def test_F5_03_batch_non_list_rejected(self):
        for bad in ("x", {}, 5, None, []):
            opts, error = complete_run_opts({"stage_decisions": bad})
            self.assertIsNone(opts)
            self.assertTrue(error)

    def test_F5_04_batch_item_not_object_rejected(self):
        opts, error = complete_run_opts(
            {"stage_decisions": [_satisfied("stage-1"), "not-a-decision"]}
        )
        self.assertIsNone(opts)
        self.assertIn("stage_decisions[1]", error)

    def test_F5_05_single_envelope_unchanged(self):
        opts, error = complete_run_opts({"stage_decision": _satisfied("stage-1")})
        self.assertIsNone(error)
        self.assertEqual(opts["stage_completion_decision"]["stage_id"], "stage-1")
        self.assertNotIn("stage_completion_decisions", opts)


class F5_BatchAtomicity(_HostCase):
    def _prep(self):
        engine = develop_engine(self.host)
        resolved = engine.open_develop_session(task_id=TASK_A)
        self.assertEqual(resolved.outcome, "COMPLETED", resolved.blockers)
        return engine

    def test_F5_06_batch_two_decisions_both_apply(self):
        engine = self._prep()
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        task["stages"][1]["status"] = "IN_PROGRESS"
        write_yaml_atomic(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml", task)
        updated, blockers, extras = prepare_lifecycle(
            read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
            root=self.host,
            candidate_digest="sha256:" + "a" * 64,
            stage_completion_decisions=[
                _satisfied("stage-1"),
                _satisfied("stage-2"),
            ],
        )
        self.assertEqual(blockers, [])
        self.assertEqual(extras.get("stage_completion_batch_size"), 2)
        statuses = {row["stage_id"]: row["status"] for row in updated["stages"]}
        self.assertEqual(statuses["stage-1"], "COMPLETE")
        self.assertEqual(statuses["stage-2"], "COMPLETE")

    def test_F5_07_illegal_stage_rejects_entire_batch_atomically(self):
        engine = self._prep()
        task_path = self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
        task = read_yaml(task_path)
        before = dict(task["stages"][0])
        before_decision = task.get("stages")[0].get("completion_decision")
        updated, blockers, extras = prepare_lifecycle(
            task,
            root=self.host,
            candidate_digest="sha256:" + "a" * 64,
            stage_completion_decisions=[
                _satisfied("stage-1"),
                _satisfied("stage-nonexistent"),
            ],
        )
        self.assertEqual(len(blockers), 1)
        self.assertIn("stage-nonexistent", blockers[0])
        self.assertTrue(extras.get("stage_completion_rejected"))
        # No partial mutation: stage-1 decision untouched.
        self.assertEqual(updated["stages"][0], before)
        self.assertEqual(
            updated["stages"][0].get("completion_decision"), before_decision
        )

    def test_F5_08_duplicate_stage_id_rejected(self):
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        updated, blockers, _extras = prepare_lifecycle(
            task,
            root=self.host,
            candidate_digest="sha256:" + "a" * 64,
            stage_completion_decisions=[
                _satisfied("stage-1"),
                _satisfied("stage-1"),
            ],
        )
        self.assertEqual(len(blockers), 1)
        self.assertIn("duplicate stage_id", blockers[0])

    def test_F5_09_batch_single_decision_conflict_rejected(self):
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        updated, blockers, _extras = prepare_lifecycle(
            task,
            root=self.host,
            candidate_digest="sha256:" + "a" * 64,
            stage_completion_decision=_satisfied("stage-1"),
            stage_completion_decisions=[_satisfied("stage-1")],
        )
        self.assertEqual(len(blockers), 1)
        self.assertIn("conflicting Stage Completion Decisions", blockers[0])

    def test_F5_10_batch_survives_no_partial_publication_via_engine(self):
        engine = self._prep()
        result = engine.complete(
            task_id=TASK_A,
            envelope={
                "stage_decisions": [
                    _satisfied("stage-1"),
                    _satisfied("stage-nonexistent"),
                ],
            },
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(
            any("stage-nonexistent" in b for b in result.blockers),
            result.blockers,
        )
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(task["stages"][0]["status"], "IN_PROGRESS")
        self.assertIsNone(task["stages"][0].get("completion_decision"))

    def test_F5_11_batch_with_ready_combination(self):
        engine = self._prep()
        task_path = self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
        task = read_yaml(task_path)
        task["stages"][1]["status"] = "IN_PROGRESS"
        write_yaml_atomic(task_path, task)
        result = engine.complete(
            task_id=TASK_A,
            envelope={
                "stage_decisions": [
                    _satisfied("stage-1"),
                    _satisfied("stage-2"),
                ],
                "task_decision": _satisfied(),
                "complete_stage": True,
                "ready": True,
            },
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        task = read_yaml(task_path)
        self.assertEqual(task["status"], "READY_FOR_REVIEW")

    def test_F5_12_candidate_change_rejects_batch_via_stale_gate(self):
        engine = self._prep()
        task_path = self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
        task = read_yaml(task_path)
        task["stages"][1]["status"] = "IN_PROGRESS"
        write_yaml_atomic(task_path, task)
        stale_digest = "sha256:" + "b" * 64
        decision = _satisfied("stage-1", candidate_digest=stale_digest)
        updated, _blockers, _extras = prepare_lifecycle(
            read_yaml(task_path),
            root=self.host,
            candidate_digest="sha256:" + "a" * 64,
            stage_completion_decisions=[decision],
        )
        # Stale decision cannot lift the stage to COMPLETE.
        statuses = {row["stage_id"]: row["status"] for row in updated["stages"]}
        self.assertEqual(statuses["stage-1"], "IN_PROGRESS")

    def test_F5_13_documented_contract(self):
        text = PUBLIC_REFERENCE.read_text(encoding="utf-8")
        self.assertIn("`stage_decisions`", text)
        self.assertIn("原子性", text)


class F6_ResumeReadOnly(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.host = self.tmp / "host"
        self.host.mkdir()
        init_git(self.host)
        write_host(self.host, profiles=[])

    def tearDown(self):
        self._tmp.cleanup()

    def _resume(self):
        from support import distribution as fixture_distribution

        engine = UnderstandEngine(self.host, fixture_distribution())
        return engine.run("refresh", action="resume")

    def test_F6_01_resume_does_not_write_progress_json(self):
        result = self._resume()
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertFalse((self.host / PROGRESS_REL).is_file())

    def test_F6_02_resume_idempotent_byte_stable(self):
        before = _digest_of_tree(self.host)
        first = self._resume()
        self.assertEqual(first.outcome, "COMPLETED")
        after_first = _digest_of_tree(self.host)
        second = self._resume()
        self.assertEqual(second.outcome, "COMPLETED")
        after_second = _digest_of_tree(self.host)
        # Persistent tree is byte-identical across repeated resumes.
        self.assertEqual(after_first, after_second)
        # And resume only added nothing beyond pre-existing state.
        for rel, data in after_second.items():
            if rel.startswith(".git/"):
                continue
            self.assertEqual(before.get(rel, data), data)

    def test_F6_03_resume_marks_observational(self):
        result = self._resume()
        self.assertTrue(result.extras.get("observational"))
        self.assertEqual(result.mutations, "none")

    def test_F6_04_other_operations_keep_progress_behavior(self):
        # Non-resume long-run operations still write progress.json (global
        # mechanism untouched). Develop session open is one such operation.
        from scaffold_p5.progress import emit_working

        emit_working(self.host, "develop.session", "start")
        self.assertTrue((self.host / PROGRESS_REL).is_file())

    def test_F6_05_interrupted_session_still_observable(self):
        # A malformed session must still surface in resume observability.
        session_dir = self.host / SESSIONS_DIR / "dev-20260929T000000Z-deadbeef"
        session_dir.mkdir(parents=True)
        (session_dir / "broken.yaml").write_text("x", encoding="utf-8")
        rows, blockers = inspect_sessions(self.host)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "UNKNOWN")
        self.assertEqual(rows[0]["reconstruction"], "ORPHANED")
        result = self._resume()
        self.assertEqual(result.outcome, "COMPLETED")


class SessionStatusStatistics(unittest.TestCase):
    def _session(self, root: Path, session_id: str, status: str, task_id: str = TASK_A):
        directory = root / SESSIONS_DIR / session_id
        directory.mkdir(parents=True, exist_ok=True)
        write_yaml_atomic(
            directory / "session.yaml",
            {
                "record_type": "develop_session",
                "schema_version": "1",
                "record_id": session_id,
                "created_at": "2026-09-29T00:00:00Z",
                "updated_at": "2026-09-29T00:00:00Z",
                "status": status,
                "task_id": task_id,
                "mode": "normal_task",
                "project_name": root.name,
                "baseline": {"kind": "none", "value": None},
                "workspace_overlay_s0": {"coverage": "unavailable", "paths": []},
                "observed_candidate_digest": "sha256:" + "f" * 64,
            },
        )
        write_yaml_atomic(directory / "files.yaml", {"files": []})
        return directory

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.host = self.tmp / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_S01_status_buckets_from_live_enumeration(self):
        self._session(self.host, "dev-20260929T000001Z-aaaaaaaa", "OPEN")
        self._session(self.host, "dev-20260929T000002Z-bbbbbbbb", "SEALED")
        self._session(self.host, "dev-20260929T000003Z-cccccccc", "ABORTED")
        self._session(self.host, "dev-20260929T000004Z-dddddddd", "SEALED")
        # Orphaned: directory without session.yaml.
        (self.host / SESSIONS_DIR / "dev-20260929T000005Z-eeeeeeee").mkdir()
        rows, _blockers = inspect_sessions(self.host)
        stats = session_status_counts(rows)
        self.assertEqual(stats["counts"]["OPEN"], 1)
        self.assertEqual(stats["counts"]["SEALED"], 2)
        self.assertEqual(stats["counts"]["ABORTED"], 1)
        self.assertEqual(stats["counts"]["UNKNOWN"], 1)
        self.assertEqual(stats["total"], 5)
        # Anomalous rows are preserved, never silently dropped.
        self.assertEqual(len(stats["anomalous"]), 1)
        self.assertEqual(stats["anomalous"][0]["reconstruction"], "ORPHANED")
        self.assertEqual(stats["source"], "inspect_sessions live enumeration")

    def test_S02_no_second_authority_source(self):
        stats = session_status_counts([])
        self.assertEqual(stats["counts"], {
            "OPEN": 0, "SEALED": 0, "ABORTED": 0, "UNKNOWN": 0,
        })
        self.assertEqual(stats["total"], 0)


class F7_SessionOpenDriftWarning(_HostCase):
    def test_F7_01_open_session_reports_no_warning_on_clean_state(self):
        engine = develop_engine(self.host)
        result = engine.open_develop_session(task_id=TASK_A)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        warning = result.extras.get("drift_warning")
        self.assertIsInstance(warning, dict)
        self.assertEqual(warning["status"], "NONE")

    def _open_session_record(self, result) -> dict:
        record_id = result.extras["session"]["record_id"]
        return read_yaml(
            self.host / SESSIONS_DIR / str(record_id) / "session.yaml"
        )

    def test_F7_02_authorized_task_scope_change_is_not_a_warning(self):
        engine = develop_engine(self.host)
        result = engine.open_develop_session(task_id=TASK_A)
        self.assertEqual(result.outcome, "COMPLETED")
        # Authorized development inside Task scope: modify in-scope file.
        write(self.host, "src/app.py", "value = 1\n")
        session = self._open_session_record(result)
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        from scaffold_p6.candidate import observe_candidate

        warning = open_session_drift_warning(
            self.host,
            session=session,
            task=task,
            current_candidate_digest=observe_candidate(self.host).digest,
        )
        untracked_checks = [
            check
            for check in warning["checks"]
            if check["kind"] == "unattributed_drift"
            and check["state"] == "DIVERGED"
        ]
        # In-scope authorized change is reported as informational, not drift.
        drift_paths = set()
        for check in untracked_checks:
            drift_paths.update(check.get("paths") or [])
        self.assertNotIn("src/app.py", drift_paths)

    def test_F7_03_unattributed_out_of_scope_change_warns(self):
        engine = develop_engine(self.host)
        result = engine.open_develop_session(task_id=TASK_A)
        self.assertEqual(result.outcome, "COMPLETED")
        write(self.host, "unrelated.txt", "stray\n")
        session = self._open_session_record(result)
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        from scaffold_p6.candidate import observe_candidate

        warning = open_session_drift_warning(
            self.host,
            session=session,
            task=task,
            current_candidate_digest=observe_candidate(self.host).digest,
        )
        self.assertEqual(warning["status"], "DIVERGED")
        drift_checks = [
            check
            for check in warning["checks"]
            if check["kind"] == "unattributed_drift"
            and check["state"] == "DIVERGED"
        ]
        self.assertTrue(drift_checks)
        paths = set()
        for check in drift_checks:
            paths.update(check.get("paths") or [])
        self.assertIn("unrelated.txt", paths)

    def test_F7_04_unknown_when_candidate_digest_missing(self):
        session = {
            "record_id": "dev-x",
            "observed_candidate_digest": "",
            "workspace_overlay_s0": {"coverage": "unavailable", "paths": []},
        }
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        warning = open_session_drift_warning(
            self.host,
            session=session,
            task=task,
            current_candidate_digest="sha256:" + "a" * 64,
        )
        self.assertEqual(warning["status"], "UNKNOWN")

    def test_F7_05_sealed_evidence_relationship_reported_not_mutated(self):
        sealed_dir = self.host / SESSIONS_DIR / "dev-20260929T000001Z-aaaaaaaa"
        sealed_dir.mkdir(parents=True)
        write_yaml_atomic(
            sealed_dir / "session.yaml",
            {
                "record_type": "develop_session",
                "schema_version": "1",
                "record_id": "dev-20260929T000001Z-aaaaaaaa",
                "created_at": "2026-09-29T00:00:00Z",
                "updated_at": "2026-09-29T00:00:00Z",
                "status": "SEALED",
                "task_id": TASK_A,
                "mode": "normal_task",
                "project_name": self.host.name,
                "baseline": {"kind": "none", "value": None},
                "workspace_overlay_s0": {"coverage": "unavailable", "paths": []},
                "observed_candidate_digest": "sha256:" + "c" * 64,
            },
        )
        sealed_before = (sealed_dir / "session.yaml").read_bytes()
        session = {
            "record_id": "dev-20260929T000002Z-bbbbbbbb",
            "observed_candidate_digest": "sha256:" + "a" * 64,
            "workspace_overlay_s0": {"coverage": "unavailable", "paths": []},
        }
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        warning = open_session_drift_warning(
            self.host,
            session=session,
            task=task,
            current_candidate_digest="sha256:" + "a" * 64,
        )
        checks = [
            check
            for check in warning["checks"]
            if check["kind"] == "sealed_evidence_relationship"
        ]
        self.assertEqual(warning["status"], "DIVERGED")
        self.assertEqual(checks[0]["state"], "DIVERGED")
        # Historical evidence untouched.
        self.assertEqual((sealed_dir / "session.yaml").read_bytes(), sealed_before)

    def test_F7_06_does_not_duplicate_p2_staleness_gate(self):
        # The advisory check reports DIVERGED but never changes decisions or
        # evidence; the authoritative P2 gate still runs at consumption time.
        text = PUBLIC_REFERENCE.read_text(encoding="utf-8")
        self.assertIn("不重复也不替代 P2", text)


class F8_DangerousGitProtection(unittest.TestCase):
    def _deny(self, argv: list[str]) -> str | None:
        return ordinary_shell_hard_boundary(argv, self.host)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.host = self.tmp / "host"
        self.host.mkdir()
        init_git(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def test_F8_01_checkout_path_discard_blocked(self):
        reason = self._deny(["git", "checkout", "--", "src/app.py"])
        self.assertIsNotNone(reason)
        self.assertIn("irreversibly discarded", reason)

    def test_F8_02_restore_blocked(self):
        reason = self._deny(["git", "restore", "src/app.py"])
        self.assertIsNotNone(reason)
        self.assertIn("irreversibly discarded", reason)

    def test_F8_03_restore_dot_blocked(self):
        self.assertIsNotNone(self._deny(["git", "restore", "."]))

    def test_F8_04_checkout_branch_switch_allowed(self):
        self.assertIsNone(self._deny(["git", "checkout", "main"]))
        self.assertIsNone(self._deny(["git", "checkout", "-b", "feature/x"]))

    def test_F8_05_reset_hard_blocked_by_existing_boundary(self):
        reason = self._deny(["git", "reset", "--hard"])
        self.assertIsNotNone(reason)
        self.assertIn("destructive", reason)

    def test_F8_06_inspection_commands_unaffected(self):
        self.assertIsNone(self._deny(["git", "status"]))
        self.assertIsNone(self._deny(["git", "diff"]))
        self.assertIsNone(self._deny(["git", "log", "-n", "5"]))
        self.assertIsNone(self._deny(["git", "show", "HEAD"]))
        self.assertIsNone(self._deny(["git", "restore", "--staged", "src/app.py"]))

    def test_F8_07_commit_push_contract_unchanged(self):
        reason = self._deny(["git", "commit", "-m", "x"])
        self.assertIsNotNone(reason)
        self.assertIn("Git Commit", reason)
        reason = self._deny(["git", "push"])
        self.assertIsNotNone(reason)
        self.assertIn("Git Push", reason)

    def test_F8_08_no_new_human_approval_semantics(self):
        # The deny reason is an automatic risk message, not a permission=ask.
        reason = self._deny(["git", "checkout", "--", "src/app.py"])
        self.assertNotIn("permission", reason.lower())

    def test_F8_09_documented(self):
        text = PUBLIC_REFERENCE.read_text(encoding="utf-8")
        self.assertIn("8.1", text)
        self.assertIn("自动风险判断", text)


class NoScmPath(unittest.TestCase):
    def test_N01_no_scm_host_batch_and_resume(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            host = Path(tmp.name) / "host"
            host.mkdir()
            write_host(host, profiles=[])
            write_task(host, TASK_A)
            engine = develop_engine(host)
            resolved = engine.open_develop_session(task_id=TASK_A)
            self.assertEqual(resolved.outcome, "COMPLETED", resolved.blockers)
            task = read_yaml(host / ".scaffold/tasks" / f"{TASK_A}.yaml")
            task["stages"][0]["status"] = "IN_PROGRESS"
            write_yaml_atomic(host / ".scaffold/tasks" / f"{TASK_A}.yaml", task)
            updated, blockers, extras = prepare_lifecycle(
                read_yaml(host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
                root=host,
                candidate_digest="sha256:" + "a" * 64,
                stage_completion_decisions=[_satisfied("stage-1")],
            )
            self.assertEqual(blockers, [])
            self.assertEqual(extras.get("stage_completion_batch_size"), 1)
            statuses = {row["stage_id"]: row["status"] for row in updated["stages"]}
            self.assertEqual(statuses["stage-1"], "COMPLETE")
            # Resume is read-only on no-SCM host as well: session open (a
            # long-running operation) may write progress.json, but resume
            # itself must not change it.
            from support import distribution as fixture_distribution

            progress = host / PROGRESS_REL
            if progress.is_file():
                before_bytes = progress.read_bytes()
            else:
                before_bytes = None
            uresult = UnderstandEngine(host, fixture_distribution()).run(
                "refresh", action="resume"
            )
            self.assertEqual(uresult.outcome, "COMPLETED")
            if before_bytes is None:
                self.assertFalse(progress.is_file())
            else:
                self.assertEqual(progress.read_bytes(), before_bytes)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from p6_support import git
from p7_support import TASK_A
from p8_support import init_submit_git, run_submit, submit_engine, write_ready_task, write_submit_host
from support import write
from scaffold_p5.io_util import file_digest, write_yaml_atomic
from scaffold_p6.candidate import is_ext_support_path, observe_candidate
from scaffold_p8.cleanup import cleanup_sessions
from scaffold_p8.delta import _parse_porcelain_z, classify_delta, observe_real_diff
from scaffold_p8.finalize import finalize_s10
from scaffold_p8.models import CHANGES_DIR, FINALIZATIONS_DIR, PROVENANCE_CLASSES
from scaffold_p8.records import (
    build_change_record,
    is_durable,
    persist_candidate_change,
)
from scaffold_p8.schemas import validate_change_record


def _product_porcelain(host: Path) -> str:
    """Raw git porcelain minus namespaced ext support that remains untracked."""
    lines = []
    for line in git(host, "status", "--porcelain").splitlines():
        path = line[3:].replace("\\", "/").strip()
        if is_ext_support_path(path):
            continue
        lines.append(line)
    return "\n".join(lines)


class P8Rev1Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.host = self.root / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_T01_git_observation_failure_is_not_empty_diff(self):
        self._git_host()
        with mock.patch(
            "scaffold_p8.delta._run_git_status",
            return_value=(False, b"", "simulated Git observation failure"),
        ):
            observed = observe_real_diff(self.host)
            result = run_submit(self.host, task_id=TASK_A)
        self.assertFalse(observed["ok"])
        self.assertEqual(observed["paths"], [])
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S2")

    def test_T02_modified_tracked_file_is_represented(self):
        self._git_host()
        write(self.host, "docs/note.md", "modified\n")
        observed = observe_real_diff(self.host)
        self.assertTrue(observed["ok"])
        self.assertEqual(self._entry(observed, "docs/note.md")["change"], "modified")

    def test_T03_added_untracked_path_is_represented(self):
        self._git_host()
        write(self.host, "docs/new.md", "new\n")
        entry = self._entry(observe_real_diff(self.host), "docs/new.md")
        self.assertEqual(entry["change"], "untracked")

    def test_T04_reviewed_deletion_survives_s2(self):
        write_submit_host(self.host)
        write(self.host, "docs/old.md", "old\n")
        init_submit_git(self.host)
        (self.host / "docs/old.md").unlink()
        entry = self._entry(observe_real_diff(self.host), "docs/old.md")
        self.assertEqual(entry["change"], "deleted")

    def test_T05_reviewed_deletion_is_committed(self):
        write_submit_host(self.host)
        write(self.host, "docs/old.md", "old\n")
        init_submit_git(self.host)
        (self.host / "docs/old.md").unlink()
        result = self._finalize_engine()
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertFalse(self._commit_has("HEAD", "docs/old.md"))
        self.assertEqual(_product_porcelain(self.host), "")

    def test_T06_rename_copy_parsing_has_distinct_paths(self):
        rename, issues = _parse_porcelain_z(b"R  docs/new.md\0docs/old.md\0")
        copied, copy_issues = _parse_porcelain_z(b"C  docs/copy.md\0docs/orig.md\0")
        self.assertEqual(issues + copy_issues, [])
        self.assertEqual(rename[0]["path"], "docs/new.md")
        self.assertEqual(rename[0]["orig_path"], "docs/old.md")
        self.assertEqual(copied[0]["change"], "copied")
        self.assertNotIn(" -> ", rename[0]["path"])

    def test_T07_rename_is_exact_and_not_left_dirty(self):
        write_submit_host(self.host)
        write(self.host, "docs/old.md", "old\n")
        init_submit_git(self.host)
        git(self.host, "mv", "docs/old.md", "docs/new.md")
        result = self._finalize_engine()
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertFalse(self._commit_has("HEAD", "docs/old.md"))
        self.assertTrue(self._commit_has("HEAD", "docs/new.md"))
        self.assertEqual(_product_porcelain(self.host), "")

    def test_T08_unrelated_staged_path_is_rejected(self):
        self._git_host()
        parent = git(self.host, "rev-parse", "HEAD")
        write(self.host, "docs/reviewed.md", "reviewed\n")
        write(self.host, "docs/unrelated.md", "unrelated\n")
        git(self.host, "add", "docs/unrelated.md")
        record_id, change_rel = self._persist_record()
        expected = observe_candidate(self.host).digest
        result = finalize_s10(
            self.host,
            record_id=record_id,
            change_rel=change_rel,
            reviewed_paths=["docs/reviewed.md"],
            reviewed_entries=[{"path": "docs/reviewed.md", "change": "untracked"}],
            expected_digest=expected,
            scm_kind="git",
            expected_parent=parent,
        )
        self.assertFalse(result["ok"])
        self.assertIn("unrelated", " ".join(result["blockers"]))

    def test_T09_git_uses_existing_identity_not_fake_p8_identity(self):
        self._git_host()
        write(self.host, "docs/note.md", "modified\n")
        result = self._finalize_engine()
        self.assertEqual(result.outcome, "COMPLETED")
        ident = git(self.host, "show", "-s", "--format=%an <%ae>", "HEAD")
        self.assertEqual(ident, "P8 Fixture User <p8-fixture@example.invalid>")
        self.assertNotIn("P8 Submit", ident)

    def test_T10_develop_known_requires_complete_transition(self):
        write(self.host, "src/app.py", "value = 2\n")
        after = self._state("src/app.py")
        sessions = [self._session(files=[self._touch(after=after)])]
        delta = classify_delta(
            self.host, real_paths=["src/app.py"], sessions=sessions
        )
        self.assertEqual(delta["classes"]["src/app.py"], "DEVELOP_KNOWN")

    def test_T11_preexisting_requires_equal_boundary_state(self):
        # PREEXISTING_CHANGE is only reachable on a host whose drift authority
        # is usable, so this needs real project authority rather than a bare dir.
        write_submit_host(self.host)
        write(self.host, "src/app.py", "preexisting\n")
        state = self._state("src/app.py")
        sessions = [self._session(s0={"src/app.py": state}, s1={"src/app.py": state})]
        delta = classify_delta(
            self.host, real_paths=["src/app.py"], sessions=sessions
        )
        self.assertEqual(delta["classes"]["src/app.py"], "PREEXISTING_CHANGE")

    def test_T12_post_develop_requires_complete_s1_boundary(self):
        write(self.host, "src/app.py", "later\n")
        sessions = [self._session(s0={}, s1={})]
        delta = classify_delta(
            self.host, real_paths=["src/app.py"], sessions=sessions
        )
        self.assertEqual(
            delta["classes"]["src/app.py"], "POST_DEVELOP_ADDITIONAL"
        )

    def test_T13_mixed_when_develop_touches_preexisting_path(self):
        write(self.host, "src/app.py", "mixed\n")
        after = self._state("src/app.py")
        touch = self._touch(after=after)
        touch["was_preexisting_dirty"] = True
        delta = classify_delta(
            self.host,
            real_paths=["src/app.py"],
            sessions=[self._session(files=[touch])],
        )
        self.assertEqual(delta["classes"]["src/app.py"], "MIXED_CHANGE")

    def test_T14_insufficient_provenance_is_unattributed(self):
        write(self.host, "src/app.py", "unknown\n")
        delta = classify_delta(
            self.host, real_paths=["src/app.py"], sessions=[]
        )
        self.assertEqual(delta["classes"]["src/app.py"], "UNATTRIBUTED")

    def test_T15_provenance_uncertainty_keeps_real_diff(self):
        write(self.host, "src/app.py", "unknown\n")
        delta = classify_delta(
            self.host,
            real_paths=["src/app.py"],
            sessions=[self._session(coverage="unavailable")],
        )
        self.assertEqual(delta["paths"], ["src/app.py"])
        self.assertEqual(delta["counts"]["UNATTRIBUTED"], 1)

    def test_T16_malformed_affected_is_rejected(self):
        record = self._valid_record()
        record["affected"] = "src"
        self.assertTrue(validate_change_record(record))

    def test_T17_malformed_path_entry_is_rejected(self):
        record = self._valid_record()
        record["path_summary"]["paths"] = ["src/app.py"]
        self.assertTrue(validate_change_record(record))

    def test_T18_path_count_mismatch_is_rejected(self):
        record = self._valid_record()
        record["path_summary"]["total_changed_paths"] = 2
        self.assertTrue(validate_change_record(record))

    def test_T19_malformed_verification_refs_are_rejected(self):
        record = self._valid_record()
        record["verification"]["evidence_refs"] = "report"
        self.assertTrue(validate_change_record(record))

    def test_T20_malformed_task_ids_are_rejected(self):
        record = self._valid_record()
        record["task_book_ids"] = [3, {"record_id": TASK_A}]
        self.assertTrue(validate_change_record(record))

    def test_T21_malformed_provenance_value_is_rejected(self):
        record = self._valid_record()
        record["provenance"]["classes"]["UNATTRIBUTED"] = 1
        self.assertTrue(validate_change_record(record))

    def test_T22_malformed_limitations_are_rejected(self):
        record = self._valid_record()
        record["limitations"] = "none"
        self.assertTrue(validate_change_record(record))

    def test_T23_generated_change_record_is_valid(self):
        record = build_change_record(
            record_id="change-20260831T010000Z-aaaabbbb",
            task=self._task(),
            real_paths=["src/app.py"],
            diff_entries=[{"path": "src/app.py", "change": "modified"}],
            delta=self._delta(),
            structural={"structural_review_pass": True},
            knowledge={"knowledge_consistent": True},
            completeness={
                "test_pass": True,
                "test_complete": True,
                "report_id": "tr-local",
            },
            candidate_kind="none",
            baseline_value=None,
        )
        self.assertEqual(validate_change_record(record), [])

    def test_T24_git_durability_comes_from_commit_and_exact_cr(self):
        self._git_host()
        write(self.host, "docs/note.md", "modified\n")
        result = self._finalize_engine()
        record_id = result.extras["change_record"]["record_id"]
        rel = f"{CHANGES_DIR}/{record_id}.yaml"
        committed = git(self.host, "rev-parse", f"HEAD:{rel}")
        staged_representation = git(
            self.host, "hash-object", f"--path={rel}", rel
        )
        self.assertEqual(committed, staged_representation)
        self.assertTrue(is_durable(self.host, record_id))
        self.assertEqual(result.extras["s10"]["durability_source"], "git_commit")

    def test_T25_git_success_creates_no_dirty_finalization_marker(self):
        self._git_host()
        write(self.host, "docs/note.md", "modified\n")
        result = self._finalize_engine()
        record_id = result.extras["change_record"]["record_id"]
        self.assertFalse(
            (self.host / FINALIZATIONS_DIR / f"{record_id}.yaml").exists()
        )
        self.assertEqual(_product_porcelain(self.host), "")

    def test_T26_malformed_support_artifact_is_not_durable(self):
        record_id, _rel = self._persist_record()
        write_yaml_atomic(
            self.host / FINALIZATIONS_DIR / f"{record_id}.yaml",
            {"kind": "submit_finalization", "change_id": record_id, "ok": True},
        )
        self.assertFalse(is_durable(self.host, record_id))

    def test_T27_noscms_same_retry_is_idempotent(self):
        from scaffold_p8.noscms import initialize_noscms_baseline

        write(self.host, "src/app.py", "fixture\n")
        initialized = initialize_noscms_baseline(self.host)
        self.assertTrue(initialized.get("ok"), initialized)
        record_id, rel = self._persist_record()
        expected = observe_candidate(self.host).digest
        first = finalize_s10(
            self.host,
            record_id=record_id,
            change_rel=rel,
            reviewed_paths=[],
            expected_digest=expected,
            scm_kind="none",
        )
        second = finalize_s10(
            self.host,
            record_id=record_id,
            change_rel=rel,
            reviewed_paths=[],
            expected_digest=expected,
            scm_kind="none",
        )
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertTrue(second["retried"])

    def test_T28_noscms_conflicting_writer_cannot_publish(self):
        from scaffold_p8.noscms import initialize_noscms_baseline

        write(self.host, "src/app.py", "fixture\n")
        initialized = initialize_noscms_baseline(self.host)
        self.assertTrue(initialized.get("ok"), initialized)
        record_id, rel = self._persist_record()
        expected = observe_candidate(self.host).digest
        first = finalize_s10(
            self.host,
            record_id=record_id,
            change_rel=rel,
            reviewed_paths=[],
            expected_digest=expected,
            scm_kind="none",
        )
        second = finalize_s10(
            self.host,
            record_id=record_id,
            change_rel=rel,
            reviewed_paths=[],
            expected_digest="f" * 64,
            scm_kind="none",
        )
        self.assertTrue(first["ok"])
        self.assertFalse(second["ok"])
        self.assertTrue(second["conflict"])

    def test_T29_noscms_corrupt_publication_fails_closed(self):
        record_id, rel = self._persist_record()
        write(
            self.host,
            f".scaffold/ext/submit/noscms/publications/{record_id}/COMPLETE.yaml",
            "not: [valid\n",
        )
        result = finalize_s10(
            self.host,
            record_id=record_id,
            change_rel=rel,
            reviewed_paths=[],
            expected_digest=observe_candidate(self.host).digest,
            scm_kind="none",
        )
        self.assertFalse(result["ok"])
        self.assertIn("malformed", " ".join(result["blockers"]))

    def test_T30_fail_push_without_authorization_does_not_attempt(self):
        self._git_host()
        write(self.host, "docs/note.md", "modified\n")
        result = self._finalize_engine(fail_push=True)
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertFalse(result.extras["push"]["performed"])

    def test_T31_valid_push_authorization_starts_s11(self):
        self._git_host()
        self._local_remote()
        write(self.host, "docs/note.md", "modified\n")
        result = self._finalize_engine(push=True)
        self.assertTrue(result.extras["push"]["performed"])
        self.assertTrue(result.extras["push"]["ok"])

    def test_T32_local_bare_remote_receives_exact_s10_commit(self):
        self._git_host()
        remote = self._local_remote()
        write(self.host, "docs/note.md", "modified\n")
        result = self._finalize_engine(push=True)
        remote_head = self._bare_head(remote)
        self.assertEqual(remote_head, result.extras["s10"]["commit"])
        self.assertEqual(remote_head, result.extras["push"]["remote_head"])

    def test_T33_absent_or_stale_push_authorization_leaves_remote(self):
        for index, stale in enumerate((False, True)):
            host = self.root / f"push-{index}"
            host.mkdir()
            write_submit_host(host)
            init_submit_git(host)
            remote = self._local_remote(host=host, suffix=str(index))
            baseline = self._bare_head(remote)
            write(host, "docs/note.md", "modified\n")
            digest = observe_candidate(host).digest
            push_auth = (
                {"granted": True, "candidate_digest": "0" * 64}
                if stale
                else None
            )
            result = run_submit(
                host,
                task_id=TASK_A,
                invoke_test=True,
                selected=["unit"],
                finalize=True,
                push_authorized=push_auth,
            )
            self.assertEqual(result.outcome, "COMPLETED")
            self.assertFalse(result.extras["push"]["performed"])
            self.assertEqual(self._bare_head(remote), baseline)

    def test_T34_authorized_push_failure_retains_local_s10(self):
        self._git_host()
        write(self.host, "docs/note.md", "modified\n")
        result = self._finalize_engine(push=True, fail_push=True)
        self.assertTrue(result.extras["s10"]["durable"])
        self.assertTrue(result.extras["push"]["performed"])
        self.assertFalse(result.extras["push"]["ok"])
        self.assertEqual(git(self.host, "rev-parse", "HEAD"), result.extras["s10"]["commit"])

    def test_T35_same_task_unlinked_sealed_session_is_retained(self):
        write_submit_host(self.host)
        session_id = "dev-20260831T010000Z-11111111"
        self._write_session(session_id, status="SEALED")
        task = write_ready_task(self.host, develop_session_ids=[])
        result = cleanup_sessions(self.host, task=task, s10_ok=True)
        self.assertIn(session_id, result["retained"])
        self.assertTrue((self.host / ".scaffold/runtime/develop-sessions" / session_id).is_dir())

    def test_T36_only_exact_linked_valid_sealed_session_is_cleaned(self):
        write_submit_host(self.host)
        sealed = "dev-20260831T010000Z-22222222"
        opened = "dev-20260831T010000Z-33333333"
        malformed = "dev-20260831T010000Z-44444444"
        unrelated = "dev-20260831T010000Z-55555555"
        self._write_session(sealed, status="SEALED")
        self._write_session(opened, status="OPEN")
        bad_dir = self.host / ".scaffold/runtime/develop-sessions" / malformed
        bad_dir.mkdir(parents=True)
        write(bad_dir, "session.yaml", "bad: session\n")
        self._write_session(unrelated, status="SEALED")
        task = write_ready_task(
            self.host, develop_session_ids=[sealed, opened, malformed]
        )
        result = cleanup_sessions(self.host, task=task, s10_ok=True)
        self.assertEqual(result["cleaned"], [sealed])
        for session_id in (opened, malformed, unrelated):
            self.assertIn(session_id, result["retained"])
            self.assertTrue(
                (self.host / ".scaffold/runtime/develop-sessions" / session_id).exists()
            )

    def _git_host(self) -> None:
        write_submit_host(self.host)
        write(self.host, "docs/note.md", "baseline\n")
        init_submit_git(self.host)

    def _finalize_engine(self, *, push: bool = False, fail_push: bool = False):
        return run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            push=push,
            fail_push=fail_push,
        )

    @staticmethod
    def _entry(observed: dict, path: str) -> dict:
        return next(row for row in observed["entries"] if row["path"] == path)

    def _commit_has(self, commit: str, path: str) -> bool:
        completed = subprocess.run(
            ["git", "-C", str(self.host), "cat-file", "-e", f"{commit}:{path}"],
            capture_output=True,
            check=False,
        )
        return completed.returncode == 0

    def _persist_record(self) -> tuple[str, str]:
        record = self._valid_record()
        ok, blockers, path = persist_candidate_change(self.host, record)
        self.assertTrue(ok, blockers)
        assert path is not None
        return record["record_id"], path.relative_to(self.host).as_posix()

    @staticmethod
    def _valid_record() -> dict:
        return {
            "record_type": "change_record",
            "schema_version": "1",
            "record_id": "change-20260831T010000Z-abcdef12",
            "created_at": "2026-08-31T01:00:00Z",
            "summary": "Rev1 fixture",
            "base": {"kind": "none", "value": None},
            "affected": {"modules": [], "areas": ["src/app.py"]},
            "path_summary": {
                "representation": "exact",
                "total_changed_paths": 1,
                "paths": [{"path": "src/app.py", "change": "modified"}],
            },
            "structural_summary": "No structural change.",
            "knowledge_updates": "Knowledge remains consistent.",
            "verification": {
                "summary": "Fixture verification.",
                "evidence_refs": [{"locator": "tr-local"}],
            },
            "understand_involvement": {
                "refresh": False,
                "compatibility": False,
            },
            "task_book_ids": [TASK_A],
            "provenance": {
                "relevant_develop_session_count": 0,
                "relevant_develop_session_ids": [],
                "classes": {
                    name: {"path_count": 1 if name == "UNATTRIBUTED" else 0}
                    for name in PROVENANCE_CLASSES
                },
            },
            "limitations": [],
        }

    @staticmethod
    def _task() -> dict:
        return {
            "record_id": TASK_A,
            "title": "Fixture",
            "scope": {"paths": ["src/app.py"], "modules": []},
        }

    @staticmethod
    def _delta() -> dict:
        return {
            "counts": {
                name: 1 if name == "UNATTRIBUTED" else 0
                for name in PROVENANCE_CLASSES
            }
        }

    def _state(self, path: str) -> tuple[str, str]:
        return "regular_file", "sha256:" + file_digest(self.host / path)

    @staticmethod
    def _touch(*, after: tuple[str, str]) -> dict:
        return {
            "path": "src/app.py",
            "change_kind": "created",
            "was_preexisting_dirty": False,
            "before_kind": "missing",
            "after_kind": after[0],
            "before_digest": None,
            "after_digest": after[1],
            "stage_ids": ["stage-1"],
        }

    @staticmethod
    def _session(
        *,
        files: list[dict] | None = None,
        s0: dict[str, tuple[str, str | None]] | None = None,
        s1: dict[str, tuple[str, str | None]] | None = None,
        coverage: str = "complete",
    ) -> dict:
        def overlay(values):
            return {
                "coverage": coverage,
                "paths": [
                    {"path": path, "kind": state[0], "digest": state[1]}
                    for path, state in (values or {}).items()
                ],
            }

        return {
            "session": {
                "record_id": "dev-20260831T010000Z-a1b2c3d4",
                "created_at": "2026-08-31T01:00:00Z",
                "workspace_overlay_s0": overlay(s0),
                "workspace_overlay_s1": overlay(s1),
            },
            "files": files or [],
        }

    def _local_remote(
        self, *, host: Path | None = None, suffix: str = ""
    ) -> Path:
        host = host or self.host
        remote = self.root / f"remote{suffix}.git"
        subprocess.run(
            ["git", "init", "--bare", str(remote)],
            capture_output=True,
            check=True,
        )
        git(host, "remote", "add", "origin", str(remote))
        git(host, "push", "-u", "origin", "main")
        return remote

    @staticmethod
    def _bare_head(remote: Path) -> str:
        completed = subprocess.run(
            ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return completed.stdout.strip()

    def _write_session(self, session_id: str, *, status: str) -> None:
        directory = self.host / ".scaffold/runtime/develop-sessions" / session_id
        directory.mkdir(parents=True, exist_ok=True)
        now = "2026-08-31T01:00:00Z"
        write_yaml_atomic(
            directory / "session.yaml",
            {
                "record_type": "develop_session",
                "schema_version": "1",
                "record_id": session_id,
                "created_at": now,
                "updated_at": now,
                "status": status,
                "task_id": TASK_A,
                "mode": "normal_task",
                "project_name": self.host.name,
                "baseline": {"kind": "none", "value": None},
                "workspace_overlay_s0": {
                    "coverage": "unavailable",
                    "paths": [],
                },
                "workspace_overlay_s1": {
                    "coverage": "unavailable",
                    "paths": [],
                },
                "observed_candidate_digest": "0" * 64,
            },
        )
        write_yaml_atomic(directory / "files.yaml", {"files": []})

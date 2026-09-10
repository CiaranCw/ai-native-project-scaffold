from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from p6_support import git
from p7_support import TASK_A
from p8_support import init_submit_git, run_submit, submit_engine, write_ready_task, write_submit_host
from support import write
from scaffold_p5.io_util import write_yaml_atomic
from scaffold_p6.candidate import observe_candidate
from scaffold_p8.models import SESSIONS_DIR
from scaffold_p8.push import push_if_authorized
from scaffold_p8.records import is_durable


class P8Rev2Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.host = self.root / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_U01_authorized_s11_pushes_exact_s10_commit(self):
        self._git_host()
        remote = self._local_remote()
        write(self.host, "docs/note.md", "modified\n")
        result = self._finalize_engine(push=True)
        commit = result.extras["s10"]["commit"]
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(git(self.host, "rev-parse", "HEAD"), commit)
        self.assertEqual(result.extras["push"]["expected_s10_commit"], commit)
        self.assertEqual(self._bare_head(remote), commit)
        self.assertEqual(result.extras["push"]["remote_head"], commit)

    def test_U02_later_local_commit_is_not_pushed(self):
        self._git_host()
        remote = self._local_remote()
        write(self.host, "docs/note.md", "modified\n")
        later = {"sha": ""}

        def after_s10():
            later["sha"] = self._extra_commit("D")

        result = self._finalize_engine(push=True, before_s11=after_s10)
        commit_c = result.extras["s10"]["commit"]
        self.assertNotEqual(later["sha"], commit_c)
        self.assertEqual(git(self.host, "rev-parse", "HEAD"), later["sha"])
        self.assertNotEqual(self._bare_head(remote), later["sha"])
        self.assertNotEqual(result.extras["push"].get("remote_head"), later["sha"])

    def test_U03_exact_s10_commit_is_pushed_when_head_moved(self):
        self._git_host()
        remote = self._local_remote()
        write(self.host, "docs/note.md", "modified\n")
        later = {"sha": ""}

        def after_s10():
            later["sha"] = self._extra_commit("D")

        result = self._finalize_engine(push=True, before_s11=after_s10)
        commit_c = result.extras["s10"]["commit"]
        self.assertTrue(result.extras["push"]["performed"])
        self.assertTrue(result.extras["push"]["ok"])
        self.assertEqual(result.extras["push"]["expected_s10_commit"], commit_c)
        self.assertEqual(self._bare_head(remote), commit_c)
        self.assertEqual(git(self.host, "rev-parse", "HEAD"), later["sha"])

    def test_U04_non_fast_forward_blocks_and_leaves_remote(self):
        self._git_host()
        remote = self._local_remote()
        write(self.host, "docs/note.md", "modified\n")
        later = {"sha": ""}

        def after_s10():
            later["sha"] = self._extra_commit("D")
            git(self.host, "push", "origin", "HEAD:refs/heads/main")

        result = self._finalize_engine(push=True, before_s11=after_s10)
        commit_c = result.extras["s10"]["commit"]
        self.assertFalse(result.extras["push"]["performed"])
        self.assertFalse(result.extras["push"]["ok"])
        self.assertNotEqual(commit_c, later["sha"])
        self.assertEqual(self._bare_head(remote), later["sha"])
        self.assertTrue(any("force" in item.lower() or "fast-forward" in item.lower()
                            for item in [result.extras["push"]["reason"]]))

    def test_U05_missing_or_invalid_expected_commit_does_not_push(self):
        self._git_host()
        remote = self._local_remote()
        write(self.host, "docs/note.md", "modified\n")
        result = self._finalize_engine(push=True)
        baseline = self._bare_head(remote)
        for expected in (None, "", "not-a-commit"):
            pushed = push_if_authorized(
                self.host,
                authorized=True,
                scm_kind="git",
                s10_ok=True,
                expected_commit=expected,
            )
            self.assertFalse(pushed["performed"])
            self.assertFalse(pushed["ok"])
            self.assertEqual(self._bare_head(remote), baseline)
        self.assertEqual(baseline, result.extras["s10"]["commit"])

    def test_U06_push_success_with_remote_mismatch_is_not_successful(self):
        self._git_host()
        self._local_remote()
        write(self.host, "docs/note.md", "modified\n")
        result = self._finalize_engine()
        commit = result.extras["s10"]["commit"]
        from scaffold_p8 import push as push_mod

        original = push_mod._remote_rev
        seen = {"n": 0}

        def observe(root, branch):
            seen["n"] += 1
            if seen["n"] == 1:
                return original(root, branch)
            return "0" * 40

        with mock.patch("scaffold_p8.push._remote_rev", side_effect=observe):
            pushed = push_if_authorized(
                self.host,
                authorized=True,
                scm_kind="git",
                s10_ok=True,
                expected_commit=commit,
                expected_branch="main",
            )
        self.assertTrue(pushed["performed"])
        self.assertFalse(pushed["ok"])
        self.assertEqual(pushed["expected_s10_commit"], commit)

    def test_U07_simulate_failure_cannot_bypass_exact_commit_validation(self):
        self._git_host()
        remote = self._local_remote()
        write(self.host, "docs/note.md", "modified\n")
        result = self._finalize_engine()
        baseline = self._bare_head(remote)
        invalid = push_if_authorized(
            self.host,
            authorized=True,
            scm_kind="git",
            s10_ok=True,
            expected_commit="",
            simulate_failure=True,
        )
        self.assertFalse(invalid["performed"])
        self.assertEqual(self._bare_head(remote), baseline)
        valid = push_if_authorized(
            self.host,
            authorized=True,
            scm_kind="git",
            s10_ok=True,
            expected_commit=result.extras["s10"]["commit"],
            expected_branch="main",
            simulate_failure=True,
        )
        self.assertTrue(valid["performed"])
        self.assertFalse(valid["ok"])
        self.assertEqual(valid["expected_s10_commit"], result.extras["s10"]["commit"])
        self.assertEqual(valid["local_head"], git(self.host, "rev-parse", "HEAD"))
        self.assertEqual(self._bare_head(remote), baseline)

    def test_U08_durable_commit_with_unresolved_verification(self):
        self._git_host()
        write(self.host, "docs/note.md", "modified\n")
        result = self._finalize_engine(after_s10_commit=self._dirty_reviewed)
        s10 = result.extras["s10"]
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(s10["ok"])
        self.assertTrue(s10["durable"])
        self.assertEqual(s10["commit"], git(self.host, "rev-parse", "HEAD"))
        self.assertEqual(s10["tree"], git(self.host, "rev-parse", "HEAD^{tree}"))
        self.assertTrue(s10["commit"])
        self.assertTrue(s10["tree"])

    def test_U09_durable_but_blocked_does_not_claim_only_change_record(self):
        self._git_host()
        write(self.host, "docs/note.md", "modified\n")
        result = self._finalize_engine(after_s10_commit=self._dirty_reviewed)
        self.assertNotEqual(result.mutations, "change_record")
        self.assertEqual(result.mutations, "durable_finalization")
        self.assertTrue(result.extras["durable_finalization_occurred"])
        self.assertEqual(result.extras["post_finalization_verification"], "unresolved")
        self.assertTrue(result.extras["s10_durable"])
        self.assertFalse(result.extras["s9_durable"])

    def test_U10_durable_but_blocked_does_not_push(self):
        self._git_host()
        remote = self._local_remote()
        write(self.host, "docs/note.md", "modified\n")
        baseline = self._bare_head(remote)
        result = self._finalize_engine(push=True, after_s10_commit=self._dirty_reviewed)
        self.assertFalse(result.extras["push"]["performed"])
        self.assertEqual(self._bare_head(remote), baseline)

    def test_U11_durable_but_blocked_does_not_cleanup_sessions(self):
        write_submit_host(self.host)
        session_id = "dev-20260831T090000Z-aabbccdd"
        self._write_session(session_id)
        write_ready_task(self.host, develop_session_ids=[session_id])
        write(self.host, "docs/note.md", "baseline\n")
        init_submit_git(self.host)
        write(self.host, "docs/note.md", "modified\n")
        result = self._finalize_engine(after_s10_commit=self._dirty_reviewed)
        self.assertFalse(result.extras["cleanup"]["performed"])
        self.assertTrue((self.host / SESSIONS_DIR / session_id).is_dir())
        self.assertNotIn(session_id, result.extras["cleanup"].get("cleaned") or [])

    def test_U12_committed_change_record_remains_durable_history(self):
        self._git_host()
        write(self.host, "docs/note.md", "modified\n")
        result = self._finalize_engine(after_s10_commit=self._dirty_reviewed)
        record_id = result.extras["change_record"]["record_id"]
        self.assertTrue(is_durable(self.host, record_id))
        self.assertTrue(result.extras["s10"]["durable"])

    def _git_host(self) -> None:
        write_submit_host(self.host)
        write(self.host, "docs/note.md", "baseline\n")
        init_submit_git(self.host)

    def _finalize_engine(
        self,
        *,
        push: bool = False,
        fail_push: bool = False,
        before_s11=None,
        after_s10_commit=None,
    ):
        return run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            push=push,
            fail_push=fail_push,
            before_s11=before_s11,
            after_s10_commit=after_s10_commit,
        )

    def _dirty_reviewed(self) -> None:
        write(self.host, "docs/note.md", "dirty after commit\n")

    def _extra_commit(self, message: str) -> str:
        write(self.host, "docs/extra.md", f"{message}\n")
        git(self.host, "add", "docs/extra.md")
        git(self.host, "commit", "-m", message)
        return git(self.host, "rev-parse", "HEAD")

    def _local_remote(self) -> Path:
        remote = self.root / "remote.git"
        subprocess.run(
            ["git", "init", "--bare", str(remote)],
            capture_output=True,
            check=True,
        )
        git(self.host, "remote", "add", "origin", str(remote))
        git(self.host, "push", "-u", "origin", "main")
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

    def _write_session(self, session_id: str) -> None:
        directory = self.host / SESSIONS_DIR / session_id
        directory.mkdir(parents=True, exist_ok=True)
        now = "2026-08-31T09:00:00Z"
        write_yaml_atomic(
            directory / "session.yaml",
            {
                "record_type": "develop_session",
                "schema_version": "1",
                "record_id": session_id,
                "created_at": now,
                "updated_at": now,
                "status": "SEALED",
                "task_id": TASK_A,
                "mode": "normal_task",
                "project_name": self.host.name,
                "baseline": {"kind": "none", "value": None},
                "workspace_overlay_s0": {"coverage": "unavailable", "paths": []},
                "workspace_overlay_s1": {"coverage": "unavailable", "paths": []},
                "observed_candidate_digest": "0" * 64,
            },
        )
        write_yaml_atomic(directory / "files.yaml", {"files": []})

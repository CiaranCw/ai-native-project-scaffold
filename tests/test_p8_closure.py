from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from p6_support import git
from p7_support import TASK_A
from p8_support import init_submit_git, submit_engine, write_submit_host
from support import write
from scaffold_p6.candidate import observe_candidate


class P8ClosureTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.host = self.root / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_V01_s11_without_drift_pushes_c_to_main(self):
        self._git_host()
        remote = self._local_remote()
        write(self.host, "docs/note.md", "modified\n")
        result = self._finalize_engine(push=True)
        commit = result.extras["s10"]["commit"]
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.extras["s10"]["branch"], "main")
        self.assertEqual(result.extras["push"]["expected_s10_branch"], "main")
        self.assertEqual(self._bare_head(remote, "main"), commit)
        self.assertFalse(self._bare_has(remote, "other"))

    def test_V02_branch_switch_does_not_push_c_to_other(self):
        self._git_host()
        remote = self._local_remote()
        write(self.host, "docs/note.md", "modified\n")
        later = {"sha": ""}

        def after_s10():
            later["sha"] = self._switch_and_commit("other", "D")

        result = self._finalize_engine(push=True, before_s11=after_s10)
        commit_c = result.extras["s10"]["commit"]
        self.assertEqual(result.extras["s10"]["branch"], "main")
        self.assertEqual(git(self.host, "rev-parse", "HEAD"), later["sha"])
        self.assertNotEqual(self._bare_head(remote, "other", missing_ok=True), commit_c)
        self.assertNotEqual(result.extras["push"].get("expected_s10_branch"), "other")

    def test_V03_branch_switch_still_publishes_c_to_main(self):
        self._git_host()
        remote = self._local_remote()
        write(self.host, "docs/note.md", "modified\n")
        later = {"sha": ""}

        def after_s10():
            later["sha"] = self._switch_and_commit("other", "D")

        result = self._finalize_engine(push=True, before_s11=after_s10)
        commit_c = result.extras["s10"]["commit"]
        self.assertTrue(result.extras["push"]["performed"])
        self.assertTrue(result.extras["push"]["ok"])
        self.assertEqual(result.extras["push"]["expected_s10_commit"], commit_c)
        self.assertEqual(result.extras["push"]["expected_s10_branch"], "main")
        self.assertEqual(self._bare_head(remote, "main"), commit_c)
        self.assertFalse(self._bare_has(remote, "other"))
        self.assertEqual(git(self.host, "rev-parse", "HEAD"), later["sha"])

    def test_V04_non_fast_forward_on_s10_branch_does_not_force(self):
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
        self.assertEqual(self._bare_head(remote, "main"), later["sha"])
        self.assertNotEqual(self._bare_head(remote, "main"), commit_c)
        self.assertIn("force", result.extras["push"]["reason"].lower())

    def test_V05_final_candidate_matches_fresh_observation(self):
        self._git_host()
        self._local_remote()
        write(self.host, "docs/note.md", "modified\n")

        def after_s10():
            self._extra_commit("D")

        result = self._finalize_engine(push=True, before_s11=after_s10)
        fresh = observe_candidate(self.host)
        self.assertEqual(result.extras["candidate"]["candidate_digest"], fresh.digest)
        self.assertEqual(result.baseline, fresh.data)

    def test_V06_s10_commit_remains_distinct_from_current_candidate(self):
        self._git_host()
        self._local_remote()
        write(self.host, "docs/note.md", "modified\n")
        later = {"sha": ""}

        def after_s10():
            later["sha"] = self._extra_commit("D")

        result = self._finalize_engine(push=True, before_s11=after_s10)
        commit_c = result.extras["s10"]["commit"]
        fresh = observe_candidate(self.host)
        self.assertEqual(commit_c, result.extras["s10"]["commit"])
        self.assertEqual(result.extras["s10"]["branch"], "main")
        self.assertEqual(fresh.data.get("revision"), later["sha"])
        self.assertNotEqual(commit_c, later["sha"])
        self.assertNotEqual(fresh.data.get("revision"), commit_c)
        self.assertEqual(result.extras["candidate"]["candidate_digest"], fresh.digest)

    def test_V07_authorized_non_fast_forward_is_not_completed(self):
        self._git_host()
        remote = self._local_remote()
        write(self.host, "docs/note.md", "modified\n")
        later = {"sha": ""}

        def after_s10():
            later["sha"] = self._extra_commit("D")
            git(self.host, "push", "origin", "HEAD:refs/heads/main")

        result = self._finalize_engine(push=True, before_s11=after_s10)
        commit_c = result.extras["s10"]["commit"]
        self.assertNotEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.extras["s10"]["durable"])
        self.assertTrue(result.extras["s10"]["ok"])
        self.assertTrue(result.blockers)
        self.assertEqual(result.next_route, "human")
        self.assertEqual(git(self.host, "rev-parse", "HEAD"), later["sha"])
        self.assertTrue(
            subprocess.run(
                ["git", "-C", str(self.host), "cat-file", "-t", commit_c],
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )
        self.assertEqual(self._bare_head(remote, "main"), later["sha"])

    def test_V08_authorized_push_failure_is_visible_without_rollback(self):
        self._git_host()
        self._local_remote()
        write(self.host, "docs/note.md", "modified\n")
        result = self._finalize_engine(push=True, fail_push=True)
        commit = result.extras["s10"]["commit"]
        self.assertNotEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.extras["s10"]["durable"])
        self.assertTrue(result.extras["s10"]["ok"])
        self.assertTrue(result.extras["push"]["performed"])
        self.assertFalse(result.extras["push"]["ok"])
        self.assertTrue(result.blockers)
        self.assertEqual(git(self.host, "rev-parse", "HEAD"), commit)
        self.assertEqual(
            git(self.host, "rev-parse", "HEAD^{tree}"),
            result.extras["s10"]["tree"],
        )

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
    ):
        digest = observe_candidate(self.host).digest
        authorization = {"granted": True, "candidate_digest": digest}
        return submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized=authorization,
            push_authorized=authorization if push else None,
            fail_push=fail_push,
            before_s11=before_s11,
        )

    def _extra_commit(self, message: str) -> str:
        write(self.host, "docs/extra.md", f"{message}\n")
        git(self.host, "add", "docs/extra.md")
        git(self.host, "commit", "-m", message)
        return git(self.host, "rev-parse", "HEAD")

    def _switch_and_commit(self, branch: str, message: str) -> str:
        git(self.host, "switch", "-c", branch)
        return self._extra_commit(message)

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

    def _bare_head(self, remote: Path, branch: str = "main", *, missing_ok: bool = False) -> str:
        completed = subprocess.run(
            ["git", "--git-dir", str(remote), "rev-parse", f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if completed.returncode != 0:
            if missing_ok:
                return ""
            completed.check_returncode()
        return completed.stdout.strip()

    def _bare_has(self, remote: Path, branch: str) -> bool:
        return bool(self._bare_head(remote, branch, missing_ok=True))

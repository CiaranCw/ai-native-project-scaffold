from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from p6_support import git, test_engine
from p7_support import TASK_A, develop_engine, write_active_host, write_task
from p8_support import bind_submit_lock, run_submit, submit_engine, write_submit_host
from support import write

from scaffold_p5 import scm as scm_mod
from scaffold_p5.io_util import read_yaml
from scaffold_p5.scm import (
    AHEAD,
    CURRENT,
    DIVERGED,
    NOT_CONFIGURED,
    OBSERVATION_FAILED,
    SCM_ABSENT,
    STALE,
    UNKNOWN,
    observe_scm,
    observe_upstream_currentness,
)
from scaffold_p6.candidate import observe_candidate
from scaffold_p8.delta import observe_real_diff
from scaffold_p8.records import is_durable


class FA2Batch2ScmTruthTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.host = self.root / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    # S01-S07: shared SCM/candidate observation.

    def test_S01_normal_git_project_observation_succeeds(self):
        write(self.host, "src/app.py", "value = 1\n")
        revision = self._init_repo(self.host)
        observed = observe_scm(self.host)
        candidate = observe_candidate(self.host)
        self.assertTrue(observed.ok)
        self.assertEqual(observed.kind, "git")
        self.assertEqual(observed.revision, revision)
        self.assertEqual(observed.observation_state, "OBSERVED")
        self.assertTrue(candidate.usable)
        self.assertEqual(candidate.data["working_tree"], "clean")

    def test_S02_git_command_failure_is_not_clean_or_empty_candidate(self):
        self._submit_host()
        self._init_repo(self.host)
        failed = scm_mod._GitBytesResult(False, 1, b"", b"fixture failure")
        with mock.patch("scaffold_p5.scm._run_git_bytes", return_value=failed):
            candidate = observe_candidate(self.host)
            engine = test_engine(self.host)
            result = engine.run("scoped_verification", selected=["unit"])
        self.assertFalse(candidate.usable)
        self.assertEqual(candidate.digest, "")
        self.assertEqual(candidate.data["working_tree"], "unknown")
        self.assertEqual(candidate.data["tracked_changes"], "unknown")
        self.assertEqual(candidate.data["untracked_changes"], "unknown")
        self.assertNotEqual(candidate.data["working_tree"], "clean")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertEqual(
            result.baseline["observation_state"], OBSERVATION_FAILED
        )

    def test_S03_git_observation_failure_does_not_become_no_scm(self):
        write(self.host, ".git/HEAD", "ref: refs/heads/main\n")
        failed = scm_mod._GitResult(False, 1, "", "fixture failure")
        with mock.patch("scaffold_p5.scm._run_git", return_value=failed):
            observed = observe_scm(self.host)
            candidate = observe_candidate(self.host)
        self.assertEqual(observed.kind, "git")
        self.assertEqual(observed.observation_state, OBSERVATION_FAILED)
        self.assertFalse(observed.ok)
        self.assertEqual(candidate.kind, "git")
        self.assertFalse(candidate.usable)

    def test_S04_nested_project_in_parent_worktree_is_git(self):
        parent, project = self._nested_project()
        self._init_repo(parent)
        observed = observe_scm(project)
        candidate = observe_candidate(project)
        self.assertTrue(observed.ok)
        self.assertEqual(observed.kind, "git")
        self.assertEqual(observed.scm_root_label, "parent")
        self.assertEqual(observed.project_prefix, "project")
        self.assertEqual(candidate.kind, "git")
        self.assertEqual(candidate.data["scm_root"], "parent")

    def test_S05_parent_changes_outside_project_are_excluded(self):
        parent, project = self._nested_project()
        self._init_repo(parent)
        write(parent, "outside.txt", "changed outside\n")
        candidate = observe_candidate(project)
        diff = observe_real_diff(project)
        self.assertTrue(candidate.usable)
        self.assertEqual(candidate.data["working_tree"], "clean")
        self.assertEqual(candidate.data["tracked_paths"], [])
        self.assertEqual(diff["paths"], [])

    def test_S06_nested_project_local_change_is_observed(self):
        parent, project = self._nested_project()
        self._init_repo(parent)
        write(project, "src/app.py", "value = 2\n")
        candidate = observe_candidate(project)
        diff = observe_real_diff(project)
        self.assertEqual(candidate.data["working_tree"], "dirty")
        self.assertEqual(
            [row["path"] for row in candidate.data["tracked_paths"]],
            ["src/app.py"],
        )
        self.assertEqual(diff["paths"], ["src/app.py"])

    def test_S07_true_no_scm_host_remains_no_scm(self):
        write(self.host, "src/app.py", "value = 1\n")
        observed = observe_scm(self.host)
        candidate = observe_candidate(self.host)
        self.assertEqual(observed.kind, "none")
        self.assertEqual(observed.observation_state, SCM_ABSENT)
        self.assertTrue(observed.ok)
        self.assertEqual(candidate.kind, "none")
        self.assertTrue(candidate.usable)

    # D01-D06: Develop D1 currentness before source mutation.

    def test_D01_current_tracking_state_may_enter_develop(self):
        self._develop_host()
        self._init_repo(self.host)
        self._track_current(self.host)
        result = self._develop_write("value = 2\n")
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual((self.host / "src/app.py").read_text(), "value = 2\n")

    def test_D02_upstream_ahead_blocks_before_source_mutation(self):
        self._develop_host()
        base = self._init_repo(self.host)
        upstream = self._commit_tree(self.host, base, "upstream")
        self._track(self.host, upstream)
        before = (self.host / "src/app.py").read_text()
        result = self._develop_write("blocked = True\n")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["d1_currentness"]["state"], STALE)
        self.assertEqual((self.host / "src/app.py").read_text(), before)
        self.assertFalse((self.host / ".scaffold/runtime/develop-sessions").exists())

    def test_D03_diverged_state_blocks_before_source_mutation(self):
        self._develop_host()
        base = self._init_repo(self.host)
        local = self._commit_tree(self.host, base, "local")
        upstream = self._commit_tree(self.host, base, "upstream")
        git(self.host, "update-ref", "refs/heads/main", local)
        self._track(self.host, upstream)
        result = self._develop_write("blocked = True\n")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["d1_currentness"]["state"], DIVERGED)
        self.assertEqual(
            (self.host / "src/app.py").read_text(encoding="utf-8"),
            "value = 1\n",
        )

    def test_D04_configured_unresolvable_upstream_fails_closed(self):
        self._develop_host()
        self._init_repo(self.host)
        self._configure_upstream(self.host)
        result = self._develop_write("blocked = True\n")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["d1_currentness"]["state"], UNKNOWN)
        self.assertFalse(result.extras["d1_currentness"]["observation_ok"])
        self.assertEqual(
            (self.host / "src/app.py").read_text(encoding="utf-8"),
            "value = 1\n",
        )

    def test_D05_local_only_git_does_not_require_upstream(self):
        self._develop_host()
        self._init_repo(self.host)
        currentness = observe_upstream_currentness(self.host)
        self.assertEqual(currentness.state, NOT_CONFIGURED)
        result = self._develop_write("value = 5\n")
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)

    def test_D06_nested_project_uses_parent_git_currentness(self):
        parent = self.root / "parent"
        project = parent / "project"
        project.mkdir(parents=True)
        self.host = project
        self._develop_host()
        self._init_repo(parent)
        self._track_current(parent)
        result = self._develop_write("value = 6\n")
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.extras["candidate"]["kind"], "git")
        self.assertEqual(observe_scm(project).scm_root_label, "parent")

    def test_D07_failed_candidate_observation_blocks_before_task_or_source_mutation(self):
        self._develop_host()
        self._init_repo(self.host)
        failed = scm_mod._GitBytesResult(False, 1, b"", b"fixture failure")
        with mock.patch("scaffold_p5.scm._run_git_bytes", return_value=failed):
            result = self._develop_write("blocked = True\n")
        task = read_yaml(
            self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(
            result.baseline["observation_state"], OBSERVATION_FAILED
        )
        self.assertEqual(task["record_revision"], 1)
        self.assertEqual(
            (self.host / "src/app.py").read_text(encoding="utf-8"),
            "value = 1\n",
        )
        self.assertFalse((self.host / ".scaffold/runtime/develop-sessions").exists())

    # R01-R07: Submit S7 currentness after S6.

    def test_R01_stable_reviewed_repository_basis_passes_s7(self):
        self._submit_host()
        self._init_submit_repo()
        self._track_current(self.host)
        digest = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.extras["s7_currentness"]["state"], CURRENT)

    def test_R02_candidate_change_after_s6_uses_existing_s8_loop(self):
        self._submit_host()
        self._init_submit_repo()
        digest = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            before_s7=lambda: write(self.host, "src/app.py", "value = 7\n"),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S8")
        self.assertEqual(result.extras["loop"], "S8→S3/S4/S5/S6")
        self.assertFalse(result.extras["submit_authorized"])

    def test_R03_tracking_ref_advance_invalidates_old_authorization(self):
        self._submit_host()
        base = self._init_submit_repo()
        self._track(self.host, base)
        upstream = self._commit_tree(self.host, base, "upstream")
        digest = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            before_s7=lambda: git(
                self.host,
                "update-ref",
                "refs/remotes/origin/main",
                upstream,
            ),
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S8")
        self.assertEqual(result.extras["s7_currentness"]["state"], STALE)
        self.assertEqual(
            result.extras["prior_candidate"],
            result.extras["current_candidate"],
        )
        self.assertFalse(result.extras["submit_authorized"])
        self.assertFalse((self.host / ".scaffold/changes").exists())

    def test_R04_diverged_repository_blocks_before_s9_s10(self):
        self._submit_host()
        base = self._init_submit_repo()
        local = self._commit_tree(self.host, base, "local")
        upstream = self._commit_tree(self.host, base, "upstream")
        git(self.host, "update-ref", "refs/heads/main", local)
        self._track(self.host, upstream)
        digest = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S8")
        self.assertEqual(result.extras["s7_currentness"]["state"], DIVERGED)
        self.assertFalse((self.host / ".scaffold/changes").exists())

    def test_R05_s7_observation_failure_never_passes_sync(self):
        self._submit_host()
        self._init_submit_repo()
        digest = observe_candidate(self.host).digest
        original = scm_mod._run_git_bytes
        fail = {"active": False}

        def status(root, *args):
            if fail["active"]:
                return scm_mod._GitBytesResult(
                    False, 1, b"", b"fixture S7 failure"
                )
            return original(root, *args)

        def activate_failure():
            fail["active"] = True

        with mock.patch("scaffold_p5.scm._run_git_bytes", side_effect=status):
            result = run_submit(self.host, 
                task_id=TASK_A,
                invoke_test=True,
                selected=["unit"],
                finalize=True,
                before_s7=activate_failure,
            )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S7")
        self.assertEqual(
            result.extras["scm_observation"]["observation_state"],
            OBSERVATION_FAILED,
        )
        self.assertFalse(result.extras["submit_authorized"])
        self.assertFalse((self.host / ".scaffold/changes").exists())

    def test_R06_nested_project_performs_git_s7_truth(self):
        parent = self.root / "parent"
        project = parent / "project"
        project.mkdir(parents=True)
        self.host = project
        self._submit_host()
        self._init_repo(parent)
        self._track_current(parent)
        digest = observe_candidate(project).digest
        result = run_submit(project, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.extras["candidate"]["kind"], "git")
        self.assertEqual(result.extras["s7_currentness"]["state"], CURRENT)

    def test_R07_local_only_git_does_not_invent_remote_requirement(self):
        self._submit_host()
        self._init_submit_repo()
        digest = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(
            result.extras["s7_currentness"]["state"], NOT_CONFIGURED
        )
        self.assertFalse(result.extras["push"]["performed"])

    def test_R08_nested_project_git_s10_and_durability_use_worktree_paths(self):
        parent = self.root / "parent"
        project = parent / "project"
        project.mkdir(parents=True)
        self.host = project
        self._submit_host()
        self._init_repo(parent)
        git(parent, "config", "--local", "user.name", "Batch 2 Fixture")
        git(
            parent,
            "config",
            "--local",
            "user.email",
            "batch2@example.invalid",
        )
        digest = observe_candidate(project).digest
        result = run_submit(project, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.extras["s10"]["kind"], "git")
        record_id = result.extras["change_record"]["record_id"]
        record_rel = f"project/.scaffold/changes/{record_id}.yaml"
        git(parent, "cat-file", "-e", f"HEAD:{record_rel}")
        self.assertTrue(is_durable(project, record_id))

    def _nested_project(self) -> tuple[Path, Path]:
        parent = self.root / "parent"
        project = parent / "project"
        project.mkdir(parents=True)
        write(parent, "outside.txt", "outside baseline\n")
        write(project, "src/app.py", "value = 1\n")
        return parent, project

    def _develop_host(self) -> None:
        write_active_host(
            self.host,
            ownership={
                ".scaffold/project.yaml": "GENERATED",
                ".scaffold/modules.yaml": "GENERATED",
                ".scaffold/commands.yaml": "GENERATED",
                ".scaffold/tests.yaml": "GENERATED",
                ".scaffold/skills.lock": "GENERATED",
                "src/": "HUMAN_OWNED",
            },
            source_areas=["src"],
        )
        write(self.host, "src/app.py", "value = 1\n")
        write_task(self.host)

    def _develop_write(self, content: str):
        return develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": content}],
        )

    def _submit_host(self) -> None:
        write_submit_host(self.host)

    def _init_submit_repo(self) -> str:
        revision = self._init_repo(self.host)
        git(self.host, "config", "--local", "user.name", "Batch 2 Fixture")
        git(
            self.host,
            "config",
            "--local",
            "user.email",
            "batch2@example.invalid",
        )
        bind_submit_lock(self.host)
        return revision

    @staticmethod
    def _init_repo(root: Path) -> str:
        write(root, ".gitignore", ".scaffold/runtime/\n__pycache__/\n*.pyc\n")
        git(root, "init")
        git(root, "branch", "-M", "main")
        git(root, "add", "-A")
        git(
            root,
            "-c",
            "user.name=Batch 2 Fixture",
            "-c",
            "user.email=batch2@example.invalid",
            "commit",
            "-m",
            "baseline",
        )
        return git(root, "rev-parse", "HEAD")

    def _track_current(self, root: Path) -> None:
        self._track(root, git(root, "rev-parse", "HEAD"))

    def _track(self, root: Path, revision: str) -> None:
        self._configure_upstream(root)
        git(root, "update-ref", "refs/remotes/origin/main", revision)

    @staticmethod
    def _configure_upstream(root: Path) -> None:
        remote = root.parent / "remote.git"
        if not remote.exists():
            subprocess.run(
                ["git", "init", "--bare", str(remote)],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        remotes = git(root, "remote").splitlines()
        if "origin" not in remotes:
            git(root, "remote", "add", "origin", str(remote))
        git(root, "config", "branch.main.remote", "origin")
        git(root, "config", "branch.main.merge", "refs/heads/main")

    @staticmethod
    def _commit_tree(root: Path, parent: str, message: str) -> str:
        tree = git(root, "rev-parse", f"{parent}^{{tree}}")
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Batch 2 Fixture",
                "-c",
                "user.email=batch2@example.invalid",
                "commit-tree",
                tree,
                "-p",
                parent,
                "-m",
                message,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return completed.stdout.strip()


if __name__ == "__main__":
    unittest.main()

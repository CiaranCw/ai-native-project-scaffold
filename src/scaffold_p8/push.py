"""S11 optional Push. Separate authorization. Never force. Never erases S10."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def push_if_authorized(
    root: Path,
    *,
    authorized: bool,
    scm_kind: str,
    s10_ok: bool,
    expected_commit: str | None = None,
    expected_branch: str | None = None,
    simulate_failure: bool = False,
) -> dict[str, Any]:
    local_head = _rev(root, "HEAD")
    if not s10_ok:
        return {
            "performed": False,
            "ok": False,
            "reason": "Push cannot start without successful S10",
            "expected_s10_commit": expected_commit or "",
            "expected_s10_branch": expected_branch or "",
            "local_head": local_head,
        }
    if scm_kind != "git":
        return {
            "performed": False,
            "ok": True,
            "reason": "Push is N/A on no-SCM",
            "expected_s10_commit": expected_commit or "",
            "expected_s10_branch": expected_branch or "",
        }
    if not authorized:
        return {
            "performed": False,
            "ok": True,
            "reason": "S10 success without Push authorization is valid local finalization",
            "expected_s10_commit": expected_commit or "",
            "expected_s10_branch": expected_branch or "",
            "local_head": local_head,
        }
    commit = _commit_id(root, expected_commit)
    if not commit:
        return {
            "performed": False,
            "ok": False,
            "reason": "expected S10 Commit is missing or is not a valid local Commit object",
            "expected_s10_commit": expected_commit or "",
            "expected_s10_branch": expected_branch or "",
            "local_head": local_head,
        }
    branch = _valid_branch(expected_branch)
    if not branch:
        return {
            "performed": False,
            "ok": False,
            "reason": (
                "authorized Push requires the exact S10 target branch; "
                "current HEAD branch is not a substitute"
            ),
            "expected_s10_commit": commit,
            "expected_s10_branch": expected_branch or "",
            "local_head": local_head,
        }
    if not _fast_forward_ok(root, branch, commit):
        return {
            "performed": False,
            "ok": False,
            "reason": (
                "Push of the exact S10 Commit would require non-fast-forward "
                "or force semantics; S11 is blocked"
            ),
            "expected_s10_commit": commit,
            "expected_s10_branch": branch,
            "local_head": local_head,
            "remote_head": _remote_rev(root, branch),
        }
    if simulate_failure:
        return {
            "performed": True,
            "ok": False,
            "reason": "Push failed; local S10 Commit is retained",
            "expected_s10_commit": commit,
            "expected_s10_branch": branch,
            "local_head": local_head,
            "simulated": True,
        }
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "push",
            "origin",
            f"{commit}:refs/heads/{branch}",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    remote = _remote_rev(root, branch)
    if completed.returncode != 0:
        return {
            "performed": True,
            "ok": False,
            "reason": "Push failed; local S10 Commit is retained",
            "expected_s10_commit": commit,
            "expected_s10_branch": branch,
            "local_head": local_head,
            "remote_head": remote,
            "stderr": completed.stderr,
        }
    if remote != commit:
        return {
            "performed": True,
            "ok": False,
            "reason": "Push returned success but remote target does not match S10 Commit",
            "expected_s10_commit": commit,
            "expected_s10_branch": branch,
            "local_head": local_head,
            "remote_head": remote,
        }
    return {
        "performed": True,
        "ok": True,
        "expected_s10_commit": commit,
        "expected_s10_branch": branch,
        "local_head": local_head,
        "remote_head": remote,
        "branch": branch,
    }


def _rev(root: Path, ref: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", ref],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _commit_id(root: Path, value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", f"{value.strip()}^{{commit}}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _valid_branch(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    name = value.strip()
    if not name or name == "HEAD":
        return ""
    if any(item in name for item in (":", "\n", "\\", " ", "..")):
        return ""
    if name.startswith("-") or name.startswith("refs/"):
        return ""
    return name


def _remote_rev(root: Path, branch: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-remote", "--heads", "origin", branch],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return ""
    return completed.stdout.split()[0]


def _fast_forward_ok(root: Path, branch: str, commit: str) -> bool:
    remote = _remote_rev(root, branch)
    if not remote or remote == commit:
        return True
    completed = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", remote, commit],
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0

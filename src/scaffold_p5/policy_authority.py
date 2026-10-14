"""Accepted-baseline check for the required-test policy.

The policy file is protected governance. A Develop session cannot write it.
Bytes on disk become required-set authority only when they match an accepted
project baseline:

- Git: the path is tracked at HEAD and the worktree matches that committed
  blob. The bound version is the last commit that changed the file.
- No SCM: the path's digest is in the accepted no-SCM baseline inventory.
  The bound version is that policy content digest, so a later baseline
  rebind that does not change the policy stays valid.

An untracked file, a dirty edit, a missing baseline, or an UNKNOWN SCM
observation stays unaccepted. Understand does not write the policy and does
not treat an Agent proposal as acceptance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.client_support import REQUIRED_TEST_POLICY
from scaffold_p5.io_util import file_digest
from scaffold_p5.scm import git_path_is_tracked, observe_scm


POLICY_REL = REQUIRED_TEST_POLICY


def evaluate_policy_acceptance(root: str | Path) -> dict[str, Any]:
    """Return whether the working policy file is an accepted authority."""
    host = Path(root)
    path = host / POLICY_REL
    recovery = (
        f"{POLICY_REL} is protected governance. A Develop session cannot "
        "write it. On Git, the project owner places the file and commits it; "
        "Git commit is not an autonomous Develop command. On a no-SCM host, "
        "the owner places the file and that exact digest must be in the "
        "accepted no-SCM baseline. An Agent-created or uncommitted copy "
        "stays UNKNOWN."
    )
    if not path.is_file() or path.is_symlink():
        return _rejected(
            f"{POLICY_REL} is not an accepted regular project file. " + recovery
        )
    try:
        current = file_digest(path)
    except OSError:
        return _rejected(f"{POLICY_REL} could not be read. " + recovery)
    scm = observe_scm(host)
    if scm.kind == "git":
        if scm.observation_state != "OBSERVED" or not scm.revision:
            return _rejected(
                "Git observation is UNKNOWN, so required-test policy "
                "acceptance stays UNKNOWN. " + recovery
            )
        tracked = git_path_is_tracked(host, POLICY_REL)
        if tracked is not True:
            return _rejected(
                f"{POLICY_REL} is not in the accepted Git HEAD. " + recovery
            )
        if not _worktree_matches_head(host):
            return _rejected(
                f"{POLICY_REL} differs from the accepted Git HEAD. " + recovery
            )
        version = _policy_commit(host)
        if not version:
            return _rejected(
                f"{POLICY_REL} has no accepted Git version. " + recovery
            )
        return {
            "ok": True,
            "source": "git_head",
            "version": version,
            "digest": current,
            "blockers": [],
        }
    if scm.kind == "none":
        from scaffold_p8.noscms import load_noscms_baseline

        loaded = load_noscms_baseline(host)
        if not loaded.get("ok"):
            return _rejected(
                f"{POLICY_REL} has no accepted no-SCM baseline. " + recovery
            )
        inventory = loaded.get("inventory")
        if not isinstance(inventory, dict):
            return _rejected(
                "the accepted no-SCM baseline inventory is unusable. " + recovery
            )
        entry = inventory.get(POLICY_REL)
        recorded = entry.get("digest") if isinstance(entry, dict) else None
        if recorded != current:
            return _rejected(
                f"{POLICY_REL} is not in the accepted no-SCM baseline "
                "at this digest. " + recovery
            )
        return {
            "ok": True,
            "source": "noscms_baseline",
            "version": current,
            "digest": current,
            "blockers": [],
        }
    return _rejected(
        "SCM observation is not an accepted Git HEAD or no-SCM baseline. " + recovery
    )


def _rejected(reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "source": "",
        "version": "",
        "digest": "",
        "blockers": [reason],
    }


def _worktree_matches_head(root: Path) -> bool:
    from scaffold_p5.scm import _run_git

    result = _run_git(root, "diff", "--quiet", "HEAD", "--", POLICY_REL)
    return bool(result.ok)


def _policy_commit(root: Path) -> str:
    from scaffold_p5.scm import _run_git

    result = _run_git(root, "log", "-1", "--format=%H", "--", POLICY_REL)
    if not result.ok:
        return ""
    return str(result.stdout or "").strip()

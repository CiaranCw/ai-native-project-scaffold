"""S10 Commit / no-SCM durable finalization. Does not invent a Git Commit on no-SCM."""

from __future__ import annotations

import contextlib
import os
import subprocess
from pathlib import Path
from typing import Any, Iterator

from scaffold_p5.io_util import file_digest, write_yaml_atomic
from scaffold_p6.candidate import observe_candidate

from scaffold_p8.models import FINALIZATIONS_DIR
from scaffold_p8.records import (
    change_path,
    durability_state,
    finalization_binding,
)


def finalize_s10(
    root: Path,
    *,
    record_id: str,
    change_rel: str,
    reviewed_paths: list[str],
    expected_digest: str,
    scm_kind: str,
    expected_parent: str | None = None,
    reviewed_entries: list[dict[str, Any]] | None = None,
    after_commit: Any = None,
) -> dict[str, Any]:
    if scm_kind != "git":
        return _finalize_noscms(
            root, record_id=record_id, expected_digest=expected_digest
        )
    current = observe_candidate(root)
    if current.digest != expected_digest:
        return {
            "ok": False,
            "kind": scm_kind,
            "durable": False,
            "blockers": [
                "candidate changed immediately before S10; "
                "reviewed candidate no longer matches"
            ],
        }
    if scm_kind == "git":
        return _finalize_git(
            root,
            record_id=record_id,
            change_rel=change_rel,
            reviewed_paths=reviewed_paths,
            expected_parent=expected_parent,
            reviewed_entries=reviewed_entries
            or [{"path": path, "change": "modified"} for path in reviewed_paths],
            after_commit=after_commit,
        )
    raise AssertionError("unreachable S10 kind")


def _finalize_git(
    root: Path,
    *,
    record_id: str,
    change_rel: str,
    reviewed_paths: list[str],
    expected_parent: str | None,
    reviewed_entries: list[dict[str, Any]],
    after_commit: Any = None,
) -> dict[str, Any]:
    current_head = _git(root, "rev-parse", "HEAD")
    if not expected_parent or not current_head:
        return _git_block(
            "S10 Git parent/base identity is UNKNOWN; Commit is blocked"
        )
    if current_head != expected_parent:
        return {
            "ok": False,
            "kind": "git",
            "durable": False,
            "blockers": [
                "S10 parent/base is not the reviewed expected revision"
            ],
        }
    pathspecs = _reviewed_pathspecs(reviewed_entries, reviewed_paths)
    allowed = sorted(set(pathspecs + [change_rel]))
    if not allowed:
        return {
            "ok": False,
            "kind": "git",
            "durable": False,
            "blockers": ["S10 has no authorized files to finalize"],
        }
    prior_staged, staged_error = _staged_names(root, current_head)
    if staged_error:
        return _git_block(staged_error)
    prior_extra = sorted(set(prior_staged) - set(allowed))
    if prior_extra:
        return _git_block(
            "unrelated file cannot silently enter finalization set: "
            + ", ".join(prior_extra)
        )
    stage_error = _stage_reviewed(
        root, reviewed_entries, change_rel=change_rel
    )
    if stage_error:
        return _git_block(stage_error)
    staged, staged_error = _staged_names(root, current_head)
    if staged_error:
        return _git_block(staged_error)
    extra = sorted(set(staged) - set(allowed))
    if extra:
        return _git_block(
            "unrelated file cannot silently enter finalization set: "
            + ", ".join(extra)
        )
    missing = sorted(_required_staged_paths(reviewed_entries) - set(staged))
    if missing:
        return _git_block(
            "reviewed Diff entry is absent from the S10 staged tree: "
            + ", ".join(missing)
        )
    if change_rel not in staged:
        return _git_block("S9 Change Record is not present in the S10 staged tree")
    expected_tree_state = {
        path: _index_object(root, path) for path in allowed
    }
    author_ok, author_reason = _usable_git_identity(root)
    if not author_ok:
        return _git_block(author_reason)
    commit = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "commit",
            "-m",
            f"submit: {record_id}",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if commit.returncode != 0:
        return {
            "ok": False,
            "kind": "git",
            "durable": False,
            "blockers": ["S10 Commit failed; Change Record remains a candidate"],
            "stderr": commit.stderr,
        }
    sha = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    branch = _attached_branch(root)
    if callable(after_commit):
        after_commit()
    verification = _verify_git_finalization(
        root,
        commit=sha,
        expected_parent=expected_parent or current_head,
        change_rel=change_rel,
        entries=reviewed_entries,
        pathspecs=pathspecs,
        expected_tree_state=expected_tree_state,
    )
    if verification:
        result = {
            "ok": False,
            "kind": "git",
            "durable": True,
            "commit": sha,
            "tree": tree,
            "blockers": verification,
            "durability_source": "git_commit",
            "post_finalization_verification": "unresolved",
        }
        if branch:
            result["branch"] = branch
        return result
    result = {
        "ok": True,
        "kind": "git",
        "durable": True,
        "commit": sha,
        "tree": tree,
        "staged": staged,
        "durability_source": "git_commit",
    }
    if branch:
        result["branch"] = branch
    return result


def _finalize_noscms(
    root: Path, *, record_id: str, expected_digest: str
) -> dict[str, Any]:
    lock = (
        root
        / ".scaffold/runtime/submit-finalization-locks"
        / f"{record_id}.lock"
    )
    try:
        with _publication_lock(lock):
            state = durability_state(root, record_id)
            if state["state"] == "malformed":
                return {
                    "ok": False,
                    "kind": "none",
                    "durable": False,
                    "conflict": True,
                    "blockers": [
                        "no-SCM publication is malformed; recovery is required"
                    ]
                    + list(state.get("blockers") or []),
                }
            record = change_path(root, record_id)
            if not record.is_file():
                return {
                    "ok": False,
                    "kind": "none",
                    "durable": False,
                    "blockers": ["S9 Change Record is missing before no-SCM S10"],
                }
            record_digest = file_digest(record)
            if state["state"] == "durable":
                data = state.get("data") or {}
                if (
                    data.get("candidate_digest") == expected_digest
                    and data.get("change_record_digest") == record_digest
                ):
                    return {
                        "ok": True,
                        "kind": "none",
                        "durable": True,
                        "retried": True,
                        "durability_source": "serialized_publication",
                    }
                return {
                    "ok": False,
                    "kind": "none",
                    "durable": False,
                    "conflict": True,
                    "blockers": [
                        "no-SCM publication conflict: an incompatible "
                        "finalization already won"
                    ],
                }
            current = observe_candidate(root)
            if current.digest != expected_digest:
                return {
                    "ok": False,
                    "kind": "none",
                    "durable": False,
                    "blockers": [
                        "candidate changed immediately before S10 (no-SCM)"
                    ],
                }
            marker = build_finalization_marker(
                record_id=record_id,
                candidate_digest=expected_digest,
                change_record_digest=record_digest,
            )
            write_yaml_atomic(
                root / FINALIZATIONS_DIR / f"{record_id}.yaml", marker
            )
            established = durability_state(root, record_id)
            if established["state"] != "durable":
                return {
                    "ok": False,
                    "kind": "none",
                    "durable": False,
                    "blockers": [
                        "no-SCM durable publication was not established"
                    ]
                    + list(established.get("blockers") or []),
                }
            return {
                "ok": True,
                "kind": "none",
                "durable": True,
                "durability_source": "serialized_publication",
            }
    except OSError as exc:
        return {
            "ok": False,
            "kind": "none",
            "durable": False,
            "blockers": [
                f"no-SCM finalization lock could not be established: {exc}"
            ],
        }


def build_finalization_marker(
    *,
    record_id: str,
    candidate_digest: str,
    change_record_digest: str,
) -> dict[str, Any]:
    return {
        "kind": "submit_finalization",
        "record_class": "support_artifact",
        "change_id": record_id,
        "ok": True,
        "scm_kind": "none",
        "candidate_digest": candidate_digest,
        "change_record_digest": change_record_digest,
        "finalization_digest": finalization_binding(
            record_id, "none", candidate_digest, change_record_digest
        ),
    }


def _staged_names(root: Path, parent: str) -> tuple[list[str], str]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "diff",
            "--cached",
            "--name-only",
            "--no-renames",
            "-z",
            parent,
        ],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return [], "Git staged-tree observation failed"
    names = [
        item.decode("utf-8", "replace").replace("\\", "/")
        for item in completed.stdout.split(b"\0")
        if item
    ]
    return names, ""


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return completed.stdout.strip()


def _attached_branch(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    name = completed.stdout.strip() if completed.returncode == 0 else ""
    if not name or name == "HEAD":
        return ""
    return name


def _git_block(reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "kind": "git",
        "durable": False,
        "blockers": [reason],
    }


def _usable_git_identity(root: Path) -> tuple[bool, str]:
    for variable in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
        completed = subprocess.run(
            ["git", "-C", str(root), "var", variable],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if completed.returncode != 0 or "<" not in completed.stdout:
            return (
                False,
                "S10 requires an existing usable Git author/committer identity; "
                "Submit will not fabricate one",
            )
    return True, ""


def _stage_reviewed(
    root: Path,
    entries: list[dict[str, Any]],
    *,
    change_rel: str,
) -> str:
    add_paths = {change_rel}
    remove_paths: set[str] = set()
    for entry in entries:
        path = str(entry.get("path") or "")
        orig = str(entry.get("orig_path") or "")
        change = entry.get("change")
        if change == "deleted":
            if path:
                remove_paths.add(path)
        elif path:
            add_paths.add(path)
        if change == "renamed" and orig:
            remove_paths.add(orig)
    if add_paths:
        added = subprocess.run(
            ["git", "-C", str(root), "add", "-A", "--", *sorted(add_paths)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if added.returncode != 0:
            return "S10 git add failed; Change Record remains a candidate"
    if remove_paths:
        removed = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "update-index",
                "--remove",
                "--",
                *sorted(remove_paths),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if removed.returncode != 0:
            return "S10 Git deletion staging failed; Change Record remains a candidate"
    return ""


def _reviewed_pathspecs(
    entries: list[dict[str, Any]], fallback: list[str]
) -> list[str]:
    paths = set(fallback)
    for entry in entries:
        path = entry.get("path")
        orig = entry.get("orig_path")
        if isinstance(path, str) and path:
            paths.add(path)
        if isinstance(orig, str) and orig:
            paths.add(orig)
    return sorted(paths)


def _required_staged_paths(entries: list[dict[str, Any]]) -> set[str]:
    required: set[str] = set()
    for entry in entries:
        path = str(entry.get("path") or "")
        orig = str(entry.get("orig_path") or "")
        if path:
            required.add(path)
        if entry.get("change") == "renamed" and orig:
            required.add(orig)
    return required


def _index_object(root: Path, path: str) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", f":{path}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _commit_object(root: Path, commit: str, path: str) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", f"{commit}:{path}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _verify_git_finalization(
    root: Path,
    *,
    commit: str,
    expected_parent: str,
    change_rel: str,
    entries: list[dict[str, Any]],
    pathspecs: list[str],
    expected_tree_state: dict[str, str | None],
) -> list[str]:
    issues: list[str] = []
    if _git(root, "rev-parse", f"{commit}^") != expected_parent:
        issues.append("S10 Commit parent does not match the reviewed base")
    for path, expected_object in expected_tree_state.items():
        if _commit_object(root, commit, path) != expected_object:
            issues.append(f"S10 Commit tree does not match staged state for {path}")
    if not expected_tree_state.get(change_rel):
        issues.append("S10 Commit does not contain the exact staged Change Record")
    for entry in entries:
        path = str(entry.get("path") or "")
        orig = str(entry.get("orig_path") or "")
        change = entry.get("change")
        if change == "deleted" and _commit_object(root, commit, path) is not None:
            issues.append(f"reviewed deletion was not finalized for {path}")
        if change == "renamed":
            if _commit_object(root, commit, path) is None:
                issues.append(f"reviewed rename destination is absent: {path}")
            if orig and _commit_object(root, commit, orig) is not None:
                issues.append(f"reviewed rename source remains present: {orig}")
        if change == "copied":
            if (
                _commit_object(root, commit, path) is None
                or not orig
                or _commit_object(root, commit, orig) is None
            ):
                issues.append(f"reviewed copy is not represented: {orig} -> {path}")
    for path in pathspecs:
        status = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v1",
                "-z",
                "--",
                path,
            ],
            capture_output=True,
            check=False,
        )
        if status.returncode != 0:
            issues.append(f"post-S10 status is UNKNOWN for reviewed path {path}")
        elif status.stdout:
            issues.append(f"reviewed path remains dirty after S10: {path}")
    return issues


@contextlib.contextmanager
def _publication_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"*")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

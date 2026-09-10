"""S10 Commit / no-SCM durable finalization. Does not invent a Git Commit on no-SCM."""

from __future__ import annotations

import contextlib
import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any, Iterator

from scaffold_p5.io_util import file_digest, read_yaml, write_yaml_atomic
from scaffold_p5.scm import (
    ScmObservation,
    observe_scm,
    project_to_worktree_path,
)
from scaffold_p6.candidate import observe_candidate

from scaffold_p8.noscms import publish_noscms_finalization
from scaffold_p8.records import (
    change_path,
    durability_state,
    finalization_binding,
)

INDEX_RECOVERY_DIR = ".scaffold/runtime/submit-index-recovery"


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
    support_artifacts: list[dict[str, str]] | None = None,
    after_commit: Any = None,
    during_s10: Any = None,
    fail_before_complete: bool = False,
    fail_baseline_cache: bool = False,
) -> dict[str, Any]:
    support = list(support_artifacts or [])
    support_issues = _support_artifact_issues(root, support)
    if support_issues:
        return {
            "ok": False,
            "kind": scm_kind,
            "durable": False,
            "blockers": support_issues,
        }
    if scm_kind != "git":
        return _finalize_noscms(
            root,
            record_id=record_id,
            expected_digest=expected_digest,
            support_artifacts=support,
            during_s10=during_s10,
            fail_before_complete=fail_before_complete,
            fail_baseline_cache=fail_baseline_cache,
        )
    current = observe_candidate(root)
    if not current.usable:
        return {
            "ok": False,
            "kind": scm_kind,
            "durable": False,
            "blockers": list(current.data.get("blockers") or [
                "candidate SCM observation is unresolved immediately before S10"
            ]),
        }
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
            support_artifacts=support,
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
    support_artifacts: list[dict[str, str]],
    after_commit: Any = None,
) -> dict[str, Any]:
    scm = observe_scm(root)
    if not scm.ok or scm.kind != "git" or scm.worktree_root is None:
        return _git_block(
            "S10 Git worktree/project-root relation is UNKNOWN; Commit is blocked"
        )
    git_root = scm.worktree_root
    worktree_change_rel = project_to_worktree_path(scm, change_rel)
    worktree_entries = _worktree_entries(scm, reviewed_entries)
    worktree_reviewed_paths = [
        path
        for value in reviewed_paths
        if (path := project_to_worktree_path(scm, value))
    ]
    worktree_support = [
        {
            "path": project_to_worktree_path(scm, str(item.get("path") or "")),
            "digest": str(item.get("digest") or ""),
        }
        for item in support_artifacts
    ]
    if (
        not worktree_change_rel
        or len(worktree_entries) != len(reviewed_entries)
        or any(not item["path"] for item in worktree_support)
    ):
        return _git_block(
            "S10 reviewed project paths cannot be resolved in the Git worktree"
        )
    current_head = _git(git_root, "rev-parse", "HEAD")
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
    pathspecs = _reviewed_pathspecs(
        worktree_entries, worktree_reviewed_paths
    )
    support_paths = [str(item["path"]) for item in worktree_support]
    pathspecs = sorted(set(pathspecs + support_paths))
    allowed = sorted(set(pathspecs + [worktree_change_rel]))
    if not allowed:
        return {
            "ok": False,
            "kind": "git",
            "durable": False,
            "blockers": ["S10 has no authorized files to finalize"],
        }
    prior_staged, staged_error = _staged_names(git_root, current_head)
    if staged_error:
        return _git_block(staged_error)
    prior_extra = sorted(set(prior_staged) - set(allowed))
    if prior_extra:
        return _git_block(
            "unrelated file cannot silently enter finalization set: "
            + ", ".join(prior_extra)
        )
    author_ok, author_reason = _usable_git_identity(git_root)
    if not author_ok:
        return _git_block(author_reason)
    touched_paths = _index_touched_paths(
        worktree_entries,
        change_rel=worktree_change_rel,
        support_paths=support_paths,
    )
    index_snapshot, snapshot_error = _capture_index_snapshot(
        git_root,
        project_root=root,
        record_id=record_id,
        touched_paths=touched_paths,
        expected_head=current_head,
    )
    if index_snapshot is None:
        return _git_block(snapshot_error)
    stage_error = _stage_reviewed(
        git_root,
        worktree_entries,
        change_rel=worktree_change_rel,
        support_paths=support_paths,
    )
    if stage_error:
        return _git_failure_after_staging(
            git_root, index_snapshot, stage_error
        )
    staged, staged_error = _staged_names(git_root, current_head)
    if staged_error:
        return _git_failure_after_staging(
            git_root, index_snapshot, staged_error
        )
    extra = sorted(set(staged) - set(allowed))
    if extra:
        return _git_failure_after_staging(
            git_root,
            index_snapshot,
            "unrelated file cannot silently enter finalization set: "
            + ", ".join(extra),
        )
    missing = sorted(_required_staged_paths(worktree_entries) - set(staged))
    missing.extend(sorted(set(support_paths) - set(staged)))
    missing = sorted(set(missing))
    if missing:
        return _git_failure_after_staging(
            git_root,
            index_snapshot,
            "reviewed Diff entry is absent from the S10 staged tree: "
            + ", ".join(missing),
        )
    if worktree_change_rel not in staged:
        return _git_failure_after_staging(
            git_root,
            index_snapshot,
            "S9 Change Record is not present in the S10 staged tree",
        )
    expected_tree_state = {
        path: _index_object(git_root, path) for path in allowed
    }
    try:
        commit = subprocess.run(
            [
                "git",
                "-C",
                str(git_root),
                "commit",
                "-m",
                f"submit: {record_id}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError as exc:
        return _git_failure_after_staging(
            git_root,
            index_snapshot,
            f"S10 Commit could not start: {exc}",
        )
    if commit.returncode != 0:
        post_commit_head = _git(git_root, "rev-parse", "HEAD")
        if post_commit_head and post_commit_head != current_head:
            _discard_index_snapshot(index_snapshot)
            return {
                "ok": False,
                "kind": "git",
                "durable": True,
                "commit": post_commit_head,
                "tree": _git(git_root, "rev-parse", "HEAD^{tree}"),
                "blockers": [
                    "Git HEAD changed during a failed Commit result; "
                    "durability requires human verification"
                ],
                "stderr": commit.stderr,
                "durability_source": "git_commit",
                "post_finalization_verification": "unresolved",
            }
        return _git_failure_after_staging(
            git_root,
            index_snapshot,
            "S10 Commit failed; Finalization Bundle remains a candidate",
            stderr=commit.stderr,
        )
    sha = _git(git_root, "rev-parse", "HEAD")
    tree = _git(git_root, "rev-parse", "HEAD^{tree}")
    if not sha or sha == current_head:
        return _git_failure_after_staging(
            git_root,
            index_snapshot,
            "S10 Commit reported success without establishing a new durable Commit",
        )
    _discard_index_snapshot(index_snapshot)
    branch = _attached_branch(git_root)
    if callable(after_commit):
        after_commit()
    verification = _verify_git_finalization(
        git_root,
        commit=sha,
        expected_parent=expected_parent or current_head,
        change_rel=worktree_change_rel,
        entries=worktree_entries,
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
    root: Path,
    *,
    record_id: str,
    expected_digest: str,
    support_artifacts: list[dict[str, str]],
    during_s10: Any = None,
    fail_before_complete: bool = False,
    fail_baseline_cache: bool = False,
) -> dict[str, Any]:
    support_issues = _support_artifact_issues(root, support_artifacts)
    if support_issues:
        return {
            "ok": False,
            "kind": "none",
            "durable": False,
            "blockers": support_issues,
        }
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
                    and list(data.get("support_artifacts") or [])
                    == support_artifacts
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
            if not current.usable:
                return {
                    "ok": False,
                    "kind": "none",
                    "durable": False,
                    "blockers": [
                        "candidate observation is unresolved immediately "
                        "before no-SCM S10"
                    ],
                }
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
                support_artifacts=support_artifacts,
            )
            published = publish_noscms_finalization(
                root,
                record_id=record_id,
                candidate_digest=expected_digest,
                change_record_digest=record_digest,
                support_artifacts=support_artifacts,
                marker=marker,
                during_s10=during_s10,
                fail_before_complete=fail_before_complete,
                fail_baseline_cache=fail_baseline_cache,
            )
            if not published.get("ok"):
                return {
                    "ok": False,
                    "kind": "none",
                    "durable": False,
                    "blockers": list(published.get("blockers") or [
                        "no-SCM durable publication was not established"
                    ]),
                }
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
                "publication_path": published.get("publication_path"),
                "representation_digest": published.get("representation_digest"),
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
    support_artifacts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    support = list(support_artifacts or [])
    marker = {
        "kind": "submit_finalization",
        "record_class": "support_artifact",
        "change_id": record_id,
        "ok": True,
        "scm_kind": "none",
        "candidate_digest": candidate_digest,
        "change_record_digest": change_record_digest,
        "finalization_digest": finalization_binding(
            record_id,
            "none",
            candidate_digest,
            change_record_digest,
            support,
        ),
    }
    if support:
        marker["support_artifacts"] = support
    return marker


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


def _index_touched_paths(
    entries: list[dict[str, Any]],
    *,
    change_rel: str,
    support_paths: list[str],
) -> list[str]:
    paths = {change_rel, *support_paths}
    for entry in entries:
        for field in ("path", "orig_path"):
            value = entry.get(field)
            if isinstance(value, str) and value:
                paths.add(value)
    return sorted(paths)


def _capture_index_snapshot(
    root: Path,
    *,
    project_root: Path,
    record_id: str,
    touched_paths: list[str],
    expected_head: str,
) -> tuple[dict[str, Any] | None, str]:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-path", "index"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    raw_path = completed.stdout.strip()
    if completed.returncode != 0 or not raw_path:
        return None, "S10 could not resolve the Git index before staging"
    index_path = Path(raw_path)
    if not index_path.is_absolute():
        index_path = root / index_path
    try:
        existed = index_path.is_file()
        index_bytes = index_path.read_bytes() if existed else b""
    except OSError as exc:
        return None, f"S10 could not snapshot the Git index before staging: {exc}"
    unrelated, observation_error = _unrelated_index_observation(
        root, set(touched_paths)
    )
    if observation_error:
        return None, observation_error
    metadata_path, snapshot_path = _index_recovery_paths(project_root, record_id)
    metadata = {
        "kind": "submit_index_recovery",
        "record_id": record_id,
        "expected_head": expected_head,
        "index_existed": existed,
        "index_snapshot_digest": _sha256(index_bytes),
        "touched_paths": list(touched_paths),
    }
    try:
        _write_bytes_atomic(snapshot_path, index_bytes)
        write_yaml_atomic(metadata_path, metadata)
    except OSError as exc:
        _remove_index_recovery_files(metadata_path, snapshot_path)
        return None, f"S10 could not persist its pre-staging index snapshot: {exc}"
    return {
        "index_path": index_path,
        "existed": existed,
        "bytes": index_bytes,
        "expected_head": expected_head,
        "touched_paths": list(touched_paths),
        "unrelated": unrelated,
        "metadata_path": metadata_path,
        "snapshot_path": snapshot_path,
    }, ""


def _unrelated_index_observation(
    root: Path,
    touched_paths: set[str],
    *,
    index_file: Path | None = None,
) -> tuple[tuple[bytes, ...], str]:
    records: list[bytes] = []
    environment = os.environ.copy()
    if index_file is not None:
        environment["GIT_INDEX_FILE"] = str(index_file)
    for args, separator in (
        (("ls-files", "--stage", "-z"), b"\t"),
        (("ls-files", "-v", "-z"), b" "),
    ):
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            check=False,
            env=environment,
        )
        if completed.returncode != 0:
            return (), "S10 could not observe unrelated Git index state"
        for record in completed.stdout.split(b"\0"):
            if not record:
                continue
            _prefix, found, path_bytes = record.partition(separator)
            if not found:
                return (), "S10 Git index observation is malformed"
            path = path_bytes.decode("utf-8", "surrogateescape").replace("\\", "/")
            if path not in touched_paths:
                records.append(
                    b"|".join((" ".join(args).encode("ascii"), record))
                )
    return tuple(sorted(records)), ""


def _selected_index_observation(
    root: Path,
    selected_paths: set[str],
    *,
    index_file: Path | None = None,
) -> tuple[tuple[bytes, ...], str]:
    records: list[bytes] = []
    environment = os.environ.copy()
    if index_file is not None:
        environment["GIT_INDEX_FILE"] = str(index_file)
    for args, separator in (
        (("ls-files", "--stage", "-z"), b"\t"),
        (("ls-files", "-v", "-z"), b" "),
    ):
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            check=False,
            env=environment,
        )
        if completed.returncode != 0:
            return (), "S10 could not observe selected Git index state"
        for record in completed.stdout.split(b"\0"):
            if not record:
                continue
            _prefix, found, path_bytes = record.partition(separator)
            if not found:
                return (), "S10 Git index observation is malformed"
            path = path_bytes.decode("utf-8", "surrogateescape").replace("\\", "/")
            if path in selected_paths:
                records.append(
                    b"|".join((" ".join(args).encode("ascii"), record))
                )
    return tuple(sorted(records)), ""


def _git_failure_after_staging(
    root: Path,
    snapshot: dict[str, Any],
    reason: str,
    *,
    stderr: str = "",
) -> dict[str, Any]:
    rollback = _rollback_index(root, snapshot)
    blockers = [reason] + list(rollback.get("blockers") or [])
    result: dict[str, Any] = {
        "ok": False,
        "kind": "git",
        "durable": False,
        "blockers": blockers,
        "index_mutated": True,
        "index_rollback": rollback,
    }
    if stderr:
        result["stderr"] = stderr
    return result


def _rollback_index(root: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    touched = list(snapshot.get("touched_paths") or [])
    blockers: list[str] = []
    if _git(root, "rev-parse", "HEAD") != snapshot.get("expected_head"):
        blockers.append(
            "S10 index rollback refused because Git HEAD changed; "
            "P8 recovery reconciliation is required"
        )
    current_unrelated, observation_error = _unrelated_index_observation(
        root, set(touched)
    )
    if observation_error:
        blockers.append(observation_error)
    elif current_unrelated != snapshot.get("unrelated"):
        blockers.append(
            "S10 index rollback refused because unrelated index state changed; "
            "P8 recovery reconciliation is required"
        )
    snapshot_path = snapshot.get("snapshot_path")
    if not isinstance(snapshot_path, Path) or not snapshot_path.is_file():
        blockers.append("S10 index rollback snapshot is malformed or missing")
        expected_touched: tuple[bytes, ...] = ()
    else:
        expected_touched, touched_error = _selected_index_observation(
            root,
            set(touched),
            index_file=snapshot_path,
        )
        if touched_error:
            blockers.append(touched_error)
    if blockers:
        return {
            "required": True,
            "ok": False,
            "restored": False,
            "touched_paths": touched,
            "blockers": blockers,
        }
    stage_records = [
        record.partition(b"|")[2]
        for record in expected_touched
        if record.startswith(b"ls-files --stage -z|")
    ]
    flag_records = [
        record.partition(b"|")[2]
        for record in expected_touched
        if record.startswith(b"ls-files -v -z|")
    ]
    removed = subprocess.run(
        ["git", "-C", str(root), "update-index", "--force-remove", "--", *touched],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if removed.returncode != 0:
        return {
            "required": True,
            "ok": False,
            "restored": False,
            "touched_paths": touched,
            "blockers": [
                "S10 path-scoped index rollback could not remove touched entries; "
                "P8 recovery reconciliation is required"
            ],
        }
    if stage_records:
        restored_entries = subprocess.run(
            ["git", "-C", str(root), "update-index", "-z", "--index-info"],
            input=b"\0".join(stage_records) + b"\0",
            capture_output=True,
            check=False,
        )
        if restored_entries.returncode != 0:
            return {
                "required": True,
                "ok": False,
                "restored": False,
                "touched_paths": touched,
                "blockers": [
                    "S10 path-scoped index entry restoration failed; "
                    "P8 recovery reconciliation is required"
                ],
            }
    restored_paths = [
        record.partition(b" ")[2].decode("utf-8", "surrogateescape")
        for record in flag_records
    ]
    if restored_paths:
        cleared = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "update-index",
                "--no-assume-unchanged",
                "--no-skip-worktree",
                "--",
                *restored_paths,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if cleared.returncode != 0:
            return {
                "required": True,
                "ok": False,
                "restored": False,
                "touched_paths": touched,
                "blockers": [
                    "S10 path-scoped index flag restoration failed; "
                    "P8 recovery reconciliation is required"
                ],
            }
        for record in flag_records:
            tag, _separator, path_bytes = record.partition(b" ")
            path = path_bytes.decode("utf-8", "surrogateescape")
            options: list[str] = []
            if tag[:1].islower():
                options.append("--assume-unchanged")
            if tag[:1].upper() == b"S":
                options.append("--skip-worktree")
            if options:
                flagged = subprocess.run(
                    ["git", "-C", str(root), "update-index", *options, "--", path],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=False,
                )
                if flagged.returncode != 0:
                    return {
                        "required": True,
                        "ok": False,
                        "restored": False,
                        "touched_paths": touched,
                        "blockers": [
                            "S10 path-scoped index flag restoration failed; "
                            "P8 recovery reconciliation is required"
                        ],
                    }
    actual_touched, touched_error = _selected_index_observation(
        root, set(touched)
    )
    final_unrelated, unrelated_error = _unrelated_index_observation(
        root, set(touched)
    )
    if (
        touched_error
        or unrelated_error
        or actual_touched != expected_touched
        or final_unrelated != current_unrelated
    ):
        return {
            "required": True,
            "ok": False,
            "restored": False,
            "touched_paths": touched,
            "blockers": [
                "S10 index rollback verification failed; "
                "P8 recovery reconciliation is required"
            ],
        }
    _discard_index_snapshot(snapshot)
    return {
        "required": True,
        "ok": True,
        "restored": True,
        "touched_paths": touched,
        "blockers": [],
    }


def reconcile_index_transactions(project_root: Path) -> list[str]:
    base = project_root / INDEX_RECOVERY_DIR
    if not base.is_dir():
        return []
    blockers: list[str] = []
    stems = {
        path.stem
        for path in base.iterdir()
        if path.is_file() and path.suffix in {".yaml", ".index"}
    }
    for stem in sorted(stems):
        metadata_path = base / f"{stem}.yaml"
        snapshot_path = base / f"{stem}.index"
        if not metadata_path.is_file() or not snapshot_path.is_file():
            blockers.append(
                "S10 index recovery coordination is incomplete; "
                "P8 reconciliation is required"
            )
            continue
        try:
            metadata = read_yaml(metadata_path)
            snapshot_bytes = snapshot_path.read_bytes()
        except (OSError, ValueError, TypeError, UnicodeError):
            blockers.append(
                "S10 index recovery coordination is unreadable; "
                "P8 reconciliation is required"
            )
            continue
        issues = _index_recovery_issues(metadata, stem=stem)
        if issues or _sha256(snapshot_bytes) != metadata.get(
            "index_snapshot_digest"
        ):
            blockers.extend(
                issues
                or [
                    "S10 index recovery snapshot integrity does not hold; "
                    "P8 reconciliation is required"
                ]
            )
            continue
        record_id = str(metadata["record_id"])
        state = durability_state(project_root, record_id)
        if state.get("state") == "durable":
            _remove_index_recovery_files(metadata_path, snapshot_path)
            continue
        if state.get("state") != "absent":
            blockers.extend(
                list(state.get("blockers") or [])
                or [
                    "S10 durability is unresolved; "
                    "P8 index reconciliation is required"
                ]
            )
            continue
        scm = observe_scm(project_root)
        if not scm.ok or scm.kind != "git" or scm.worktree_root is None:
            blockers.append(
                "S10 index recovery cannot resolve its Git worktree; "
                "P8 reconciliation is required"
            )
            continue
        index_path, index_error = _resolve_index_path(scm.worktree_root)
        if index_path is None:
            blockers.append(index_error)
            continue
        touched = list(metadata.get("touched_paths") or [])
        unrelated, observation_error = _unrelated_index_observation(
            scm.worktree_root,
            set(touched),
            index_file=snapshot_path,
        )
        if observation_error:
            blockers.append(observation_error)
            continue
        rollback = _rollback_index(
            scm.worktree_root,
            {
                "index_path": index_path,
                "existed": metadata.get("index_existed") is True,
                "bytes": snapshot_bytes,
                "expected_head": metadata.get("expected_head"),
                "touched_paths": touched,
                "unrelated": unrelated,
                "metadata_path": metadata_path,
                "snapshot_path": snapshot_path,
            },
        )
        if not rollback.get("ok"):
            blockers.extend(list(rollback.get("blockers") or []))
    return sorted(set(blockers))


def _index_recovery_issues(data: Any, *, stem: str) -> list[str]:
    required = {
        "kind",
        "record_id",
        "expected_head",
        "index_existed",
        "index_snapshot_digest",
        "touched_paths",
    }
    if not isinstance(data, dict) or set(data) != required:
        return ["S10 index recovery metadata is malformed"]
    issues: list[str] = []
    if data.get("kind") != "submit_index_recovery":
        issues.append("S10 index recovery kind is malformed")
    record_id = data.get("record_id")
    if not isinstance(record_id, str) or hashlib.sha256(
        record_id.encode("utf-8")
    ).hexdigest() != stem:
        issues.append("S10 index recovery identity does not match its files")
    expected_head = data.get("expected_head")
    if not isinstance(expected_head, str) or not expected_head:
        issues.append("S10 index recovery expected HEAD is missing")
    if type(data.get("index_existed")) is not bool:
        issues.append("S10 index recovery existence state is malformed")
    digest = data.get("index_snapshot_digest")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        issues.append("S10 index recovery digest is malformed")
    touched = data.get("touched_paths")
    if (
        not isinstance(touched, list)
        or not touched
        or any(not isinstance(path, str) or not path for path in touched)
        or len(touched) != len(set(touched))
    ):
        issues.append("S10 index recovery touched paths are malformed")
    return issues


def _resolve_index_path(root: Path) -> tuple[Path | None, str]:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-path", "index"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    raw = completed.stdout.strip()
    if completed.returncode != 0 or not raw:
        return None, "S10 could not resolve the Git index"
    path = Path(raw)
    return (path if path.is_absolute() else root / path), ""


def _index_recovery_paths(
    project_root: Path,
    record_id: str,
) -> tuple[Path, Path]:
    stem = hashlib.sha256(record_id.encode("utf-8")).hexdigest()
    base = project_root / INDEX_RECOVERY_DIR
    return base / f"{stem}.yaml", base / f"{stem}.index"


def _discard_index_snapshot(snapshot: dict[str, Any]) -> None:
    metadata = snapshot.get("metadata_path")
    index = snapshot.get("snapshot_path")
    if isinstance(metadata, Path) and isinstance(index, Path):
        _remove_index_recovery_files(metadata, index)


def _remove_index_recovery_files(metadata: Path, snapshot: Path) -> None:
    for path in (metadata, snapshot):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            continue
    try:
        metadata.parent.rmdir()
    except OSError:
        pass


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _support_artifact_issues(
    root: Path,
    artifacts: list[dict[str, str]],
) -> list[str]:
    issues: list[str] = []
    seen: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != {"path", "digest"}:
            issues.append("S9 support artifact descriptor is malformed")
            continue
        raw = str(item.get("path") or "").replace("\\", "/")
        path = Path(raw)
        if (
            not raw
            or path.is_absolute()
            or bool(path.anchor)
            or any(part in {"", ".", ".."} for part in path.parts)
            or not raw.startswith(".scaffold/ext/")
        ):
            issues.append("S9 support artifact path is not a portable ext path")
            continue
        if raw in seen:
            issues.append(f"S9 support artifact path is duplicated: {raw}")
            continue
        seen.add(raw)
        expected = str(item.get("digest") or "")
        target = root / raw
        if (
            len(expected) != 64
            or any(char not in "0123456789abcdef" for char in expected)
            or not target.is_file()
        ):
            issues.append(f"S9 support artifact is missing or malformed: {raw}")
        elif file_digest(target) != expected:
            issues.append(f"S9 support artifact integrity does not match: {raw}")
    return issues


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
    support_paths: list[str],
) -> str:
    add_paths = {change_rel, *support_paths}
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


def _worktree_entries(
    scm: ScmObservation,
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    translated: list[dict[str, Any]] = []
    for entry in entries:
        path = project_to_worktree_path(scm, str(entry.get("path") or ""))
        if not path:
            return []
        row = dict(entry)
        row["path"] = path
        orig = str(entry.get("orig_path") or "")
        if orig:
            worktree_orig = project_to_worktree_path(scm, orig)
            if not worktree_orig:
                return []
            row["orig_path"] = worktree_orig
        translated.append(row)
    return translated


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

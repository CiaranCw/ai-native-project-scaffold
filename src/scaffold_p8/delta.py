"""S2 real Diff and provenance classification. Workspace/SCM wins over Session memory."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from scaffold_p5.io_util import file_digest, read_yaml
from scaffold_p5.schemas import CORE_MACHINE_ARTIFACTS
from scaffold_p6.candidate import RUNTIME_PREFIX
from scaffold_p7.schemas import validate_develop_session, validate_files_yaml

from scaffold_p8.models import PROVENANCE_CLASSES, SESSIONS_DIR


def observe_real_paths(root: Path) -> list[str]:
    observation = observe_real_diff(root)
    if not observation["ok"]:
        raise RuntimeError("; ".join(observation["blockers"]))
    return list(observation["paths"])


def observe_real_diff(root: Path) -> dict[str, Any]:
    if (root / ".git").exists():
        ok, payload, reason = _run_git_status(root)
        if not ok:
            return {
                "ok": False,
                "kind": "git",
                "entries": [],
                "paths": [],
                "blockers": [reason or "Git real Diff observation is UNKNOWN"],
            }
        entries, parse_issues = _parse_porcelain_z(payload)
        if parse_issues:
            return {
                "ok": False,
                "kind": "git",
                "entries": [],
                "paths": [],
                "blockers": parse_issues,
            }
        entries = [
            row
            for row in entries
            if not _runtime_path(str(row.get("path") or ""))
            and not _runtime_path(str(row.get("orig_path") or ""))
        ]
        return {
            "ok": True,
            "kind": "git",
            "entries": entries,
            "paths": _entry_paths(entries),
            "pathspecs": _entry_pathspecs(entries),
            "blockers": [],
        }
    paths = _noscms_paths(root)
    return {
        "ok": True,
        "kind": "none",
        "entries": [{"path": path, "change": "modified"} for path in paths],
        "paths": paths,
        "pathspecs": paths,
        "blockers": [],
    }


def classify_delta(
    root: Path,
    *,
    real_paths: list[str],
    sessions: list[dict[str, Any]],
    entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    classes: dict[str, str] = {}
    for path in real_paths:
        classes[path] = _classify_path(root, path, sessions)
    counts = {name: 0 for name in PROVENANCE_CLASSES}
    for label in classes.values():
        counts[label] = counts.get(label, 0) + 1
    return {
        "paths": real_paths,
        "entries": list(entries or []),
        "classes": classes,
        "counts": counts,
        "session_memory_overridden": _session_overridden(real_paths, sessions),
        "attribution_complete": all(
            label != "UNATTRIBUTED" for label in classes.values()
        )
        if classes
        else True,
    }


def load_sealed_sessions(
    root: Path, *, linked_ids: set[str] | None = None
) -> list[dict[str, Any]]:
    folder = root / SESSIONS_DIR
    if not folder.is_dir():
        return []
    rows = []
    for directory in sorted(folder.iterdir()):
        if linked_ids is not None and directory.name not in linked_ids:
            continue
        session_path = directory / "session.yaml"
        files_path = directory / "files.yaml"
        if not session_path.is_file():
            continue
        try:
            session = read_yaml(session_path)
        except (OSError, ValueError, TypeError, UnicodeError):
            continue
        if (
            not isinstance(session, dict)
            or validate_develop_session(session, expected_id=directory.name)
            or session.get("status") != "SEALED"
        ):
            continue
        if not files_path.is_file():
            continue
        try:
            payload = read_yaml(files_path)
        except (OSError, ValueError, TypeError, UnicodeError):
            continue
        if validate_files_yaml(payload):
            continue
        files = list(payload.get("files") or [])
        rows.append({"session": session, "files": files, "directory": directory})
    return sorted(
        rows,
        key=lambda row: (
            str(row["session"].get("created_at") or ""),
            str(row["session"].get("record_id") or ""),
        ),
    )


def _classify_path(
    root: Path, path: str, sessions: list[dict[str, Any]]
) -> str:
    if not sessions:
        return "UNATTRIBUTED"
    observed = _path_state(root, path)
    touched = [
        item
        for row in sessions
        for item in row.get("files") or []
        if isinstance(item, dict) and item.get("path") == path
    ]
    if touched:
        if any(item.get("was_preexisting_dirty") is True for item in touched):
            return "MIXED_CHANGE"
        if not _continuous_touched_chain(touched):
            return "MIXED_CHANGE"
        latest = _manifest_after_state(touched[-1])
        if latest is None or latest != observed:
            return "MIXED_CHANGE"
        return "DEVELOP_KNOWN"

    if _proven_preexisting(path, observed, sessions):
        return "PREEXISTING_CHANGE"
    if _proven_post_develop(path, sessions):
        return "POST_DEVELOP_ADDITIONAL"
    return "UNATTRIBUTED"


def _session_overridden(real_paths: list[str], sessions: list[dict[str, Any]]) -> bool:
    remembered = set()
    for row in sessions:
        for item in row.get("files") or []:
            if isinstance(item, dict) and item.get("path"):
                remembered.add(str(item["path"]))
            elif isinstance(item, str):
                remembered.add(item)
    return bool(remembered - set(real_paths))


def _run_git_status(root: Path) -> tuple[bool, bytes, str]:
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, b"", f"Git real Diff observation failed: {exc}"
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        return False, b"", "Git real Diff observation failed" + (
            f": {detail}" if detail else ""
        )
    return True, completed.stdout, ""


def _parse_porcelain_z(
    payload: bytes,
) -> tuple[list[dict[str, Any]], list[str]]:
    entries: list[dict[str, Any]] = []
    issues: list[str] = []
    parts = payload.split(b"\0")
    index = 0
    while index < len(parts):
        raw = parts[index]
        index += 1
        if not raw:
            continue
        text = raw.decode("utf-8", "replace")
        if len(text) < 4 or text[2] != " ":
            issues.append("Git real Diff contains a malformed porcelain entry")
            continue
        code = text[:2]
        path = text[3:].replace("\\", "/")
        if not path:
            issues.append("Git real Diff contains an empty path")
            continue
        rename_or_copy = any(item in {"R", "C"} for item in code)
        orig_path = ""
        if rename_or_copy:
            if index >= len(parts) or not parts[index]:
                issues.append("Git rename/copy entry is missing its original path")
                continue
            orig_path = (
                parts[index].decode("utf-8", "replace").replace("\\", "/")
            )
            index += 1
        entries.append(
            {
                "path": path,
                "orig_path": orig_path,
                "change": _change_kind(code),
                "index_status": code[0],
                "worktree_status": code[1],
            }
        )
    return entries, issues


def _change_kind(code: str) -> str:
    if code == "??":
        return "untracked"
    if "R" in code:
        return "renamed"
    if "C" in code:
        return "copied"
    if "D" in code:
        return "deleted"
    if "A" in code:
        return "added"
    if "T" in code:
        return "type_changed"
    return "modified"


def _entry_paths(entries: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            str(row.get("path"))
            for row in entries
            if isinstance(row.get("path"), str) and row.get("path")
        }
    )


def _entry_pathspecs(entries: list[dict[str, Any]]) -> list[str]:
    paths = set(_entry_paths(entries))
    for row in entries:
        orig = str(row.get("orig_path") or "")
        if orig:
            paths.add(orig)
    return sorted(paths)


def _runtime_path(path: str) -> bool:
    return bool(
        path
        and (path.startswith(RUNTIME_PREFIX) or path == ".scaffold/runtime")
    )


def _noscms_paths(root: Path) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name for name in dirnames if name not in {".git", "__pycache__"}
        ]
        for name in filenames:
            full = Path(dirpath) / name
            rel = str(full.relative_to(root)).replace("\\", "/")
            if rel.startswith(RUNTIME_PREFIX) or rel.endswith(".pyc"):
                continue
            if rel in CORE_MACHINE_ARTIFACTS:
                continue
            if full.is_file():
                out.append(rel)
    return sorted(out)


def path_digest(root: Path, rel: str) -> str:
    path = root / rel
    if not path.is_file():
        return ""
    return file_digest(path)


def _path_state(root: Path, rel: str) -> tuple[str, str | None]:
    path = root / rel
    if not path.exists():
        return "missing", None
    if path.is_symlink():
        target = os.readlink(path)
        return "symlink", "sha256:" + _text_digest(target)
    if path.is_file():
        return "regular_file", "sha256:" + file_digest(path)
    return "other", None


def _text_digest(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _manifest_before_state(item: dict[str, Any]) -> tuple[str, str | None] | None:
    return _recorded_state(item, "before")


def _manifest_after_state(item: dict[str, Any]) -> tuple[str, str | None] | None:
    return _recorded_state(item, "after")


def _recorded_state(
    item: dict[str, Any], prefix: str
) -> tuple[str, str | None] | None:
    kind = item.get(f"{prefix}_kind")
    digest = item.get(f"{prefix}_digest")
    if kind == "missing":
        return "missing", None
    if kind not in {"regular_file", "symlink", "other"}:
        return None
    if kind in {"regular_file", "symlink"} and not isinstance(digest, str):
        return None
    return str(kind), str(digest) if digest is not None else None


def _continuous_touched_chain(touched: list[dict[str, Any]]) -> bool:
    for item in touched:
        if (
            item.get("was_preexisting_dirty") is not False
            or _manifest_before_state(item) is None
            or _manifest_after_state(item) is None
        ):
            return False
    for previous, current in zip(touched, touched[1:]):
        if _manifest_after_state(previous) != _manifest_before_state(current):
            return False
    return True


def _overlay(
    session: dict[str, Any], name: str
) -> tuple[str, dict[str, tuple[str, str | None]]]:
    value = session.get(name)
    if not isinstance(value, dict):
        return "unavailable", {}
    rows: dict[str, tuple[str, str | None]] = {}
    for item in value.get("paths") or []:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        kind = item.get("kind")
        digest = item.get("digest")
        if kind == "missing":
            rows[item["path"]] = ("missing", None)
        elif kind in {"regular_file", "symlink", "other"}:
            rows[item["path"]] = (
                str(kind),
                str(digest) if digest is not None else None,
            )
    return str(value.get("coverage") or "unavailable"), rows


def _proven_preexisting(
    path: str,
    observed: tuple[str, str | None],
    sessions: list[dict[str, Any]],
) -> bool:
    states: list[tuple[str, str | None]] = []
    for row in sessions:
        session = row["session"]
        s0_coverage, s0 = _overlay(session, "workspace_overlay_s0")
        s1_coverage, s1 = _overlay(session, "workspace_overlay_s1")
        if s0_coverage != "complete" or s1_coverage != "complete":
            return False
        if path not in s0 or path not in s1:
            return False
        states.extend([s0[path], s1[path]])
    return bool(states) and all(state == observed for state in states)


def _proven_post_develop(
    path: str, sessions: list[dict[str, Any]]
) -> bool:
    for row in sessions:
        session = row["session"]
        s0_coverage, s0 = _overlay(session, "workspace_overlay_s0")
        s1_coverage, s1 = _overlay(session, "workspace_overlay_s1")
        if s0_coverage != "complete" or s1_coverage != "complete":
            return False
        if path in s0 or path in s1:
            return False
    return bool(sessions)

"""Task Book authority. Plan/progress only. Does not invent tasks from caller prose."""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from scaffold_p5.io_util import read_yaml, write_yaml_atomic

from scaffold_p7.models import TASKS_DIR
from scaffold_p7.schemas import TASK_ID_RE, validate_task_book

TASK_LOCKS_DIR = ".scaffold/runtime/task-locks"


class TaskResolution:
    def __init__(
        self,
        *,
        ok: bool,
        task: dict[str, Any] | None = None,
        path: Path | None = None,
        blockers: list[str] | None = None,
        route: str = "stop",
    ):
        self.ok = ok
        self.task = task
        self.path = path
        self.blockers = blockers or []
        self.route = route


@dataclass
class TaskPublication:
    ok: bool
    task: dict[str, Any] | None = None
    expected_revision: int | None = None
    published_revision: int | None = None
    actual_revision: int | None = None
    conflict: bool = False
    blockers: list[str] = field(default_factory=list)


def resolve_task(root: Path, *, task_id: Any, caller_prose: Any = None) -> TaskResolution:
    if _has_caller_prose(caller_prose) and not _valid_task_id(task_id):
        return TaskResolution(
            ok=False,
            blockers=[
                "caller-supplied prose cannot replace Task Book authority"
            ],
        )
    if task_id in (None, ""):
        available = _task_ids(root)
        if len(available) > 1:
            return TaskResolution(
                ok=False,
                blockers=["ambiguous Task Book identity; task_id is required"],
            )
        return TaskResolution(
            ok=False,
            blockers=["missing Task Book identity"],
        )
    if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
        return TaskResolution(
            ok=False,
            blockers=["invalid Task Book identity"],
        )
    path = root / TASKS_DIR / f"{task_id}.yaml"
    if not path.is_file():
        return TaskResolution(
            ok=False,
            blockers=[f"Task Book {task_id} is missing"],
        )
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return TaskResolution(
            ok=False,
            blockers=[f"Task Book {task_id} is malformed or unreadable"],
        )
    issues = validate_task_book(data, expected_id=task_id)
    if issues:
        return TaskResolution(
            ok=False,
            blockers=["Task Book is malformed"] + issues,
        )
    assert isinstance(data, dict)
    return TaskResolution(ok=True, task=data, path=path)


def mode_compatible(task: dict[str, Any], mode: str) -> tuple[bool, str]:
    status = task.get("status")
    if status == "CANCELED":
        return False, "CANCELED Task Book cannot enter Develop"
    if status == "DRAFT":
        return False, "DRAFT Task Book is not accepted as the active development plan"
    if status == "READY_FOR_REVIEW":
        return False, (
            "READY_FOR_REVIEW Task Book is Develop's terminal success state; "
            "P7 does not silently reopen it"
        )
    if status != "IN_PROGRESS":
        return False, f"Task Book status {status!r} is incompatible with Develop"
    if mode == "repair":
        return True, "IN_PROGRESS may enter repair"
    if mode == "normal_task":
        return True, "IN_PROGRESS may enter normal_task"
    return False, f"unsupported Develop mode {mode!r}"


def persist_ready_for_review(task: dict[str, Any]) -> dict[str, Any]:
    """In-memory READY status only. Canonical revision is set by publish_task."""
    updated = dict(task)
    updated["status"] = "READY_FOR_REVIEW"
    return updated


def task_revision(task: dict[str, Any]) -> int | None:
    value = task.get("record_revision")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return None
    return value


def publish_task(
    path: Path,
    task: dict[str, Any],
    *,
    expected_revision: int,
) -> TaskPublication:
    """Publish one Task Book mutation as P3 N → N+1 under a per-record lock."""
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
        return TaskPublication(
            ok=False,
            expected_revision=None,
            blockers=["Task Book expected_revision is missing or malformed"],
        )
    try:
        with _task_publication_lock(_lock_path(path)):
            return _publish_under_lock(path, task, expected_revision)
    except OSError as exc:
        return TaskPublication(
            ok=False,
            expected_revision=expected_revision,
            blockers=[
                "Task Book publication lock could not be established; "
                f"mutation is blocked ({exc})"
            ],
        )


def task_complete(task: dict[str, Any]) -> bool:
    stages = task.get("stages") or []
    if not stages:
        return False
    return all(stage.get("status") == "COMPLETE" for stage in stages)


def ready_for_review_gates(task: dict[str, Any]) -> tuple[bool, str]:
    if not task_complete(task):
        return False, "TASK_COMPLETE does not hold; READY_FOR_REVIEW is blocked"
    finals = task.get("final_tests")
    if not isinstance(finals, list):
        return False, "final_tests authority is UNKNOWN"
    for item in finals:
        if not isinstance(item, dict):
            return False, "final_tests entry is malformed"
        outcome = item.get("observed_outcome")
        if outcome != "PASS":
            return False, (
                "task-level final required tests do not satisfy defined acceptance"
            )
    if not isinstance(task.get("acceptance"), str) or not str(task["acceptance"]).strip():
        return False, "declared Task-level acceptance is UNKNOWN"
    return True, "READY_FOR_REVIEW gates hold"


def apply_session_progress(
    task: dict[str, Any],
    session_id: str,
    *,
    mode: str,
) -> dict[str, Any]:
    """Compose one in-memory mutation. Does not advance record_revision."""
    updated = link_session(task, session_id)
    if mode == "normal_task":
        updated = mark_first_stage_in_progress(updated)
    return updated


def link_session(task: dict[str, Any], session_id: str) -> dict[str, Any]:
    ids = [str(item) for item in (task.get("develop_session_ids") or [])]
    if session_id not in ids:
        ids.append(session_id)
    updated = dict(task)
    updated["develop_session_ids"] = ids
    return updated


def mark_first_stage_in_progress(task: dict[str, Any]) -> dict[str, Any]:
    stages = list(task.get("stages") or [])
    if any(stage.get("status") == "IN_PROGRESS" for stage in stages):
        return task
    updated_stages = []
    changed = False
    for stage in stages:
        row = dict(stage)
        if not changed and row.get("status") == "PENDING":
            row["status"] = "IN_PROGRESS"
            changed = True
        updated_stages.append(row)
    if not changed:
        return task
    updated = dict(task)
    updated["stages"] = updated_stages
    return updated


def _publish_under_lock(
    path: Path,
    task: dict[str, Any],
    expected_revision: int,
) -> TaskPublication:
    if not path.is_file():
        return TaskPublication(
            ok=False,
            expected_revision=expected_revision,
            blockers=["Task Book is missing"],
        )
    try:
        current = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return TaskPublication(
            ok=False,
            expected_revision=expected_revision,
            blockers=["Task Book is malformed or unreadable"],
        )
    if not isinstance(current, dict):
        return TaskPublication(
            ok=False,
            expected_revision=expected_revision,
            blockers=["Task Book is malformed"],
        )
    actual = task_revision(current)
    if actual != expected_revision:
        return TaskPublication(
            ok=False,
            conflict=True,
            task=current,
            expected_revision=expected_revision,
            actual_revision=actual,
            blockers=[
                "Task Book revision conflict: expected "
                f"{expected_revision}, published revision is {actual}"
            ],
        )
    published = dict(task)
    published["record_revision"] = expected_revision + 1
    write_yaml_atomic(path, published)
    return TaskPublication(
        ok=True,
        task=published,
        expected_revision=expected_revision,
        published_revision=expected_revision + 1,
        actual_revision=expected_revision + 1,
    )


def _lock_path(task_path: Path) -> Path:
    host = task_path.parent.parent.parent
    return host / TASK_LOCKS_DIR / f"{task_path.stem}.lock"


@contextlib.contextmanager
def _task_publication_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"*")
            handle.flush()
        handle.seek(0)
        _lock_exclusive(handle)
        yield
    finally:
        try:
            handle.seek(0)
            _unlock_exclusive(handle)
        finally:
            handle.close()


def _lock_exclusive(handle) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_exclusive(handle) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _valid_task_id(task_id: Any) -> bool:
    return isinstance(task_id, str) and bool(TASK_ID_RE.fullmatch(task_id))


def _has_caller_prose(value: Any) -> bool:
    if value in (None, "", {}, []):
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _task_ids(root: Path) -> list[str]:
    folder = root / TASKS_DIR
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.yaml")):
        if TASK_ID_RE.fullmatch(path.stem):
            out.append(path.stem)
    return out

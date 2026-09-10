"""Task Book authority. Plan/progress only. Does not invent tasks from caller prose."""

from __future__ import annotations

import contextlib
import os
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from scaffold_p5 import yaml_lite
from scaffold_p5.io_util import read_yaml, write_yaml_atomic

from scaffold_p7.models import TASKS_DIR
from scaffold_p7.schemas import TASK_ID_RE, validate_task_book

TASK_LOCKS_DIR = ".scaffold/runtime/task-locks"
_LOCAL_LOCK_INITIALIZATION = threading.Lock()


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


def mode_compatible(
    task: dict[str, Any],
    mode: str,
    *,
    ready_repair_eligible: bool = False,
) -> tuple[bool, str]:
    status = task.get("status")
    if status == "CANCELED":
        return False, "CANCELED Task Book cannot enter Develop"
    if status == "DRAFT":
        return False, "DRAFT Task Book is not accepted as the active development plan"
    if status == "READY_FOR_REVIEW":
        if mode == "repair" and ready_repair_eligible:
            return True, "READY_FOR_REVIEW may enter Stage-targeted submit_to_develop repair"
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


def publish_initial_task(root: Path, task: dict[str, Any]) -> TaskPublication:
    """Atomically publish revision 1 only when the Task identity is absent."""
    record_id = task.get("record_id")
    if not isinstance(record_id, str) or not TASK_ID_RE.fullmatch(record_id):
        return TaskPublication(
            ok=False,
            expected_revision=0,
            blockers=["initial Task Book identity is missing or malformed"],
        )
    if task.get("record_revision") != 1:
        return TaskPublication(
            ok=False,
            expected_revision=0,
            blockers=["initial Task Book record_revision must be 1"],
        )
    issues = validate_task_book(task, expected_id=record_id)
    if issues:
        return TaskPublication(
            ok=False,
            expected_revision=0,
            blockers=["initial Task Book is malformed"] + issues,
        )
    ready_blockers = ready_publication_blockers(root, task)
    if ready_blockers:
        return TaskPublication(
            ok=False,
            expected_revision=0,
            blockers=ready_blockers,
        )
    path = root / TASKS_DIR / f"{record_id}.yaml"
    try:
        with _task_publication_lock(_lock_path(path)):
            if path.exists():
                return TaskPublication(
                    ok=False,
                    expected_revision=0,
                    actual_revision=_existing_revision(path),
                    conflict=True,
                    blockers=["Task Book identity already exists; initial publication blocked"],
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_root = root / TASK_LOCKS_DIR
            tmp_root.mkdir(parents=True, exist_ok=True)
            tmp = tmp_root / f"{record_id}.{secrets.token_hex(4)}.tmp"
            try:
                with open(tmp, "x", encoding="utf-8", newline="\n") as handle:
                    handle.write(yaml_lite.dump(task))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.link(tmp, path)
            finally:
                try:
                    tmp.unlink()
                except FileNotFoundError:
                    pass
    except OSError as exc:
        return TaskPublication(
            ok=False,
            expected_revision=0,
            blockers=[
                "initial Task Book publication could not be established "
                f"atomically ({exc})"
            ],
        )
    return TaskPublication(
        ok=True,
        task=dict(task),
        expected_revision=0,
        published_revision=1,
        actual_revision=1,
    )


def valid_tasks(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Load canonical valid Task Books; malformed authority remains explicit."""
    folder = root / TASKS_DIR
    if not folder.exists():
        return [], []
    if not folder.is_dir():
        return [], ["Task Book namespace is not a directory"]
    tasks: list[dict[str, Any]] = []
    blockers: list[str] = []
    for path in sorted(folder.glob("*.yaml"), key=lambda item: item.name):
        if not TASK_ID_RE.fullmatch(path.stem):
            blockers.append(f"Task Book filename is malformed: {path.name}")
            continue
        try:
            data = read_yaml(path)
        except (OSError, ValueError, TypeError, UnicodeError):
            blockers.append(f"Task Book is malformed or unreadable: {path.name}")
            continue
        issues = validate_task_book(data, expected_id=path.stem)
        if issues:
            blockers.append(f"Task Book is malformed: {path.name}")
            blockers.extend(issues)
            continue
        assert isinstance(data, dict)
        tasks.append(data)
    return tasks, sorted(set(blockers))


def allocate_task_id(root: Path) -> str:
    used = set(_task_ids(root))
    for _ in range(64):
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        candidate = f"task-{timestamp}-{secrets.token_hex(4)}"
        if candidate not in used:
            return candidate
    raise RuntimeError("unable to allocate unique Task Book identity")


@contextlib.contextmanager
def task_intake_lock(root: Path) -> Iterator[None]:
    """Serialize proposal matching plus initial publication across Task ids."""
    lock = root / TASK_LOCKS_DIR / "intake.lock"
    with _task_publication_lock(lock):
        yield


def task_complete(task: dict[str, Any]) -> bool:
    stages = task.get("stages") or []
    if not stages:
        return False
    return all(stage.get("status") == "COMPLETE" for stage in stages)


def ready_for_review_gates(
    task: dict[str, Any],
    *,
    candidate_digest: str | None = None,
    root: Path | None = None,
) -> tuple[bool, str]:
    from scaffold_p7.lifecycle import evaluate_ready_for_review

    return evaluate_ready_for_review(
        task, candidate_digest=candidate_digest, root=root
    )


def ready_publication_blockers(
    root: Path,
    task: dict[str, Any],
    *,
    current: dict[str, Any] | None = None,
) -> list[str]:
    """CAS does not authorize READY; Records §11 / evaluate_ready_for_review does.

    A READY publication may not change the P6 substantive Task authority
    projection while relying on current-candidate completion decisions
    (Records §8.7 / FND3-E04). Compare the current canonical Task against
    the proposed Task before observing the pre-write candidate.
    """
    if task.get("status") != "READY_FOR_REVIEW":
        return []
    from scaffold_p6.candidate import observe_candidate, task_authority_digest

    if current is not None:
        if task_authority_digest(task) != task_authority_digest(current):
            return [
                "READY_FOR_REVIEW cannot mix lifecycle publication with a "
                "substantive Task authority change; publish the substantive "
                "mutation as IN_PROGRESS, then revalidate completion decisions "
                "for the new candidate"
            ]
    candidate = observe_candidate(root)
    if not candidate.usable:
        return [
            "READY_FOR_REVIEW cannot be published without a usable current candidate"
        ] + [str(item) for item in (candidate.data.get("blockers") or []) if item]
    ok, reason = ready_for_review_gates(
        task, candidate_digest=candidate.digest, root=root
    )
    if ok:
        return []
    return [
        "READY_FOR_REVIEW cannot become canonical without current "
        f"completion authority: {reason}"
    ]


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
    ready_blockers = ready_publication_blockers(
        _project_root_from_task_path(path), published, current=current
    )
    if ready_blockers:
        return TaskPublication(
            ok=False,
            task=current,
            expected_revision=expected_revision,
            actual_revision=actual,
            blockers=ready_blockers,
        )
    write_yaml_atomic(path, published)
    return TaskPublication(
        ok=True,
        task=published,
        expected_revision=expected_revision,
        published_revision=expected_revision + 1,
        actual_revision=expected_revision + 1,
    )


def _project_root_from_task_path(task_path: Path) -> Path:
    return task_path.parent.parent.parent


def _lock_path(task_path: Path) -> Path:
    return _project_root_from_task_path(task_path) / TASK_LOCKS_DIR / f"{task_path.stem}.lock"


def _existing_revision(path: Path) -> int | None:
    try:
        current = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None
    return task_revision(current) if isinstance(current, dict) else None


@contextlib.contextmanager
def _task_publication_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCAL_LOCK_INITIALIZATION:
        try:
            with open(lock_path, "xb") as created:
                created.write(b"*")
                created.flush()
                os.fsync(created.fileno())
        except FileExistsError:
            pass
        if lock_path.stat().st_size == 0:
            with open(lock_path, "r+b") as existing:
                existing.write(b"*")
                existing.flush()
                os.fsync(existing.fileno())
    handle = open(lock_path, "r+b")
    locked = False
    try:
        handle.seek(0)
        _lock_exclusive(handle)
        locked = True
        yield
    finally:
        try:
            if locked:
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

"""Current Develop execution authority. Not a repository-global capability."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p6.candidate import observe_candidate
from scaffold_p7.models import SESSIONS_DIR
from scaffold_p7.mutation import (
    authorize_path_mutation,
    is_protected_governance_path,
    overlay_path_set,
    path_in_scope,
    path_in_supporting_scope,
    task_module_paths,
)
from scaffold_p7.preflight import inspect_host_project
from scaffold_p7.schemas import SESSION_ID_RE, validate_develop_session
from scaffold_p7.session import (
    MUTATION_CANCELLED,
    MUTATION_FAILED,
    MUTATION_OBSERVED,
    MUTATION_PENDING,
    OPEN_INVENTORY_NAME,
    execution_workspace_digests,
    file_sha256,
    load_files_yaml,
    load_mutation_attempts,
    load_open_inventory,
    path_kind,
    persist_mutation_attempts,
    record_touch,
    snapshot_open_inventory,
)
from scaffold_p7.tasks import resolve_task
from scaffold_p7.unexplained import physical_authority_issues, reconcile_unexplained_drift


EXECUTION_POINTER_REL = ".scaffold/runtime/develop-execution.yaml"


@dataclass
class CurrentDevelopAuthority:
    ok: bool
    reason: str
    task: dict[str, Any] | None = None
    session: dict[str, Any] | None = None
    mutable_stage_ids: list[str] = field(default_factory=list)
    task_id: str = ""
    session_id: str = ""
    role: str = ""
    lineage_digest: str = ""
    directory: Path | None = None


def resolve_current_develop_authority(
    root: str | Path,
    *,
    require_provenance: bool = True,
) -> CurrentDevelopAuthority:
    """Resolve editor mutation authority from the current execution pointer.

    A raw OPEN Develop Session is durable history. It is not current editor
    authority. Discovery of OPEN Sessions must not auto-select mutation.
    """
    host = Path(root)
    pointer, pointer_error = load_execution_pointer(host)
    if pointer_error:
        return CurrentDevelopAuthority(ok=False, reason=pointer_error)
    if pointer is None:
        return CurrentDevelopAuthority(
            ok=False,
            reason="no current Develop execution binding",
        )
    selected_id = str(pointer.get("session_id") or "").strip()
    if not selected_id:
        return CurrentDevelopAuthority(
            ok=False,
            reason="current Develop execution pointer is missing required fields",
        )
    session, directory, issues = load_canonical_open_session(host, selected_id)
    if session is None or directory is None:
        return CurrentDevelopAuthority(
            ok=False,
            reason=issues[0] if issues else "current Develop execution Session is invalid",
            session_id=selected_id,
        )
    return _authority_from_session(
        host,
        session,
        directory,
        require_provenance=require_provenance,
    )


def mutable_stage_ids(task: dict[str, Any] | None) -> list[str]:
    ids: list[str] = []
    if not isinstance(task, dict):
        return ids
    for stage in task.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        if stage.get("status") != "IN_PROGRESS":
            continue
        stage_id = str(stage.get("stage_id") or "").strip()
        if stage_id:
            ids.append(stage_id)
    return ids


def authorize_mutation_paths(
    root: str | Path,
    paths: list[str],
    *,
    authority: CurrentDevelopAuthority | None = None,
) -> tuple[bool, str]:
    """Authorize editor mutation targets through canonical P7 path authority."""
    host = Path(root)
    current = authority or resolve_current_develop_authority(host)
    if not current.ok or current.task is None:
        return False, current.reason
    if not paths:
        return False, "mutation target path is missing; fail closed"
    _status, _reasons, project = inspect_host_project(host)
    if not isinstance(project, dict):
        return False, "project ownership registry is UNKNOWN; mutation is blocked"
    for rel in paths:
        normalized = str(rel or "").replace("\\", "/").strip().strip("/")
        if not normalized:
            return False, "mutation target path is missing; fail closed"
        if is_protected_governance_path(normalized):
            return False, f"{normalized} is protected Scaffold governance"
        allowed, reason, _role = authorize_path_mutation(
            host,
            normalized,
            task=current.task,
            project=project,
            require_in_progress=True,
        )
        if not allowed:
            return False, reason
    return True, current.reason


def bind_current_execution(
    root: str | Path,
    *,
    session_id: str,
    task_id: str,
    opened_candidate_digest: str,
    lineage_digest: str,
) -> None:
    host = Path(root)
    path = host / EXECUTION_POINTER_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml_atomic(
        path,
        {
            "schema_version": "1",
            "record_type": "develop_execution",
            "session_id": session_id,
            "task_id": task_id,
            "opened_candidate_digest": opened_candidate_digest,
            "lineage_digest": lineage_digest,
            "selected_at": _iso_utc(),
        },
    )


def bind_open_execution(
    root: str | Path,
    *,
    session_id: str,
    task_id: str,
    directory: Path,
    opened_candidate_digest: str,
) -> None:
    """Bind the current execution pointer and freeze open-inventory if needed.

    Explicit `develop session` is the canonical rebind. It does not rewrite an
    existing open inventory, so deleting the pointer cannot launder drift.
    """
    existed = (directory / OPEN_INVENTORY_NAME).is_file()
    snapshot_open_inventory(root, directory, overwrite=False)
    reconcile_unexplained_drift(
        root, boundary="resume" if existed else "open"
    )
    digest = str(opened_candidate_digest or "")
    bind_current_execution(
        root,
        session_id=session_id,
        task_id=task_id,
        opened_candidate_digest=digest,
        lineage_digest=digest,
    )


def clear_current_execution(root: str | Path, *, session_id: str | None = None) -> None:
    host = Path(root)
    path = host / EXECUTION_POINTER_REL
    if not path.is_file():
        return
    if session_id:
        pointer, _error = load_execution_pointer(host)
        if pointer and str(pointer.get("session_id") or "") != session_id:
            return
    try:
        path.unlink()
    except OSError:
        return


def load_execution_pointer(root: str | Path) -> tuple[dict[str, Any] | None, str]:
    host = Path(root)
    path = host / EXECUTION_POINTER_REL
    if not path.is_file():
        return None, ""
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None, "current Develop execution pointer is malformed"
    if not isinstance(data, dict):
        return None, "current Develop execution pointer is malformed"
    if data.get("record_type") != "develop_execution":
        return None, "current Develop execution pointer is malformed"
    if str(data.get("schema_version") or "") != "1":
        return None, "current Develop execution pointer schema is unsupported"
    session_id = str(data.get("session_id") or "").strip()
    task_id = str(data.get("task_id") or "").strip()
    if not session_id or not task_id:
        return None, "current Develop execution pointer is missing required fields"
    return data, ""


def load_canonical_open_session(
    root: Path,
    session_id: str,
    *,
    expected_task_id: str | None = None,
) -> tuple[dict[str, Any] | None, Path | None, list[str]]:
    if not SESSION_ID_RE.fullmatch(session_id):
        return None, None, ["Develop Session identity is malformed"]
    directory = root / SESSIONS_DIR / session_id
    path = directory / "session.yaml"
    if directory.exists() and not directory.is_dir():
        return None, None, ["Develop Session path is not a directory"]
    if not path.is_file():
        return None, None, ["Develop Session is missing or orphaned"]
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None, None, ["Develop Session is malformed or unreadable"]
    issues = validate_develop_session(data, expected_id=session_id)
    if issues:
        return None, None, ["Develop Session is malformed"] + issues
    assert isinstance(data, dict)
    status = data.get("status")
    if status != "OPEN":
        return (
            None,
            None,
            [f"Develop Session status {status!r} cannot authorize mutation"],
        )
    if expected_task_id and str(data.get("task_id") or "") != expected_task_id:
        return None, None, ["Develop Session cannot be reused for a different Task Book"]
    files, file_issues = load_files_yaml(directory)
    if file_issues or files is None:
        return None, None, file_issues or ["Develop Session files.yaml is unusable"]
    return data, directory, []


def list_canonical_open_sessions(
    root: Path,
) -> list[tuple[dict[str, Any], Path]]:
    folder = root / SESSIONS_DIR
    if not folder.is_dir():
        return []
    rows: list[tuple[dict[str, Any], Path]] = []
    for directory in sorted(folder.iterdir()):
        if not directory.is_dir():
            continue
        session, loaded, issues = load_canonical_open_session(root, directory.name)
        if session is None or loaded is None or issues:
            continue
        rows.append((session, loaded))
    return rows


def raw_open_sessions_for_task(root: str | Path, task_id: str) -> list[dict[str, Any]]:
    """Status==OPEN records for leak detection. Not mutation authority."""
    folder = Path(root) / SESSIONS_DIR
    wanted = str(task_id or "").strip()
    if not folder.is_dir() or not wanted:
        return []
    rows: list[dict[str, Any]] = []
    for directory in sorted(folder.iterdir()):
        if not directory.is_dir():
            continue
        path = directory / "session.yaml"
        if not path.is_file():
            continue
        try:
            session = read_yaml(path)
        except (OSError, ValueError, TypeError, UnicodeError):
            continue
        if not isinstance(session, dict):
            continue
        if session.get("status") != "OPEN":
            continue
        if str(session.get("task_id") or "").strip() != wanted:
            continue
        rows.append(session)
    return rows


def open_sessions_for_task(root: str | Path, task_id: str) -> list[dict[str, Any]]:
    return raw_open_sessions_for_task(root, task_id)


def compute_lineage_digest(root: str | Path, task: dict[str, Any] | None = None) -> str:
    """Opened-candidate metadata. Not mutation authority and not a scope-omit digest."""
    del task
    observed = observe_candidate(root)
    return str(observed.digest or "")


def execution_provenance_issues(
    root: str | Path,
    *,
    task: dict[str, Any],
    session: dict[str, Any] | None,
    directory: Path,
    for_seal: bool = False,
) -> list[str]:
    """Compare workspace files to open inventory + observed mutation provenance.

    Task scope says WHERE a Task may change. files.yaml records successful
    observed Develop mutations. Pending authorization is not provenance.
    """
    del session
    host = Path(root)
    inventory = load_open_inventory(directory)
    if inventory is None:
        return ["Develop execution open inventory is missing"]
    files, file_issues = load_files_yaml(directory)
    if file_issues or files is None:
        return file_issues or ["Develop Session files.yaml is unusable"]
    attempts, attempt_issues = load_mutation_attempts(directory)
    if attempt_issues or attempts is None:
        return attempt_issues or ["Develop Session mutation-attempts.yaml is unusable"]
    current = execution_workspace_digests(host)
    recorded = {
        str(row.get("path") or "").replace("\\", "/").strip().strip("/"): row
        for row in files
        if isinstance(row, dict) and row.get("path") and _is_observed_success(row)
    }
    pending_paths = _attempt_paths(attempts, MUTATION_PENDING)
    issues: list[str] = []
    for path, digest in current.items():
        rec = recorded.get(path)
        opened = inventory.get(path)
        if rec is not None:
            if rec.get("change_kind") == "deleted" or rec.get("after_kind") == "missing":
                issues.append(
                    f"authorized deleted path {path} reappeared after execution recording"
                )
                continue
            after = rec.get("after_digest")
            if isinstance(after, str) and after and after != digest:
                issues.append(
                    f"authorized path {path} changed out of band after execution recording"
                )
            continue
        if path in pending_paths:
            if for_seal:
                issues.append(f"unresolved pending mutation authorization: {path}")
            continue
        if opened == digest:
            continue
        role = _execution_scope_role(host, path, task)
        if role in {"product", "supporting"}:
            issues.append(f"unexplained same-scope drift: {path}")
        else:
            issues.append(f"out-of-scope drift: {path}")
    for path, opened in inventory.items():
        if path in current:
            continue
        rec = recorded.get(path)
        if rec is not None and (
            rec.get("change_kind") == "deleted" or rec.get("after_kind") == "missing"
        ):
            continue
        if rec is not None:
            issues.append(
                f"authorized path {path} is missing after execution recording"
            )
            continue
        if path in pending_paths:
            if for_seal:
                issues.append(f"unresolved pending mutation authorization: {path}")
            continue
        role = _execution_scope_role(host, path, task)
        if role in {"product", "supporting"}:
            issues.append(f"unexplained same-scope deletion: {path}")
        else:
            issues.append(f"out-of-scope deletion: {path}")
    if for_seal:
        for path in sorted(pending_paths):
            marker = f"unresolved pending mutation authorization: {path}"
            if marker not in issues:
                issues.append(marker)
    return issues


_EDITOR_NONBLOCKING_PREFIXES = (
    "unexplained same-scope drift:",
    "unexplained same-scope deletion:",
)


def editor_blocking_provenance_issues(issues: list[str]) -> list[str]:
    """Same-scope unexplained drift is durable, not a global Develop lock.

    Out-of-scope drift, out-of-band authorized-path changes, and seal-time
    unresolved pending rows remain blocking. Mutation of the drifted path
    itself still requires normal scope/ownership authority.
    """
    return [
        item
        for item in issues
        if not item.startswith(_EDITOR_NONBLOCKING_PREFIXES)
    ]


def record_pending_mutation(
    root: str | Path,
    paths: list[str],
    *,
    tool_name: str = "",
    tool_use_id: str = "",
    authority: CurrentDevelopAuthority | None = None,
) -> None:
    """Record preToolUse authorization. This is not mutation provenance."""
    host = Path(root)
    current = authority or resolve_current_develop_authority(host)
    if not current.ok or current.directory is None or current.session is None:
        return
    attempts, attempt_issues = load_mutation_attempts(current.directory)
    if attempt_issues or attempts is None:
        return
    normalized = _normalize_paths(paths)
    if not normalized:
        return
    before: dict[str, Any] = {}
    scope_roles: dict[str, str] = {}
    for rel in normalized:
        dest = host / rel
        before[rel] = {
            "kind": path_kind(dest),
            "digest": file_sha256(dest),
        }
        if current.task is not None:
            scope_roles[rel] = _execution_scope_role(host, rel, current.task)
    attempts.append(
        {
            "attempt_id": secrets.token_hex(8),
            "session_id": current.session_id,
            "task_id": current.task_id,
            "tool_use_id": str(tool_use_id or "").strip(),
            "tool_name": str(tool_name or "").strip(),
            "paths": normalized,
            "state": MUTATION_PENDING,
            "authorization_state": "allow",
            "scope_roles": scope_roles,
            "before": before,
            "after": {},
            "recorded_at": _iso_utc(),
        }
    )
    persist_mutation_attempts(current.directory, attempts)


def observe_authorized_mutation(
    root: str | Path,
    paths: list[str],
    *,
    tool_name: str = "",
    tool_use_id: str = "",
    event: str = "postToolUse",
) -> tuple[bool, str]:
    """Resolve a pending authorization from a terminal or after-file observation."""
    host = Path(root)
    current = resolve_current_develop_authority(host, require_provenance=False)
    if not current.ok or current.directory is None or current.session is None:
        return False, current.reason or "no current Develop execution binding"
    attempts, attempt_issues = load_mutation_attempts(current.directory)
    if attempt_issues or attempts is None:
        return False, (attempt_issues or ["mutation-attempts.yaml is unusable"])[0]
    event_paths = _normalize_paths(paths)
    after_event = event in {"afterFileEdit", "afterTabFileEdit"}
    matched, ambiguous = _match_pending_attempt(
        attempts,
        session_id=current.session_id,
        tool_use_id=str(tool_use_id or "").strip(),
        paths=event_paths,
        require_unique_path=after_event,
    )
    if ambiguous:
        return False, "after-file mutation observation is ambiguous; ignored as provenance"
    if matched is None:
        return False, "no compatible current pending mutation authorization"
    observe_paths = list(matched.get("paths") or []) if not after_event else event_paths
    observe_paths = [rel for rel in _normalize_paths(observe_paths) if rel in set(matched.get("paths") or [])]
    if after_event and not observe_paths:
        return False, "no compatible current pending mutation authorization"
    if not observe_paths:
        observe_paths = _normalize_paths(list(matched.get("paths") or []))
    recorded_after = dict(matched.get("after") or {})
    files, file_issues = load_files_yaml(current.directory)
    if file_issues or files is None:
        return False, (file_issues or ["files.yaml is unusable"])[0]
    overlay = overlay_path_set(current.session)
    stages = list(current.mutable_stage_ids)
    for rel in observe_paths:
        dest = host / rel
        recorded_after[rel] = {
            "kind": path_kind(dest),
            "digest": file_sha256(dest),
        }
    matched["after"] = recorded_after
    pending_paths = _normalize_paths(list(matched.get("paths") or []))
    if after_event and any(rel not in recorded_after for rel in pending_paths):
        persist_mutation_attempts(current.directory, attempts)
        return True, "after-file observation recorded against current pending authorization"
    updated = list(files)
    before_map = matched.get("before") if isinstance(matched.get("before"), dict) else {}
    for rel in pending_paths:
        dest = host / rel
        after_info = recorded_after.get(rel) or {
            "kind": path_kind(dest),
            "digest": file_sha256(dest),
        }
        before_info = before_map.get(rel) if isinstance(before_map.get(rel), dict) else {}
        before_kind = str(before_info.get("kind") or path_kind(dest))
        before_digest = before_info.get("digest")
        after_kind = str(after_info.get("kind") or path_kind(dest))
        after_digest = after_info.get("digest")
        if after_kind == "missing":
            change_kind = "deleted"
        elif before_kind == "missing":
            change_kind = "created"
        elif after_kind != before_kind:
            change_kind = "type_changed"
        else:
            change_kind = "modified"
        updated = record_touch(
            current.directory,
            updated,
            rel=rel,
            before_kind=before_kind,
            after_kind=after_kind,
            before_digest=before_digest,
            after_digest=after_digest,
            change_kind=change_kind,
            was_preexisting_dirty=rel in overlay,
            stage_ids=stages,
            mutation_state=MUTATION_OBSERVED,
        )
    matched["state"] = MUTATION_OBSERVED
    matched["observed_at"] = _iso_utc()
    persist_mutation_attempts(current.directory, attempts)
    return True, "observed successful Develop mutation"


def fail_authorized_mutation(
    root: str | Path,
    paths: list[str],
    *,
    tool_name: str = "",
    tool_use_id: str = "",
    state: str = MUTATION_FAILED,
) -> tuple[bool, str]:
    """Retract a pending authorization after a failed/cancelled tool attempt."""
    del tool_name
    host = Path(root)
    current = resolve_current_develop_authority(host, require_provenance=False)
    if not current.ok or current.directory is None:
        return False, current.reason or "no current Develop execution binding"
    attempts, attempt_issues = load_mutation_attempts(current.directory)
    if attempt_issues or attempts is None:
        return False, (attempt_issues or ["mutation-attempts.yaml is unusable"])[0]
    matched, ambiguous = _match_pending_attempt(
        attempts,
        session_id=current.session_id,
        tool_use_id=str(tool_use_id or "").strip(),
        paths=_normalize_paths(paths),
        require_unique_path=False,
    )
    if ambiguous or matched is None:
        return False, "no compatible current pending mutation authorization"
    matched["state"] = state if state in {MUTATION_FAILED, MUTATION_CANCELLED} else MUTATION_FAILED
    matched["failed_at"] = _iso_utc()
    persist_mutation_attempts(current.directory, attempts)
    return True, "mutation attempt failed; no execution provenance"


def record_authorized_mutation(
    root: str | Path,
    paths: list[str],
    *,
    observed: bool,
    authority: CurrentDevelopAuthority | None = None,
    tool_name: str = "",
    tool_use_id: str = "",
) -> None:
    """Compatibility wrapper. Pre-events pending; observed events resolve provenance."""
    if observed:
        observe_authorized_mutation(
            root,
            paths,
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            event="postToolUse",
        )
        return
    record_pending_mutation(
        root,
        paths,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        authority=authority,
    )


def _execution_scope_role(root: Path, rel: str, task: dict[str, Any]) -> str:
    scope = task.get("scope") if isinstance(task.get("scope"), dict) else {}
    in_support, _reason = path_in_supporting_scope(rel, scope)
    if in_support:
        return "supporting"
    modules = task_module_paths(root, scope)
    in_product, _reason = path_in_scope(rel, scope, modules)
    if in_product:
        return "product"
    return "outside"


def _is_observed_success(row: dict[str, Any]) -> bool:
    state = str(row.get("mutation_state") or "").strip()
    if state in {MUTATION_PENDING, MUTATION_FAILED, MUTATION_CANCELLED}:
        return False
    if state == MUTATION_OBSERVED:
        return True
    if row.get("change_kind") == "deleted":
        return True
    if row.get("after_kind") == "missing" and not row.get("after_digest"):
        return False
    return isinstance(row.get("after_digest"), str) and bool(row.get("after_digest"))


def _normalize_paths(paths: list[str] | tuple[str, ...]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        rel = str(raw or "").replace("\\", "/").strip().strip("/")
        if not rel or rel in seen:
            continue
        seen.add(rel)
        unique.append(rel)
    return unique


def _attempt_paths(attempts: list[dict[str, Any]], state: str) -> set[str]:
    out: set[str] = set()
    for attempt in attempts:
        if str(attempt.get("state") or "") != state:
            continue
        for raw in attempt.get("paths") or []:
            rel = str(raw or "").replace("\\", "/").strip().strip("/")
            if rel:
                out.add(rel)
    return out


def _match_pending_attempt(
    attempts: list[dict[str, Any]],
    *,
    session_id: str,
    tool_use_id: str,
    paths: list[str],
    require_unique_path: bool,
) -> tuple[dict[str, Any] | None, bool]:
    pending = [
        attempt
        for attempt in attempts
        if isinstance(attempt, dict)
        and str(attempt.get("state") or "") == MUTATION_PENDING
        and str(attempt.get("session_id") or "") == session_id
    ]
    if tool_use_id:
        by_id = [
            attempt
            for attempt in pending
            if str(attempt.get("tool_use_id") or "") == tool_use_id
        ]
        if len(by_id) == 1:
            return by_id[0], False
        if len(by_id) > 1:
            return None, True
        return None, False
    wanted = set(paths)
    if not wanted:
        if len(pending) == 1 and not require_unique_path:
            return pending[0], False
        return None, bool(len(pending) > 1 and not require_unique_path)
    overlapping = [
        attempt
        for attempt in pending
        if wanted & set(_normalize_paths(list(attempt.get("paths") or [])))
    ]
    if len(overlapping) == 1:
        return overlapping[0], False
    if len(overlapping) > 1:
        return None, True
    return None, False


def other_valid_open_session(
    root: Path,
    *,
    task_id: str,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    wanted_task = str(task_id or "").strip()
    current_id = str(session_id or "").strip()
    for session, _directory in list_canonical_open_sessions(root):
        other_id = str(session.get("record_id") or "")
        other_task = str(session.get("task_id") or "")
        if current_id and other_id == current_id:
            continue
        if other_task != wanted_task:
            return session
        if other_id and other_id != current_id:
            return session
    return None


def _authority_from_session(
    host: Path,
    session: dict[str, Any],
    directory: Path,
    *,
    require_provenance: bool = True,
) -> CurrentDevelopAuthority:
    task_id = str(session.get("task_id") or "").strip()
    session_id = str(session.get("record_id") or "").strip()
    resolved = resolve_task(host, task_id=task_id)
    if not resolved.ok or resolved.task is None:
        return CurrentDevelopAuthority(
            ok=False,
            reason=resolved.blockers[0] if resolved.blockers else "bound Task Book is missing",
            session=session,
            session_id=session_id,
            task_id=task_id,
            directory=directory,
        )
    task = resolved.task
    if str(task.get("record_id") or "") != task_id:
        return CurrentDevelopAuthority(
            ok=False,
            reason="Develop Session is bound to the wrong Task Book",
            task=task,
            session=session,
            session_id=session_id,
            task_id=task_id,
            directory=directory,
        )
    if task.get("status") != "IN_PROGRESS":
        return CurrentDevelopAuthority(
            ok=False,
            reason=f"Task status {task.get('status')} cannot authorize Develop mutation",
            task=task,
            session=session,
            session_id=session_id,
            task_id=task_id,
            directory=directory,
        )
    stage_ids = mutable_stage_ids(task)
    if not stage_ids:
        return CurrentDevelopAuthority(
            ok=False,
            reason="COMPLETE-only Stage does not authorize mutation",
            task=task,
            session=session,
            session_id=session_id,
            task_id=task_id,
            mutable_stage_ids=stage_ids,
            directory=directory,
        )
    others = other_valid_open_session(
        host, task_id=task_id, session_id=session_id
    )
    if others:
        return CurrentDevelopAuthority(
            ok=False,
            reason="multiple OPEN Develop Sessions claim editor authority",
            task=task,
            session=session,
            session_id=session_id,
            task_id=task_id,
            mutable_stage_ids=stage_ids,
            directory=directory,
        )
    physical = physical_authority_issues(host)
    if physical:
        return CurrentDevelopAuthority(
            ok=False,
            reason=physical[0],
            task=task,
            session=session,
            session_id=session_id,
            task_id=task_id,
            mutable_stage_ids=stage_ids,
            directory=directory,
        )
    provenance = execution_provenance_issues(
        host, task=task, session=session, directory=directory
    )
    blocking = editor_blocking_provenance_issues(provenance)
    if require_provenance and blocking:
        return CurrentDevelopAuthority(
            ok=False,
            reason=blocking[0],
            task=task,
            session=session,
            session_id=session_id,
            task_id=task_id,
            mutable_stage_ids=stage_ids,
            directory=directory,
        )
    return CurrentDevelopAuthority(
        ok=True,
        reason="current Develop execution Session authorizes scoped mutation",
        task=task,
        session=session,
        mutable_stage_ids=stage_ids,
        task_id=task_id,
        session_id=session_id,
        lineage_digest=str(session.get("observed_candidate_digest") or ""),
        directory=directory,
    )


def _iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
